from datetime import date,datetime, timedelta
import telegram
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns

import pandahouse as ph
from datetime import datetime, timedelta
import pandas as pd
import io
import requests

from airflow.decorators import dag, task
from airflow.operators.python import get_current_context


# Функция для CH
connection = {'host': 'host',
                      'database':'db',
                      'user':'user', 
                      'password':'password'} #вводим свои данные
default_args = {
    'owner': 'e-bobylev', #заменяем на свое имя
    'depends_on_past': False,
    'retries': 2,
    'retry_delay': timedelta(minutes = 5),
    'start_date': datetime(2023, 5, 12),
}

# Интервал запуска DAG
schedule_interval = '0 11 * * *'

my_token = 'token' # тут нужно заменить на токен вашего бота
bot = telegram.Bot(token = my_token) # получаем доступ
chat = 123456789 #вводим ид личного чата
chat_id = chat or 123456789 #или ид группы

yesterday = date.today() - timedelta(days = 1)
yesterday = yesterday.strftime('%d/%m/%Y')

@dag(default_args = default_args, schedule_interval = schedule_interval, catchup = False)
def ebobylev_bot1():
    @task()
    def query_yesterday(): 
        q = """
                    SELECT toDate(time) as date, 
                           uniqExact(user_id) as DAU, 
                           sum(action = 'like') as likes,
                           sum(action = 'view') as views, 
                           likes/views as CTR
                    FROM bd.feed_actions
                    WHERE toDate(time) = yesterday()
                    GROUP BY date
        """

        sql_day_ago = ph.read_clickhouse(q, connection = connection)
        return sql_day_ago
    
    @task()
    def query_last_week():
        q = """
                    SELECT toDate(time) as date, 
                           uniqExact(user_id) as DAU, 
                           sum(action = 'like') as likes,
                           sum(action = 'view') as views, 
                           likes/views as CTR
                           FROM bd.feed_actions
                    WHERE toDate(time) between today() - 8 and today() - 1
                    GROUP BY date
        """

        sql_week = ph.read_clickhouse(q, connection=connection)
        return sql_week
    
    @task()
    def message(sql_day_ago,sql_week, chat_id=None): #Загружаем данные за прошлую неделею
        chat_id = chat or 123456789
        dau1 = sql_day_ago['DAU'].sum()
        views1 = sql_day_ago['views'].sum()
        likes1 = sql_day_ago['likes'].sum()
        ctr1 = sql_day_ago['CTR'].sum()
        dau7 = sql_week['DAU'].sum()
        views7 = sql_week['views'].sum()
        likes7 = sql_week['likes'].sum()
        ctr7 = sql_week['likes'].sum() / sql_week['views'].sum()
        
        

        msg = '*' * 37 + '\n' +  f'Добрый день, Господин. Ваш отчет за {yesterday}:\n👨‍👩‍👧‍👦DAU: {dau1}\n👀Просмотры: {views1}\n❤️Лайки: {likes1}\n📈CTR: {ctr1:.2f}\n \
        Отчет за 7 дней:\n👨‍👩‍👧‍👦DAU: {dau7}\n👀Просмотры: {views7}\n❤️Лайки: {likes7}\n📈CTR: {ctr7:.2f}\n' + '*' * 37
        

        bot.sendMessage(chat_id = chat_id, text = msg)

    @task()
    def grafik(sql_week, chat_id=None):
        chat_id = chat_id or 123456789
        fig, axes = plt.subplots(2, 2, figsize = (25, 20))

        fig.suptitle('Метрики за неделю', fontsize = 35)

        sns.lineplot(ax = axes[0, 0], data = sql_week, x = 'date', y = 'DAU', color = 'red')
        axes[0, 0].set_title('DAU',fontsize=18)
        axes[0, 0].grid()


        sns.lineplot(ax = axes[1, 0], data = sql_week, x = 'date', y = 'views', color = 'purple')
        axes[1, 0].set_title('Просмотры',fontsize=18)
        axes[1, 0].grid()

        
        sns.lineplot(ax = axes[1, 1], data = sql_week, x = 'date', y = 'likes',color = 'green')
        axes[1, 1].set_title('Лайки',fontsize=18)
        axes[1, 1].grid()
        
        
        sns.lineplot(ax = axes[0, 1], data = sql_week, x = 'date', y = 'CTR')
        axes[0, 1].set_title('CTR',fontsize=18)
        axes[0, 1].grid()

        
        plot_object = io.BytesIO()
        plt.savefig(plot_object)
        plot_object.seek(0)
        plot_object.name = 'grafikweek.png'
        plt.close()

        bot.sendPhoto(chat_id = chat_id, photo = plot_object)
        
        
    
    sql_day_ago = query_yesterday()
    sql_week = query_last_week()
    message(sql_day_ago,sql_week, chat_id=None)
    
    grafik(sql_week, chat_id)
    
    
    
ebobylev_bot1 = ebobylev_bot1()
