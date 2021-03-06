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
from plugins.CountriesPublicFrame import CountriesPublicFrame
from plugins.CountriesAppFrame import CountriesAppFrame
import json
import logging
from airflow.models import Variable
import requests
import os
from airflow.sensors import OssSensor

args = {
    'owner': 'lishuai',
    'start_date': datetime(2020, 3, 8),
    'depends_on_past': False,
    'retries': 3,
    'retry_delay': timedelta(minutes=2),
    'email': ['bigdata_dw@opay-inc.com'],
    'email_on_failure': True,
    'email_on_retry': False,
}

dag = airflow.DAG('dwd_oride_driver_rights_conf_df',
                  schedule_interval="00 02 * * *",
                  default_args=args)

##----------------------------------------- 依赖 ---------------------------------------##

ods_sqoop_base_data_driver_rights_conf_df_task = OssSensor(
    task_id='ods_sqoop_base_data_driver_rights_conf_df_task',
    bucket_key="{hdfs_path_str}/dt={pt}/_SUCCESS".format(
        hdfs_path_str="oride_dw_sqoop/oride_data/data_driver_rights_conf",

        pt="{{ds}}"
    ),
    bucket_name='opay-datalake',
    poke_interval=60,  # 依赖不满足时，一分钟检查一次依赖状态
    dag=dag
)

##----------------------------------------- 变量 ---------------------------------------##

db_name = "oride_dw"
table_name = "dwd_oride_driver_rights_conf_df"
hdfs_path = "oss://opay-datalake/oride/oride_dw/" + table_name


##----------------------------------------- 任务超时监控 ---------------------------------------##

def fun_task_timeout_monitor(ds, dag, **op_kwargs):
    dag_ids = dag.dag_id

    msg = [
        {"dag": dag, "db": "oride_dw", "table": "{dag_name}".format(dag_name=dag_ids),
         "partition": "country_code=nal/dt={pt}".format(pt=ds), "timeout": "800"}
    ]

    TaskTimeoutMonitor().set_task_monitor(msg)


task_timeout_monitor = PythonOperator(
    task_id='task_timeout_monitor',
    python_callable=fun_task_timeout_monitor,
    provide_context=True,
    dag=dag
)


##----------------------------------------- 脚本 ---------------------------------------##

def dwd_oride_driver_rights_conf_df_sql_task(ds):
    HQL = '''


    set hive.exec.parallel=true;
    set hive.exec.dynamic.partition.mode=nonstrict;
    CREATE TEMPORARY FUNCTION from_json AS 'brickhouse.udf.json.FromJsonUDF';
    
    INSERT overwrite TABLE oride_dw.{table} partition(country_code,dt)

    select
          id,
          serv_type,
          aa.city_id,
          from_unixtime(start_time),
          from_unixtime(end_time),
          status,
          bbb.driver_level,
          bbb.s_proportion,
          bbb.e_proportion,
          bbb.type_rules[0]["type"],
          bbb.type_rules[0]["type_proportion"],
          ccc.driver_level,
          ccc.type_rules[0]["type"],
          ccc.type_rules[0]["type_proportion"],
          'nal' as country_code,
          '{pt}' as dt
          from 
          oride_dw_ods.ods_sqoop_base_data_driver_rights_conf_df
          lateral view explode(split(substr(city_id,2,length(city_id)-2),',')) aa as city_id
          LATERAL VIEW EXPLODE(from_json(driver_rules,array(named_struct("driver_level",cast(1 as bigint),"s_proportion",cast(1 as double),"e_proportion",cast(1 as double),
          "type_rules",array(map("",1)))))) bb AS bbb
          LATERAL VIEW EXPLODE(from_json(new_driver_rules,array(named_struct("driver_level",cast(1 as bigint),"type_rules",array(map("",1)))))) cc AS ccc
          where dt='{pt}'

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
    _sql = "\n" + cf.alter_partition() + "\n" + dwd_oride_driver_rights_conf_df_sql_task(ds)

    logging.info('Executing: %s', _sql)

    # 执行Hive
    hive_hook.run_cli(_sql)

    # 生产success
    cf.touchz_success()

dwd_oride_driver_rights_conf_df_task = PythonOperator(
    task_id='dwd_oride_driver_rights_conf_df_task',
    python_callable=execution_data_task_id,
    provide_context=True,
    op_kwargs={
        'v_execution_date': '{{execution_date.strftime("%Y-%m-%d %H:%M:%S")}}',
        'v_execution_day': '{{execution_date.strftime("%Y-%m-%d")}}',
        'v_execution_hour': '{{execution_date.strftime("%H")}}'
    },
    dag=dag
)

ods_sqoop_base_data_driver_rights_conf_df_task >> dwd_oride_driver_rights_conf_df_task