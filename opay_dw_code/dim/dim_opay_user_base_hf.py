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

args = {
    'owner': 'xiedong',
    'start_date': datetime(2020, 2, 20),
    'depends_on_past': False,
    'retries': 3,
    'retry_delay': timedelta(minutes=2),
    'email': ['bigdata_dw@opay-inc.com'],
    'email_on_failure': True,
    'email_on_retry': False,
}

dag = airflow.DAG('dim_opay_user_base_hf',
                  schedule_interval="03 23 19 02 *",
                  default_args=args,
                  catchup=False)

config = eval(Variable.get("utc_locale_time_config"))
time_zone = config['NG']['time_zone']

##----------------------------------------- 依赖 ---------------------------------------##
### 检查上一个小时的本地时间依赖
dim_opay_user_base_hf_pre_locale_task = OssSensor(
    task_id='dim_opay_user_base_hf_pre_locale_task',
    bucket_key='{hdfs_path_str}/country_code=NG/dt={pt}/hour={hour}/_SUCCESS'.format(
        hdfs_path_str="opay/opay_dw/dim_opay_user_base_hf",
        pt='{{{{(execution_date+macros.timedelta(hours=({time_zone}+{gap_hour}))).strftime("%Y-%m-%d")}}}}'.format(time_zone=time_zone,gap_hour=-1),
        hour='{{{{(execution_date+macros.timedelta(hours=({time_zone}+{gap_hour}))).strftime("%H")}}}}'.format(time_zone=time_zone,gap_hour=-1)
    ),
    bucket_name='opay-datalake',
    poke_interval=60,  # 依赖不满足时，一分钟检查一次依赖状态
    dag=dag
)
### 检查当前小时的分区依赖
ods_opay_user_base_hi_check_task = OssSensor(
        task_id='ods_opay_user_base_hi_check_task',
        bucket_key='{hdfs_path_str}/dt={pt}/hour={hour}/_SUCCESS'.format(
            hdfs_path_str="opay_binlog/opay_user_db.opay_user.user",
            pt='{{ds}}',
            hour='{{ execution_date.strftime("%H") }}'
        ),
        bucket_name='opay-datalake',
        poke_interval=60,  # 依赖不满足时，一分钟检查一次依赖状态
        dag=dag
    )

##----------------------------------------- 任务超时监控 ---------------------------------------##
# def fun_task_timeout_monitor(ds, dag, **op_kwargs):
#     dag_ids = dag.dag_id
#
#     msg = [
#         {"dag": dag, "db": "opay_dw", "table": "{dag_name}".format(dag_name=dag_ids),
#          "partition": "country_code=NG/dt=2020-02-20/hour=00".format(pt=ds), "timeout": "3000"}
#     ]
#
#     TaskTimeoutMonitor().set_task_monitor(msg)
#
#
# task_timeout_monitor = PythonOperator(
#     task_id='task_timeout_monitor',
#     python_callable=fun_task_timeout_monitor,
#     provide_context=True,
#     dag=dag
# )

##----------------------------------------- 变量 ---------------------------------------##
db_name = "opay_dw"

table_name = "dim_opay_user_base_hf"
hdfs_path = "oss://opay-datalake/opay/opay_dw/" + table_name


def dim_opay_user_base_hf_sql_task(ds):
    HQL = '''
    CREATE temporary FUNCTION localeTime AS 'com.udf.dev.LocaleUDF' USING JAR 'oss://opay-datalake/test/pro_dev.jar';
    CREATE temporary FUNCTION maxLocalTimeRange AS 'com.udf.dev.MaxLocaleUDF' USING JAR 'oss://opay-datalake/test/pro_dev.jar';
    CREATE temporary FUNCTION minLocalTimeRange AS 'com.udf.dev.MinLocaleUDF' USING JAR 'oss://opay-datalake/test/pro_dev.jar';
    set hive.exec.dynamic.partition.mode=nonstrict;
    set hive.exec.parallel=true;
    insert overwrite table {db}.{table} partition (country_code, dt, hour)
    
    select 
        id,
        user_id,
        mobile,
        business_name,
        first_name,
        middle_name,
        surname,
        kyc_level,
        kyc_update_time,
        bvn,
        birthday,
        gender,
        country,
        STATE,
        city,
        address,
        lga,
        ROLE,
        referral_code,
        referrer_code,
        notification,
        create_time,
        update_time,
        register_client,
          agent_referrer_code,
          photo,
          big_picture,
          nick_name,
        date_format('{pt}', 'yyyy-MM-dd HH') as utc_date_hour,
        country_code,
        date_format(localeTime("{config}", country_code, '{pt}', 0), 'yyyy-MM-dd') as dt,
        hour(localeTime("{config}", country_code, '{pt}', 0)) as hour
    from (
        select 
            id,
            user_id,
            mobile,
            business_name,
            first_name,
            middle_name,
            surname,
            kyc_level,
            kyc_update_time,
            bvn,
            birthday,
            gender,
            country,
            STATE,
            city,
            address,
            lga,
            ROLE,
            referral_code,
            referrer_code,
            notification,
            create_time,
            update_time,
            register_client,
            agent_referrer_code,
            photo,
            big_picture,
            nick_name,
            country_code,
            row_number() over(partition by user_id order by update_time desc) rn
        from (
            SELECT 
               id,
               user_id,
               mobile,
               business_name,
               first_name,
               middle_name,
               surname,
               kyc_level,
               kyc_update_time,
               bvn,
               birthday,
               gender,
               country,
               STATE,
               city,
               address,
               lga,
               ROLE,
               referral_code,
               referrer_code,
               notification,
               create_time,
               update_time,
               register_client,
               agent_referrer_code,
               photo,
               big_picture,
               nick_name,
               country_code
            from opay_dw.dim_opay_user_base_hf 
            where concat(dt, " ", hour) between minLocalTimeRange("{config}", '{pt}', -1) and maxLocalTimeRange("{config}", '{pt}', -1) 
                and utc_date_hour = from_unixtime(cast(unix_timestamp('{pt}', 'yyyy-MM-dd HH') - 3600 as BIGINT), 'yyyy-MM-dd HH')
            union all
            SELECT 
                id,
                user_id,
                mobile,
                business_name,
                first_name,
                middle_name,
                surname,
                kyc_level,
                kyc_update_time,
                bvn,
                dob as birthday,
                gender,
                country,
                STATE,
                city,
                address,
                lga,
                ROLE,
                referral_code,
                referrer_code,
                notification,
                localeTime("{config}", 'NG', create_time, 0) as create_time,
                localeTime("{config}", 'NG', update_time, 0) as update_time,
                register_client,
                agent_referrer_code,
                photo,
                big_picture,
                nick_name,
                'NG' AS country_code
            from opay_dw_ods.ods_binlog_base_user_hi 
            where concat(dt, " ", hour) = date_format('{pt}', 'yyyy-MM-dd HH') and `__deleted` = 'false'
        ) t0 
    ) t1 where rn = 1
    
    
    '''.format(
        pt=ds,
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

    # hive_hook = HiveCliHook()

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
            "is_result_force_exist": "true",
            "execute_time": v_date,
            "is_hour_task": "true",
            "frame_type": "local"
        }
    ]

    cf = CountriesPublicFrame_dev(args)

    # 删除分区
    # cf.delete_partition()

    # 读取sql
    # _sql="\n"+cf.alter_partition()+"\n"+test_dim_oride_city_sql_task(ds)

    # logging.info('Executing: %s',_sql)

    # 执行Hive
    # hive_hook.run_cli(_sql)

    # 熔断数据，如果数据不能为0
    # check_key_data_cnt_task(ds)

    # 熔断数据
    # check_key_data_task(ds)

    # 生产success
    cf.touchz_success()


dim_opay_user_base_hf_task = PythonOperator(
    task_id='dim_opay_user_base_hf_task',
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

dim_opay_user_base_hf_pre_locale_task >> dim_opay_user_base_hf_task
ods_opay_user_base_hi_check_task >> dim_opay_user_base_hf_task
