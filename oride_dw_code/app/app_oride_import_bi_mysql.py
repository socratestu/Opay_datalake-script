# -*- coding: utf-8 -*-
"""
oride_dw库下app表全部镜像到bi mysql
"""
import airflow
from datetime import datetime, timedelta
from airflow.operators.python_operator import PythonOperator
from utils.connection_helper import get_hive_cursor, get_db_conn
from airflow.sensors.hive_partition_sensor import HivePartitionSensor
from airflow.operators.bash_operator import BashOperator
import logging

args = {
    'owner': 'wuduo',
    'start_date': datetime(2019, 9, 11),
    'depends_on_past': False,
    'retries': 1,
    'retry_delay': timedelta(minutes=5),
    'email': ['bigdata_dw@opay-inc.com'],
    'email_on_failure': True,
    'email_on_retry': False,
}

dag = airflow.DAG(
    'app_oride_import_bi_mysql',
    schedule_interval="30 4 * * *",
    max_active_runs=1,
    default_args=args
)

sleep_time = BashOperator(
    task_id='sleep_id',
    depends_on_past=False,
    bash_command='sleep 60',
    dag=dag
)

# hive 与 mysql数据类型影射
type_map = {
    "tinyint":  {"type": "tinyint", "ext": " not null default 0"},
    "smallint": {"type": "smallint","ext": " not null default 0"},
    "string":   {"type": "varchar", "ext": "(64) not null default ''"},
    "int":      {"type": "int",     "ext": " not null default 0"},
    "bigint":   {"type": "bigint",  "ext": " not null default 0"},
    "double":   {"type": "double",  "ext": " not null default '0.00'"},
    "float":    {"type": "float",   "ext": " not null default '0.00'"},
    "decimal":  {"type": "decimal", "ext": "(38,2) not null default '0.00'"}
}

# 需要同步到mysql的表
hive_sync_db = [
    {'hive_db': 'oride_dw', 'mysql_conn': 'mysql_bi'}
]

mysql_connectors = {}


# 关闭mysql连接
def close_db_conn(**op_kwargs):
    for k in mysql_connectors:
        mysql_connectors[k].close()


close_db_connectors = PythonOperator(
    task_id='close_db_connectors',
    python_callable=close_db_conn,
    provide_context=True,
    dag=dag
)


# 关闭hive连接
def close_hive_conn(**op_kwargs):
    hive = op_kwargs.get('hive')
    if hive:
        hive.close()


# 创建mysql数据表
def create_bi_mysql_table(conn, db, table, columns):
    if conn not in mysql_connectors:
        mconn = get_db_conn(conn)
        mysql_connectors[conn] = mconn.cursor()

    mcursor = mysql_connectors[conn]
    sql = '''
        SELECT 
            COLUMN_NAME, 
            DATA_TYPE  
        FROM information_schema.COLUMNS 
        WHERE TABLE_SCHEMA='{db}' AND 
            TABLE_NAME='{table}' 
        ORDER BY ORDINAL_POSITION
    '''.format(
        db=db,
        table=table
    )
    mcursor.execute(sql)
    res = mcursor.fetchall()
    # mysql表不存在
    if len(res) <= 0:
        cols = []
        for v in columns:
            types = type_map.get(v['type'].lower().strip(), {
                "type": "varchar",
                "ext": "(64) not null default ''"
            })
            cols.append("{name} {type}{ext} comment '{comment}'".format(
                name=v['name'],
                type=types['type'],
                ext=types['ext'],
                comment=v['comment']
            ))

        sql = '''
            CREATE TABLE IF NOT EXISTS {db}.{table} (
                {columns}
            )engine=InnoDB default charset=utf8mb4
        '''.format(
            db=db,
            table=table,
            columns=",\n".join(cols)
        )
        logging.info(sql)
        mcursor.execute(sql)
        return True

    # mysql表存在
    mysql_columns = {}
    for (name, d_type) in res:
        name = name.lower().strip()
        mysql_columns[name] = d_type.lower().strip()

    sql = 'ALTER TABLE {db}.{table} '.format(db=db, table=table)
    for k, v in enumerate(columns):
        types = type_map.get(v['type'].lower().strip(), {
            "type": "varchar",
            "ext": "(64) not null default ''"
        })
        # if k < len(res):
        mysql_coltype = mysql_columns.get(v['name'], None)
        if not mysql_coltype:
            if k == 0:
                alter_sql = "add {name} {type} comment '{comment}' first".format(
                    name=v['name'],
                    type=types['type'] + types['ext'],
                    comment=v['comment']
                )
            else:
                alter_sql = "add {name} {type} comment '{comment}' after {prev}".format(
                    name=v['name'],
                    type=types['type'] + types['ext'],
                    comment=v['comment'],
                    prev=columns[k-1]['name'].lower()
                )
            logging.info(sql + alter_sql)
            mcursor.execute(sql + alter_sql)
        else:
            if types['type'] != mysql_coltype:
                alter_sql = "change {name} {name} {type} comment '{comment}'".format(
                    name=name,
                    type=types['type'] + types['ext'],
                    comment=v['comment']
                )
                logging.info(sql + alter_sql)
                mcursor.execute(sql + alter_sql)
        # else:
        #    alter_sql = "add {name} {type} comment '{comment}' after {prev}".format(
        #        name=v['name'].lower(),
        #        type=types['type'] + types['ext'],
        #        comment=v['comment'],
        #        prev=columns[k-1]['name'].lower()
        #    )
        #    logging.info(sql + alter_sql)
        #    mcursor.execute(sql + alter_sql)
    return False


# 获取hive表的列字段
def get_hive_table_columns(conn, db, table):
    hql = '''
        DESCRIBE FORMATTED {db}.{table}
    '''.format(
        db=db,
        table=table
    )
    logging.info(hql)
    conn.execute(hql)
    res = conn.fetchall()
    columns = []
    for (col_name, col_type, col_comment) in res:
        col_name = col_name.lower().strip()
        if col_name == '# col_name' or col_name == '' or col_name == '# partition information':
            continue
        if col_name == '# detailed table information':
            break

        if "decimal" in col_type.lower():
            type = "decimal"
        else:
            type = col_type.lower().strip()
        columns.append({
            'name': col_name,
            'type': type,
            'comment': col_comment.lower().strip()
        })

    logging.info(columns)
    return columns


# 根据hive数据表 更新 mysql数据表
def init_mysql_table(**op_kwargs):
    hive_cursor = op_kwargs.get('conn')
    hive_db = op_kwargs.get('db')
    hive_table = op_kwargs.get('table')
    mysql_cursor = op_kwargs.get('mysql_conn')
    dt = op_kwargs.get('ds')

    hive_columns = get_hive_table_columns(hive_cursor, hive_db, hive_table)
    cols = []
    mcols = []
    for v in hive_columns:
        cols.append("if({} is NULL, 0, {})".format(v['name'].lower(), v['name'].lower()))
        mcols.append(v['name'].lower())
    new_table = create_bi_mysql_table(mysql_cursor, hive_db, hive_table, hive_columns)
    if new_table:       # 新表 全量
        hql = '''
            SELECT 
                {cols} 
            FROM {db}.{table} 
        '''.format(
            db=hive_db,
            table=hive_table,
            cols=",".join(cols)
        )
    else:               # 增量
        hql = '''
            SELECT 
                {cols}
            FROM {db}.{table} 
            WHERE dt = '{dt}'
        '''.format(
            db=hive_db,
            table=hive_table,
            cols=",".join(cols),
            dt=dt
        )
    logging.info(hql)
    hive_cursor.execute(hql)
    res = hive_cursor.fetchall()
    __data_to_mysql(mysql_cursor, hive_db, hive_table, res, mcols, dt)


# 数据写入mysql
def __data_to_mysql(conn, db, table, data, column, dt):
    mcursor = mysql_connectors[conn]
    mcursor.execute("DELETE FROM {db}.{table} WHERE dt = '{dt}'".format(db=db, table=table, dt=dt))

    isql = 'replace into {db}.{table} ({cols})'.format(
        db=db,
        table=table,
        cols=','.join(column)
    )
    esql = '{0} values {1}'
    sval = ''
    cnt = 0
    try:
        for row in data:
            if sval == '':
                sval = '(\'{}\')'.format('\',\''.join([str(x) for x in row]))
            else:
                sval += ',(\'{}\')'.format('\',\''.join([str(x) for x in row]))
            cnt += 1
            if cnt >= 1000:
                # logging.info(esql.format(isql, sval))
                mcursor.execute(esql.format(isql, sval))
                cnt = 0
                sval = ''

        if cnt > 0 and sval != '':
            # logging.info(esql.format(isql, sval))
            mcursor.execute(esql.format(isql, sval))
    except BaseException as e:
        logging.info(e)
        return


# 遍历同步的数据库
for hive_db_info in hive_sync_db:
    hive_cursor = get_hive_cursor()
    hql = '''
        SHOW TABLES IN {hive_db} 'app_*'
    '''.format(hive_db=hive_db_info.get('hive_db'))
    hive_cursor.execute(hql)
    hive_tables = hive_cursor.fetchall()

    for (table, ) in hive_tables:
        if table == 'app_oride_order_dispatch_d':
            continue
        # 依赖hive表分区
        table_validate_task = HivePartitionSensor(
            task_id="table_validate_task_{}_{}".format(hive_db_info.get('hive_db'), table),
            table=table,
            partition="dt='{{ds}}'",
            schema=hive_db_info.get('hive_db'),
            poke_interval=60,  # 依赖不满足时，一分钟检查一次依赖状态
            dag=dag
        )

        # 同步hive与mysql表结构
        sync_table_schema = PythonOperator(
            task_id='sync_table_schema_{}_{}'.format(hive_db_info.get('hive_db'), table),
            python_callable=init_mysql_table,
            provide_context=True,
            op_kwargs={
                "conn": hive_cursor,
                "db": hive_db_info.get('hive_db'),
                "table": table,
                "mysql_conn": hive_db_info.get('mysql_conn'),
                "ds": '{{ ds }}'
            },
            dag=dag
        )

        table_validate_task >> sync_table_schema >> sleep_time

    # 关闭hive连接
    close_hive_connectors = PythonOperator(
        task_id='close_hive_connectors',
        python_callable=close_hive_conn,
        provide_context=True,
        op_kwargs={
            "hive": hive_cursor
        },
        dag=dag
    )

    sleep_time >> close_hive_connectors

sleep_time >> close_db_connectors