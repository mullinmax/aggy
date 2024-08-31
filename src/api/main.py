from fastapi import FastAPI
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import logging
from contextlib import asynccontextmanager
import uvicorn
from datetime import datetime

from config import config
from routers.admin import admin_router
from routers.auth import auth_router
from routers.category import category_router
from routers.feed_template import feed_template_router
from routers.feed import feed_router
from routers.item import item_router
from ingest.jobs import (
    feed_ingestion_scheduling_job,
    feed_ingestion_job,
    download_embedding_model_job,
)

# Scheduler instance
scheduler = AsyncIOScheduler()


@asynccontextmanager
async def app_lifespan(app: FastAPI):
    logging.info("API starting up...")
    scheduler.add_job(
        func=feed_ingestion_scheduling_job,
        trigger="interval",
        seconds=60 * config.get("FEED_READ_INTERVAL_MINUTES"),
        id="feed_ingestion_scheduling_job",
        replace_existing=False,
        next_run_time=datetime.now(),
    )

    # add scheduler job for ingesting feeds every n seconds
    scheduler.add_job(
        func=feed_ingestion_job,
        trigger="interval",
        seconds=config.get("FEED_INGESTION_RUN_INTERVAL_SECONDS"),
        id="feed_ingestion_job",
        replace_existing=False,
        next_run_time=datetime.now(),
    )

    # # add scheduler job for downloading the rss bridge templates every 12 hours
    # scheduler.add_job(
    #     func=rss_bridge_get_templates_job,
    #     trigger="interval",
    #     seconds=60 * 60 * 12,
    #     id="rss_bridge_get_templates_job",
    #     replace_existing=False,
    #     next_run_time=datetime.now()
    # )

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

# routers
app.include_router(admin_router, tags=["Admin"])
app.include_router(auth_router, prefix="/auth", tags=["Authentication"])
app.include_router(category_router, prefix="/category", tags=["Categories"])
app.include_router(
    feed_template_router, prefix="/feed_template", tags=["Feed Templates"]
)
app.include_router(feed_router, prefix="/feed", tags=["Feeds"])
app.include_router(item_router, prefix="/item", tags=["Items"])


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
