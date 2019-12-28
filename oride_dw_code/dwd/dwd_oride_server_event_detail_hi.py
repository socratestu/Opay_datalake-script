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
from plugins.TaskTimeoutMonitor import TaskTimeoutMonitor
from plugins.TaskTouchzSuccess import TaskTouchzSuccess
from airflow.sensors.s3_key_sensor import S3KeySensor

args = {
    'owner': 'linan',
    'start_date': datetime(2019, 10, 7),
    'depends_on_past': False,
    'retries': 3,
    'retry_delay': timedelta(minutes=2),
    'email': ['bigdata_dw@opay-inc.com'],
    'email_on_failure': True,
    'email_on_retry': False,
}

dag = airflow.DAG('dwd_oride_server_event_detail_hi',
                  schedule_interval="30 * * * *",
                  default_args=args,
                  catchup=False)

sleep_time = BashOperator(
    task_id='sleep_id',
    depends_on_past=False,
    bash_command='sleep 30',
    dag=dag)
##----------------------------------------- 变量 ---------------------------------------##

db_name = "oride_dw"
table_name = "dwd_oride_server_event_detail_hi"

##----------------------------------------- 依赖 ---------------------------------------##
#获取变量
code_map=eval(Variable.get("sys_flag"))

#判断ufile(cdh环境)
if code_map["id"].lower()=="ufile":

    # 依赖前一小时分区
    dependence_server_event_prev_hour_task = S3KeySensor(
        task_id="dependence_server_event_prev_hour_task",
        bucket_key='{hdfs_path_str}/dt={pt}/hour={hour}/_SUCCESS'.format(
            hdfs_path_str="oride_buried/ordm.server_event",
            pt='{{ds}}',
            hour='{{ execution_date.strftime("%H") }}'
        ),
        bucket_name='opay-bi',
        poke_interval=60,  # 依赖不满足时，一分钟检查一次依赖状态
        dag=dag
    )
    hdfs_path = "ufile://opay-datalake/oride/oride_dw/" + table_name

else:
    print("成功")
    dependence_server_event_prev_hour_task = S3KeySensor(
        task_id="dependence_server_event_prev_hour_task",
        bucket_key='{hdfs_path_str}/dt={pt}/hour={hour}/_SUCCESS'.format(
            hdfs_path_str="oride_buried/ordm.server_event",
            pt='{{ds}}',
            hour='{{ execution_date.strftime("%H") }}'
        ),
        bucket_name='opay-bi',
        poke_interval=60,  # 依赖不满足时，一分钟检查一次依赖状态
        dag=dag
    )
    hdfs_path = "oss://opay-datalake/oride/oride_dw/" + table_name

##----------------------------------------- 任务超时监控 ---------------------------------------##

def fun_task_timeout_monitor(ds, execution_date, dag, **op_kwargs):
    dag_ids = dag.dag_id

    tb = [
        {"db": "oride_dw", "table": "{dag_name}".format(dag_name=dag_ids),
         "partition": "country_code=nal/dt={pt}/hour={hour}".format(pt=ds, hour=execution_date.strftime("%H")),
         "timeout": "600"}
    ]

    TaskTimeoutMonitor().set_task_monitor(tb)


task_timeout_monitor = PythonOperator(
    task_id='task_timeout_monitor',
    python_callable=fun_task_timeout_monitor,
    provide_context=True,
    dag=dag
)


##----------------------------------------- 脚本 ---------------------------------------##


def dwd_oride_server_event_detail_hi_sql_task(ds, execution_date):
    HQL = '''
    set hive.exec.parallel=true;
    set hive.exec.dynamic.partition.mode=nonstrict;

    INSERT OVERWRITE TABLE {db}.{table} partition(country_code,dt,hour)
    SELECT  ip
           ,server_ip
           ,`timestamp`
           ,common.user_id
           ,common.user_number
           ,common.client_timestamp
           ,common.platform
           ,common.os_version
           ,common.app_name
           ,common.app_version
           ,common.locale
           ,common.device_id
           ,common.device_screen
           ,common.device_model
           ,common.device_manufacturer
           ,common.is_root
           ,common.channel
           ,common.subchannel
           ,common.gaid
           ,common.appsflyer_id
           ,e.event_time
           ,e.event_name
           ,e.page
           ,e.source
           ,e.event_value
           ,'nal' AS country_code
           ,dt
           ,hour
    FROM oride_source.server_event LATERAL VIEW EXPLODE
    (events
    ) es AS e
    WHERE dt='{now_day}' 
    AND hour='{now_hour}' 
    ;

'''.format(
        pt=ds,
        now_day=ds,
        now_hour=execution_date.strftime("%H"),
        table=table_name,
        db=db_name
    )
    return HQL


# 主流程
def execution_data_task_id(ds, execution_date, **kargs):
    hive_hook = HiveCliHook()

    # 读取sql
    _sql = dwd_oride_server_event_detail_hi_sql_task(ds, execution_date)

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
    TaskTouchzSuccess().countries_touchz_success(ds, db_name, table_name, hdfs_path, "true", "false",
                                                 execution_date.strftime("%H"))


dwd_oride_server_event_detail_hi_task = PythonOperator(
    task_id='dwd_oride_server_event_detail_hi_task',
    python_callable=execution_data_task_id,
    provide_context=True,
    dag=dag
)

dependence_server_event_prev_hour_task >> sleep_time >> dwd_oride_server_event_detail_hi_task
