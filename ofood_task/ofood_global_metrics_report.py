# coding=utf-8

import airflow
from datetime import datetime, timedelta
from airflow.operators.bash_operator import BashOperator
from airflow.operators.python_operator import PythonOperator
from airflow.operators.hive_operator import HiveOperator
from airflow.utils.email import send_email
import logging
from airflow.models import Variable
from utils.connection_helper import get_hive_cursor
from plugins.comwx import ComwxApi
from constant.metrics_constant import *
from airflow.sensors.hive_partition_sensor import HivePartitionSensor
from utils.validate_metrics_utils import *


comwx = ComwxApi('wwd26d45f97ea74ad2', 'BLE_v25zCmnZaFUgum93j3zVBDK-DjtRkLisI_Wns4g', '1000011')

args = {
    'owner': 'linan',
    'start_date': datetime(2019, 6, 14),
    'depends_on_past': False,
    'retries': 1,
    'retry_delay': timedelta(minutes=5),
}

dag = airflow.DAG(
    'ofood_global_metrics_report',
    schedule_interval="20 03 * * *",
    default_args=args)



'''
校验分区代码
'''

validate_partition_data = PythonOperator(
    task_id='validate_partition_data',
    python_callable=validate_partition,
    provide_context=True,
    op_kwargs={
        # 验证table
        "table_names":
            [
                'ofood_dw_ods.ods_sqoop_base_jh_order_df',
                'ofood_dw_ods.ods_sqoop_base_jh_order_log_df ',
                'ofood_dw_ods.ods_sqoop_base_jh_waimai_order_df',
                'ofood_dw_ods.ods_sqoop_base_jh_shop_df',
                'ofood_dw_ods.ods_sqoop_base_jh_waimai_df',
                'ofood_dw_ods.ods_log_client_event_hi'
            ],
        # 任务名称
        "task_name": "ofood全局运营指标"
    },
    dag=dag
)


# 熔断阻塞流程
jh_order_validate_task = HivePartitionSensor(
    task_id="jh_order_validate_task",
    table="ods_sqoop_base_jh_order_df",
    partition="dt='{{ds}}'",
    schema="ofood_dw_ods",
    poke_interval=60,  # 依赖不满足时，一分钟检查一次依赖状态
    dag=dag
)


jh_order_log_validate_task = HivePartitionSensor(
    task_id="jh_order_log_validate_task",
    table="ods_sqoop_base_jh_order_log_df",
    partition="dt='{{ds}}'",
    schema="ofood_dw_ods",
    poke_interval=60,  # 依赖不满足时，一分钟检查一次依赖状态
    dag=dag
)



jh_waimai_order_validate_task = HivePartitionSensor(
    task_id="jh_waimai_order_validate_task",
    table="ods_sqoop_base_jh_waimai_order_df",
    partition="dt='{{ds}}'",
    schema="ofood_dw_ods",
    poke_interval=60,  # 依赖不满足时，一分钟检查一次依赖状态
    dag=dag
)


jh_shop_validate_task = HivePartitionSensor(
    task_id="jh_shop_validate_task",
    table="ods_sqoop_base_jh_shop_df",
    partition="dt='{{ds}}'",
    schema="ofood_dw_ods",
    poke_interval=60,  # 依赖不满足时，一分钟检查一次依赖状态
    dag=dag
)


jh_waimai_validate_task = HivePartitionSensor(
    task_id="jh_waimai_validate_task",
    table="ods_sqoop_base_jh_waimai_df",
    partition="dt='{{ds}}'",
    schema="ofood_dw_ods",
    poke_interval=60,  # 依赖不满足时，一分钟检查一次依赖状态
    dag=dag
)


client_event_validate_task = HivePartitionSensor(
    task_id="client_event_validate_task",
    table="ods_log_client_event_hi",
    partition="dt='{{ds}}'",
    schema="ofood_dw_ods",
    poke_interval=60,  # 依赖不满足时，一分钟检查一次依赖状态
    dag=dag
)


insert_ofood_global_metrics = HiveOperator(
    task_id='insert_ofood_global_metrics',
    hql='''
        with 
        order_data as 
        (
            select 
            o.day ,
            count(o.order_id) place_order_num,
            count(distinct(o.uid)) place_user_num,
            count(if(o.order_status = 8,o.order_id,null)) complete_num,
            count(distinct(if(o.order_status = 8,o.uid,null))) complete_user_num,
            count(distinct(if(o.order_status = 8,o.shop_id,null))) complete_merchant_num,
            count(distinct(o.shop_id)) legal_merchant_num,
            count(distinct if(olm.order_id is not null and o.order_status in (-1,-2,-3) and o.pay_status <> 0 and o.refund_status <> 0,o.order_id,null)) merchant_cancel_num,
            count(distinct if(olu.order_id is null and o.order_status in (-1,-2,-3) and o.pay_status <> 0 and o.refund_status <> 0,o.order_id,null)) user_cancel_num,
            sum(if(wo.order_id is not null and o.order_status = 8,wo.origin_product + wo.origin_package + wo.origin_delivery,0)) order_total_price_sum,
            sum(if(wo.order_id is not null and o.order_status = 8,wo.origin_product + wo.origin_package + wo.origin_delivery - order_youhui - first_youhui,0)) order_actual_price_sum,
            sum(if(wo.order_id is not null and o.order_status = 8,wo.first_roof + wo.roof_mj + wo.roof_delivery + wo.roof_capped + wo.roof_plat_coupon,0)) c_subsidy_price_sum
            from ofood_dw_ods.ods_sqoop_base_jh_order_df o
            left join (
                select 
                from_unixtime(dateline,'yyyyMMdd') day,
                order_id
                from ofood_dw_ods.ods_sqoop_base_jh_order_log_df
                where status = -1
                and from_unixtime(dateline,'yyyyMMdd') = '{{ ds_nodash }}'
                and `from`='shop'
                and dt = '{{ ds }}'   
            ) olm on  o.day = olm.day and o.order_id = olm.order_id
            left join (
                select 
                from_unixtime(dateline,'yyyyMMdd') day,
                order_id
                from 
                ofood_dw_ods.ods_sqoop_base_jh_order_log_df
                where status = -1
                and `from` in('system','shop','admin')
                and from_unixtime(dateline,'yyyyMMdd') = '{{ ds_nodash }}'
                and dt = '{{ ds }}'   
            ) olu on  o.day = olu.day and o.order_id = olu.order_id
            left join (
                select 
                order_id,
                origin_product,
                origin_package,
                origin_delivery,
                first_roof,
                roof_mj,
                roof_delivery,
                roof_capped,
                roof_plat_coupon 
                from 
                ofood_dw_ods.ods_sqoop_base_jh_waimai_order_df
                where dt = '{{ ds }}'
            ) wo on wo.order_id = o.order_id
            where o.dt = '{{ ds }}' and o.day = '{{ ds_nodash }}'
            group by o.day
        ),
        
        
        order_data_lfw as (
            select 
            from_unixtime(unix_timestamp('{{ ds_nodash }}', 'yyyyMMdd'),'yyyyMMdd') day,
            round(count(if(
            datediff('{{ ds }}', from_unixtime(unix_timestamp(cast(o.day as string),'yyyyMMdd'),'yyyy-MM-dd'))>0
            and datediff('{{ ds }}', from_unixtime(unix_timestamp(cast(o.day as string),'yyyyMMdd'),'yyyy-MM-dd'))<=28
            and from_unixtime(unix_timestamp(cast(o.day as string),'yyyyMMdd'),'u') = from_unixtime(unix_timestamp('{{ ds_nodash }}', 'yyyyMMdd'),'u'),
            order_id,null
            ))/4,0) lfw_place_order_num,
            round(count(if(
            datediff('{{ ds }}', from_unixtime(unix_timestamp(cast(o.day as string),'yyyyMMdd'),'yyyy-MM-dd'))>0
            and datediff('{{ ds }}', from_unixtime(unix_timestamp(cast(o.day as string),'yyyyMMdd'),'yyyy-MM-dd'))<=28
            and from_unixtime(unix_timestamp(cast(o.day as string),'yyyyMMdd'),'u') = from_unixtime(unix_timestamp('{{ ds_nodash }}', 'yyyyMMdd'),'u')
            and o.order_status = 8,
            order_id,null
            ))/4,0) lfw_complete_num,
        
            round(count(distinct if(
            datediff('{{ ds }}', from_unixtime(unix_timestamp(cast(o.day as string),'yyyyMMdd'),'yyyy-MM-dd'))>0
            and datediff('{{ ds }}', from_unixtime(unix_timestamp(cast(o.day as string),'yyyyMMdd'),'yyyy-MM-dd'))<=28
            and from_unixtime(unix_timestamp(cast(o.day as string),'yyyyMMdd'),'u') = from_unixtime(unix_timestamp('{{ ds_nodash }}', 'yyyyMMdd'),'u')
            and o.order_status = 8,
            shop_id,null
            ))/4,0) lfw_complete_merchant_num
        
            from ofood_dw_ods.ods_sqoop_base_jh_order_df o
            where dt = '{{ ds }}' 
            group by from_unixtime(unix_timestamp('{{ ds_nodash }}', 'yyyyMMdd'),'yyyyMMdd')
        ),
        
        
        
        --商户指标
        
        merchant_new as (
            select 
            from_unixtime(dateline,'yyyyMMdd') day,
            count(shop_id) new_register_merchant_num
            from ofood_dw_ods.ods_sqoop_base_jh_shop_df
            where  from_unixtime(dateline,'yyyyMMdd') = '{{ ds_nodash }}'
            and dt = '{{ ds }}'
            group by from_unixtime(dateline,'yyyyMMdd')
        ),
        
        
        merchant_alive as (
            select 
            from_unixtime(unix_timestamp('{{ ds_nodash }}', 'yyyyMMdd'),'yyyyMMdd') day,
            count(shop_id) total_alive_merchant_num
            from ofood_dw_ods.ods_sqoop_base_jh_waimai_df
            where  from_unixtime(dateline,'yyyyMMdd') <= '{{ ds_nodash }}'
            and closed = 0
            and  audit = 1
            and dt = '{{ ds }}'
            group by from_unixtime(unix_timestamp('{{ ds_nodash }}', 'yyyyMMdd'),'yyyyMMdd')
        ),
        
        
        --首次完单用户数
        
        new_user as (
            select 
            d.ft day,
            count(d.uid) first_complete_user_num
            from 
            (
                select 
                uid,
                DATE_FORMAT(from_unixtime(min(dateline)),'yyyyMMdd') ft 
                from ofood_dw_ods.ods_sqoop_base_jh_order_df
                where order_status = 8
                and dt = '{{ ds }}'
                group by uid
            ) d
            where d.ft = '{{ ds_nodash }}'
            group by d.ft
        ),
        
        
        event_data as (
            select 
            from_unixtime(unix_timestamp(dt,'yyyy-MM-dd'),'yyyyMMdd') day,
            count(distinct(if(event_name = 'ofood_show' ,user_id,null))) active_user_num,
            count(distinct(if(event_name = 'restaurant_detail_show' ,user_id,null))) enter_restaurant_num
            from ofood_dw_ods.ods_log_client_event_hi
            where dt = '{{ ds }}'
            and (event_name = 'ofood_show' or event_name = 'restaurant_detail_show')
            group by from_unixtime(unix_timestamp(dt,'yyyy-MM-dd'),'yyyyMMdd')
        )
        
        insert overwrite table  ofood_bi.ofood_order_global_daily_report partition (dt = '{{ ds }}')
        select 
        nvl(od.place_order_num,0),
        nvl(odl.lfw_place_order_num,0),
        nvl(od.place_user_num,0),
        nvl(od.complete_num,0),
        nvl(odl.lfw_complete_num,0),
        nvl(od.complete_user_num,0),
        nvl(od.complete_merchant_num,0),
        nvl(odl.lfw_complete_merchant_num,0),
        nvl(od.legal_merchant_num,0),
        nvl(od.merchant_cancel_num,0),
        nvl(od.user_cancel_num,0),
        nvl(od.order_total_price_sum,0),
        nvl(od.order_actual_price_sum,0),
        nvl(mn.new_register_merchant_num,0),
        nvl(ma.total_alive_merchant_num,0),
        nvl(nu.first_complete_user_num,0),
        nvl(ed.active_user_num,0),
        nvl(ed.enter_restaurant_num,0),
        nvl(od.c_subsidy_price_sum,0)
        
        from 
        order_data od 
        left join order_data_lfw odl on od.day = odl.day
        left join merchant_new mn on od.day = mn.day 
        left join merchant_alive ma on od.day = ma.day
        left join new_user nu on od.day = nu.day
        left join event_data ed on od.day = ed.day
        
        ;
        
        
        ''',
    schema='ofood_bi',
    dag=dag)


def send_report_email(ds_nodash, ds, **kwargs):
    cursor = get_hive_cursor()
    sql = '''
        
    select 
    from_unixtime(unix_timestamp(dt, 'yyyy-MM-dd'),'yyyyMMdd') as dt,
    from_unixtime(unix_timestamp(dt, 'yyyy-MM-dd'),'u') as week,
    place_order_num,
    lfw_place_order_num,
    complete_num,
    lfw_complete_num,
    complete_merchant_num,
    lfw_complete_merchant_num,
    concat(cast(nvl(round(complete_num * 100/place_order_num,2),0) as string),'%') complete_rate,
    new_register_merchant_num,
    total_alive_merchant_num,
    legal_merchant_num,
    concat(cast(nvl(round(legal_merchant_num * 100/total_alive_merchant_num,2),0) as string),'%') legal_merchant_rate,
    concat(cast(nvl(round(enter_restaurant_num * 100/active_user_num,2),0) as string),'%') restaurant_transfer_rate,
    concat(cast(nvl(round(place_user_num * 100/enter_restaurant_num,2),0) as string),'%') place_order_transfer_rate,
    concat(cast(nvl(round((place_order_num - complete_num) * 100 / place_order_num,2),0) as string),'%') cancel_rate,
    concat(cast(nvl(round(merchant_cancel_num * 100 / place_order_num,2),0) as string),'%') merchant_cancel_rate,
    concat(cast(nvl(round(user_cancel_num * 100 / place_order_num,2),0) as string),'%') user_cancel_rate,
    active_user_num,
    enter_restaurant_num,
    place_user_num,
    complete_user_num,
    first_complete_user_num,
    concat(cast(nvl(round(first_complete_user_num * 100 /complete_user_num,2),0) as string),'%') first_complete_user_rate,
    order_total_price_sum,
    concat(cast(nvl(round((c_subsidy_price_sum) * 100 / order_total_price_sum,2),0) as string),'%') subsidy_rate,
    nvl(round(order_total_price_sum/complete_num,2),0) order_pay_avg,
    nvl(round(order_actual_price_sum/complete_num,2),0) order_pay_actual_avg
    
    from ofood_bi.ofood_order_global_daily_report
    where dt between  '{start_date}' and '{dt}'
    ORDER BY dt DESC
    '''.format(dt=ds,
               start_date=airflow.macros.ds_add(ds, -13))

    html_fmt = '''
           <html>
           <head>
           <title></title>
           <style type="text/css">
               table
               {{
                   font-family: "Trebuchet MS", Arial, Helvetica, sans-serif;
                   border-collapse: collapse;
                   margin: 0 auto;
                   text-align: left;
                   align:left;
               }}
               table td, table th
               {{
                   border: 1px solid #000000;
                   color: #000000;
                   height: 30px;
                   padding: 5px 10px 5px 5px;
               }}
               table thead th
               {{
                   background-color: #f9cb9c;
                   //color: white;
                   width: 100px;
                   color: #000000;
               }}
           </style>
           </head>
           <body>
               <table width="100%" class="table">
                   <caption>
                       <h3>ofood全局运营指标</h3>
                   </caption>
               </table>
               <table width="100%" class="table">
                   <thead>
                       <tr>
                           <th></th>
                           <th colspan="7" style="text-align: center;">关键指标</th>
                           <th colspan="6" style="text-align: center;">商户指标</th>
                           <th colspan="3" style="text-align: center;">服务指标</th>
                           <th colspan="6" style="text-align: center;">用户指标</th>
                           <th colspan="4" style="text-align: center;">财务</th>
                       </tr>
                       <tr>
                           <th>日期</th>
                           <!--关键指标-->
                           <th>下单数</th>
                           <th>下单数（近四周均值）</th>
                           <th>完单数</th>
                           <th>完单数（近四周均值）</th>
                           <th>完单商户</th>
                           <th>完单商户（近四周均值）</th>
                           <th>完单率</th>
                           <!--商户指标-->
                           <th>新注册商户数</th>
                           <th>总存活商户数</th>
                           <th>有订单商户数</th>
                           <th>动销率</th>
                           <th>平均进店转化率</th>
                           <th>平均下单转化率</th>
                           <!--服务指标-->
                           <th>订单取消率</th>
                           <th>商户原因取消订单率</th>
                           <th>用户原因取消订单率</th>
                           <!--用户指标-->
                           <th>活跃用户数</th>
                           <th>进店用户数</th>
                           <th>下单用户数</th>
                           <th>完单用户数</th>
                           <th>首次完单用户数</th>
                           <th>完单新客占比</th>
                           <!--财务-->
                           <th>GMV</th>
                           <th>C端补贴率</th>
                           <th>单均应付</th>
                           <th>单均实付</th>
                       </tr>
                   </thead>
                   <tbody>
                   {rows}
                   </tbody>
               </table>
           </body>
           </html>
           '''

    tr_fmt = '''
               <tr>{row}</tr>
           '''
    weekend_tr_fmt = '''
               <tr style="background:#fff2cc">{row}</tr>
           '''

    row_html = ''

    logging.info(sql)
    cursor.execute(sql)
    data_list = cursor.fetchall()

    if len(data_list) > 0:

        row_fmt = '''
                       <td>{0}</td>
                       <!--关键指标-->
                       <td>{2}</td>
                       <td>{3}</td>
                       <td>{4}</td>
                       <td>{5}</td>
                       <td>{6}</td>
                       <td>{7}</td>
                       <td>{8}</td>
                       <!--商户指标-->
                       <td>{9}</td>
                       <td>{10}</td>
                       <td>{11}</td>
                       <td>{12}</td>
                       <td>{13}</td>
                       <td>{14}</td>
                       <!--服务指标-->
                       <td>{15}</td>
                       <td>{16}</td>
                       <td>{17}</td>
                       <!--用户指标-->
                       <td>{18}</td>
                       <td>{19}</td>
                       <td>{20}</td>
                       <td>{21}</td>
                       <td>{22}</td>
                       <td>{23}</td>
                       <!--财务-->
                       <td>{24}</td>
                       <td>{25}</td>
                       <td>{26}</td>
                       <td>{27}</td>
               '''

        for data in data_list:
            row = row_fmt.format(*list(data))
            week = data[1]
            if week == '6' or week == '7':
                row_html += weekend_tr_fmt.format(row=row)
            else:
                row_html += tr_fmt.format(row=row)

    html = html_fmt.format(rows=row_html)

    logging.info(html)

    # send mail
    email_subject = 'ofood全局运营指标_{}'.format(ds)
    send_email(
        Variable.get("ofood_metrics_report_receivers").split()
        # ['nan.li@opay-inc.com']
        , email_subject, html, mime_charset='utf-8')
    cursor.close()
    return


send_report = PythonOperator(
    task_id='send_report',
    python_callable=send_report_email,
    provide_context=True,
    dag=dag
)


validate_partition_data >> jh_order_log_validate_task >> insert_ofood_global_metrics
validate_partition_data >> jh_order_validate_task >> insert_ofood_global_metrics
validate_partition_data >> jh_shop_validate_task >> insert_ofood_global_metrics
validate_partition_data >> jh_waimai_order_validate_task >> insert_ofood_global_metrics
validate_partition_data >> jh_waimai_validate_task >> insert_ofood_global_metrics
validate_partition_data >> client_event_validate_task >> insert_ofood_global_metrics
insert_ofood_global_metrics >> send_report
