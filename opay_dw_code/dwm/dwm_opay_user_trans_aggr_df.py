# -*- coding: utf-8 -*-
import airflow
from datetime import datetime, timedelta
from airflow.operators.hive_operator import HiveOperator
from airflow.operators.impala_plugin import ImpalaOperator
from utils.connection_helper import get_hive_cursor
from airflow.operators.python_operator import PythonOperator
from airflow.contrib.hooks.redis_hook import RedisHook
from airflow.hooks.hive_hooks import HiveCliHook, HiveServer2Hook
from airflow.operators.hive_to_mysql import HiveToMySqlTransfer
from airflow.operators.mysql_operator import MySqlOperator
from airflow.operators.dagrun_operator import TriggerDagRunOperator
from airflow.sensors.external_task_sensor import ExternalTaskSensor
from airflow.operators.bash_operator import BashOperator
from airflow.sensors.named_hive_partition_sensor import NamedHivePartitionSensor
from airflow.sensors.hive_partition_sensor import HivePartitionSensor
from airflow.sensors import UFileSensor
from plugins.TaskTimeoutMonitor import TaskTimeoutMonitor
from airflow.sensors import OssSensor

from plugins.TaskTouchzSuccess import TaskTouchzSuccess
import json
import logging
from airflow.models import Variable
import requests
import os

args = {
    'owner': 'xiedong',
    'start_date': datetime(2020, 3, 22),
    'depends_on_past': False,
    'retries': 3,
    'retry_delay': timedelta(minutes=2),
    'email': ['bigdata_dw@opay-inc.com'],
    'email_on_failure': True,
    'email_on_retry': False,
}

dag = airflow.DAG('dwm_opay_user_trans_aggr_df',
                  schedule_interval="40 01 * * *",
                  default_args=args,
                  )

##----------------------------------------- 依赖 ---------------------------------------##

dwd_opay_user_transaction_record_df_prev_day_task = OssSensor(
    task_id='dwd_opay_user_transaction_record_df_prev_day_task',
    bucket_key='{hdfs_path_str}/dt={pt}/_SUCCESS'.format(
        hdfs_path_str="opay/opay_dw/dwd_opay_user_transaction_record_df/country_code=NG",
        pt='{{ds}}'
    ),
    bucket_name='opay-datalake',
    poke_interval=60,  # 依赖不满足时，一分钟检查一次依赖状态
    dag=dag
)

##----------------------------------------- 任务超时监控 ---------------------------------------##
def fun_task_timeout_monitor(ds,dag,**op_kwargs):

    dag_ids=dag.dag_id

    msg = [
        {"dag":dag, "db": "opay_dw", "table":"{dag_name}".format(dag_name=dag_ids), "partition": "country_code=NG/dt={pt}".format(pt=ds), "timeout": "3000"}
    ]

    TaskTimeoutMonitor().set_task_monitor(msg)

task_timeout_monitor= PythonOperator(
    task_id='task_timeout_monitor',
    python_callable=fun_task_timeout_monitor,
    provide_context=True,
    dag=dag
)

##----------------------------------------- 变量 ---------------------------------------##
db_name = "opay_dw"

table_name = "dwm_opay_user_trans_aggr_df"
hdfs_path = "oss://opay-datalake/opay/opay_dw/" + table_name


def dwm_opay_user_trans_aggr_df_sql_task(ds):
    HQL = '''
    
    set mapred.max.split.size=1000000;
    set hive.exec.dynamic.partition.mode=nonstrict;
    set hive.exec.parallel=true;
    
    insert overwrite table {db}.{table} partition(country_code, dt)
    select 
        user_id,
        sum(if(date_format(create_time, 'yyyy-MM-dd') = date_format('{pt}', 'yyyy-MM-dd'), 1, 0)) as order_cnt_d,
        sum(if(order_status = 'SUCCESS' and date_format(create_time, 'yyyy-MM-dd') = date_format('{pt}', 'yyyy-MM-dd'), 1, 0)) as order_suc_cnt_d,
        sum(if(order_status = 'SUCCESS' and date_format(create_time, 'yyyy-MM-dd') = date_format('{pt}', 'yyyy-MM-dd'), amount, 0)) as order_suc_amt_d,
        
        sum(if(order_status = 'SUCCESS' and date_format(create_time, 'yyyy-MM-dd')
            between date_sub(next_day('{pt}', 'mo'), 7)  and date_sub(next_day('{pt}', 'mo'), 1), 1, 0)) as order_suc_cnt_w,
        sum(if(order_status = 'SUCCESS' and date_format(create_time, 'yyyy-MM-dd') 
            between date_sub(next_day('{pt}', 'mo'), 7)  and date_sub(next_day('{pt}', 'mo'), 1), amount, 0)) as order_suc_amt_w,
        
        sum(if(order_status = 'SUCCESS' and date_format(create_time, 'yyyy-MM') = date_format('{pt}', 'yyyy-MM'), 1, 0)) as order_suc_cnt_m,
        sum(if(order_status = 'SUCCESS' and date_format(create_time, 'yyyy-MM') = date_format('{pt}', 'yyyy-MM'), amount, 0)) as order_suc_amt_m,
        
        sum(if(order_status = 'SUCCESS' and date_format(create_time, 'yyyy') = date_format('{pt}', 'yyyy'), 1, 0)) as order_suc_cnt_y,
        sum(if(order_status = 'SUCCESS' and date_format(create_time, 'yyyy') = date_format('{pt}', 'yyyy'), amount, 0)) as order_suc_amt_y,
        
        sum(if(order_status = 'SUCCESS' and date_format(create_time, 'yyyy-MM-dd') between date_sub('{pt}', 7) and '{pt}', 1, 0)) as order_suc_cnt_7d,
        sum(if(order_status = 'SUCCESS' and date_format(create_time, 'yyyy-MM-dd') between date_sub('{pt}', 7) and '{pt}', amount, 0)) as order_suc_amt_7d,
    
        sum(if(order_status = 'SUCCESS' and date_format(create_time, 'yyyy-MM-dd') between date_sub('{pt}', 30) and '{pt}', 1, 0)) as order_suc_cnt_30d,
        sum(if(order_status = 'SUCCESS' and date_format(create_time, 'yyyy-MM-dd') between date_sub('{pt}', 30) and '{pt}', amount, 0)) as order_suc_amt_30d,
        
        count(*) as order_suc_cnt,
        sum(amount) as order_suc_amt,
        'NG' as country_code,
        '{pt}' as dt
    from opay_dw.dwd_opay_user_transaction_record_df
    where dt = if('{pt}' <= '2020-03-21', '2020-03-21', '{pt}') 
        and date_format(create_time, 'yyyy-MM-dd') >= date_sub('{pt}', 366) and user_id is not null and user_id != ''
    group by user_id
    '''.format(
        pt=ds,
        table=table_name,
        db=db_name
    )
    return HQL


def execution_data_task_id(ds, **kargs):
    hive_hook = HiveCliHook()

    # 读取sql
    _sql = dwm_opay_user_trans_aggr_df_sql_task(ds)

    logging.info('Executing: %s', _sql)

    # 执行Hive
    hive_hook.run_cli(_sql)

    # 生成_SUCCESS
    """
    第一个参数true: 数据目录是有country_code分区。false 没有
    第二个参数true: 数据有才生成_SUCCESS false 数据没有也生成_SUCCESS 

    """
    TaskTouchzSuccess().countries_touchz_success(ds, db_name, table_name, hdfs_path, "true", "true")


dwm_opay_user_trans_aggr_df_task = PythonOperator(
    task_id='dwm_opay_user_trans_aggr_df_task',
    python_callable=execution_data_task_id,
    provide_context=True,
    dag=dag
)

dwd_opay_user_transaction_record_df_prev_day_task >> dwm_opay_user_trans_aggr_df_task

