# -*- coding: utf-8 -*-
import airflow
from datetime import datetime, timedelta
from airflow.operators.hive_operator import HiveOperator
from airflow.operators.impala_plugin import ImpalaOperator
from utils.connection_helper import get_hive_cursor
from airflow.operators.python_operator import PythonOperator
from airflow.contrib.hooks.redis_hook import RedisHook
from airflow.hooks.hive_hooks import HiveCliHook
from airflow.operators.hive_to_mysql import HiveToMySqlTransfer
from airflow.operators.mysql_operator import MySqlOperator
from airflow.operators.dagrun_operator import TriggerDagRunOperator
from airflow.sensors.external_task_sensor import ExternalTaskSensor
from airflow.operators.bash_operator import BashOperator
from airflow.sensors.named_hive_partition_sensor import NamedHivePartitionSensor
from airflow.sensors.hive_partition_sensor import HivePartitionSensor
from airflow.sensors import UFileSensor
import json
import logging
from airflow.models import Variable
import requests
import os

args = {
    'owner': 'linan',
    'start_date': datetime(2019, 5, 20),
    'depends_on_past': False,
    'retries': 3,
    'retry_delay': timedelta(minutes=2),
    'email': ['bigdata_dw@opay-inc.com'],
    'email_on_failure': True,
    'email_on_retry': False,
}

dag = airflow.DAG('dwd_oride_passanger_location_event_di',
                  schedule_interval="30 4 * * *",
                  default_args=args,
                  catchup=False)

sleep_time = BashOperator(
    task_id='sleep_id',
    depends_on_past=False,
    bash_command='sleep 10',
    dag=dag)

##----------------------------------------- 依赖 ---------------------------------------##


# 依赖前一小时分区
dwd_oride_passanger_location_event_hi_prev_day_task = HivePartitionSensor(
    task_id="dwd_oride_passanger_location_event_hi_prev_day_task",
    table="dwd_oride_passanger_location_event_hi",
    partition="""dt='{{ ds }}' and hour='23'""",
    schema="oride_dw",
    poke_interval=60,  # 依赖不满足时，一分钟检查一次依赖状态
    dag=dag
)

##----------------------------------------- 变量 ---------------------------------------##


table_name = "dwd_oride_passanger_location_event_di"
hdfs_path = "ufile://opay-datalake/oride/oride_dw/" + table_name

##----------------------------------------- 脚本 ---------------------------------------##

dwd_oride_passanger_location_event_di_task = HiveOperator(
    task_id='dwd_oride_passanger_location_event_di_task',
    hql='''
        SET hive.exec.parallel=TRUE;
        SET hive.exec.dynamic.partition.mode=nonstrict;

        insert overwrite table oride_dw.{table} partition(country_code,dt)
        
        select 
        order_id , 
        user_id  ,
        replace(concat_ws(',',collect_set(looking_for_a_driver_show_lat)),',','')  ,
        replace(concat_ws(',',collect_set(looking_for_a_driver_show_lng)),',','') ,
        replace(concat_ws(',',collect_set(successful_order_show_lat)),',','') ,
        replace(concat_ws(',',collect_set(successful_order_show_lng)),',','')  ,
        replace(concat_ws(',',collect_set(start_ride_show_lat)),',','') ,
        replace(concat_ws(',',collect_set(start_ride_show_lng)),',','') ,
        replace(concat_ws(',',collect_set(complete_the_order_show_lat)),',','') ,
        replace(concat_ws(',',collect_set(complete_the_order_show_lng)),',','') ,
        replace(concat_ws(',',collect_set(rider_arrive_show_lat)),',','') ,
        replace(concat_ws(',',collect_set(rider_arrive_show_lng)),',',''),
        
        
        'nal' as country_code,
        '{pt}' as dt
        
        
        from 
        oride_dw.dwd_oride_passanger_location_event_hi
        where dt = '{pt}'
        group by order_id ,
        user_id 

        ;


'''.format(
        pt='{{ds}}',
        now_day='{{ds}}',
        table=table_name
    ),
    dag=dag
)


def check_key_data(ds, **kargs):
    # 主键重复校验
    HQL_DQC = '''
    SELECT count(1) as nm
    FROM
     (SELECT order_id,
             user_id,
             count(1) as cnt
      FROM oride_dw.{table}

      WHERE dt='{pt}'
      GROUP BY 
      order_id,user_id 
      HAVING count(1)>1) t1
    '''.format(
        pt=ds,
        now_day=ds,
        table=table_name
    )

    cursor = get_hive_cursor()
    logging.info('Executing 主键重复校验: %s', HQL_DQC)

    cursor.execute(HQL_DQC)
    res = cursor.fetchone()

    if res[0] > 1:
        raise Exception("Error The primary key repeat !", res)
    else:
        print("-----> Notice Data Export Success ......")


# 主键重复校验
task_check_key_data = PythonOperator(
    task_id='check_data',
    python_callable=check_key_data,
    provide_context=True,
    dag=dag)

# 生成_SUCCESS
touchz_data_success = BashOperator(

    task_id='touchz_data_success',

    bash_command="""
    line_num=`$HADOOP_HOME/bin/hadoop fs -du -s {hdfs_data_dir} | tail -1 | awk '{{print $1}}'`

    if [ $line_num -eq 0 ]
    then
        echo "FATAL {hdfs_data_dir} is empty"
        exit 1
    else
        echo "DATA EXPORT Successed ......"
        $HADOOP_HOME/bin/hadoop fs -touchz {hdfs_data_dir}/_SUCCESS
    fi
    """.format(
        pt='{{ds}}',
        now_day='{{macros.ds_add(ds, +1)}}',
        hdfs_data_dir=hdfs_path + '/country_code=nal/dt={{ds}}'
    ),
    dag=dag)

dwd_oride_passanger_location_event_hi_prev_day_task >> sleep_time >> dwd_oride_passanger_location_event_di_task >> task_check_key_data >> touchz_data_success
