import json
import logging
import threading

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from typing import List, Optional, Union

from db.feed import Feed, ITEM_AGE_WINDOWS, ITEM_SORTS, POST_TYPES
from db.user import User
from route_models.feed import FeedResponse
from route_models.graph import (
    FeedGraphResponse,
    GraphEdgeResponse,
    GraphNodeResponse,
)
from route_models.source import SourceRouteModel
from route_models.item import (
    DuplicateMemberResponse,
    ItemDuplicatesResponse,
    ItemResponse,
    RelatedItemResponse,
    RelatedItemsResponse,
)
from route_models.acknowledge import AcknowledgeResponse
from route_models.ranking import (
    FieldContributionResponse,
    FieldPreviewResponse,
    ItemExplanationResponse,
    ModelStatsResponse,
    RankingStatsResponse,
    TrainingProgressResponse,
    TrainingStatusResponse,
)
from routers.auth import authenticate
from ranking import progress
from ranking.engine import (
    label_counts,
    load_model_stats,
    run_training,
    start_training,
    training_summary,
)
from ranking.explain import (
    ExplanationBaseline,
    ExplanationStarted,
    ExplanationUnavailable,
    FieldScored,
    explain_item,
    explain_item_stream,
)

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
    post_types: Optional[str] = Query(
        None,
        description="Comma-separated post types to keep: image, video, link, "
        "text. The types overlap (an illustrated article is both image and "
        "text), so an item is kept when it matches any of them. Omit for all.",
    ),
    max_age: str = Query(
        "all", description="Only items this recent: day, week, month, year, all"
    ),
    collapse_duplicates: Optional[bool] = Query(
        None,
        description="Show one member of each duplicate group -- the one the "
        "current model scores highest -- with item_duplicate_count saying how "
        "many others it stands for. False returns every member. Omit for the "
        "server default.",
    ),
    only_duplicates: bool = Query(
        False,
        description="Keep only articles that arrived more than once, for "
        "reviewing what the collapse is hiding. Composes with "
        "collapse_duplicates: collapsed, one row per duplicated story; "
        "uncollapsed, every copy of them.",
    ),
    user: User = Depends(authenticate),
) -> List[ItemResponse]:
    feed = Feed.read(user_hash=user.name_hash, name_hash=feed_name_hash)

    if feed is None:
        raise HTTPException(status_code=404, detail="Feed not found")

    if sort not in ITEM_SORTS:
        raise HTTPException(status_code=422, detail=f"Unknown sort '{sort}'")

    if max_age != "all" and max_age not in ITEM_AGE_WINDOWS:
        raise HTTPException(status_code=422, detail=f"Unknown max_age '{max_age}'")

    source_hashes = (
        [s for s in sources.split(",") if s] if sources is not None else None
    )

    types = (
        [t.strip() for t in post_types.split(",") if t.strip()]
        if post_types is not None
        else None
    )
    unknown = [t for t in types or [] if t not in POST_TYPES]
    if unknown:
        raise HTTPException(status_code=422, detail=f"Unknown post type '{unknown[0]}'")

    return [
        ItemResponse.from_db_model(item, **meta)
        for item, meta in feed.query_items_with_sources(
            skip=skip,
            limit=limit,
            sort=sort,
            include_read=include_read,
            source_hashes=source_hashes,
            post_types=types,
            max_age=None if max_age == "all" else max_age,
            collapse_duplicates=collapse_duplicates,
            only_duplicates=only_duplicates,
        )
    ]


def _training_progress(feed: Feed) -> Optional[TrainingProgressResponse]:
    run = progress.status(feed.user_hash, feed.name_hash)
    return TrainingProgressResponse(**run) if run else None


def _stats_fields(feed: Feed) -> dict:
    """Everything in the stats response except the run in flight."""
    counts = label_counts(feed)
    return {
        "models": [ModelStatsResponse(**row) for row in load_model_stats(feed)],
        "up_votes": counts["up"],
        "down_votes": counts["down"],
        "neutral_votes": counts["neutral"],
        "total_items": counts["total_items"],
        "predicted_items": counts["predicted_items"],
        **training_summary(feed),
    }


@feed_router.get(
    "/ranking_stats",
    summary="Vote-prediction model performance for a feed",
    response_model=RankingStatsResponse,
)
def get_ranking_stats(
    feed_name_hash: str, user: User = Depends(authenticate)
) -> RankingStatsResponse:
    feed = get_feed_by_name_hash(user.name_hash, feed_name_hash)
    return RankingStatsResponse(
        **_stats_fields(feed), training=_training_progress(feed)
    )


@feed_router.get(
    "/training_status",
    summary="Progress of a feed's model training, and how stale its models are",
    response_model=TrainingStatusResponse,
)
def get_training_status(
    feed_name_hash: str, user: User = Depends(authenticate)
) -> TrainingStatusResponse:
    """Cheap enough to poll while a retrain runs: no per-model stats, just
    where the run has got to and when the models were last rebuilt."""
    feed = get_feed_by_name_hash(user.name_hash, feed_name_hash)
    return TrainingStatusResponse(
        training=_training_progress(feed), **training_summary(feed)
    )


@feed_router.post(
    "/rerank",
    summary="Start re-evaluating prediction models and re-ranking a feed",
    response_model=RankingStatsResponse,
)
def rerank_feed(
    feed_name_hash: str, user: User = Depends(authenticate)
) -> RankingStatsResponse:
    """Kick off a training run and return straight away.

    Cross-validating the whole model zoo takes long enough that holding the
    request open would time out on a big feed and pin the UI to one screen.
    The run happens on a background thread instead; poll `/training_status`
    to follow it, and re-read `/ranking_stats` once it reports done. Asking
    again while a run is in flight simply joins the existing one.

    This deliberately bypasses `feeds_needing_training`: the scheduled job
    only retrains a feed whose votes moved, and asking for a retrain anyway
    — to see the bake-off re-run, or after changing the model zoo — is now
    the whole point of this endpoint.
    """
    feed = get_feed_by_name_hash(user.name_hash, feed_name_hash)

    # Read the "before" picture first: the run below can finish while this
    # request is still being served on a small feed, and the caller asked for
    # the state it started from.
    fields = _stats_fields(feed)

    def run() -> None:
        try:
            run_training(feed)
        except Exception as e:
            logging.exception(f"Ranking feed {feed.name} failed: {e}")

    # The run is claimed here rather than on the thread, so the response
    # already reports it as running however fast the thread gets going.
    if start_training(feed):
        threading.Thread(target=run, name="feed-rerank", daemon=True).start()

    return RankingStatsResponse(**fields, training=_training_progress(feed))


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


def _preview(p) -> FieldPreviewResponse:
    """One article's own data for a field, as the explanation shows it. Shared
    by the whole-body route and the streaming one, which send the same thing."""
    return FieldPreviewResponse(
        text=p.text,
        image_url=p.image_url,
        source=p.source,
        author=p.author,
        date_published=p.date_published,
        has_image=p.has_image,
        has_media=p.has_media,
        image_embedded=p.image_embedded,
        voted_neighbors=p.voted_neighbors,
    )


# The explanation as it is computed, one JSON object per line.
#
# Fitting the model is the slow part and it is the *last* thing the reader
# needs: what the model was shown is known before it is fitted, and each
# field's contribution lands one at a time after it. Holding all of that back
# to answer once means several seconds of a spinner over a modal that could
# have been full of the article's own text from the start.
#
# NDJSON rather than server-sent events because this needs the Authorization
# header, which EventSource cannot set. Left out of the OpenAPI schema on
# purpose: the generated SDK parses a whole body as one JSON document, which is
# exactly what this is not -- the reader in app.js consumes it line by line.
#
# Line types:
#   {"type": "started",  "fields": [...], "preview": {...}}
#   {"type": "baseline", "model_name": str, "baseline_score": float}
#   {"type": "field",    "field": str, "marks": [{field, sign, level}, ...]}
#   {"type": "done"}
#   {"type": "error",    "detail": str}
#
# A `field` line carries the marks for every field measured so far, not just
# its own: marks are ranked against each other, so an earlier field's level can
# move as later ones land (see ranking.explain.FieldScored).
@feed_router.get(
    "/item_explanation_stream",
    summary="Stream an item's explanation as it is computed",
    include_in_schema=False,
)
def get_item_explanation_stream(
    feed_name_hash: str,
    item_url_hash: str,
    user: User = Depends(authenticate),
):
    feed = get_feed_by_name_hash(user.name_hash, feed_name_hash)
    events = explain_item_stream(feed, item_url_hash)

    # Drawn from the generator here, before the response starts, so "not enough
    # votes yet" is still a 409 the client can read as a status rather than an
    # error line inside a 200.
    try:
        first = next(events)
    except ExplanationUnavailable as unavailable:
        raise HTTPException(status_code=409, detail=str(unavailable)) from None
    except StopIteration:
        raise HTTPException(
            status_code=409,
            detail="Not enough votes yet to explain this recommendation.",
        ) from None

    def encode(event) -> dict:
        if isinstance(event, ExplanationStarted):
            return {
                "type": "started",
                "fields": [
                    {
                        "field": outline.field,
                        "label": outline.label,
                        "description": outline.description,
                    }
                    for outline in event.fields
                ],
                "preview": _preview(event.preview).model_dump(mode="json"),
            }
        if isinstance(event, ExplanationBaseline):
            return {
                "type": "baseline",
                "model_name": event.model_name,
                "baseline_score": event.baseline_score,
            }
        if isinstance(event, FieldScored):
            return {
                "type": "field",
                "field": event.field,
                "marks": [
                    {"field": m.field, "sign": m.sign, "level": m.level}
                    for m in event.marks
                ],
            }
        raise TypeError(f"unknown explanation event {type(event)!r}")

    def lines():
        yield json.dumps(encode(first)) + "\n"
        try:
            for event in events:
                yield json.dumps(encode(event)) + "\n"
        except ExplanationUnavailable as unavailable:
            # Choosing the model is left until after the previews, so this can
            # land mid-stream. It is a reason, not a fault: say it as one.
            yield json.dumps({"type": "error", "detail": str(unavailable)}) + "\n"
            return
        except Exception as e:
            # The response is already a 200 by now, so a failure has to be said
            # in the body. The reader shows it in place of the marks and keeps
            # the previews it already has.
            logging.exception(f"Explaining {item_url_hash} failed: {e}")
            failed = {"type": "error", "detail": "Could not finish this explanation."}
            yield json.dumps(failed) + "\n"
            return
        yield json.dumps({"type": "done"}) + "\n"

    return StreamingResponse(
        lines(),
        media_type="application/x-ndjson",
        # nginx and friends will happily sit on a streamed body until it ends,
        # which would undo the whole point of sending it in pieces.
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


@feed_router.get(
    "/item_duplicates",
    summary="The items a duplicate badge stands for",
    response_model=ItemDuplicatesResponse,
)
def get_item_duplicates(
    feed_name_hash: str,
    group_hash: str,
    user: User = Depends(authenticate),
) -> ItemDuplicatesResponse:
    """Every member of a duplicate group, in the order the feed ranks them.

    The feed shows one member per group, so this is how the UI expands the
    badge into the copies it is standing in for. The first member is the one
    being shown; it is included rather than filtered out so the UI can mark it
    without having to work out which one it already has.

    Groups are per account, so an unknown group reads as 404 rather than as an
    empty list: there is no such thing as a group this caller can see but has
    no members in.
    """
    feed = get_feed_by_name_hash(user.name_hash, feed_name_hash)
    rows = feed.duplicate_group_members(group_hash)
    if not rows:
        raise HTTPException(status_code=404, detail="Duplicate group not found")

    return ItemDuplicatesResponse(
        duplicate_group=group_hash,
        members=[
            DuplicateMemberResponse(
                item_hash=row["url_hash"],
                item_url=row["url"],
                item_title=row["title"],
                item_source_name=row["source_name"],
                item_predicted_score=row["predicted_score"],
                item_predicted_confidence=row["predicted_confidence"],
                item_date_published=row["date_published"],
                item_duplicate_signal=row["signal"],
                item_duplicate_confidence=row["confidence"],
                item_is_shown=index == 0,
            )
            for index, row in enumerate(rows)
        ],
    )


@feed_router.get(
    "/related_items",
    summary="The articles in this feed most like a given one",
    response_model=RelatedItemsResponse,
)
def get_related_items(
    feed_name_hash: str,
    item_url_hash: str,
    limit: int = Query(
        5,
        ge=1,
        le=25,
        description="How many related articles to return, most similar first.",
    ),
    user: User = Depends(authenticate),
) -> RelatedItemsResponse:
    """What else in this feed is about the same thing, read out of the
    nearest-neighbour graph.

    Other copies of the same story are left out: those are what the duplicate
    badge stands for, and repeating them here would fill the rail with the
    article the reader already has open.

    An empty list is a normal answer, not an error -- an article ingested
    minutes ago has not been linked into the graph yet, and one in a feed of
    two articles has nothing much to be near.
    """
    feed = get_feed_by_name_hash(user.name_hash, feed_name_hash)
    return RelatedItemsResponse(
        item_hash=item_url_hash,
        related=[
            RelatedItemResponse.from_item(
                item,
                meta["similarity"],
                source_name=meta["source_name"],
                source_color=meta["source_color"],
                user_score=meta["user_score"],
                is_read=meta["is_read"],
                in_list=meta["in_list"],
                predicted_score=meta["predicted_score"],
                predicted_confidence=meta["predicted_confidence"],
                duplicate_count=meta["duplicate_count"],
                duplicate_group=meta["duplicate_group"],
            )
            for item, meta in feed.related_items(item_url_hash, limit)
        ],
    )


@feed_router.get(
    "/item",
    summary="One article of this feed, in full",
    response_model=ItemResponse,
)
def get_feed_item(
    feed_name_hash: str,
    item_url_hash: str,
    user: User = Depends(authenticate),
) -> ItemResponse:
    """One article, with its body, media and vote state.

    The graph view is what wants this. Its nodes carry only what a dot and its
    detail card need, so opening one for real -- with its pictures, its player
    and its text -- means asking for the article itself. Exactly one, rather
    than paging the feed to find it.
    """
    feed = get_feed_by_name_hash(user.name_hash, feed_name_hash)
    item, meta = feed.item(item_url_hash)
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found in this feed")
    return ItemResponse.from_db_model(item, **meta)


@feed_router.get(
    "/graph",
    summary="The feed's articles and the similarity links between them",
    response_model=FeedGraphResponse,
)
def get_feed_graph(
    feed_name_hash: str,
    limit: Optional[int] = Query(
        300,
        ge=10,
        description="How many articles to draw. A picture of ten thousand "
        "articles is a hairball, so the graph shows a window of the feed. "
        "Omit for every article the filters leave, which is honest for a feed "
        "of a few thousand and expensive for a very large one.",
    ),
    sort: str = Query(
        "newest",
        description="Which end of the feed a limited window keeps. The same "
        "orders /feed/items takes: " + ", ".join(ITEM_SORTS),
    ),
    include_read: bool = True,
    sources: Optional[str] = Query(
        None, description="Comma-separated source name hashes to include"
    ),
    post_types: Optional[str] = Query(
        None,
        description="Comma-separated post types to keep: image, video, link, "
        "text. Omit for all.",
    ),
    max_age: str = Query(
        "all", description="Only items this recent: day, week, month, year, all"
    ),
    collapse_duplicates: Optional[bool] = Query(
        None,
        description="Draw one node per duplicate group rather than one per "
        "copy. Omit for the server default.",
    ),
    only_duplicates: bool = Query(
        False, description="Keep only articles that arrived more than once."
    ),
    user: User = Depends(authenticate),
) -> FeedGraphResponse:
    """Everything the graph view draws: the feed's articles under the filters
    in force, and the stored links between the ones it returns.

    Every filter /feed/items takes, this takes too, and applies through the
    same code -- the graph is a picture of the list you were just looking at,
    so the two must agree about what is hidden.

    Edges with one end outside the window are left out rather than drawn
    dangling, so what comes back is a true subgraph of the feed's own graph.

    An article with no links yet is still a node -- it has been ingested and
    not yet placed, and a feed mid-backfill should look like a graph filling in
    rather than a graph with holes in it.
    """
    feed = get_feed_by_name_hash(user.name_hash, feed_name_hash)

    if sort not in ITEM_SORTS:
        raise HTTPException(status_code=422, detail=f"Unknown sort '{sort}'")
    if max_age != "all" and max_age not in ITEM_AGE_WINDOWS:
        raise HTTPException(status_code=422, detail=f"Unknown max_age '{max_age}'")

    source_hashes = (
        [s for s in sources.split(",") if s] if sources is not None else None
    )
    types = (
        [t.strip() for t in post_types.split(",") if t.strip()]
        if post_types is not None
        else None
    )
    unknown = [t for t in types or [] if t not in POST_TYPES]
    if unknown:
        raise HTTPException(status_code=422, detail=f"Unknown post type '{unknown[0]}'")

    nodes, edges = feed.graph(
        limit=limit,
        sort=sort,
        include_read=include_read,
        source_hashes=source_hashes,
        post_types=types,
        max_age=None if max_age == "all" else max_age,
        collapse_duplicates=collapse_duplicates,
        only_duplicates=only_duplicates,
    )
    return FeedGraphResponse(
        total_items=feed.stats()["feed_item_count"],
        nodes=[
            GraphNodeResponse(
                item_hash=node["url_hash"],
                item_url=node["url"],
                item_title=node["title"],
                item_date_published=node["date_published"],
                item_source_name=node["source_name"],
                item_source_color=node["source_color"],
                item_image_url=node["image_url"],
                item_media=node["media"],
                item_predicted_score=node["predicted_score"],
                item_predicted_confidence=node["predicted_confidence"],
                item_user_score=node["user_score"],
                item_is_read=node["is_read"],
                item_duplicate_group=node["duplicate_group"],
            )
            for node in nodes
        ],
        edges=[
            GraphEdgeResponse(
                source=edge["source"],
                target=edge["target"],
                similarity=edge["similarity"],
            )
            for edge in edges
        ],
    )


# TODO search items in a feed
