from fastapi import FastAPI
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import logging
from contextlib import asynccontextmanager
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi.responses import RedirectResponse
from starlette.requests import Request
import uvicorn

from config import config
from routers.auth import auth_router
from routers.category import category_router
from routers.feed import feed_router
from routers.item import item_router
from ingest.jobs import feed_ingestion_job, feed_ingestion_scheduling_job

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

    yield

    logging.info("API shutting down...")
    scheduler.shutdown(wait=False)


# create app with lifespan context manager
app = FastAPI(lifespan=app_lifespan)

# routers
app.include_router(auth_router, prefix="/auth", tags=["auth"])
app.include_router(category_router, prefix="/category", tags=["category"])
app.include_router(feed_router, prefix="/feed", tags=["feed"])
app.include_router(item_router, prefix="/item", tags=["item"])


# Custom middleware to handle 404 errors and redirect to docs
class Custom404Middleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        if response.status_code == 404:
            return RedirectResponse(url="/docs")
        return response


app.add_middleware(Custom404Middleware)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
