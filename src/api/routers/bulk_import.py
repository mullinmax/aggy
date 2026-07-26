from fastapi import APIRouter, Depends, HTTPException

import bulk_import
from db.feed import Feed
from db.source import Source
from db.source_template import SourceTemplate
from db.user import User
from route_models.bulk_import import (
    BulkCreateRequest,
    BulkCreateResponse,
    BulkCreateResult,
    BulkCreateResultStatus,
    ImportCandidateResponse,
    ImportParseRequest,
    ImportParseResponse,
    ImportPlatform,
)
from routers.auth import authenticate

bulk_import_router = APIRouter()

# One import request creates at most this many sources; the UI never sends
# more rows than parse returned, so this only guards hand-crafted requests.
MAX_BULK_SOURCES = 2000


@bulk_import_router.post(
    "/parse",
    summary="Parse subscription data (export file, pasted list, or username) "
    "into source candidates",
    response_model=ImportParseResponse,
)
def parse_subscriptions(
    request: ImportParseRequest,
    user: User = Depends(authenticate),
) -> ImportParseResponse:
    try:
        if request.platform == ImportPlatform.bluesky:
            if not (request.username or "").strip():
                raise ValueError("Enter a Bluesky handle, e.g. jay.bsky.team")
            candidates, warnings = bulk_import.fetch_bluesky_follows(request.username)
        else:
            if not (request.data or "").strip():
                raise ValueError("Upload an export file or paste your subscriptions")
            if request.platform == ImportPlatform.reddit:
                candidates, warnings = bulk_import.parse_reddit(request.data)
            elif request.platform == ImportPlatform.youtube:
                candidates, warnings = bulk_import.parse_youtube(request.data)
            else:
                candidates, warnings = bulk_import.parse_opml(request.data)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception:
        raise HTTPException(
            status_code=502,
            detail="Couldn't reach the platform to look up subscriptions; try again",
        )

    if not candidates:
        raise HTTPException(
            status_code=422, detail="No sources found in the provided data"
        )

    return ImportParseResponse(
        candidates=[ImportCandidateResponse(**c.model_dump()) for c in candidates],
        warnings=warnings,
    )


@bulk_import_router.post(
    "/create",
    summary="Create many sources at once, each in its chosen feed",
    response_model=BulkCreateResponse,
)
def bulk_create_sources(
    request: BulkCreateRequest,
    user: User = Depends(authenticate),
) -> BulkCreateResponse:
    if len(request.sources) > MAX_BULK_SOURCES:
        raise HTTPException(
            status_code=422,
            detail=f"At most {MAX_BULK_SOURCES} sources per import",
        )

    feeds: dict = {}  # feed_name_hash -> Feed (or None when missing)
    templates: dict = {}  # template_name_hash -> SourceTemplate (or None)
    results = []

    def result(row, status, detail=None):
        results.append(
            BulkCreateResult(
                source_name=row.source_name,
                feed_name_hash=row.feed_name_hash,
                status=status,
                detail=detail,
            )
        )

    for row in request.sources:
        if row.feed_name_hash not in feeds:
            feeds[row.feed_name_hash] = Feed.read(
                user_hash=user.name_hash, name_hash=row.feed_name_hash
            )
        feed = feeds[row.feed_name_hash]
        if feed is None:
            result(row, BulkCreateResultStatus.error, "Feed not found")
            continue

        name = (row.source_name or "").strip()
        if not name:
            result(row, BulkCreateResultStatus.error, "Source name cannot be empty")
            continue

        template = None
        if row.template_name_hash:
            if row.template_name_hash not in templates:
                templates[row.template_name_hash] = SourceTemplate.read(
                    name_hash=row.template_name_hash
                )
            template = templates[row.template_name_hash]
            if template is None:
                result(row, BulkCreateResultStatus.error, "Source template not found")
                continue

        try:
            if template:
                url = template.create_rss_url(**(row.template_parameters or {}))
            elif row.source_url:
                url = row.source_url
            else:
                result(row, BulkCreateResultStatus.error, "Source has no URL")
                continue

            source = Source(
                user_hash=user.name_hash,
                feed_hash=row.feed_name_hash,
                name=name,
                url=url,
                template_name_hash=template.name_hash if template else None,
                template_parameters=row.template_parameters if template else None,
                # a template's sources are read the way the template says
                kind=template.kind if template else "rss",
            )
        except Exception as e:
            result(row, BulkCreateResultStatus.error, str(e))
            continue

        if source.exists():
            result(
                row,
                BulkCreateResultStatus.duplicate,
                "A source with this name already exists in the feed",
            )
            continue

        try:
            # New sources are created due for ingestion, so the scheduler
            # drains a large import gradually instead of fetching hundreds
            # of feeds at once.
            feed.add_source(source)
            result(row, BulkCreateResultStatus.created)
        except Exception as e:
            result(row, BulkCreateResultStatus.error, str(e))

    counts = {status: 0 for status in BulkCreateResultStatus}
    for r in results:
        counts[r.status] += 1
    return BulkCreateResponse(
        results=results,
        created=counts[BulkCreateResultStatus.created],
        duplicates=counts[BulkCreateResultStatus.duplicate],
        errors=counts[BulkCreateResultStatus.error],
    )
