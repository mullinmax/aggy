import os
import threading

# Guard against the musl/OpenBLAS segfault on alpine: BLAS must not spawn
# its own worker threads (they get musl's 128KB stack and crash on big
# matrices), and Python-created worker threads (uvicorn's threadpool,
# APScheduler) need a roomier stack for numpy. Both must be set before
# numpy is first imported / any thread is started.
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")
threading.stack_size(4 * 1024 * 1024)

from pathlib import Path
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import logging
from contextlib import asynccontextmanager
import uvicorn
from datetime import datetime

BASE_DIR = Path(__file__).resolve().parent

from config import config
from routers.admin import admin_router
from routers.auth import auth_router
from routers.feed import feed_router
from routers.source_template import source_template_router
from routers.source import source_router
from routers.source_analyze import source_analyze_router
from routers.bulk_import import bulk_import_router
from routers.item import item_router
from routers.web import web_router
from bridge.jobs import rss_bridge_get_templates_job
from builtin_templates import create_builtin_source_templates
from ingest.jobs import (
    source_ingestion_scheduling_job,
    source_ingestion_job,
    download_embedding_model_job,
)
from ranking.engine import feed_ranking_job

# Scheduler instance
scheduler = AsyncIOScheduler()


@asynccontextmanager
async def app_lifespan(app: FastAPI):
    logging.info("API starting up...")

    # Fail fast on missing critical config instead of erroring on first login.
    config.get("JWT_SECRET")

    try:
        create_builtin_source_templates()
    except Exception as e:
        logging.error(f"Failed to seed builtin source templates: {e}")

    scheduler.add_job(
        func=source_ingestion_scheduling_job,
        trigger="interval",
        seconds=60 * config.get_int("SOURCE_READ_INTERVAL_MINUTES"),
        id="source_ingestion_scheduling_job",
        replace_existing=False,
        next_run_time=datetime.now(),
    )

    # add scheduler job for ingesting sources every n seconds
    scheduler.add_job(
        func=source_ingestion_job,
        trigger="interval",
        seconds=config.get_int("SOURCE_INGESTION_RUN_INTERVAL_SECONDS"),
        id="source_ingestion_job",
        replace_existing=False,
        next_run_time=datetime.now(),
    )

    # add scheduler job for parsing the rss bridge templates every 12 hours
    scheduler.add_job(
        func=rss_bridge_get_templates_job,
        trigger="interval",
        seconds=60 * 60 * 12,
        id="rss_bridge_get_templates_job",
        replace_existing=False,
        next_run_time=datetime.now(),
    )

    # re-rank feeds whose votes/items changed since the last prediction pass
    scheduler.add_job(
        func=feed_ranking_job,
        trigger="interval",
        seconds=60 * config.get_int("RANKING_INTERVAL_MINUTES"),
        id="feed_ranking_job",
        replace_existing=False,
        next_run_time=datetime.now(),
    )

    # add scheduler job for downloading the embedding model once at start up
    scheduler.add_job(
        func=download_embedding_model_job,
        trigger="date",
        run_date=datetime.now(),
        id="download_embedding_model_job",
        replace_existing=False,
    )

    scheduler.start()

    yield

    logging.info("API shutting down...")
    scheduler.shutdown(wait=False)


# create app with lifespan context manager
app = FastAPI(lifespan=app_lifespan, version=config.get("BUILD_VERSION"))

# static files
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

# routers
app.include_router(admin_router, tags=["Admin"])
app.include_router(auth_router, prefix="/auth", tags=["Authentication"])
app.include_router(feed_router, prefix="/feed", tags=["Feeds"])
app.include_router(
    source_template_router, prefix="/source_template", tags=["Source Templates"]
)
app.include_router(source_router, prefix="/source", tags=["Sources"])
app.include_router(
    source_analyze_router, prefix="/source_analyze", tags=["Source Analysis"]
)
app.include_router(bulk_import_router, prefix="/import", tags=["Bulk Import"])
app.include_router(item_router, prefix="/item", tags=["Items"])
app.include_router(web_router)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        log_level="info",
        proxy_headers=True,
        forwarded_allow_ips="*",
    )
