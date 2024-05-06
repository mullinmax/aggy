from fastapi import FastAPI
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import logging
from contextlib import asynccontextmanager
import uvicorn

from config import config
from routers.auth import auth_router
from routers.category import category_router
from routers.item import item_router
from ingest.jobs import feed_ingestion_job, feed_ingestion_scheduling_job

app = FastAPI()

# Include your routers
app.include_router(auth_router, prefix="/auth", tags=["auth"])
app.include_router(category_router, prefix="/category", tags=["category"])
app.include_router(item_router, prefix="/item", tags=["item"])

# Scheduler instance
scheduler = AsyncIOScheduler()


@asynccontextmanager
async def app_lifespan(app: FastAPI):
    logging.info("API starting up...")
    scheduler.add_job(
        func=feed_ingestion_scheduling_job,
        trigger="interval",
        seconds=60 * config.get("FEED_CHECK_INTERVAL_MINUTES"),
        id="feed_ingestion_scheduling_job",
        replace_existing=False,
    )
    scheduler.add_job(
        func=feed_ingestion_job,
        trigger="interval",
        seconds=5,  # TODO: make this configurable
        id="feed_ingestion_job",
        replace_existing=False,
    )
    scheduler.start()

    yield  # The application runs as long as this yield is here

    logging.info("API shutting down...")
    scheduler.shutdown(wait=False)


# Assign the lifespan context manager to the FastAPI app
app = FastAPI(lifespan=app_lifespan)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
