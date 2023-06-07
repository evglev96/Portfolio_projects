from datetime import date,datetime, timedelta
import telegram
import numpy as np
import matplotlib.pyplot as plt
import plotly.express as px
import seaborn as sns
import io
import pandas as pd
import pandahouse as ph


from airflow.decorators import dag, task
from airflow.operators.python import get_current_context


# Функция для подключения к CH
connection = {'host': 'host',
                      'database':'db',
                      'user':'user', 
                      'password':'password'} #вводим свои данные
default_args = {
    'owner': 'e-bobylev', #заменяем на свое имя
    'depends_on_past': False,
    'retries': 2,
    'retry_delay': timedelta(minutes = 5),
    'start_date': datetime(2023, 5, 17),
}

# Интервал запуска DAG
schedule_interval = '*/15 * * * *'

my_token = 'your_token' # тут нужно заменить на токен вашего бота
bot = telegram.Bot(token = my_token) # получаем доступ

chat_id =  123456789 # вводим свой ИД бота

metrics_feed = ['users_feed', 'views','likes', 'CTR']
metrics_message = ['users_mes', 'messages_cnt']


@dag(default_args = default_args, schedule_interval = schedule_interval, catchup = False)
def ebobylev_alerts():
    
    @task
    def extract_query1(): #Запрос SQL
        query_feed = """SELECT toStartOfFifteenMinutes(time) as date_time,
                                toDate(time) as date,
                                formatDateTime(date_time,'%R') as timeHM,
                                uniqExact(user_id) as users_feed,
                                countIf(user_id, action = 'view') as views,
                                countIf(user_id, action = 'like') as likes,
                                likes / views as CTR
                                FROM simulator_20230420.feed_actions WHERE toDate(time) >= today() - 1 and time < toStartOfFifteenMinutes(now())
                                GROUP BY date_time,date,timeHM ORDER BY  date_time"""
        feed = ph.read_clickhouse(query_feed, connection = connection)
        return feed
    
    @task   
    def extract_query2():
        query_message = """SELECT toStartOfFifteenMinutes(time) as date_time,
                                toDate(time) as date,
                                formatDateTime(date_time,'%R') as timeHM,
                                uniqExact(user_id) as users_mes,
                                count(user_id) as messages_cnt
                                FROM simulator_20230420.message_actions WHERE toDate(time) >= today() - 1 and time < toStartOfFifteenMinutes(now())
                                GROUP BY date_time,date,timeHM ORDER BY  date_time"""
        
        message = ph.read_clickhouse(query_message,connection = connection)
        return message
    
    
    def anomaly_search(df, metric, a = 5,n = 5): # ищем аномалии. a = коэффициент интервала(ширина) n - количество временных промежутков
        df['quantile25'] = df[metric].shift(1).rolling(n).quantile(0.25) #сдвигаем шифтом окно
        df['quantile75'] = df[metric].shift(1).rolling(n).quantile(0.75)
        df['iqr'] = df['quantile75'] - df['quantile25']
        df['upper_limit'] = (df['quantile75'] + a * df['iqr']).rolling(window=n, center=True, min_periods = 1).mean()
        df['lower_limit'] = (df['quantile25'] - a * df['iqr']).rolling(window=n, center=True, min_periods = 1).mean()
        
        if df[metric].iloc[-1] < df['lower_limit'].iloc[-1] or df[metric].iloc[-1] > df['upper_limit'].iloc[-1]:
            alert = 1
        else:
            alert = 0
        return alert, df
    
    @task
    def alerts_system(query_sql,metrics):
        for metric in metrics:
            df = query_sql[['date_time','date','timeHM',metric]].copy()
            alert, df2 = anomaly_search(df, metric)
            
            if alert == 1: #or True - если хотим, чтобы бот всегда отправлял сообщение, даже если нет аномалии
                msg = f'🔔ALERT!!!\n Метрика {metric} имеет аномальное значение:\n Текущее значение {df[metric].iloc[-1]:.2f}\n Отклонение от нормы {1 - df[metric].iloc[-1]/df[metric].iloc[-2]:.2%}'
                sns.set_style('darkgrid')
                plt.figure(figsize=(15, 10))
                
                ax = sns.lineplot( x = df2['date_time'], y = df2[metric], label = metric, color = 'g')
                ax = sns.lineplot( x = df2['date_time'], y = df2['upper_limit'], label = 'upper_limit', color = 'r')
                ax = sns.lineplot( x = df2['date_time'], y = df2['lower_limit'], label = 'lower_limit', color = 'orange')
                ax.set_title(metric)
                ax.set(ylim = (0, None))
                
                plot_object = io.BytesIO()
                plt.savefig(plot_object)
                plot_object.name = f'{metric}.png'
                plot_object.seek(0)
                plt.close()
                bot.sendMessage(chat_id = chat_id, text = msg)
                bot.sendPhoto(chat_id = chat_id, photo = plot_object)
                
    feed = extract_query1()
    message = extract_query2()
    alerts_system(feed,metrics_feed)
    alerts_system(message,metrics_message)

ebobylev_alerts = ebobylev_alerts()
