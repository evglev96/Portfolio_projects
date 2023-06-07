# coding=utf-8
import pandahouse
from datetime import datetime, timedelta
import pandas as pd
from io import StringIO
import requests

from airflow.decorators import dag, task
from airflow.operators.python import get_current_context

# Функция для подключения к ClickHouse
connection = {'host': 'host',
                      'database':'database',
                      'user':'user', 
                      'password':'password'}

#СОединение для загрузки в ClickHouse
connection_test = {'host': 'host',
                   'password': 'password',
                   'user': 'user',
                   'database': 'test'}
#создаем таблицу
query_test = '''CREATE TABLE IF NOT EXISTS test.ebobylev_table1
                    (event_date Date,
                    dimension String,
                    dimension_value String,
                    views UInt64,
                    likes UInt64,
                    messages_received UInt64,
                    messages_sent UInt64,
                    users_received UInt64,
                    users_sent UInt64)
                    ENGINE = MergeTree()
                    ORDER BY event_date'''

# Дефолтные параметры, которые прокидываются в таски.
default_args = {
    'owner': 'e-bobylev',
    'depends_on_past': False,
    'retries': 2,
    'retry_delay': timedelta(minutes = 5),
    'start_date': datetime(2023, 5, 8),
}
# Интервал запуска DAG
schedule_interval = '0 23 * * *'

@dag(default_args=default_args, schedule_interval=schedule_interval, catchup=False)
def ebobylev_metriсs2():
    @task()
    def extract_feedaction():
        query = """SELECT
                  user_id as users,
                  toDate(time) as event_date,
                  gender,
                  age,
                  os,
                  countIf(action = 'like') as likes,
                  countIf(action = 'view') as views
                FROM
                  simulator_20230420.feed_actions
                WHERE
                  toDate(time) = yesterday()
                GROUP BY
                  user_id,
                  event_date,
                  gender,
                  age,
                  os """
        df_cube_feedaction = pandahouse.read_clickhouse(query, connection=connection)
        return df_cube_feedaction
    @task()
    def extract_message_actions(): 
        
        query = """SELECT
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
                      simulator_20230420.message_actions
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
                      simulator_20230420.message_actions
                    WHERE
                      toDate(time) = yesterday()
                    GROUP BY
                      users,
                      event_date,
                      gender,
                      age,
                      os
                  ) AS t2 using users"""
            
        df_message_actions = pandahouse.read_clickhouse(query, connection = connection)
        return df_message_actions
    @task()
    def merge_table(df_cube_feedaction, df_message_actions):       
        merge_table = df_cube_feedaction.merge(df_message_actions, on = ['users', 'event_date', 'gender', 'age', 'os'], how = 'outer').fillna(0)
        return merge_table
    
    @task() #группировка по gender
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
        return group_gender

    
    @task() #группировка по age
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
    
    
    @task() #группировка по os
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
    
    
    @task() #конкатенируем таблицы
    def concat_df(group_gender, group_age, group_os):
        new_table = pd.concat([group_gender, group_age, group_os])
        new_table = new_table.astype({"likes":"int","views":"int", "messages_received":"int","messages_sent":"int", "users_sent":"int","users_received":"int"})
        return new_table
    
    @task() #загружаем в CH
    def load_to_CH(new_table):
        pandahouse.execute(query = query_test, connection = connection_test)
        pandahouse.to_clickhouse(new_table, 'ebobylev_table1', index = False, connection = connection_test)
    
    df_cube_feedaction = extract_feedaction()
    df_message_actions = extract_message_actions()
    merge_table = merge_table(df_cube_feedaction,df_message_actions)
    
    group_gender = group_gender(merge_table)
    group_age = group_age(merge_table)
    group_os = group_os(merge_table)
    new_table = concat_df(group_gender, group_age, group_os)
    upload = load_to_CH(new_table)

    
ebobylev_metriсs2 = ebobylev_metriсs2()
    
    

    
