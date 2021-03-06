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
from plugins.TaskTimeoutMonitor import TaskTimeoutMonitor
from plugins.TaskTouchzSuccess import TaskTouchzSuccess
from airflow.sensors import OssSensor
import json
import logging
from airflow.models import Variable
import requests
import os

args = {
    'owner': 'yuanfeng',
    'start_date': datetime(2019, 10, 24),
    'depends_on_past': False,
    'retries': 3,
    'retry_delay': timedelta(minutes=2),
    'email': ['bigdata_dw@opay-inc.com'],
    'email_on_failure': True,
    'email_on_retry': False,
}

dag = airflow.DAG('dwd_active_user_month_di',
                  schedule_interval="00 02 1 * *",
                  default_args=args,
                  )

##----------------------------------------- 依赖 ---------------------------------------##

dwd_pre_opos_payment_order_di_task = OssSensor(
    task_id='dwd_pre_opos_payment_order_di_task',
    bucket_key='{hdfs_path_str}/country_code=nal/dt={pt}/_SUCCESS'.format(
        hdfs_path_str="opos/opos_dw/dwd_pre_opos_payment_order_di",
        pt='{{ds}}'
    ),
    bucket_name='opay-datalake',
    poke_interval=60,  # 依赖不满足时，一分钟检查一次依赖状态
    dag=dag
)

##----------------------------------------- 变量 ---------------------------------------##

db_name = "opos_dw"
table_name = "dwd_active_user_month_di"
hdfs_path = "oss://opay-datalake/opos/opos_dw/" + table_name


##----------------------------------------- 任务超时监控 ---------------------------------------##

def fun_task_timeout_monitor(ds, dag, **op_kwargs):
    dag_ids = dag.dag_id

    tb = [
        {"dag": dag, "db": "opos_dw", "table": "{dag_name}".format(dag_name=dag_ids),
         "partition": "country_code=nal/dt={pt}".format(pt=ds), "timeout": "1200"}
    ]

    TaskTimeoutMonitor().set_task_monitor(tb)


task_timeout_monitor = PythonOperator(
    task_id='task_timeout_monitor',
    python_callable=fun_task_timeout_monitor,
    provide_context=True,
    dag=dag
)


##----------------------------------------- 脚本 ---------------------------------------##

def dwd_active_user_month_di_sql_task(ds):
    HQL = '''


--插入数据
set hive.exec.parallel=true;
set hive.exec.dynamic.partition.mode=nonstrict;
set hive.strict.checks.cartesian.product=false;


--01.先求出本周有多少用户
with
sender_id as (
  select
  create_year
  ,create_month
  ,city_id
  ,sender_id
  from
  opos_dw.dwd_pre_opos_payment_order_di
  where
  country_code='nal' 
  and dt>='{pt}'
  and dt<=concat(substr('{pt}',0,7),'-31')
  and trade_status='SUCCESS'
  group by
  create_year
  ,create_month
  ,city_id
  ,sender_id
),

--02.再求首单用户
first_order_sender_id as (
  select
  create_year
  ,create_month
  ,city_id
  ,sender_id
  from
  opos_dw.dwd_pre_opos_payment_order_di
  where
  country_code='nal' 
  and dt>='{pt}'
  and dt<=concat(substr('{pt}',0,7),'-31')
  and trade_status='SUCCESS'
  and first_order='1'
  group by
  create_year
  ,create_month
  ,city_id
  ,sender_id
)

insert overwrite table opos_dw.dwd_active_user_month_di partition(country_code,dt)
select
a.create_year
,a.create_month
,a.city_id
,a.sender_id
,if(b.sender_id is null,'0','1') as first_order

,'nal' as country_code
,'{pt}' as dt
from
sender_id as a
left join
first_order_sender_id as b
on a.create_month=b.create_month
and a.city_id=b.city_id
and a.sender_id=b.sender_id;

--03.求有多少商铺
with
receipt_id as (
  select
  create_year
  ,create_month
  ,city_id
  ,receipt_id
  from
  opos_dw.dwd_pre_opos_payment_order_di
  where
  country_code='nal' 
  and dt>='{pt}'
  and dt<=concat(substr('{pt}',0,7),'-31')
  and trade_status='SUCCESS'
  group by
  create_year
  ,create_month
  ,city_id
  ,receipt_id
),

--04.求有多少新增商铺
first_order_receipt_id as (
  select
  create_year
  ,create_month
  ,city_id
  ,receipt_id
  from
  opos_dw.dwd_pre_opos_payment_order_di
  where
  country_code='nal' 
  and dt>='{pt}'
  and dt<=concat(substr('{pt}',0,7),'-31')
  and trade_status='SUCCESS'
  and substr(created_at,0,7)=substr('{pt}',0,7)
  group by
  create_year
  ,create_month
  ,city_id
  ,receipt_id
)

insert overwrite table opos_dw.dwd_active_shop_month_di partition(country_code,dt)
select
a.create_year
,a.create_month
,a.city_id
,a.receipt_id
,if(b.receipt_id is null,'0','1') as first_order

,'nal' as country_code
,'{pt}' as dt
from
receipt_id as a
left join
first_order_receipt_id as b
on a.create_month=b.create_month
and a.city_id=b.city_id
and a.receipt_id=b.receipt_id;



'''.format(
        pt=ds,
        before_7_day=airflow.macros.ds_add(ds, -7),
        table=table_name,
        now_day='{{macros.ds_add(ds, +1)}}',
        db=db_name
    )
    return HQL


# 主流程
def execution_data_task_id(ds, **kargs):
    hive_hook = HiveCliHook()

    # 读取sql
    _sql = dwd_active_user_month_di_sql_task(ds)

    logging.info('Executing: %s', _sql)

    # 执行Hive
    hive_hook.run_cli(_sql)

    # 熔断数据
    # check_key_data_task(ds)

    # 生成_SUCCESS
    """
    第一个参数true: 数据目录是有country_code分区。false 没有
    第二个参数true: 数据有才生成_SUCCESS false 数据没有也生成_SUCCESS 

    """
    TaskTouchzSuccess().countries_touchz_success(ds, db_name, table_name, hdfs_path, "true", "true")


dwd_active_user_month_di_task = PythonOperator(
    task_id='dwd_active_user_month_di_task',
    python_callable=execution_data_task_id,
    provide_context=True,
    dag=dag
)

dwd_pre_opos_payment_order_di_task >> dwd_active_user_month_di_task
# 查看任务命令
# airflow list_tasks dwd_active_user_month_di -sd /root/feng.yuan/dwd_active_user_month_di.py
# 测试任务命令
# airflow test dwd_active_user_month_di dwd_active_user_month_di_task 2019-11-28 -sd /root/feng.yuan/dwd_active_user_month_di.py


