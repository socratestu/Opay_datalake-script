# -*- coding: utf-8 -*-
"""
监控任务执行是否超时
"""
from utils.connection_helper import get_hive_cursor
from plugins.comwx import ComwxApi
import logging
import os
import asyncio


"""
监控数据表分区产出的_SUCCESS文件
调用示例:
from plugins.TaskTimeoutMonitor import TaskTimeoutMonitor

def test_t11(**op_kwargs):
    sub = TaskTimeoutMonitor()
    tb = [
        {"db": "oride_dw", "table": "app_oride_driver_base_d", "partition": "aaaaa", "timeout": "60"},
        {"db": "oride_dw", "table": "app_oride_order_base_d", "partition": "type=all/country_code=nal/dt=2019-09-20", "timeout": "120"}
    ]

    sub.set_task_monitor(tb)

t1 = PythonOperator(
    task_id='test_t1',
    python_callable=test_t11,
    provide_context=True,
    dag=dag
)

t1
"""


class TaskTimeoutMonitor(object):

    hive_cursor = None
    comwx = None

    def __init__(self):
        self.hive_cursor = get_hive_cursor()
        self.comwx = ComwxApi('wwd26d45f97ea74ad2', 'BLE_v25zCmnZaFUgum93j3zVBDK-DjtRkLisI_Wns4g', '1000011')

    def __del__(self):
        self.hive_cursor.close()
        self.hive_cursor = None

    """
    检查文件，协程多个调用并发执行
    """
    @asyncio.coroutine
    def task_trigger(self, command, table, partition, timeout):
        sum_timeout = 0
        timeout_step = 30
        command = command.strip()

        while sum_timeout <= int(timeout):
            logging.info(command)
            yield from asyncio.sleep(int(timeout_step))

            sum_timeout += timeout_step
            out = os.popen(command, 'r')
            res = out.readlines()
            logging.info(res)
            res = 0 if res is None else res[0].lower().strip()
            out.close()

            if res == '' or res == 'None' or res == '0':
                if sum_timeout >= int(timeout):
                    self.comwx.postAppMessage(
                        '重要重要重要：{table} 分区 {partition}/_SUCCESS NOT FOUND in {timeout} seconds'.format(
                            table=table,
                            partition=partition,
                            timeout=timeout
                        ),
                        '271'
                    )
                    break
            else:
                break

    """
    设置任务监控
    @:param list 
    [{"db":"", "table":"table", "partition":"partition", "timeout":"timeout"},]
    """
    def set_task_monitor(self, tables):
        commands = []
        for item in tables:
            table = item.get('table', None)
            db = item.get('db', None)
            partition = item.get('partition', None)
            timeout = item.get('timeout', None)

            if table is None or db is None or partition is None or timeout is None:
                return None

            location = None
            hql = '''
                DESCRIBE FORMATTED {db}.{table}
            '''.format(table=table, db=db)
            logging.info(hql)
            self.hive_cursor.execute(hql)
            res = self.hive_cursor.fetchall()
            for (col_name, col_type, col_comment) in res:
                col_name = col_name.lower().strip()
                if col_name == 'location:':
                    location = col_type
                    break

            if location is None:
                return None

            commands.append({
                'cmd': '''
                        hadoop fs -ls {path}/{partition}/_SUCCESS >/dev/null 2>/dev/null && echo 1 || echo 0
                    '''.format(
                        timeout=timeout,
                        path=location,
                        partition=partition
                    ),
                'partition': partition,
                'timeout': timeout,
                'table': table
                }
            )

        loop = asyncio.get_event_loop()
        tasks = [self.task_trigger(item['cmd'], item['table'], item['partition'], item['timeout']) for item in commands]
        loop.run_until_complete(asyncio.wait(tasks))
        loop.close()