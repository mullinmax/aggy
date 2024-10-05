from datetime import datetime

from config import config
from jobs.ml.jobs import (
    score_estimate_training_scheduling_job,
    score_estimate_inference_scheduling_job,
    score_estimate_trainging_job,
    score_estimate_inference_job,
)
from jobs.bridge.jobs import rss_bridge_get_templates_job
from jobs.ingest.jobs import (
    source_ingestion_scheduling_job,
    source_ingestion_job,
    download_embedding_model_job,
)

jobs = [
    {
        "func": source_ingestion_scheduling_job,
        "trigger": "interval",
        "seconds": 60 * config.get("SOURCE_INGESTION_INTERVAL_MINUTES"),
        "id": "source_ingestion_scheduling_job",
        "replace_existing": False,
        "next_run_time": datetime.now(),
    },
    {
        "func": source_ingestion_job,
        "trigger": "interval",
        "seconds": config.get("SOURCE_INGESTION_RUN_INTERVAL_SECONDS"),
        "id": "source_ingestion_job",
        "replace_existing": False,
        "next_run_time": datetime.now(),
    },
    {
        "func": rss_bridge_get_templates_job,
        "trigger": "interval",
        "seconds": 60 * 60 * 12,
        "id": "rss_bridge_get_templates_job",
        "replace_existing": False,
        "next_run_time": datetime.now(),
    },
    {
        "func": download_embedding_model_job,
        "trigger": "date",
        "run_date": datetime.now(),
        "id": "download_embedding_model_job",
        "replace_existing": False,
    },
    {
        "func": score_estimate_training_scheduling_job,
        "trigger": "interval",
        "seconds": 60 * 60 * config.get("SCORE_ESTIMATE_TRAINING_INTERVAL_HOURS"),
        "id": "score_estimate_training_scheduling_job",
        "replace_existing": False,
        "next_run_time": datetime.now(),
    },
    {
        "func": score_estimate_inference_scheduling_job,
        "trigger": "interval",
        "seconds": 60 * 60 * config.get("SCORE_ESTIMATE_REFRESH_HOURS"),
        "id": "score_estimate_inference_scheduling_job",
        "replace_existing": False,
        "next_run_time": datetime.now(),
    },
    {
        "func": score_estimate_trainging_job,
        "trigger": "interval",
        "seconds": 60 * 60 * config.get("SCORE_ESTIMATE_TRAINING_RUN_INTERVAL_SECONDS"),
        "id": "score_estimate_trainging_job",
        "replace_existing": False,
        "next_run_time": datetime.now(),
    },
    {
        "func": score_estimate_inference_job,
        "trigger": "interval",
        "seconds": 60 * 60 * config.get("SCORE_ESTIMATE_REFRESH_RUN_INTERVAL_SECONDS"),
        "id": "score_estimate_inference_job",
        "replace_existing": False,
        "next_run_time": datetime.now(),
    },
]
