from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from typing import List, Union

from db.feed import Feed
from db.source import Source
from db.source_template import SourceTemplate
from db.user import User
from ingest.jobs import ingest_source_now, rescrape_source
from route_models.item import ItemResponse
from route_models.acknowledge import AcknowledgeResponse
from route_models.source import SourceRouteModel
from route_models.source_update import SourceUpdate
from routers.auth import authenticate

source_router = APIRouter()


@source_router.post(
    "/create",
    summary="Create a source (within a feed)",
    response_model=AcknowledgeResponse,
)
def create_source(
    feed_name_hash: str,
    source_name: str,
    source_url: str,
    background_tasks: BackgroundTasks,
    user: User = Depends(authenticate),
) -> AcknowledgeResponse:
    feed = Feed.read(user_hash=user.name_hash, name_hash=feed_name_hash)
    if feed is None:
        raise HTTPException(status_code=404, detail="Feed not found")
    source = Source(
        user_hash=user.name_hash,
        feed_hash=feed_name_hash,
        name=source_name,
        url=source_url,
    )
    if source.exists():
        raise HTTPException(
            status_code=409,
            detail=f'A source named "{source_name}" already exists in this feed',
        )
    feed.add_source(source)
    # kick off the first ingest right away instead of waiting for the schedule
    background_tasks.add_task(ingest_source_now, source)
    return AcknowledgeResponse()


@source_router.post(
    "/update",
    summary="Update a source's name, URL, or template parameters",
    response_model=SourceRouteModel,
)
def update_source(
    update: SourceUpdate,
    background_tasks: BackgroundTasks,
    user: User = Depends(authenticate),
) -> SourceRouteModel:
    try:
        source = Source.read(
            user_hash=user.name_hash,
            feed_hash=update.feed_name_hash,
            source_hash=update.source_name_hash,
        )
    except ValueError:
        raise HTTPException(status_code=404, detail="Source not found")

    new_name = update.source_name.strip()
    if not new_name:
        raise HTTPException(status_code=422, detail="Source name cannot be empty")

    # renaming must not collide with another source in the feed
    if new_name != source.name:
        other = Source(
            user_hash=user.name_hash,
            feed_hash=update.feed_name_hash,
            name=new_name,
            url=str(source.url),
        )
        if other.exists():
            raise HTTPException(
                status_code=409,
                detail=f'A source named "{new_name}" already exists in this feed',
            )

    new_url = str(source.url)
    new_parameters = None
    if source.template_name_hash and update.parameters is not None:
        template = SourceTemplate.read(name_hash=source.template_name_hash)
        if not template:
            raise HTTPException(status_code=404, detail="Source template not found")
        try:
            new_url = template.create_rss_url(**update.parameters)
        except Exception as e:
            raise HTTPException(status_code=422, detail=str(e))
        new_parameters = update.parameters
    elif update.source_url:
        new_url = update.source_url

    url_changed = new_url != str(source.url)
    update_kwargs = {}
    # null means "reset to server default", so only apply the interval when
    # the field was actually sent
    if "ingest_interval_minutes" in update.model_fields_set:
        update_kwargs["ingest_interval"] = update.ingest_interval_minutes
    if update.source_color is not None:
        update_kwargs["color"] = update.source_color
    source.update(
        name=new_name,
        url=new_url,
        template_parameters=new_parameters,
        **update_kwargs,
    )

    if url_changed:
        # fetch the new URL right away instead of waiting for the schedule
        background_tasks.add_task(ingest_source_now, source)

    return SourceRouteModel.from_db_model(source)


@source_router.post(
    "/rescrape",
    summary="Re-scrape a source's items for content, media, and embeddings",
    response_model=AcknowledgeResponse,
)
def rescrape_source_route(
    feed_name_hash: str,
    source_name_hash: str,
    background_tasks: BackgroundTasks,
    user: User = Depends(authenticate),
) -> AcknowledgeResponse:
    try:
        source = Source.read(
            user_hash=user.name_hash,
            feed_hash=feed_name_hash,
            source_hash=source_name_hash,
        )
    except ValueError:
        raise HTTPException(status_code=404, detail="Source not found")

    # Re-collect images/content/media and regenerate embeddings in the
    # background; this does NOT re-fetch the RSS feed for new items.
    background_tasks.add_task(rescrape_source, source)
    return AcknowledgeResponse()


@source_router.get(
    "/items", summary="Get all items in a source", response_model=List[ItemResponse]
)
def get_items(
    feed_name_hash: str,
    source_name_hash: str,
    skip: Union[int, None] = None,
    limit: Union[int, None] = None,
    user: User = Depends(authenticate),
) -> List[ItemResponse]:
    try:
        source = Source.read(
            user_hash=user.name_hash,
            feed_hash=feed_name_hash,
            source_hash=source_name_hash,
        )
        items = source.query_items(skip=skip, limit=limit)
        return [ItemResponse.from_db_model(item) for item in items]
    except Exception:
        raise HTTPException(status_code=404, detail="Source not found")


@source_router.delete(
    "/delete",
    summary="Delete a source",
    response_model=AcknowledgeResponse,
)
def delete_source(
    feed_name_hash: str, source_name_hash: str, user: User = Depends(authenticate)
) -> AcknowledgeResponse:
    feed = Feed.read(user_hash=user.name_hash, name_hash=feed_name_hash)
    source = Source.read(
        user_hash=user.name_hash,
        feed_hash=feed_name_hash,
        source_hash=source_name_hash,
    )
    feed.delete_source(source)
    return AcknowledgeResponse
