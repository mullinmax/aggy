from fastapi import APIRouter, Depends, HTTPException, Query

from typing import List, Optional, Union

from db.feed import Feed, ITEM_SORTS
from db.user import User
from route_models.feed import FeedResponse
from route_models.source import SourceRouteModel
from route_models.item import ItemResponse
from route_models.acknowledge import AcknowledgeResponse
from route_models.ranking import (
    FieldContributionResponse,
    FieldPreviewResponse,
    ItemExplanationResponse,
    ModelStatsResponse,
    RankingStatsResponse,
)
from routers.auth import authenticate
from ranking.engine import label_counts, load_model_stats, rank_feed
from ranking.explain import explain_item

feed_router = APIRouter()


def get_feed_by_name_hash(user_hash: str, name_hash: str) -> Feed:
    feed = Feed.read(user_hash=user_hash, name_hash=name_hash)
    if feed is None:
        raise HTTPException(status_code=404, detail="Feed not found")

    return feed


# create feed
@feed_router.post("/create", summary="Create a feed", response_model=FeedResponse)
def create_feed(feed_name: str, user: User = Depends(authenticate)) -> FeedResponse:
    feed = Feed(user_hash=user.name_hash, name=feed_name)
    if not feed.exists():
        feed.create()
    return FeedResponse.from_db_model(feed)


# rename feed
@feed_router.post("/rename", summary="Rename a feed", response_model=FeedResponse)
def rename_feed(
    feed_name_hash: str, new_name: str, user: User = Depends(authenticate)
) -> FeedResponse:
    feed = get_feed_by_name_hash(user.name_hash, feed_name_hash)

    new_name = new_name.strip()
    if not new_name:
        raise HTTPException(status_code=422, detail="Feed name cannot be empty")

    if new_name != feed.name:
        # renaming must not collide with another of the user's feeds
        if Feed(user_hash=user.name_hash, name=new_name).exists():
            raise HTTPException(
                status_code=409,
                detail=f'A feed named "{new_name}" already exists',
            )
        feed.rename(new_name)

    return FeedResponse.from_db_model(feed)


# delete feed
@feed_router.delete(
    "/delete",
    summary="Delete a feed",
    response_model=AcknowledgeResponse,
)
def delete_feed(
    feed_name_hash: str, user: User = Depends(authenticate)
) -> AcknowledgeResponse:
    feed = get_feed_by_name_hash(user.name_hash, feed_name_hash)
    if feed.exists():
        feed.delete()
        return AcknowledgeResponse()

    raise HTTPException(status_code=404, detail="Feed not found")


# get a feed
@feed_router.get("/get", summary="Get a feed", response_model=FeedResponse)
def get_feed(feed_name_hash: str, user: User = Depends(authenticate)) -> FeedResponse:
    feed = get_feed_by_name_hash(user.name_hash, feed_name_hash)

    if feed is None:
        raise HTTPException(status_code=404, detail="Feed not found")

    return FeedResponse.from_db_model(feed)


# get all feeds
@feed_router.get(
    "/list",
    summary="List feeds a user has created",
    response_model=List[FeedResponse],
)
def list_feeds(user: User = Depends(authenticate)) -> List[FeedResponse]:
    # TODO add list of sources in each feed in the response
    return [
        FeedResponse.from_db_model(f, stats=f.stats())
        for f in user.feeds
        if f is not None
    ]


# get all sources in a feed
@feed_router.get(
    "/sources",
    summary="List all sources in a feed",
    response_model=List[SourceRouteModel],
)
def sources(
    feed_name_hash: str, user: User = Depends(authenticate)
) -> List[SourceRouteModel]:
    feed = Feed.read(user_hash=user.name_hash, name_hash=feed_name_hash)

    if feed is None:
        raise HTTPException(status_code=404, detail="Feed not found")

    return [
        SourceRouteModel.from_stats_row(feed.name_hash, row)
        for row in feed.sources_with_stats()
    ]


# get all items in a feed
@feed_router.get(
    "/items",
    summary="List all items in a feed",
    response_model=List[ItemResponse],
)
def get_feed_items(
    feed_name_hash: str,
    skip: Union[int, None] = None,
    limit: Union[int, None] = None,
    sort: str = Query(
        "best",
        description="best, predicted, predicted_asc, controversial, "
        "confident, newest, oldest",
    ),
    include_read: bool = True,
    sources: Optional[str] = Query(
        None, description="Comma-separated source name hashes to include"
    ),
    text_only: Optional[bool] = Query(
        None, description="true: only text posts, false: only posts with media"
    ),
    user: User = Depends(authenticate),
) -> List[ItemResponse]:
    feed = Feed.read(user_hash=user.name_hash, name_hash=feed_name_hash)

    if feed is None:
        raise HTTPException(status_code=404, detail="Feed not found")

    if sort not in ITEM_SORTS:
        raise HTTPException(status_code=422, detail=f"Unknown sort '{sort}'")

    source_hashes = (
        [s for s in sources.split(",") if s] if sources is not None else None
    )

    return [
        ItemResponse.from_db_model(item, **meta)
        for item, meta in feed.query_items_with_sources(
            skip=skip,
            limit=limit,
            sort=sort,
            include_read=include_read,
            source_hashes=source_hashes,
            text_only=text_only,
        )
    ]


@feed_router.get(
    "/ranking_stats",
    summary="Vote-prediction model performance for a feed",
    response_model=RankingStatsResponse,
)
def get_ranking_stats(
    feed_name_hash: str, user: User = Depends(authenticate)
) -> RankingStatsResponse:
    feed = get_feed_by_name_hash(user.name_hash, feed_name_hash)
    counts = label_counts(feed)
    return RankingStatsResponse(
        models=[ModelStatsResponse(**row) for row in load_model_stats(feed)],
        up_votes=counts["up"],
        down_votes=counts["down"],
        neutral_votes=counts["neutral"],
        total_items=counts["total_items"],
        predicted_items=counts["predicted_items"],
    )


@feed_router.post(
    "/rerank",
    summary="Re-evaluate prediction models and re-rank a feed now",
    response_model=RankingStatsResponse,
)
def rerank_feed(
    feed_name_hash: str, user: User = Depends(authenticate)
) -> RankingStatsResponse:
    feed = get_feed_by_name_hash(user.name_hash, feed_name_hash)
    stats = rank_feed(feed)
    counts = label_counts(feed)
    return RankingStatsResponse(
        models=[
            ModelStatsResponse(
                model_name=s.model_name,
                n_labels=s.n_labels,
                mae=s.mae,
                rmse=s.rmse,
                sign_accuracy=s.sign_accuracy,
                chosen=s.chosen,
            )
            for s in stats
        ],
        up_votes=counts["up"],
        down_votes=counts["down"],
        neutral_votes=counts["neutral"],
        total_items=counts["total_items"],
        predicted_items=counts["predicted_items"],
    )


@feed_router.get(
    "/item_explanation",
    summary="Explain why an item got its predicted score",
    response_model=ItemExplanationResponse,
)
def get_item_explanation(
    feed_name_hash: str,
    item_url_hash: str,
    user: User = Depends(authenticate),
) -> ItemExplanationResponse:
    feed = get_feed_by_name_hash(user.name_hash, feed_name_hash)
    explanation = explain_item(feed, item_url_hash)
    if explanation is None:
        raise HTTPException(
            status_code=409,
            detail="Not enough votes yet to explain this recommendation.",
        )
    def _preview(p) -> FieldPreviewResponse:
        return FieldPreviewResponse(
            text=p.text,
            image_url=p.image_url,
            source=p.source,
            author=p.author,
            date_published=p.date_published,
            has_image=p.has_image,
            has_media=p.has_media,
            image_embedded=p.image_embedded,
        )

    return ItemExplanationResponse(
        model_name=explanation.model_name,
        baseline_score=explanation.baseline_score,
        fields=[
            FieldContributionResponse(
                field=f.field,
                label=f.label,
                sign=f.sign,
                level=f.level,
                description=f.description,
                preview=_preview(f.preview),
            )
            for f in explanation.fields
        ],
    )


# TODO search items in a feed
