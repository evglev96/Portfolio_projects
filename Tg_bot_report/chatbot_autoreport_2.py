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


# Функция для CH
connection = {'host': 'host',
                      'database':'db',
                      'user':'user', 
                      'password':'password'} #вводим свои данные
default_args = {
    'owner': 'e-bobylev',
    'depends_on_past': False,
    'retries': 2,
    'retry_delay': timedelta(minutes = 5),
    'start_date': datetime(2023, 5, 12),
}

# Интервал запуска DAG
schedule_interval = '0 11 * * *'

my_token = 'token' # тут нужно заменить на токен вашего бота
bot = telegram.Bot(token = my_token) # получаем доступ

chat_id =  123456789 #ид вашего чата

yesterday = date.today() - timedelta(days = 1)
yesterday = yesterday.strftime('%d/%m/%Y')

@dag(default_args = default_args, schedule_interval = schedule_interval, catchup = False)
def ebobylev_bot_report_app1():
    
    @task()
    def df_retention():
        
        query1 = """WITH 
                        lost_users_status AS(SELECT user_id, 
                                groupUniqArray(toMonday(toDate(time))) as weeks_visited, 
                                addWeeks(arrayJoin(weeks_visited), 1) as this_week, addWeeks(this_week, -1) as prev_week,
                                if(has(weeks_visited, this_week) = 1,'retained','lost') as user_status
                        FROM bd.feed_actions
                        group by user_id),
                        new_users_status AS(SELECT user_id, 
                                            groupUniqArray(toMonday(toDate(time))) as weeks_visited,
                                            arrayJoin(weeks_visited) as this_week,
                                            addWeeks(this_week,-1) as prev_week,
                                            if(has(weeks_visited,addWeeks(this_week, -1)) = 1,'retained', 'new') as user_status
                        FROM bd.feed_actions
                        group by user_id)
                        
                        
                        SELECT this_week, prev_week,user_status, toInt64(-uniq(user_id)) as num_users 
                        FROM lost_users_status where user_status = 'lost' and this_week != addWeeks(toMonday(today()),1)
                        GROUP BY this_week,prev_week,user_status
                        UNION all
                        SELECT this_week, prev_week, user_status, toInt64(uniq(user_id)) as num_users 
                        FROM new_users_status
                        GROUP BY this_week, prev_week, user_status
                """
        
        df_retention = ph.read_clickhouse(query1, connection = connection)
        df_retention = df_retention.sort_values(by = 'this_week')
        return df_retention
    @task()
    def df_feedactions():
        
        query2 = """SELECT
                      user_id as users,
                      toDate(time) as event_date,
                      gender,
                      age,
                      os,
                      countIf(action = 'like') as likes,
                      countIf(action = 'view') as views
                    FROM
                      bd.feed_actions
                    WHERE
                      toDate(time) = yesterday()
                    GROUP BY
                      user_id,
                      event_date,
                      gender,
                      age,
                      os """
        
        df_feedaction = ph.read_clickhouse(query2, connection = connection)
        return df_feedaction
    
    @task()
    def df_message_actions():
            
        query3 = """SELECT
                      users,
                      event_date,
                      gender,
                      age,
                      os,
                      messages_received,
                      messages_sent,
                      users_received,
                      users_sent
                    FROM
                      (
                        SELECT
                          user_id as users,
                          toDate(time) as event_date,
                          gender,
                          age,
                          os,
                          count(reciever_id) as messages_sent,
                          uniq(reciever_id) as users_sent
                        FROM
                          bd.message_actions
                        WHERE
                          toDate(time) = yesterday()
                        GROUP BY
                          user_id,
                          event_date,
                          gender,
                          age,
                          os
                      ) AS t1 
                      FULL OUTER JOIN 
                      (SELECT
                          reciever_id as users,
                          toDate(time) as event_date,
                          gender,
                          age,
                          os,
                          count(reciever_id) as messages_received,
                          uniq(user_id) as users_received
                        FROM
                          bd.message_actions
                        WHERE
                          toDate(time) = yesterday()
                        GROUP BY
                          users,
                          event_date,
                          gender,
                          age,
                          os
                      ) AS t2 using users"""
        
        df_message_actions = ph.read_clickhouse(query3, connection = connection)
        return df_message_actions
    
    @task()
    def total_dau():
        total_dau_q4 = """SELECT date as date, MIN(users) AS users
                                FROM
                                  (SELECT date, uniqExact(user_id) AS users
                                   FROM
                                     (SELECT user_id, toDate(time) AS date
                                      FROM bd.feed_actions
                                      GROUP BY user_id, date
    
                                      UNION ALL 
    
                                      SELECT user_id, toDate(time) AS date
                                      FROM bd.message_actions
                                      GROUP BY user_id, date)
                                    GROUP BY date) AS t1
                                WHERE date between today() -8 and today() - 1
                                GROUP BY date
                                ORDER BY date"""
    
        total_dau = ph.read_clickhouse(total_dau_q4, connection = connection)
        return total_dau
    
    @task()
    def dau_feed():
        query_feed = """SELECT toDate(time) AS date,
                            count(DISTINCT user_id) AS DAU,
                            countIf(user_id, action='like') as likes,
                            countIf(user_id, action='view') as views,
                            likes / views AS CTR
                            FROM bd.feed_actions
                            WHERE date between today() -8 and today() - 1
                            GROUP BY date
                            ORDER BY date"""
    
        dau_feed = ph.read_clickhouse(query_feed, connection = connection)
        return dau_feed
    
    @task()
    def dau_msg():
        query_dau_messages =  '''SELECT toDate(time) as date,
                                    count(user_id) AS DAU
                             FROM
                                    (SELECT DISTINCT user_id,
                                     time
                             FROM
                                     (SELECT user_id,
                                             time::date as time
                                      from bd.feed_actions) t1
                                   JOIN
                                     (SELECT user_id,
                                             time::date as time
                                      from bd.message_actions) t2 ON t1.user_id = t2.user_id
                                   and t1.time = t2.time) AS virtual_table WHERE time between today() -8 and today() - 1
                                    GROUP BY date
                                    ORDER BY date'''
    
        dau_msg = ph.read_clickhouse(query_dau_messages, connection = connection)
        return dau_msg
    
    
    
    @task()
    def merge_table(df_cube_feedaction,df_message_actions):
        
        merge_table = df_cube_feedaction.merge(df_message_actions, on = ['users', 'event_date', 'gender', 'age', 'os'], how = 'outer').fillna(0)
        merge_table = merge_table.astype({'likes':'int','views':'int','messages_received':'int','messages_sent':'int','users_received':'int','users_sent':'int'})
        return merge_table
    
    
    @task()
    def group_gender(merge_table):
        
        group_gender = merge_table.assign(dimension = 'gender')\
                                      .rename(columns = {'gender':'dimension_value'})\
                                      .groupby(['event_date','dimension','dimension_value'])\
                                      .agg({'views':'sum',
                                            'likes':'sum',
                                            'messages_received':'sum',
                                            'messages_sent':'sum',
                                            'users_received':'sum',
                                            'users_sent':'sum'}).reset_index()
        group_gender['dimension_value'] = group_gender['dimension_value'].replace({0:'Female', 1:'Male'})
        return group_gender
    
        
    @task()
    def group_age(merge_table):
        
        group_age = merge_table.assign(dimension = 'age')\
                                     .rename(columns = {'age':'dimension_value'})\
                                     .groupby(['event_date','dimension','dimension_value'])\
                                     .agg({'views':'sum',
                                           'likes':'sum',
                                           'messages_received':'sum',
                                           'messages_sent':'sum',
                                           'users_received':'sum',
                                           'users_sent':'sum'}).reset_index()
        return group_age
        
        
     #группировка по os
    @task()
    def group_os(merge_table):
        group_os = merge_table.assign(dimension = 'os')\
                                  .rename(columns = {'os':'dimension_value'})\
                                  .groupby(['event_date','dimension','dimension_value'])\
                                  .agg({'views':'sum',
                                        'likes':'sum',
                                        'messages_received':'sum',
                                        'messages_sent':'sum',
                                        'users_received':'sum',
                                        'users_sent':'sum'}).reset_index()
        return group_os
         
        
    @task()    
    def message(total_dau, dau_feed, dau_msg):
        week_diff_dau = round((int(total_dau.iloc[-1].users) - int(total_dau.iloc[0].users)) / int(total_dau.iloc[0].users) * 100, 2)
        week_diff_dau_feed = round((int(dau_feed.iloc[-1].DAU) - int(dau_feed.iloc[0].DAU)) / int(dau_feed.iloc[0].DAU) * 100, 2)
        week_diff_dau_messages = round((int(dau_msg.iloc[-1].DAU) - int(dau_msg.iloc[0].DAU)) / int(dau_msg.iloc[0].DAU) * 100, 2)
        msg = '*' * 45 + '\n' +  f'📈Метрики за {yesterday}:\n\
    DAU\n\
    Общая аудитория: {total_dau.iloc[-1].users}, Неделю назад: {total_dau.iloc[0].users} ({week_diff_dau}%)\n\
    Только лента: {dau_feed.iloc[-1].DAU}, Неделю назад: {dau_feed.iloc[0].DAU} ({week_diff_dau_feed}%) \n\
    Только мессенджер: {dau_msg.iloc[-1].DAU}, Неделю назад: {dau_msg.iloc[0].DAU} ({week_diff_dau_messages}%)\n\
    Также смотри вложения 👇\n' + '*' * 45
        
        bot.sendMessage(chat_id = chat_id, text = msg)
        return msg
        
        
    @task()
    def plot_retention(df_retention):
        sns.set_style('darkgrid')
        plt.figure(figsize=(15, 10))
        sns.barplot(data = df_retention, x = df_retention.this_week.dt.strftime('%Y-%m-%d'), y = 'num_users', hue = 'user_status', palette = sns.color_palette("Set2"))
        plt.suptitle('Аудитория по неделям')
        plt.xticks(rotation=45)
        plt.ylabel('День')
        plt.xlabel('Пользователи')
        plot_object = io.BytesIO()
        plt.savefig(plot_object)
        plot_object.seek(0)
        plot_object.name = 'plot_retention.png'
        plt.close()
        bot.sendPhoto(chat_id = chat_id, photo = plot_object)
    @task()   
    def plot_gender(group_gender):
        fig, axes = plt.subplots(2, 2, figsize=(25, 20))
        fig.suptitle('Метрики за неделю по полу', fontsize=35)
        
        sns.barplot(ax = axes[0, 0], data = group_gender, x = 'dimension_value', y = 'views', palette = sns.color_palette("Paired"))
        axes[0, 0].set_title('Просмотры',fontsize=18)
        axes[0, 0].grid()
        
        
        sns.barplot(ax = axes[1, 0], data = group_gender, x = 'dimension_value', y = 'likes', palette = sns.color_palette("rocket"))
        axes[1, 0].set_title('Лайки',fontsize=18)
        axes[1, 0].grid()
        
                
        sns.barplot(ax = axes[1, 1], data = group_gender, x = 'dimension_value', y = 'messages_received', palette = sns.color_palette("pastel"))
        axes[1, 1].set_title('Сообщения полученные',fontsize=18)
        axes[1, 1].grid()
                
                
        sns.barplot(ax = axes[0, 1], data = group_gender, x = 'dimension_value', y = 'messages_sent', palette = sns.color_palette("husl", 9))
        axes[0, 1].set_title('Сообщения отправленные',fontsize=18)
        axes[0, 1].grid()
        
        
        plot_object = io.BytesIO()
        plt.savefig(plot_object)
        plot_object.seek(0)
        plot_object.name = 'gender_metric.png'
        plt.close()
        bot.sendPhoto(chat_id=chat_id, photo=plot_object)
        
    @task()    
    def plot_age(group_age):    
        fig, axes = plt.subplots(2, 2, figsize = (35, 25))
        fig.suptitle('Метрики за неделю по возрасту', fontsize=35)
        
        sns.barplot(ax = axes[0, 0], data = group_age, x = 'dimension_value', y = 'views', palette = sns.color_palette("Paired"))
        axes[0, 0].set_title('Просмотры',fontsize=18)
        axes[0, 0].grid()
        
        
        sns.barplot(ax = axes[1, 0], data = group_age, x = 'dimension_value', y = 'likes', palette = sns.color_palette("rocket"))
        axes[1, 0].set_title('Лайки',fontsize=18)
        axes[1, 0].grid()
        
                
        sns.barplot(ax = axes[1, 1], data = group_age, x = 'dimension_value', y = 'messages_received', palette = sns.color_palette("pastel"))
        axes[1, 1].set_title('Сообщения полученные',fontsize=18)
        axes[1, 1].grid()
                
                
        sns.barplot(ax = axes[0, 1], data = group_age, x = 'dimension_value', y = 'messages_sent', palette = sns.color_palette("husl", 9))
        axes[0, 1].set_title('Сообщения отправленные',fontsize=18)
        axes[0, 1].grid()
        
        plot_object = io.BytesIO()
        plt.savefig(plot_object)
        plot_object.seek(0)
        plot_object.name = 'age_metric.png'
        plt.close()
        bot.sendPhoto(chat_id = chat_id, photo = plot_object)
        
    @task()
    def plot_ctr_dau(dau_feed):
        sns.set_style('darkgrid')
        plt.figure(figsize=(15, 10))
        sns.lineplot(x = "date", y = "DAU", data=dau_feed, marker = "o", color = 'red')
        plt.xticks(rotation=45)
        plt.xlabel(None)
        plt.yticks(color = "red")
        ax2 = plt.twinx()
        sns.lineplot(x = "date", y = "CTR", data = dau_feed, marker="o", color = "green", ax = ax2)
        plt.suptitle('DAU,CTR 7 дней')       
        plt.yticks(color="green")
    
        plot_object = io.BytesIO()
        plt.savefig(plot_object)
        plot_object.seek(0)
        plot_object.name = 'age_metric.png'
        plt.close()
        bot.sendPhoto(chat_id = chat_id, photo = plot_object)
        
    
    
    
    df_retention = df_retention()
    df_feedactions = df_feedactions()
    df_message_actions = df_message_actions()
    total_dau = total_dau()
    dau_feed = dau_feed()
    dau_msg = dau_msg()
    merge_table = merge_table(df_feedactions,df_message_actions)
    group_gender = group_gender(merge_table)
    group_age = group_age(merge_table)
    group_os = group_os(merge_table)    
    msg = message(total_dau,dau_feed,dau_msg)
    
    plot_retention(df_retention)
    plot_gender(group_gender)
    plot_age(group_age)
    plot_ctr_dau(dau_feed)

    
ebobylev_bot_report_app1 = ebobylev_bot_report_app1()