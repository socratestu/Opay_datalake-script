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
from airflow.sensors.web_hdfs_sensor import WebHdfsSensor
from airflow.sensors import UFileSensor
from plugins.TaskTimeoutMonitor import TaskTimeoutMonitor
from plugins.TaskTouchzSuccess import TaskTouchzSuccess
from plugins.CountriesPublicFrame import CountriesPublicFrame
import json
import logging
from airflow.models import Variable
import requests
import os
from airflow.sensors import OssSensor

args = {
    'owner': 'lili.chen',
    'start_date': datetime(2020, 1, 8),
    'depends_on_past': False,
    'retries': 3,
    'retry_delay': timedelta(minutes=2),
    'email': ['bigdata_dw@opay-inc.com'],
    'email_on_failure': True,
    'email_on_retry': False,
}

dag = airflow.DAG('dwd_oride_order_base_di',
                  schedule_interval="20 00 * * *",
                  default_args=args,
                  )

##----------------------------------------- 变量 ---------------------------------------##

db_name = "oride_dw"
table_name = "dwd_oride_order_base_di"
hdfs_path = "oss://opay-datalake/oride/oride_dw/" + table_name

##----------------------------------------- 依赖 ---------------------------------------##
# 依赖前一天分区
ods_binlog_data_order_hi_prev_day_task = OssSensor(
    task_id='ods_binlog_base_data_order_hi_prev_day_task',
    bucket_key='{hdfs_path_str}/dt={pt}/hour=23/_SUCCESS'.format(
        hdfs_path_str="oride_binlog/oride_db.oride_data.data_order",
        pt='{{ds}}',
        now_day='{{macros.ds_add(ds, +1)}}'
    ),
    bucket_name='opay-datalake',
    poke_interval=60,  # 依赖不满足时，一分钟检查一次依赖状态
    dag=dag
)

# 依赖前一天分区
dwd_oride_order_payment_base_di_prev_day_task = OssSensor(
    task_id='dwd_oride_order_payment_base_di_prev_day_task',
    bucket_key='{hdfs_path_str}/dt={pt}/_SUCCESS'.format(
        hdfs_path_str="oride/oride_dw/dwd_oride_order_payment_base_di/country_code=nal",
        pt='{{ds}}'
    ),
    bucket_name='opay-datalake',
    poke_interval=60,  # 依赖不满足时，一分钟检查一次依赖状态
    dag=dag
)

# 依赖前一天分区
ods_sqoop_base_data_country_conf_df_prev_day_task = OssSensor(
        task_id='ods_sqoop_base_data_country_conf_df_prev_day_task',
        bucket_key='{hdfs_path_str}/dt={pt}/_SUCCESS'.format(
            hdfs_path_str="oride_dw_sqoop/oride_data/data_country_conf",
            pt='{{ds}}'
        ),
        bucket_name='opay-datalake',
        poke_interval=60,  # 依赖不满足时，一分钟检查一次依赖状态
        dag=dag
    )

##----------------------------------------- 任务超时监控 ---------------------------------------##

def fun_task_timeout_monitor(ds, dag, **op_kwargs):
    dag_ids = dag.dag_id

    tb = [
        {"dag":dag,"db": "oride_dw", "table": "{dag_name}".format(dag_name=table_name),
         "partition": "country_code=NG/dt={pt}".format(pt=ds), "timeout": "1500"}
    ]

    TaskTimeoutMonitor().set_task_monitor(tb)


task_timeout_monitor = PythonOperator(
    task_id='task_timeout_monitor',
    python_callable=fun_task_timeout_monitor,
    provide_context=True,
    dag=dag
)


##----------------------------------------- 脚本 ---------------------------------------##
##----------------------------------------订单表使用说明-------------------------------##
#！！！！由于数据迁移，oride订单表只支持从20200108号数据回溯
##------------------------------------------------------------------------------------##
def dwd_oride_order_base_di_sql_task(ds):
    hql = '''
SET hive.exec.parallel=TRUE;
SET hive.exec.dynamic.partition.mode=nonstrict;


INSERT overwrite TABLE oride_dw.{table} partition(country_code,dt)
SELECT base.id as order_id,
       --订单 ID

       nvl(city_id,-999) as city_id,
       --所属城市(-999 无效数据) 

       base.serv_type AS product_id,
       --订单车辆类型(0: 专快混合 1:driect[专车] 2: street[快车] 3:Otrike 99:招手停)

       user_id AS passenger_id,
       --乘客 ID

       start_name,
       --(用户下单时输入)起点名称

       start_lng,
       --(用户下单时输入)起点经度

       start_lat,
       --(用户下单时输入)起点纬度

       end_name,
       --(用户下单时输入)终点名称

       end_lng,
       --(用户下单时输入)终点经度

       end_lat,
       --(用户下单时输入)终点纬度

       duration,
       --订单持续时间

       distance,
       --订单距离

       basic_fare,
       --起步价

       dst_fare,
       -- 里程费

       dut_fare,
       -- 时长费

       dut_price,
       --时长价格

       dst_price,
       --距离价格

       base.price,
       -- 订单价格

       reward,
       -- 司机奖励

       base.driver_id,
       --司机 ID

       plate_num,
       --车牌号

       local_take_time as take_time,
       --接单(应答)时间

       local_wait_time as wait_time,
       --到达接送点时间

       local_pickup_time as pickup_time,
       --接到乘客时间

       local_arrive_time as arrive_time,
       --到达终点时间

       local_finish_time as finish_time,
       --订单(支付)完成时间

       cancel_role,
       --取消人角色(1: 用户, 2: 司机, 3:系统 4:Admin)

       local_cancel_time as cancel_time,
       --取消时间

       cancel_type,
       --取消原因类型

       null as cancel_reason,
       --取消原因

       base.status,
       --订单状态 (0: wait assign, 1: pick up passenger, 2: wait passenger, 3: send passenger, 4: arrive destination, 5: finished, 6: cancel)

       base.local_create_time as create_time,
       -- 创建时间

       fraud,
       --是否欺诈(0否1是)

       driver_serv_type,
       --司机服务类型(1: Direct 2:Street 3:Otrike)

       null as refund_before_pay,
       --支付前资金调整

       null as refund_after_pay,
       --支付后资金调整

       abnormal,
       --异常状态(0 否 1 逃单)

       null as flag_down_phone,
       --招手停上报手机号

       zone_hash,
       --所属区域 hash

       base.updated_time as updated_time,
       --最后更新时间

       from_unixtime(base.local_create_time,'yyyy-MM-dd') AS create_date,
       --创建日期(local_create_time,yyyy-MM-dd)

       (CASE
            WHEN base.driver_id <> 0 THEN 1
            ELSE 0
        END) AS is_td_request,
       --当天是否接单(应答)

       (CASE
            WHEN base.status IN (4,
                            5) THEN 1
            ELSE 0
        END) AS is_td_finish,
       --当天是否完单


       (CASE
            WHEN pickup_time <> 0 THEN pickup_time - take_time
            ELSE 0
        END) AS td_pick_up_dur,
       --当天接驾时长（秒）

       (CASE
            WHEN take_time <> 0 THEN take_time - base.create_time
            ELSE 0
        END) AS td_take_dur,
       --当天应答时长（秒）

       (CASE
            WHEN cancel_time>0
                 AND take_time > 0 THEN cancel_time - take_time
            ELSE 0
        END) AS td_cannel_pick_dur,
       --当天取消接驾时长（秒）

       (CASE
            WHEN pickup_time>0
                 AND wait_time > 0 THEN pickup_time - wait_time
            ELSE 0
        END) AS td_wait_dur,
       --当天等待上车时长（秒）


       (CASE
            WHEN arrive_time>0
                 AND take_time > 0 THEN arrive_time - take_time
            ELSE 0
        END) AS td_service_dur,
       --当天服务时长（秒）


       (CASE
            WHEN arrive_time>0
                 AND pickup_time > 0 THEN arrive_time - pickup_time
            ELSE 0
        END) AS td_billing_dur,
       --当天计费时长（秒）

       (CASE
            WHEN base.status = 5 
                 and finish_time>0
                 AND arrive_time > 0 THEN finish_time - arrive_time
            ELSE 0
        END) AS td_pay_dur,
       --当天支付时长(秒)

       (CASE
            WHEN base.status = 6
                 AND (cancel_role = 3
                      OR cancel_role = 4) THEN 1
            ELSE 0
        END) AS is_td_sys_cancel,
       --是否当天系统取消

       (CASE
            WHEN base.status = 6
                 AND base.driver_id = 0
                 AND cancel_role = 1 THEN 1
            ELSE 0
        END) AS is_td_passanger_before_cancel,
       --是否当天乘客应答前取消

       (CASE
            WHEN base.status = 6
                 AND base.driver_id <> 0
                 AND cancel_role = 1 THEN 1
            ELSE 0
        END) AS is_td_passanger_after_cancel,
       --是否当天乘客应答后取消

       (CASE
            WHEN base.status = 5 THEN 1
            ELSE 0
        END) AS is_td_finish_pay,
       --是否当天完成支付

       nvl(pay.amount,0) as pay_amount,
       --实付金额

       pay.`mode` as pay_mode,
       --支付方式（0: 未知, 1: 线下支付, 2: opay, 3: 余额）,

       pay.status as pay_status, --支付类型（0: 支付中, 1: 成功, 2: 失败） 

       '' as part_hour, --小时分区时间(yyyy-mm-dd HH)

       (CASE
            WHEN base.status = 6
                 AND base.driver_id <> 0
                 AND cancel_role = 2 THEN 1
            ELSE 0
        END) AS is_td_driver_after_cancel,
       --是否当天司机应答后取消

       (CASE
            WHEN base.status in (4,5) and arrive_time>0
                 AND pickup_time > 0 THEN arrive_time - pickup_time
            ELSE 0
        END) AS td_finish_billing_dur,
       --当天完单计费时长（分钟）

       (CASE
            WHEN base.driver_id <> 0 
            and take_time > 0 and finish_time>0 THEN finish_time - take_time
            ELSE 0
        END) AS td_finish_order_dur,
       --当天完成做单时长（分钟）  
       (CASE
            WHEN (base.status = 6 AND base.driver_id <> 0)
                THEN 1
            ELSE 0
        END) AS is_td_after_cancel,
       --是否当天应答后取消

       (CASE
           WHEN base.status =6   AND cancel_role = 1 AND base.driver_id != 0
                THEN cancel_time - take_time
            ELSE 0
        END) AS td_passanger_after_cancel_time_dur,
       --当天乘客应答后取消时长(秒)

       (CASE
           WHEN base.status =6   AND cancel_role = 2 
                THEN cancel_time - take_time
            ELSE 0
        END) AS td_driver_after_cancel_time_dur,
       --当天司机应答后取消平均时长（秒） 
       concat(base.serv_type,'_',driver_serv_type) as serv_union_type,  --业务类型，下单类型+司机类型(serv_type+driver_serv_type)
       pax_num, -- 乘客数量 
       base.tip,  --小费
       trip_id, --'行程 ID'
       null as is_strong_dispatch,  
       --是否强制派单1:是，0:否
       wait_carpool,--'是否在等在拼车'
       estimate_duration,  -- 预估时间                
       estimate_distance, -- 预估距离                
       estimate_price,  --  预估价格                              
       is_carpool, --是否拼车  
       falsify, --取消罚款
       falsify_get, --取消罚款实际获得
       falsify_driver_cancel, --司机取消罚款
       falsify_get_driver_cancel, --司机取消罚款用户实际获得
       wait_lng, --等待乘客上车位置经度
       wait_lat, --等待乘客上车位置纬度
       wait_in_radius, --是否在接驾范围内
       wait_distance, --等待乘客上车距离
       local_cancel_wait_payment_time as cancel_wait_payment_time,  --乘客取消待支付时间  
       premium_rate,  --溢价倍数
       original_price, --溢价前费用 
       premium_price_limit, --溢价金额上限
       premium_adjust_price, --溢价金额
       local_gov, --围栏ID
       estimate_id,  --预估价记录表id  
       gender, --性别:0.未设置 1.男 2.女
       base.surcharge, --服务费
       user_agree_surcharge, --用户是否同意服务费(1同意 2 不同意)
       take_lng, --司机接单位置经度
       take_lat, --司机接单位置纬度
       minimum_fare, --最低消费
       discount, --动态折扣(如:70，7折)
       discount_price_max, --可享受折扣金额上限.)
       driver_depart, --接单取消时骑手是否出发 0 已出发（默认） 1 未出发
       change_target, --否修改终点(0 no 1 yes) 
       user_version, --乘客端版本（发单）
       driver_version, --司机端版本（接单）
       pax_ratio, --乘客系数
       driver_ratio, --司机系数
       driver_fee_rate, --司机佣金费率
       driver_price, --司机价格
       driver_original_price, --司机原始价格
       original_distance, --实际距离
       driver_distance, --司机计价距离(乘以系数后)
       insurance_id,--保险活动id
       pax_insurance_price, --乘客保险费
       driver_insurance_price, --司机保险费
       insurance_deduct_type, --保险扣减库存状态(0.未扣减 1.乘客已扣减 2.司机已扣减 3.乘客司机均扣减)
       enter_code, --乘车码
       malice_brush_driver_deduct, --恶意刷单司机扣款
       malice_brush_user_reward,  --恶意刷单乘客奖励
       order_type, --订单类型 (0: 普通订单, 1: 顺路单)
       price_mode, --计价模式(0 范围 1 固定)
       pay.coupon_amount, 
       --使用的优惠券金额
       pay.bonus, 
       --使用的奖励金
       pay.balance,
       -- 使用的余额
       pay.opay_amount,
       --opay 支付的金额
       pay.tip_rake,
       --小费抽成 
       pay.surcharge as pay_surcharge,
       --服务费
       base.pay_type,
       --支付类型(0:收银台 1:auto pay)
       
       base.scramble,
       --是否抢单pk 0 否 1 是
       
       base.level,
       --司机等级
       
       base.is_use_level_fee_rate,
       -- 是否使用等级抽佣配置
       
       base.source_type,
       --'订单来源(0.默认oride 1.h5)
       
       if(base.cancel_time>0,(base.cancel_time - base.create_time),0) as td_ord_to_cancel_dur,
        --当天下单到取消时长
        
       if(base.wait_time>0 and base.take_time>0,(base.wait_time-base.take_time),0) as driver_arrive_car_point_dur,
        --司机接单到到达上车点时长
        
       if(base.arrive_time>0,(base.arrive_time-base.create_time),0) as ord_to_arrive_dur,
        --下单到送达总时长
        
       base.client_os,
       --乘客端操作系统
       
       nvl(country.country_code,'nal') as country_code,

       '{pt}' AS dt
FROM (select *
     from (SELECT *,
             if(t.create_time=0,0,(t.create_time + 1 * 60 * 60)) as local_create_time,
             if(t.take_time=0,0,(t.take_time + 1 * 60 * 60)) as local_take_time ,
             if(t.wait_time=0,0,(t.wait_time + 1 * 60 * 60)) as local_wait_time ,
             if(t.pickup_time=0,0,(t.pickup_time + 1 * 60 * 60)) as local_pickup_time ,
             if(t.arrive_time=0,0,(t.arrive_time + 1 * 60 * 60)) as local_arrive_time ,
             if(t.finish_time=0,0,(t.finish_time + 1 * 60 * 60)) as local_finish_time ,
             if(t.cancel_time=0,0,(t.cancel_time + 1 * 60 * 60)) as local_cancel_time ,
             if(t.cancel_wait_payment_time=0,0,(t.cancel_wait_payment_time + 1 * 60 * 60 * 1)) as local_cancel_wait_payment_time ,
             
             from_unixtime((unix_timestamp(regexp_replace(regexp_replace(t.updated_at,'T',' '),'Z',''))+3600),'yyyy-MM-dd HH:mm:ss') as updated_time,
             
             row_number() over(partition by t.id order by t.`__ts_ms` desc,t.`__file` desc,cast(t.`__pos` as int) desc) as order_by

        FROM oride_dw_ods.ods_binlog_base_data_order_hi t

        WHERE concat_ws(' ',dt,hour) BETWEEN '{bef_yes_day} 23' AND '{pt} 23' --取昨天1天数据与今天早上00数据

        AND (from_unixtime((t.create_time + 1 * 60 * 60 * 1),'yyyy-MM-dd') = '{pt}' 
              or 
              from_unixtime((unix_timestamp(regexp_replace(regexp_replace(t.updated_at,'T',' '),'Z',''))+3600),'yyyy-MM-dd')='{pt}'
             )
         ) t1
where --t1.`__deleted` = 'false' and  -- 由于订单每天会将30天之前的订单移动到data_order_history表中，因此移动走的打标为deleted，但是这些订单状态有改变是需留存的，因此不要限定删除条件
t1.order_by = 1) base
LEFT OUTER JOIN
(SELECT *
FROM oride_dw.dwd_oride_order_payment_base_di
WHERE dt = '{pt}' 
and from_unixtime(local_create_time,'yyyy-MM-dd')=dt) pay  --切换后只能保证当天下单或更新的订单对应的支付单是当天创建的才可以关联上【并且只保证当天下单当天产生支付的能准确关联】，如果要用支付表中的金额，建议自己关联
ON base.id=pay.order_id

left join
(SELECT *
   FROM oride_dw_ods.ods_sqoop_base_data_country_conf_df 
   WHERE dt='{pt}') country
on base.country_id=country.id;
'''.format(
        pt=ds,
        now_day=airflow.macros.ds_add(ds, +1),
        bef_yes_day=airflow.macros.ds_add(ds, -1),
        now_hour='{{ execution_date.strftime("%H") }}',
        table=table_name,
        db=db_name
    )
    return hql


def check_key_data_task(ds):
    # 主键重复校验
    HQL_DQC = '''
    SELECT count(1) as nm
    FROM
     (SELECT order_id,
             count(1) as cnt
      FROM oride_dw.{table}

      WHERE dt='{pt}'
      GROUP BY order_id HAVING count(1)>1) t1
    '''.format(
        pt=ds,
        now_day=airflow.macros.ds_add(ds, +1),
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


# 主流程
def execution_data_task_id(ds, **kwargs):
    v_date = kwargs.get('v_execution_date')
    v_day = kwargs.get('v_execution_day')
    v_hour = kwargs.get('v_execution_hour')

    hive_hook = HiveCliHook()

    """
        #功能函数
        alter语句: alter_partition
        删除分区: delete_partition
        生产success: touchz_success

        #参数
        第一个参数true: 所有国家是否上线。false 没有
        第二个参数true: 数据目录是有country_code分区。false 没有
        第三个参数true: 数据有才生成_SUCCESS false 数据没有也生成_SUCCESS 

        #读取sql
        %_sql(ds,v_hour)

        第一个参数ds: 天级任务
        第二个参数v_hour: 小时级任务，需要使用

    """

    cf = CountriesPublicFrame("true", ds, db_name, table_name, hdfs_path, "true", "true")

    # 删除分区
    cf.delete_partition()

    # 读取sql
    _sql = "\n" + cf.alter_partition() + "\n" + dwd_oride_order_base_di_sql_task(ds)

    logging.info('Executing: %s', _sql)

    # 执行Hive
    hive_hook.run_cli(_sql)

    # 熔断数据，如果数据不能为0
    # check_key_data_cnt_task(ds)

    # 熔断数据
    check_key_data_task(ds)

    # 生产success
    cf.touchz_success()


dwd_oride_order_base_di_task = PythonOperator(
    task_id='dwd_oride_order_base_di_task',
    python_callable=execution_data_task_id,
    provide_context=True,
    op_kwargs={
        'v_execution_date': '{{execution_date.strftime("%Y-%m-%d %H:%M:%S")}}',
        'v_execution_day': '{{execution_date.strftime("%Y-%m-%d")}}',
        'v_execution_hour': '{{execution_date.strftime("%H")}}'
    },
    dag=dag
)

ods_binlog_data_order_hi_prev_day_task >> dwd_oride_order_base_di_task
dwd_oride_order_payment_base_di_prev_day_task >> dwd_oride_order_base_di_task
ods_sqoop_base_data_country_conf_df_prev_day_task >> dwd_oride_order_base_di_task
