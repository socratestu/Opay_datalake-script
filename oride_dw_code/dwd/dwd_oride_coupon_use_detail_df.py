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
from plugins.TaskTouchzSuccess import TaskTouchzSuccess
from plugins.CountriesAppFrame import CountriesAppFrame
import json
import logging
from airflow.models import Variable
import requests
import os
from airflow.sensors import OssSensor

args = {
    'owner': 'lijialong',
    'start_date': datetime(2019, 10, 1),
    'depends_on_past': False,
    'retries': 3,
    'retry_delay': timedelta(minutes=2),
    'email': ['bigdata_dw@opay-inc.com'],
    'email_on_failure': True,
    'email_on_retry': False,
}

dag = airflow.DAG('dwd_oride_coupon_use_detail_df',
                  schedule_interval="00 02 * * *",
                  default_args=args,
                  )



##----------------------------------------- 变量 ---------------------------------------##

db_name="oride_dw"
table_name="dwd_oride_coupon_use_detail_df"

##----------------------------------------- 依赖 ---------------------------------------##

#获取变量
code_map=eval(Variable.get("sys_flag"))

#判断ufile(cdh环境)
if code_map["id"].lower()=="ufile":

    # 依赖前一天分区
    ods_sqoop_base_data_coupon_df_task = UFileSensor(
        task_id='ods_sqoop_base_data_coupon_df_task',
        filepath='{hdfs_path_str}/dt={pt}/_SUCCESS'.format(
            hdfs_path_str="oride_dw_sqoop/oride_data/data_coupon",
            pt='{{ds}}'
        ),
        bucket_name='opay-datalake',
        poke_interval=60,  # 依赖不满足时，一分钟检查一次依赖状态
        dag=dag
    )
    # 路径
    hdfs_path="ufile://opay-datalake/oride/oride_dw/"+table_name
else:
    print("成功")

    # 依赖前一天分区
    ods_sqoop_base_data_coupon_df_task = OssSensor(
        task_id='ods_sqoop_base_data_coupon_df_task',
        bucket_key='{hdfs_path_str}/dt={pt}/_SUCCESS'.format(
            hdfs_path_str="oride_dw_sqoop/oride_data/data_coupon",
            pt='{{ds}}'
        ),
        bucket_name='opay-datalake',
        poke_interval=60,  # 依赖不满足时，一分钟检查一次依赖状态
        dag=dag
    )
    # 路径
    hdfs_path = "oss://opay-datalake/oride/oride_dw/" + table_name


##----------------------------------------- 任务超时监控 ---------------------------------------## 
def fun_task_timeout_monitor(ds,dag,**op_kwargs):

    dag_ids=dag.dag_id

    msg = [
        {"dag":dag,"db": "oride_dw", "table":"{dag_name}".format(dag_name=dag_ids), "partition": "country_code=nal/dt={pt}".format(pt=ds), "timeout": "600"}
    ]

    TaskTimeoutMonitor().set_task_monitor(msg)



task_timeout_monitor = PythonOperator(
    task_id='task_timeout_monitor',
    python_callable=fun_task_timeout_monitor,
    provide_context=True,
    dag=dag
)

##----------------------------------------- 脚本 ---------------------------------------##

def dwd_oride_coupon_use_detail_df_sql_task(ds):

    HQL='''
        SET hive.exec.parallel=TRUE;
        SET hive.exec.dynamic.partition.mode=nonstrict;

        insert overwrite table oride_dw.{table} partition(country_code,dt)

        SELECT
            id as coupon_id,--券ID
            user_id as passenger_id,--用户ID
            order_id,--订单ID
            name,--优惠券名称
            amount,--面值 
            max_amount,--最大优惠金额 
            discount,--折扣 
            start_price,--最低使用金额 
            type,--1: 满减 2: 折扣 
            status,--状态(0: Receive 1:used) 
            source,--来源(0: 预热 1: 推广码) 
            if(start_time=0,0,(start_time + 1*60*60*1))  as start_time,--开始时间 
            if(expire_time=0,0,(expire_time + 1*60*60*1)) as expire_time ,--过期时间 
            if(used_time=0,0,(used_time + 1*60*60*1)) as used_time,--用户使用时间 
            if(receive_time = 0,0,(receive_time + 1*60*60*1)) as receive_time,--领取时间 
            template_id,--模版ID 
            city_id,--城市ID(0: all) 
            serv_type as product_id,--可用服务类型 
            is_popped,--是否已推送
            'nal' as country_code,
            '{pt}' as dt
        FROM
            oride_dw_ods.ods_sqoop_base_data_coupon_df
        WHERE
            dt='{pt}'
        ;
'''.format(
        pt=ds,
        table=table_name,
        db=db_name
        )
    return HQL

#主流程
def execution_data_task_id(ds,dag,**kwargs):

    v_date=kwargs.get('v_execution_date')
    v_day=kwargs.get('v_execution_day')
    v_hour=kwargs.get('v_execution_hour')

    hive_hook = HiveCliHook()

    args = [
        {
            "dag": dag,
            "is_countries_online": "false",
            "db_name": db_name,
            "table_name": table_name,
            "data_oss_path": hdfs_path,
            "is_country_partition": "true",
            "is_result_force_exist": "false",
            "execute_time": v_date,
            "is_hour_task": "false",
            "frame_type": "local",
            "is_offset": "true",
            "execute_time_offset": -1,
            "business_key": "oride"
        }
    ]

    cf = CountriesAppFrame(args)

    # 读取sql
    _sql = "\n" + cf.alter_partition() + "\n" + dwd_oride_coupon_use_detail_df_sql_task(ds)

    logging.info('Executing: %s', _sql)

    # 执行Hive
    hive_hook.run_cli(_sql)

    # 生产success
    cf.touchz_success()


dwd_oride_coupon_use_detail_df_task = PythonOperator(
    task_id='dwd_oride_coupon_use_detail_df_task',
    python_callable=execution_data_task_id,
    provide_context=True,
    op_kwargs={
        'v_execution_date': '{{execution_date.strftime("%Y-%m-%d %H:%M:%S")}}',
        'v_execution_day': '{{execution_date.strftime("%Y-%m-%d")}}',
        'v_execution_hour': '{{execution_date.strftime("%H")}}'
    },
    dag=dag
)

ods_sqoop_base_data_coupon_df_task >> dwd_oride_coupon_use_detail_df_task
