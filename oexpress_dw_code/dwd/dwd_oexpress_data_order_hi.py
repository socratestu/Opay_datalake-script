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
from plugins.CountriesPublicFrame_dev import CountriesPublicFrame_dev

from plugins.TaskTouchzSuccess import TaskTouchzSuccess
import json
import logging
from airflow.models import Variable
import requests
import os
from utils.get_local_time import GetLocalTime

args = {
    'owner': 'yuanfeng',
    'start_date': datetime(2020, 4, 13),
    'depends_on_past': False,
    'retries': 3,
    'retry_delay': timedelta(minutes=2),
    'email': ['bigdata_dw@opay-inc.com'],
    'email_on_failure': True,
    'email_on_retry': False,
}

dag = airflow.DAG('dwd_oexpress_data_order_hi',
                  schedule_interval="40 * * * *",
                  default_args=args,
                  )

##----------------------------------------- 变量 ---------------------------------------##
db_name = "oexpress_dw"
table_name = "dwd_oexpress_data_order_hi"
hdfs_path = "oss://opay-datalake/oexpress/oexpress_dw/" + table_name
config = eval(Variable.get("oexpress_time_zone_config"))
time_zone = config['NG']['time_zone']

##----------------------------------------- 依赖 ---------------------------------------##
### 检查当前小时的分区依赖
###oss://opay-datalake/oexpress_all_hi/ods_binlog_base_data_order_all_hi
ods_binlog_base_data_order_all_hi_check_task = OssSensor(
    task_id='ods_binlog_base_data_order_all_hi_check_task',
    bucket_key='{hdfs_path_str}/dt={pt}/hour={hour}/_SUCCESS'.format(
        hdfs_path_str="oexpress_all_hi/ods_binlog_base_data_order_all_hi",
        pt='{{ds}}',
        hour='{{ execution_date.strftime("%H") }}'
    ),
    bucket_name='opay-datalake',
    poke_interval=60,  # 依赖不满足时，一分钟检查一次依赖状态
    dag=dag
)

##----------------------------------------- 任务超时监控 ---------------------------------------##
def fun_task_timeout_monitor(ds, dag, execution_date, **op_kwargs):
    dag_ids = dag.dag_id

    # 监控国家
    v_country_code = 'NG'

    # 时间偏移量
    v_gap_hour = 0

    v_date = GetLocalTime("oexpress", execution_date.strftime("%Y-%m-%d %H"), v_country_code, v_gap_hour)['date']
    v_hour = GetLocalTime("oexpress", execution_date.strftime("%Y-%m-%d %H"), v_country_code, v_gap_hour)['hour']

    # 小时级监控
    tb_hour_task = [
        {"dag": dag, "db": "oexpress_dw", "table": "{dag_name}".format(dag_name=dag_ids),
         "partition": "country_code={country_code}/dt={pt}/hour={now_hour}".format(country_code=v_country_code,
                                                                                   pt=v_date, now_hour=v_hour),
         "timeout": "3000"}
    ]

    TaskTimeoutMonitor().set_task_monitor(tb_hour_task)


task_timeout_monitor = PythonOperator(
    task_id='task_timeout_monitor',
    python_callable=fun_task_timeout_monitor,
    provide_context=True,
    dag=dag
)


def dwd_oexpress_data_order_hi_sql_task(ds, v_date):
    HQL = '''

set mapred.max.split.size=1000000;
set hive.exec.parallel=true;
set hive.exec.dynamic.partition.mode=nonstrict;
set hive.strict.checks.cartesian.product=false;

--1.将数据关联后插入最终表中
insert overwrite table oexpress_dw.dwd_oexpress_data_order_hi partition(country_code,dt,hour)
select
  id
  ,city_id
  ,create_user_id
  ,order_source
  ,sender_cell
  ,sender_first_name
  ,sender_last_name
  ,without_collect
  ,ori_hub_id
  ,ori_lat
  ,ori_lng
  ,ori_addr
  ,ori_detailed_addr
  ,receiver_cell
  ,receiver_first_name
  ,receiver_last_name
  ,dest_hub_id
  ,dest_lat
  ,dest_lng
  ,dest_addr
  ,dest_detailed_addr
  ,current_transport_id
  ,current_hold_record_id
  ,status
  ,confirm_time
  ,collected_time
  ,finish_time
  ,close_time
  ,cancel_time
  ,cancel_role
  ,cancel_comment
  ,product_category
  ,product_category_name
  ,basic_fee
  ,weight_fee
  ,insurance_fee
  ,pickup_fee
  ,tax_fee
  ,deliver_fee
  ,payment_method
  ,price
  ,weight
  ,volume
  ,comment
  ,delivery_code
  ,pickup_pic_url_list
  ,delivered_pic_url_list
  ,create_time
  ,update_time
  ,item_code
  ,cash_received
  ,use_universal_code

  ,date_format('{v_date}', 'yyyy-MM-dd HH') as utc_date_hour

  ,'NG' as country_code
  ,date_format(default.localTime("{config}", 'NG', '{v_date}', 0), 'yyyy-MM-dd') as dt
  ,date_format(default.localTime("{config}", 'NG', '{v_date}', 0), 'HH') as hour
from
  (
  select
    id
    ,city_id
    ,create_user_id
    ,order_source
    ,sender_cell
    ,sender_first_name
    ,sender_last_name
    ,without_collect
    ,ori_hub_id
    ,ori_lat
    ,ori_lng
    ,ori_addr
    ,ori_detailed_addr
    ,receiver_cell
    ,receiver_first_name
    ,receiver_last_name
    ,dest_hub_id
    ,dest_lat
    ,dest_lng
    ,dest_addr
    ,dest_detailed_addr
    ,current_transport_id
    ,current_hold_record_id
    ,status
    ,default.localTime("{config}",'NG',from_unixtime(cast(confirm_time as bigint),'yyyy-MM-dd HH:mm:ss'),0) as confirm_time
    ,default.localTime("{config}",'NG',from_unixtime(cast(collected_time as bigint),'yyyy-MM-dd HH:mm:ss'),0) as collected_time
    ,default.localTime("{config}",'NG',from_unixtime(cast(finish_time as bigint),'yyyy-MM-dd HH:mm:ss'),0) as finish_time
    ,default.localTime("{config}",'NG',from_unixtime(cast(close_time as bigint),'yyyy-MM-dd HH:mm:ss'),0) as close_time
    ,default.localTime("{config}",'NG',from_unixtime(cast(cancel_time as bigint),'yyyy-MM-dd HH:mm:ss'),0) as cancel_time
    ,cancel_role
    ,cancel_comment
    ,product_category
    ,product_category_name
    ,basic_fee
    ,weight_fee
    ,insurance_fee
    ,pickup_fee
    ,tax_fee
    ,deliver_fee
    ,payment_method
    ,price
    ,weight
    ,volume
    ,comment
    ,delivery_code
    ,pickup_pic_url_list
    ,delivered_pic_url_list
    ,default.localTime("{config}",'NG',from_unixtime(cast(create_time as bigint),'yyyy-MM-dd HH:mm:ss'),0) as create_time
    ,concat(substr(update_time,0,10),' ',substr(update_time,12,8)) as update_time
    ,item_code
    ,cash_received
    ,use_universal_code

    ,row_number() over(partition by id order by `__ts_ms` desc,`__file` desc,cast(`__pos` as int) desc) rn
  from
    oexpress_dw_ods.ods_binlog_base_data_order_all_hi
  where
    dt = date_format('{v_date}', 'yyyy-MM-dd')
    and hour= date_format('{v_date}', 'HH')
    and `__deleted` = 'false'
  ) as v1
where
  rn = 1
;


    '''.format(
        pt=ds,
        v_date=v_date,
        table=table_name,
        db=db_name,
        config=config

    )
    return HQL


# 主流程
def execution_data_task_id(ds, dag, **kwargs):
    v_date = kwargs.get('v_execution_date')
    v_day = kwargs.get('v_execution_day')
    v_hour = kwargs.get('v_execution_hour')

    hive_hook = HiveCliHook()

    """
        #功能函数
            alter语句: alter_partition()
            删除分区: delete_partition()
            生产success: touchz_success()

        #参数
            is_countries_online --是否开通多国家业务 默认(true 开通)
            db_name --hive 数据库的名称
            table_name --hive 表的名称
            data_oss_path --oss 数据目录的地址
            is_country_partition --是否有国家码分区,[默认(true 有country_code分区)]
            is_result_force_exist --数据是否强行产出,[默认(true 必须有数据才生成_SUCCESS)] false 数据没有也生成_SUCCESS 
            execute_time --当前脚本执行时间(%Y-%m-%d %H:%M:%S)
            is_hour_task --是否开通小时级任务,[默认(false)]
            frame_type --模板类型(只有 is_hour_task:'true' 时生效): utc 产出分区为utc时间，local 产出分区为本地时间,[默认(utc)]。

        #读取sql
            %_sql(ds,v_hour)

    """

    args = [
        {
            "dag": dag,
            "is_countries_online": "true",
            "db_name": db_name,
            "table_name": table_name,
            "data_oss_path": hdfs_path,
            "is_country_partition": "true",
            "is_result_force_exist": "false",
            "execute_time": v_date,
            "is_hour_task": "true",
            "frame_type": "local"
        }
    ]

    cf = CountriesPublicFrame_dev(args)

    # 读取sql
    _sql = "\n" + cf.alter_partition() + "\n" + dwd_oexpress_data_order_hi_sql_task(ds, v_date)

    logging.info('Executing: %s', _sql)

    # 执行Hive
    hive_hook.run_cli(_sql)

    # 生产success
    cf.touchz_success()


dwd_oexpress_data_order_hi_task = PythonOperator(
    task_id='dwd_oexpress_data_order_hi_task',
    python_callable=execution_data_task_id,
    provide_context=True,
    op_kwargs={
        'v_execution_date': '{{execution_date.strftime("%Y-%m-%d %H:%M:%S")}}',
        'v_execution_day': '{{execution_date.strftime("%Y-%m-%d")}}',
        'v_execution_hour': '{{execution_date.strftime("%H")}}',
        'owner': '{{owner}}'
    },
    dag=dag
)

ods_binlog_base_data_order_all_hi_check_task >> dwd_oexpress_data_order_hi_task


