from airflow import DAG
from airflow.operators.python_operator import PythonOperator
from datetime import datetime, timedelta

from ingest.jobs import source_ingestion_job

default_args = {
    "owner": "airflow",
    "depends_on_past": False,
    "start_date": datetime(2025, 4, 10),
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
}


dag = DAG(
    "aggy_source_ingestion",
    default_args=default_args,
    description="A DAG to ingest sources for Aggy",
    schedule_interval=timedelta(hours=1),
)

ingest = PythonOperator(
    task_id="source_ingestion_job",
    python_callable=source_ingestion_job,
    dag=dag,
)
