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
import json
import logging
from airflow.models import Variable
import requests
import os

args = {
    'owner': 'yuanfeng',
    'start_date': datetime(2019, 11, 24),
    'depends_on_past': False,
    'retries': 3,
    'retry_delay': timedelta(minutes=2),
    'email': ['bigdata_dw@opay-inc.com'],
    'email_on_failure': True,
    'email_on_retry': False,
}

dag = airflow.DAG('app_opos_metrics_daily_history_d',
                  schedule_interval="10 04 * * *",
                  default_args=args,
                  catchup=False)

##----------------------------------------- 依赖 ---------------------------------------##

dwd_pre_opos_payment_order_di_task = UFileSensor(
    task_id='dwd_pre_opos_payment_order_di_task',
    filepath='{hdfs_path_str}/country_code=nal/dt={pt}/_SUCCESS'.format(
        hdfs_path_str="opos/opos_dw/dwd_pre_opos_payment_order_di",
        pt='{{ds}}'
    ),
    bucket_name='opay-datalake',
    poke_interval=60,  # 依赖不满足时，一分钟检查一次依赖状态
    dag=dag
)

ods_sqoop_base_bd_admin_users_df_task = UFileSensor(
    task_id='ods_sqoop_base_bd_admin_users_df_task',
    filepath='{hdfs_path_str}/dt={pt}/_SUCCESS'.format(
        hdfs_path_str="opos_dw_sqoop/opay_crm/bd_admin_users",
        pt='{{ds}}'
    ),
    bucket_name='opay-datalake',
    poke_interval=60,  # 依赖不满足时，一分钟检查一次依赖状态
    dag=dag
)

##----------------------------------------- 变量 ---------------------------------------##

db_name = "opos_dw"
table_name = "app_opos_metrics_daily_history_d"
hdfs_path = "ufile://opay-datalake/opos/opos_dw/" + table_name


##----------------------------------------- 任务超时监控 ---------------------------------------##

def fun_task_timeout_monitor(ds, dag, **op_kwargs):
    dag_ids = dag.dag_id

    tb = [
        {"db": "opos_dw", "table": "{dag_name}".format(dag_name=dag_ids),
         "partition": "country_code=nal/dt={pt}".format(pt=ds), "timeout": "600"}
    ]

    TaskTimeoutMonitor().set_task_monitor(tb)


task_timeout_monitor = PythonOperator(
    task_id='task_timeout_monitor',
    python_callable=fun_task_timeout_monitor,
    provide_context=True,
    dag=dag
)


##----------------------------------------- 脚本 ---------------------------------------##

def app_opos_metrics_daily_history_d_sql_task(ds):
    HQL = '''
    
    
    
--插入数据
set hive.exec.parallel=true;
set hive.exec.dynamic.partition.mode=nonstrict;

--每天将历史数据和最新一天的数据累加，计算后放入历史表中,因为会有新增的情况，故需要用fulljoin
insert overwrite table opos_dw.app_opos_metrics_daily_history_d partition(country_code,dt)
select
0 as id
,v3.week_of_year as create_week
,substr('{pt}',0,7) as create_month
,substr('{pt}',0,4) as create_year

,nvl(v1.hcm_id,0) as hcm_id
,nvl(hcm.name,'-') as hcm_name
,nvl(v1.cm_id,0) as cm_id
,nvl(cm.name,'-') as cm_name
,nvl(v1.rm_id,0) as rm_id
,nvl(rm.name,'-') as rm_name
,nvl(v1.bdm_id,0) as bdm_id
,nvl(bdm.name,'-') as bdm_name
,nvl(v1.bd_id,0) as bd_id
,nvl(bd.name,'-') as bd_name

,nvl(v1.city_id,'-') as city_id
,nvl(v2.name,'-') as city_name
,nvl(v2.country,'-') as country

,v1.his_pos_complete_order_cnt
,v1.his_qr_complete_order_cnt
,v1.his_complete_order_cnt
,v1.his_gmv
,v1.his_actual_amount
,v1.his_return_amount
,v1.his_new_user_cost
,v1.his_old_user_cost
,v1.his_return_amount_order_cnt
,v1.his_order_merchant_cnt
,v1.his_pos_order_merchant_cnt
,v1.his_user_active_cnt
,v1.his_pos_user_active_cnt
,v1.his_qr_user_active_cnt

,'nal' as country_code
,'{pt}' as dt
from
  (
  select 
  hcm_id
  ,cm_id
  ,rm_id
  ,bdm_id
  ,bd_id
  
  ,city_id
  
  ,nvl(count(if(order_type = 'pos',order_id,null)),0) as his_pos_complete_order_cnt
  ,nvl(count(if(order_type = 'qrcode',order_id,null)),0) as his_qr_complete_order_cnt
  ,nvl(count(order_id),0) as his_complete_order_cnt
  ,nvl(sum(nvl(org_payment_amount,0)),0) as his_gmv
  ,nvl(sum(nvl(pay_amount,0)),0) as his_actual_amount
  ,nvl(sum(nvl(return_amount,0)),0) as his_return_amount
  ,nvl(sum(if(first_order = '1',nvl(org_payment_amount,0) - nvl(pay_amount,0) + nvl(user_subsidy,0),0)),0) as his_new_user_cost
  ,nvl(sum(if(first_order <> '1',nvl(org_payment_amount,0) - nvl(pay_amount,0) + nvl(user_subsidy,0),0)),0) as his_old_user_cost
  ,nvl(count(if(return_amount > 0,order_id,null)),0) as his_return_amount_order_cnt
  
  ,count(distinct(receipt_id)) as his_order_merchant_cnt
  ,count(distinct(if(order_type = 'pos',receipt_id,null))) as his_pos_order_merchant_cnt
  ,count(distinct(sender_id)) as his_user_active_cnt
  ,count(distinct(if(order_type = 'pos',sender_id,null))) as his_pos_user_active_cnt
  ,count(distinct(if(order_type = 'qrcode',sender_id,null))) as his_qr_user_active_cnt
  
  from 
  opos_dw.dwd_pre_opos_payment_order_di as p
  where 
  country_code='nal' 
  and dt >= '2019-11-01' 
  and dt <= '{pt}' 
  and trade_status = 'SUCCESS'
  group by
  hcm_id
  ,cm_id
  ,rm_id
  ,bdm_id
  ,bd_id
  
  ,city_id
  ) as v1
left join
  (select id,name from opos_dw_ods.ods_sqoop_base_bd_admin_users_df where dt = '{pt}') as bd
  on v1.bd_id=bd.id
left join
  (select id,name from opos_dw_ods.ods_sqoop_base_bd_admin_users_df where dt = '{pt}') as bdm
  on v1.bdm_id=bdm.id
left join
  (select id,name from opos_dw_ods.ods_sqoop_base_bd_admin_users_df where dt = '{pt}') as rm
  on v1.rm_id=rm.id
left join
  (select id,name from opos_dw_ods.ods_sqoop_base_bd_admin_users_df where dt = '{pt}') as cm
  on v1.cm_id=cm.id
left join
  (select id,name from opos_dw_ods.ods_sqoop_base_bd_admin_users_df where dt = '{pt}') as hcm
  on v1.hcm_id=hcm.id
left join
  (select id,name,country from opos_dw_ods.ods_sqoop_base_bd_city_df where dt = '{pt}') as v2
on v1.city_id=v2.id
left join
  (select dt,week_of_year from public_dw_dim.dim_date where dt = '{pt}') as v3
on 1=1
;






'''.format(
        pt=ds,
        table=table_name,
        now_day='{{macros.ds_add(ds, +1)}}',
        db=db_name
    )
    return HQL


# 主流程
def execution_data_task_id(ds, **kargs):
    hive_hook = HiveCliHook()

    # 读取sql
    _sql = app_opos_metrics_daily_history_d_sql_task(ds)

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


app_opos_metrics_daily_history_d_task = PythonOperator(
    task_id='app_opos_metrics_daily_history_d_task',
    python_callable=execution_data_task_id,
    provide_context=True,
    dag=dag
)

dwd_pre_opos_payment_order_di_task >> app_opos_metrics_daily_history_d_task
ods_sqoop_base_bd_admin_users_df_task >> app_opos_metrics_daily_history_d_task

# 查看任务命令
# airflow list_tasks app_opos_metrics_daily_history_d -sd /home/feng.yuan/app_opos_metrics_daily_history_d.py
# 测试任务命令
# airflow test app_opos_metrics_daily_history_d app_opos_metrics_daily_history_d_task 2019-11-24 -sd /home/feng.yuan/app_opos_metrics_daily_history_d.py
