import airflow
from airflow.hooks.base_hook import BaseHook
from airflow.operators.bash_operator import BashOperator
from airflow.hooks.hive_hooks import HiveCliHook, HiveServer2Hook
from airflow.hooks.mysql_hook import MySqlHook
from airflow.operators.hive_operator import HiveOperator
from airflow.operators.python_operator import PythonOperator
from datetime import datetime, timedelta
from utils.validate_metrics_utils import *
import logging
from plugins.SqoopSchemaUpdate import SqoopSchemaUpdate
from plugins.TaskTimeoutMonitor import TaskTimeoutMonitor
from utils.util import on_success_callback
from airflow.models import Variable

args = {
    'owner': 'zhenqian.zhang',
    'start_date': datetime(2020, 1, 12),
    'depends_on_past': False,
    'retries': 1,
    'retry_delay': timedelta(minutes=5),
    'email': ['bigdata_dw@opay-inc.com'],
    'email_on_failure': True,
    'email_on_retry': False,
    'on_success_callback':on_success_callback,
}
schedule_interval="00 01 * * *"

dag = airflow.DAG(
    'opay_source_sqoop_df',
    schedule_interval=schedule_interval,
    concurrency=40,
    max_active_runs=1,
    default_args=args)

dag_monitor = airflow.DAG(
    'opay_source_sqoop_df_monitor',
    schedule_interval=schedule_interval,
    default_args=args)

##----------------------------------------- 任务超时监控 ---------------------------------------##

def fun_task_timeout_monitor(ds, db_name, table_name, **op_kwargs):
    tb = [
        {"dag":dag,"db": db_name, "table": table_name, "partition": "dt={pt}".format(pt=ds), "timeout": "7200","flag":"ods"}
    ]

    TaskTimeoutMonitor().set_task_monitor(tb)

# 忽略数据量检查的table
IGNORED_TABLE_LIST = [
    'user_limit',
    'channel_router_rule',
]

'''
导入数据的列表
db_name,table_name,conn_id,prefix_name,priority_weight
'''
#

table_list = [
    #("opay_bigorder","big_order", "opay_db_3317", "base",1),
    #("opay_bigorder","merchant_order", "opay_db_3317", "base",2),

    #("opay_transaction","user_transfer_user_record", "opay_db_3316", "base",1),
    #("opay_transaction","merchant_transfer_user_record", "opay_db_3316", "base",1),
    #("opay_transaction","airtime_topup_record", "opay_db_3316", "base",1),
    #("opay_transaction","betting_topup_record", "opay_db_3316", "base",1),
    #("opay_transaction","user_topup_record", "opay_db_3316", "base",1),

    # ("opay_user","user_upgrade", "opay_user", "base",3),
    #("opay_user","user", "opay_db_3321", "base",1),
    # ("opay_user","user_operator", "opay_user", "base", 1),
    # ("opay_user","user_payment_instrument", "opay_user", "base", 1),
    # ("opay_user", "user_token", "opay_user", "base", 1),
    ("opay_user", "user_telesale", "opay_user", "base", 1),
    # ("opay_user", "user_reseller", "opay_user", "base", 1),
 #   ("opay_user", "user_push_token", "opay_user", "base", 1),
 #    ("opay_user", "user_operator", "opay_user", "base", 1),
    ("opay_user", "user_nearby_agent", "opay_user", "base", 1),
    # ("opay_user", "user_message", "opay_user", "base", 1),

 #   ("opay_account","account_user", "opay_account", "base", 2),
#    ("opay_account","account_merchant", "opay_account", "base", 2),
#     ("opay_account","accounting_merchant_record", "opay_account", "base", 1),
    #("opay_account","accounting_record", "opay_account", "base", 1),

    # ("opay_overlord","overlord_user", "opay_overlord", "base", 1),
    # ("opay_overlord","terminal", "opay_overlord", "base", 1),

    # ("opay_merchant","merchant", "opay_merchant", "base", 1),

    # ("opay_sms","message_template", "opay_sms", "base", 1),

    ("opay_activity", "activity", "opay_activity", "base", 1),
    ("opay_activity", "activity_rules", "opay_activity", "base", 1),
    #("opay_activity", "preferential_record", "opay_db_3322", "base", 1),

    ("opay_commission", "commission_account_balance", "opay_commission", "base", 1),
    ("opay_commission", "commission_order", "opay_commission", "base", 1),
    ("opay_commission", "commission_top_up_record", "opay_commission", "base", 1),

    # ("opay_agent_crm", "bd_agent", "opay_agent_crm_db", "base", 2),
    # ("opay_agent_crm", "bd_admin_users", "opay_agent_crm_db", "base", 2),

    # ("opay_channel", "card_bin", "opay_channel", "base", 3),

    ("voucher_db", "opay_voucher_grab_hist", "voucher_db", "coupon", 3),
    ("voucher_db", "voucher_batch_stat", "voucher_db", "coupon", 3),

    ("ads_data", "coupon_batch", "ads_data", "coupon", 3),
    ("ads_data", "coupon_package", "ads_data", "coupon", 3),
    ("ads_data", "coupon_template", "ads_data", "coupon", 3),

    ("opay_activity", "voucher_record", "opay_activity", "coupon", 3),

]

"""
    ("opay_transaction","adjustment_decrease_record", "opay_db", "base",3),
    ("opay_transaction","adjustment_increase_record", "opay_db", "base",3),
    ("opay_transaction","electricity_topup_record", "opay_db", "base",3),
    ("opay_transaction","merchant_acquiring_record", "opay_db", "base",3),
    ("opay_transaction","merchant_pos_transaction_record", "opay_db", "base",3),
    ("opay_transaction","merchant_receive_money_record", "opay_db", "base",3),
    ("opay_transaction","merchant_topup_record", "opay_db", "base",3),
    ("opay_transaction","merchant_transfer_card_record", "opay_db", "base",3),
    ("opay_transaction","mobiledata_topup_record", "opay_db", "base",3),
    ("opay_transaction","payment_authorization_record", "opay_db", "base",3),
    ("opay_transaction","payment_token_record", "opay_db", "base",3),
    ("opay_transaction","receive_money_request_record", "opay_db", "base",3),
    ("opay_transaction","transfer_not_register_record", "opay_db", "base",3),
    ("opay_transaction","tv_topup_record", "opay_db", "base",3),
    ("opay_transaction","user_easycash_record", "opay_db", "base",3),
    ("opay_transaction","user_pos_transaction_record", "opay_db", "base",3),
    ("opay_transaction","user_receive_money_record", "opay_db", "base",3),
    ("opay_transaction","user_transfer_card_record", "opay_db", "base",3),
    ("opay_bigorder","user_order", "opay_db", "base",3),
    ("opay_account","accounting_request_record", "opay_db", "base",3),
    ("opay_merchant","merchant_email_setting", "opay_db", "base",3),
    ("opay_merchant","merchant_key", "opay_db", "base",3),
    ("opay_merchant","merchant_operator", "opay_db", "base",3),
    ("opay_merchant","merchant_pos_limit", "opay_db", "base",3),
    ("opay_merchant","merchant_remittance_limit", "opay_db", "base",3),
    ("opay_merchant","merchant_reseller", "opay_db", "base",3),
    ("opay_channel","card_token", "opay_db", "base",3),
    ("opay_channel","channel_response_code", "opay_db", "base",3),
    ("opay_channel","channel_router_rule", "opay_db", "base",3),
    ("opay_channel","channel_transaction", "opay_db", "base",3),
    ("opay_channel","channel_transaction_mq_record", "opay_db", "base",3),
    ("opay_channel","channel_transaction_record", "opay_db", "base",3),
    ("opay_channel","channel_transaction_retry", "opay_db", "base",3),
    ("opay_recon","collect_diff_detail", "opay_db", "base",3),
    ("opay_recon","collect_record", "opay_db", "base",3),
    ("opay_recon","exception_log", "opay_db", "base",3),
    ("opay_recon","external_record", "opay_db", "base",3),
    ("opay_recon","external_request_record", "opay_db", "base",3),
    ("opay_recon","internal_record", "opay_db", "base",3),
    ("opay_recon","internal_request_record", "opay_db", "base",3),
    ("opay_user","upload_file", "opay_db", "base",3),
    ("opay_user","user_bvn", "opay_db", "base",3),
    ("opay_user","user_kyc", "opay_db", "base",3),
    ("opay_user","user_kyc_upload", "opay_db", "base",3),
    ("opay_user","user_limit", "opay_db", "base",3),
    ("opay_user","user_token", "opay_db", "base",3),
    ("opay_user","user_kyc_record", "opay_db", "base",3),
    ("opay_transaction","business_collection_record", "opay_db", "base",3),
"""

HIVE_DB = 'opay_dw_ods'
HIVE_TABLE = 'ods_sqoop_%s_%s_df'
UFILE_PATH = 'oss://opay-datalake/opay_dw_sqoop/%s/%s'
ODS_CREATE_TABLE_SQL = '''
    CREATE EXTERNAL TABLE IF NOT EXISTS {db_name}.`{table_name}`(
        {columns}
    )
    PARTITIONED BY (
      `dt` string)
    ROW FORMAT SERDE
      'org.apache.hadoop.hive.serde2.lazy.LazySimpleSerDe'
    STORED AS INPUTFORMAT
      'org.apache.hadoop.mapred.TextInputFormat'
    OUTPUTFORMAT
      'org.apache.hadoop.hive.ql.io.HiveIgnoreKeyTextOutputFormat'
    LOCATION
      '{ufile_path}';
    MSCK REPAIR TABLE {db_name}.`{table_name}`;
    -- delete opay_dw table
    -- DROP TABLE IF EXISTS {db_name}.`{table_name}`;
'''

# 需要验证的核心业务表
table_core_list = [
    # ("oride_data", "data_order", "sqoop_db", "base", "create_time","priority_weight")
]

# 不需要验证的维度表，暂时为null
table_dim_list = []

# 需要验证的非核心业务表，根据需求陆续添加
table_not_core_list = []


def run_check_table(db_name, table_name, conn_id, hive_table_name, **kwargs):
    sqoopSchema = SqoopSchemaUpdate()
    response = sqoopSchema.update_hive_schema(
        hive_db=HIVE_DB,
        hive_table=hive_table_name,
        mysql_db=db_name,
        mysql_table=table_name,
        mysql_conn=conn_id
    )
    if response:
        return True

    # SHOW TABLES in oride_db LIKE 'data_aa'
    check_sql = 'SHOW TABLES in %s LIKE \'%s\'' % (HIVE_DB, hive_table_name)
    hive2_conn = HiveServer2Hook().get_conn()
    cursor = hive2_conn.cursor()
    cursor.execute(check_sql)
    if len(cursor.fetchall()) == 0:
        logging.info('Create Hive Table: %s.%s', HIVE_DB, hive_table_name)
        # get table column
        column_sql = '''
            SELECT
                COLUMN_NAME,
                DATA_TYPE,
                NUMERIC_PRECISION,
                NUMERIC_SCALE,COLUMN_COMMENT
            FROM
                information_schema.columns
            WHERE
                table_schema='{db_name}' and table_name='{table_name}'
        '''.format(db_name=db_name, table_name=table_name)
        mysql_hook = MySqlHook(conn_id)
        mysql_conn = mysql_hook.get_conn()
        mysql_cursor = mysql_conn.cursor()
        mysql_cursor.execute(column_sql)
        results = mysql_cursor.fetchall()
        rows = []
        for result in results:
            if result[0] == 'dt':
                col_name = '_dt'
            else:
                col_name = result[0]
            if result[1] == 'timestamp' or result[1] == 'varchar' or result[1] == 'char' or result[1] == 'text' or result[1] == 'longtext' or \
                    result[1] == 'datetime':
                data_type = 'string'
            elif result[1] == 'decimal':
                data_type = result[1] + "(" + str(result[2]) + "," + str(result[3]) + ")"
            else:
                data_type = result[1]
            rows.append("`%s` %s comment '%s'" % (col_name, data_type, result[4]))
        mysql_conn.close()

        # hive create table
        hive_hook = HiveCliHook()
        sql = ODS_CREATE_TABLE_SQL.format(
            db_name=HIVE_DB,
            table_name=hive_table_name,
            columns=",\n".join(rows),
            ufile_path=UFILE_PATH % (db_name, table_name)
        )
        logging.info('Executing: %s', sql)
        hive_hook.run_cli(sql)
    return


conn_conf_dict = {}
for db_name, table_name, conn_id, prefix_name,priority_weight_nm in table_list:
    if conn_id not in conn_conf_dict:
        conn_conf_dict[conn_id] = BaseHook.get_connection(conn_id)

    hive_table_name = HIVE_TABLE % (prefix_name, table_name)
    # sqoop import
    import_table = BashOperator(
        task_id='import_table_{}'.format(hive_table_name),
        priority_weight=priority_weight_nm,
        bash_command='''
            #!/usr/bin/env bash
            sqoop import "-Dorg.apache.sqoop.splitter.allow_text_splitter=true" \
            -D mapred.job.queue.name=root.opay_collects \
            --connect "jdbc:mysql://{host}:{port}/{schema}?tinyInt1isBit=false&useUnicode=true&characterEncoding=utf8" \
            --username {username} \
            --password {password} \
            --table {table} \
            --target-dir {ufile_path}/dt={{{{ ds }}}}/ \
            --fields-terminated-by "\\001" \
            --lines-terminated-by "\\n" \
            --hive-delims-replacement " " \
            --delete-target-dir \
            --compression-codec=snappy \
            -m {m}
        '''.format(
            host=conn_conf_dict[conn_id].host,
            port=conn_conf_dict[conn_id].port,
            schema=db_name,
            username=conn_conf_dict[conn_id].login,
            password=conn_conf_dict[conn_id].password,
            table=table_name,
            ufile_path=UFILE_PATH % (db_name, table_name),
            m=18 if table_name=='channel_response_code' else 20
    ),
        dag=dag,
    )

    # check table
    check_table = PythonOperator(
        task_id='check_table_{}'.format(hive_table_name),
        priority_weight=priority_weight_nm,
        python_callable=run_check_table,
        provide_context=True,
        op_kwargs={
            'db_name': db_name,
            'table_name': table_name,
            'conn_id': conn_id,
            'hive_table_name': hive_table_name
        },
        dag=dag
    )
    # add partitions
    add_partitions = HiveOperator(
        task_id='add_partitions_{}'.format(hive_table_name),
        priority_weight=priority_weight_nm,
        hql='''
                ALTER TABLE {table} ADD IF NOT EXISTS PARTITION (dt = '{{{{ ds }}}}')
            '''.format(table=hive_table_name),
        schema=HIVE_DB,
        dag=dag)

    validate_all_data = PythonOperator(
        task_id='validate_data_{}'.format(hive_table_name),
        priority_weight=priority_weight_nm,
        python_callable=validata_data,
        provide_context=True,
        op_kwargs={
            'db': HIVE_DB,
            'table_name': hive_table_name,
            'table_format': HIVE_TABLE,
            'table_core_list': table_core_list,
            'table_not_core_list': table_not_core_list
        },
        dag=dag
    )

    if table_name in IGNORED_TABLE_LIST:
        import_table >> validate_all_data
    else:
        # 数据量监控
        volume_monitoring = PythonOperator(
            task_id='volume_monitorin_{}'.format(hive_table_name),
            python_callable=data_volume_monitoring,
            provide_context=True,
            op_kwargs={
                'db_name': HIVE_DB,
                'table_name': hive_table_name,
                'is_valid_success':"true"
            },
            dag=dag
        )
        import_table >> volume_monitoring >> validate_all_data
    # 超时监控
    task_timeout_monitor= PythonOperator(
        task_id='task_timeout_monitor_{}'.format(hive_table_name),
        python_callable=fun_task_timeout_monitor,
        provide_context=True,
        op_kwargs={
            'db_name': HIVE_DB,
            'table_name': hive_table_name,
        },
        dag=dag_monitor
    )

    check_table >> add_partitions >> import_table
