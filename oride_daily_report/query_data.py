# -*- coding: utf-8 -*-
from datetime import datetime, timedelta
import time
import csv
from utils.connection_helper import get_hive_cursor, get_db_conn, get_pika_connection, get_redis_connection
from utils.util import *
import smtplib
from email.mime.text import MIMEText
from email.header import Header
from email.mime.multipart import MIMEMultipart
from oride_daily_report.driver_data import get_driver_data
from airflow.models import Variable


sender = 'research@opay-inc.com'
password = 'G%4nlD$YCJol@Op'
# receivers = ['lichang.zhang@opay-inc.com']
receivers = Variable.get("oride_daily_report_receivers").split()

part_html1 = """<tr><td class="title_td">{key}</td>"""
part_html2 = """<td class="value_td">{val}</td>"""
part_html2_1 = """<td class="value_1_td">{val}</td>"""
part_html3 = """</tr>"""

css_style = '''
<style type="text/css">
.title_td{border:solid#000 1px;width:300px;overflow:hidden;text-align:center}
.value_td{border:solid#000 1px;width:100px;overflow:hidden;text-align:right}
.value_1_td{border:solid#000 1px;width:100px;overflow:hidden;text-align:center}
.table{border-collapse:collapse;border:none;}
</style>
'''
mail_msg_header = """
<html lang="en" dir="ltr">
  <head>
    <meta charset="utf-8">
    <title></title>
  </head>
  <body>
    <h3 style="color:#F00">The report will be offline, and the data will be subject to the new report. If you need the new report permissions, please contact jinping.yan@opay-inc.com. Detailed indicator definition reference https://docs.qq.com/sheet/DY215b3pud0V5Y0Jh?tab=tuo617&coord=D15%24D15%240%240%2416%240 , if there are new data needs, please contact  jinping.yan@opay-inc.com.</h3>
    <h4>The detail of driver analysis is in attachment.</h4>
    </br>
    <table class="table" cellpadding="5">
      <caption><h4>Oride {dt1} -- {dt2} Daily Report</h4></caption>
"""
mail_msg_tail = '''
    </table>
  </body>
</html>
'''


query1 = '''
select count(*) as call_num,
sum(if(status=5,1,0)) as success_num,
sum(if(status=5,price,0)) as gmv,
sum(if(driver_id=0,1,0) * if(status=6,1,0)) as cancel_before_dispatching_num,
sum(if(driver_id>0,1,0) * if(status=6,1,0) * if (cancel_role=1,1,0)) as cancel_after_dispatching_by_user_num,
sum(if(driver_id>0,1,0) * if(status=6,1,0) * if (cancel_role=2,1,0)) as cancel_after_dispatching_by_driver_num,
sum(if(pickup_time>=create_time,1,0)) as pickup_num,
sum(if(pickup_time>=create_time,pickup_time-create_time,0)) as pickup_total_time,
sum(if(take_time>=create_time,1,0)) as take_num,
sum(if(take_time>=create_time,take_time-create_time,0)) as take_total_time,
sum(if(status=5,reward,0)) as total_reward
FROM oride_db.data_order 
where dt = "{dt}" 
and
create_time BETWEEN unix_timestamp('{dt} 00:00:00') and unix_timestamp('{dt} 23:59:59')
'''

query2 = '''
select count(*) as pay_num,
sum(price) as total_price,
sum(price-amount) as total_c_discount,
sum(if(mode=1,1,0)) as offline_num
FROM 
(
select id from
oride_db.data_order
where dt = "{dt}"
and status=5
and create_time BETWEEN unix_timestamp('{dt} 00:00:00') and unix_timestamp('{dt} 23:59:59')
) a 
join
(
select * from
oride_db.data_order_payment
where dt = "{dt}"
) b
on a.id = b.id
'''

query4 = '''
select 
count(distinct(user_id)) as call_user_num,
count(distinct(user_id * `order`.is_finished)) - if(sum(if(user_id * `order`.is_finished = 0, 1, 0)) > 0, 1, 0) as finished_user_num,
count(distinct(user_id * `order`.is_finished * `user`.is_new)) - if(sum(if(user_id * `order`.is_finished * `user`.is_new = 0, 1, 0)) > 0, 1, 0) as new_finished_user_num
from
(
  SELECT user_id, driver_id, if(status=5,1,0) as is_finished
  FROM oride_db.data_order 
  where dt = "{dt}"
  and
  create_time BETWEEN unix_timestamp('{dt} 00:00:00') and unix_timestamp('{dt} 23:59:59')
) as `order`
join
(
    SELECT id,
    if(register_time BETWEEN unix_timestamp('{dt} 00:00:00') and unix_timestamp('{dt} 23:59:59'),1,0) as is_new
    FROM oride_db.data_user_extend
    where dt = "{dt}"
    and register_time <= unix_timestamp('{dt} 23:59:59')
) as `user`
on `order`.user_id = `user`.id
'''

query5 = '''
SELECT 
count(*),
sum(if(login_time BETWEEN unix_timestamp('{dt} 00:00:00') and unix_timestamp('{dt} 23:59:59'),1,0)) as login_num,
sum(if(register_time BETWEEN unix_timestamp('{dt} 00:00:00') and unix_timestamp('{dt} 23:59:59'),1,0)) as new_num
FROM oride_db.data_driver_extend
where dt = "{dt}"
and register_time <= unix_timestamp('{dt} 23:59:59')
'''

query6 = '''
select
count(distinct(driver_id)) as order_driver_num,
count(distinct(driver_id * `order`.is_finished)) - if(sum(if(driver_id * `order`.is_finished = 0, 1, 0)) > 0, 1, 0) as finished_driver_num,
count(distinct(driver_id * `order`.is_finished * `driver`.is_new)) - if(sum(if(driver_id * `order`.is_finished * `driver`.is_new = 0, 1, 0)) > 0, 1, 0) as new_finished_driver_num
from
(
  SELECT user_id, driver_id, if(status=5,1,0) as is_finished
  FROM oride_db.data_order 
  where dt = "{dt}"
  and
  create_time BETWEEN unix_timestamp('{dt} 00:00:00') and unix_timestamp('{dt} 23:59:59')
) as `order`
join
(
    SELECT id,
    if(register_time BETWEEN unix_timestamp('{dt} 00:00:00') and unix_timestamp('{dt} 23:59:59'),1,0) as is_new
    FROM oride_db.data_driver_extend
    where dt = "{dt}"
    and register_time <= unix_timestamp('{dt} 23:59:59')
) as driver
on `order`.driver_id = driver.id
'''

query7 = '''
select sum(if(action="bubble",1,0)) from oride_source.user_action where dt="{dt}"
'''

query9 = '''
SELECT 
sum(if(register_time BETWEEN unix_timestamp('{dt} 00:00:00') and unix_timestamp('{dt} 23:59:59'),1,0)) as new_num
FROM oride_db.data_user_extend
where dt = "{dt}"
and register_time <= unix_timestamp('{dt} 23:59:59')
'''

INSERT_SQL = '''
REPLACE INTO oride_data.daily_report VALUES (
%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 
%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 
%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 
%s, %s, %s, %s, %s, %s, %s)
'''

QUERY_DATA_RANGE = 8
QUERY_EMAIL_DATA = '''
select * from oride_data.daily_report where dt>="%s" and dt<="%s"
'''
col_meaning = ["Date", 'No. of completed ride', 'Fullfillment rate', 'No. of view', 'No. of request',
    'View to request transfer rate', 'Online rider', 'Accepted order rider', 'GMV', 'ASP', 'B-subsidy',
    'C-subsidy', 'Avg. B-sub per order', 'Avg. C-sub per order', 'Total subsidy ratio',
    'Cancel rate before rider accept', 'Cancel rate after rider accept',
    'Driver cancel rate (after driver accept)', 'ATA(min)', 'Avg order accept time(s)',
    'Total registered rider', 'New registered rider', 'Completed-order rider', 'New completed-order rider',
    'New completed-order rider ratio', 'No. of requested passenager', 'Completed order passenager',
    'New registered passenger', 'New completed order passenger',
    'New completed order passenger / Completed order passenager', 'New completed order passenger / New registered passenger',
    'No. of online order', 'No. of offine order',
    'Driver online with order time / Driver online time',
    'Driver online time / Driver work duration (15hours)',
    'Avg. Arrived Order per online driver'
    ]

not_show_indexs = [col_meaning.index("No. of view"), col_meaning.index("View to request transfer rate"),
                   col_meaning.index('Driver online time / Driver work duration (15hours)')]


def query_data(**op_kwargs):
    dt = op_kwargs.get('ds')
    cursor = get_hive_cursor()
    cursor.execute("set hive.execution.engine=tez")
    repair_table_names = ["data_driver_extend", "data_driver_reward",
                          "data_order", "data_order_payment", "data_user_extend",
                          "user_action", "client_event"]
    for name in repair_table_names:
        print(name)
        db_name = "oride_source."
        if name.startswith("data"):
            db_name = "oride_db."
        cursor.execute(repair_table_query % (db_name + name))
    cursor.execute(query1.format(dt=dt))
    res1 = cursor.fetchall()
    res1 = map(mapper, list(res1[0]))
    [call_num, success_num, gmv, cancel_before_dispatching_num, cancel_after_dispatching_by_user_num,
     cancel_after_dispatching_by_driver_num, pickup_num, pickup_total_time, take_num,
     take_total_time, total_driver_price] = res1
    print(1)
    cursor.execute(query2.format(dt=dt))
    res2 = cursor.fetchall()
    res2 = map(mapper, list(res2[0]))
    [pay_num, total_price, total_c_discount, offline_num] = res2
    print(2)
    cursor.execute(query4.format(dt=dt))
    res4 = cursor.fetchall()
    res4 = map(mapper, list(res4[0]))
    [call_user_num, finished_user_num, new_finished_user_num] = res4
    print(4)
    cursor.execute(query5.format(dt=dt))
    res5 = cursor.fetchall()
    res5 = map(mapper, list(res5[0]))
    [total_driver_num, login_driver_num, new_driver_num] = res5
    print(5)
    cursor.execute(query6.format(dt=dt))
    res6 = cursor.fetchall()
    res6 = map(mapper, list(res6[0]))
    [order_driver_num, finished_driver_num, new_finished_driver_num] = res6
    print(6)
    cursor.execute(query7.format(dt=dt))
    res7 = cursor.fetchall()
    res7 = map(mapper, list(res7[0]))
    [bubble_num] = res7
    print(7)
    cursor.execute(query9.format(dt=dt))
    res9 = cursor.fetchall()
    res9 = map(mapper, list(res9[0]))
    [new_passenger_num] = res9
    print(9)
    (transport_efficiency, avg_order_per_driver, online_driver_num) = get_driver_data(dt)
    print(10)
    data = [
        success_num,
        success_num / float(call_num) if call_num > 0 else 0,
        bubble_num,
        call_num,
        call_num / float(bubble_num) if bubble_num > 0 else 0,
        online_driver_num,
        order_driver_num,
        round(float(gmv), 2),
        round(float(gmv) / float(success_num) if success_num > 0 else 0, 2),
        round(float(total_driver_price), 2),
        round(float(total_c_discount), 2),
        round(float(total_driver_price) / float(success_num) if success_num > 0 else 0, 2),
        round(float(total_c_discount) / float(success_num) if success_num > 0 else 0, 2),
        float(total_driver_price + total_c_discount) / float(total_price) if total_price > 0 else 0,
        cancel_before_dispatching_num / float(call_num) if call_num > 0 else 0,
        cancel_after_dispatching_by_user_num / float(call_num) if call_num > 0 else 0,
        cancel_after_dispatching_by_driver_num / float(call_num) if call_num > 0 else 0,
        round(pickup_total_time / float(pickup_num * 60) if pickup_num > 0 else 0, 2),
        round(take_total_time / float(take_num) if take_num > 0 else 0, 2),
        total_driver_num,
        new_driver_num,
        finished_driver_num,
        new_finished_driver_num,
        new_finished_driver_num / float(finished_driver_num) if finished_driver_num > 0 else 0,
        call_user_num,
        finished_user_num,
        new_passenger_num,
        new_finished_user_num,
        new_finished_user_num / float(finished_user_num) if finished_driver_num > 0 else 0,
        new_finished_user_num / new_passenger_num if new_passenger_num > 0 else 0,
        pay_num - offline_num,
        offline_num,
        transport_efficiency,
        0,
        avg_order_per_driver
    ]
    insert_data = [None, dt] + data
    sql_conn = get_db_conn()
    sql_cursor = sql_conn.cursor()
    sql_cursor.execute(INSERT_SQL, insert_data)


def write_email(**op_kwargs):
    dt = op_kwargs.get('ds')
    init_day = n_days_ago(dt, QUERY_DATA_RANGE)
    sql_conn = get_db_conn()
    sql_cursor = sql_conn.cursor()
    sql_cursor.execute(QUERY_EMAIL_DATA % (init_day, dt))
    res = sql_cursor.fetchall()
    res = list(res)
    if len(res) < 1:
        return
    res = map(list, res)
    arr = []
    for elem in res:
        elem[1] = elem[1].strftime('%Y-%m-%d')
        arr.append(elem)
    arr.sort(key=lambda x: x[1], reverse=True)
    h = mail_msg_header.format(dt1=arr[0][1], dt2=arr[-1][1])
    for x in range(len(col_meaning)):
        if x in not_show_indexs:
            continue
        h += part_html1.format(key=col_meaning[x])
        for y in range(len(arr)):
            tmp_val = arr[y][x + 1]
            if tmp_val is None:
                tmp_val = "-"
            elif "ratio" in col_meaning[x] or "rate" in col_meaning[x] or "/" in col_meaning[x]:
                tmp_val = "%.2f%%" % (tmp_val * 100)
            h += part_html2.format(val=tmp_val) if x > 0 else part_html2_1.format(val=tmp_val)
        h += part_html3
    h += mail_msg_tail
    h += css_style
    message = MIMEMultipart()
    subject = 'Oride {dt1} -- {dt2} Daily Report'.format(dt1=arr[0][1], dt2=arr[-1][1])
    message['Subject'] = Header(subject, 'utf-8')
    message.attach(MIMEText(h, 'html', 'utf-8'))
    att1 = MIMEText(open("/tmp/%s_driver_data.csv" % dt, 'r').read(), 'plain', 'utf-8')
    att1["Content-Type"] = 'application/octet-stream'
    att1["Content-Disposition"] = 'attachment; filename="driver_stat_%s.csv"' % dt
    message.attach(att1)
    att2 = MIMEText(open("/tmp/%s_online_driver_num.csv" % dt, 'r').read(), 'plain', 'utf-8')
    att2["Content-Type"] = 'application/octet-stream'
    att2["Content-Disposition"] = 'attachment; filename="%s_online_driver_num.csv"' % dt
    message.attach(att2)
    try:
        server = smtplib.SMTP('mail.opay-inc.com', 25)
        server.ehlo()
        server.starttls()
        server.login(sender, password)
        server.sendmail(sender, receivers, message.as_string())
        print("邮件发送成功")
    except smtplib.SMTPException as e:
        print(e.message)
