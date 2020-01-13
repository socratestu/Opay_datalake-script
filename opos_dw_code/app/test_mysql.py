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
    'start_date': datetime(2019, 11, 24),
    'depends_on_past': False,
    'retries': 3,
    'retry_delay': timedelta(minutes=2),
    'email': ['bigdata_dw@opay-inc.com'],
    'email_on_failure': True,
    'email_on_retry': False,
}

dag = airflow.DAG('test_mysql',
                  schedule_interval="30 02 * * *",
                  default_args=args,
                  catchup=False)

db_name = "opos_dw"
table_name = "app_opos_shop_target_week_w"
hdfs_path = "oss://opay-datalake/opos/opos_dw/" + table_name


drop_mysql_yesterday_data = MySqlOperator(
    task_id='drop_mysql_yesterday_data',
    sql="""
        DELETE FROM opos_dw.app_opos_shop_target_week_w WHERE dt='{ds}';
    """.format(
        ds='{{ds}}',
        before_1_day ='{{ macros.ds_add(ds, -1) }}'
    ),
    mysql_conn_id='mysql_dw',
    dag=dag)

insert_mysql_today_data = HiveToMySqlTransfer(
    task_id='insert_mysql_today_data',
    sql="""
select
0 as id
,shop_id
,opay_id
,shop_name
,opay_account

,concat(
case 
when create_week=1 and cast(substr(dt,-2) as int)>8 then cast(cast(substr(dt,0,4) as int)+1 as string)
when create_week=53 and cast(substr(dt,-2) as int)<8 then cast(cast(substr(dt,0,4) as int)-1 as string)
else substr(dt,0,4)
end
,lpad(create_week,2,'0')
) as create_week

,city_code
,city_name
,country

,hcm_id
,hcm_name
,cm_id
,cm_name
,rm_id
,rm_name
,bdm_id
,bdm_name
,bd_id
,bd_name

,sum(nvl(order_cnt,0)) as order_cnt
,sum(nvl(cashback_order_cnt,0)) as cashback_order_cnt
,sum(nvl(cashback_fail_order_cnt,0)) as cashback_fail_order_cnt
,sum(nvl(cashback_order_gmv,0)) as cashback_order_gmv
,sum(nvl(cashback_per_order_amt,0)) as cashback_per_order_amt
,sum(nvl(cashback_per_people_amt,0)) as cashback_per_people_amt
,sum(nvl(cashback_people_cnt,0)) as cashback_people_cnt
,sum(nvl(cashback_first_people_cnt,0)) as cashback_first_people_cnt
,sum(nvl(cashback_zero_order_cnt,0)) as cashback_zero_order_cnt
,sum(nvl(cashback_amt,0)) as cashback_amt
,sum(nvl(reduce_order_cnt,0)) as reduce_order_cnt
,sum(nvl(reduce_zero_order_cnt,0)) as reduce_zero_order_cnt
,sum(nvl(reduce_amt,0)) as reduce_amt
,sum(nvl(reduce_order_gmv,0)) as reduce_order_gmv
,sum(nvl(reduce_people_cnt,0)) as reduce_people_cnt
,sum(nvl(reduce_first_people_cnt,0)) as reduce_first_people_cnt
,sum(nvl(bonus_order_cnt,0)) as bonus_order_cnt
,sum(nvl(order_people,0)) as order_people
,sum(nvl(not_first_order_people,0)) as not_first_order_people
,sum(nvl(first_order_people,0)) as first_order_people
,sum(nvl(first_bonus_order_people,0)) as first_bonus_order_people
,sum(nvl(order_gmv,0)) as order_gmv
,sum(nvl(bonus_order_gmv,0)) as bonus_order_gmv
,sum(nvl(bonus_order_amt,0)) as bonus_order_amt
,sum(nvl(sweep_amt,0)) as sweep_amt
,sum(nvl(bonus_order_people,0)) as bonus_order_people
,sum(nvl(bonus_order_times,0)) as bonus_order_times
,sum(nvl(order_create_cnt,0)) as order_create_cnt
,sum(nvl(order_pay_cnt,0)) as order_pay_cnt
,sum(nvl(order_fail_cnt,0)) as order_fail_cnt
,sum(nvl(order_pending_cnt,0)) as order_pending_cnt
,sum(nvl(coupon_order_cnt,0)) as coupon_order_cnt
,sum(nvl(coupon_order_people,0)) as coupon_order_people
,sum(nvl(coupon_first_order_people,0)) as coupon_first_order_people
,sum(nvl(coupon_pay_amount,0)) as coupon_pay_amount
,sum(nvl(coupon_order_gmv,0)) as coupon_order_gmv
,sum(nvl(coupon_discount_amount,0)) as coupon_discount_amount
,sum(nvl(coupon_useless_order_cnt,0)) as coupon_useless_order_cnt
,sum(nvl(coupon_useless_order_people,0)) as coupon_useless_order_people
,sum(nvl(coupon_useless_pay_amount,0)) as coupon_useless_pay_amount
,sum(nvl(coupon_useless_order_gmv,0)) as coupon_useless_order_gmv

,0 as bak1
,0 as bak2
,0 as bak3
,0 as bak4
,0 as bak5
,0 as bak6
,0 as bak7
,0 as bak8
,0 as bak9
,0 as bak10
,0 as bak11
,0 as bak12
,0 as bak13
,0 as bak14
,0 as bak15

,'-' as bak16
,'-' as bak17
,'-' as bak18
,'-' as bak19
,'-' as bak20

,'nal' as country_code
,'{ds}' as dt
from
opos_dw.app_opos_shop_target_d
where
country_code = 'nal'
and dt='{ds}'
group BY
shop_id
,opay_id
,shop_name
,opay_account

,concat(
case 
when create_week=1 and cast(substr(dt,-2) as int)>8 then cast(cast(substr(dt,0,4) as int)+1 as string)
when create_week=53 and cast(substr(dt,-2) as int)<8 then cast(cast(substr(dt,0,4) as int)-1 as string)
else substr(dt,0,4)
end
,lpad(create_week,2,'0')
)

,city_code
,city_name
,country

,hcm_id
,hcm_name
,cm_id
,cm_name
,rm_id
,rm_name
,bdm_id
,bdm_name
,bd_id
,bd_name

    """.format(
        ds='{{ds}}',
        before_1_day ='{{ macros.ds_add(ds, -1) }}'
    ),
    mysql_conn_id='mysql_dw',
    mysql_table='app_opos_shop_target_week_w',
    dag=dag)


drop_mysql_yesterday_data >> insert_mysql_today_data







