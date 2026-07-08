from fastapi import APIRouter, BackgroundTasks, HTTPException, Depends
from typing import Dict, List, Union


from db.source_template import SourceTemplate
from db.source import Source
from route_models.source import SourceRouteModel
from route_models.source_from_template import SourceFromTemplate
from db.user import User
from db.feed import Feed
from ingest.jobs import ingest_source_now
from routers.auth import authenticate

source_template_router = APIRouter()


@source_template_router.get(
    "/list_all", summary="List all source templates", response_model=Dict[str, str]
)
def list_source_templates(
    user: User = Depends(authenticate),
) -> Dict[str, str]:  # TODO add response model
    source_templates = SourceTemplate.read_all()
    # TODO alphabetize?
    return {t.name_hash: t.user_friendly_name for t in source_templates}


@source_template_router.get(
    "/get",
    summary="Get a source template",
    response_model=SourceTemplate,
)
def get_source_template(
    name_hash: str, user: User = Depends(authenticate)
) -> SourceTemplate:
    source_template = SourceTemplate.read(name_hash)
    if source_template:
        return source_template
    else:
        raise HTTPException(status_code=404, detail="Source template not found")


# create a source from a template
@source_template_router.post(
    "/create",
    summary="Create a source from a template",
    response_model=SourceRouteModel,
)
def create_source_from_template(
    sf_template: SourceFromTemplate,
    background_tasks: BackgroundTasks,
    user: User = Depends(authenticate),
) -> SourceRouteModel:
    # confirm the feed exists
    feed = Feed.read(user.name_hash, sf_template.feed_hash)
    if not feed:
        raise HTTPException(status_code=404, detail="Feed not found")

    # find the source template
    source_template = SourceTemplate.read(
        name_hash=sf_template.source_template_name_hash
    )

    if not source_template:
        raise HTTPException(status_code=404, detail="Source template not found")

    try:
        source_url = source_template.create_rss_url(**sf_template.parameters)
    except Exception as e:
        # bad/missing template parameters — tell the user what's wrong
        raise HTTPException(status_code=422, detail=str(e))
    source = Source(
        user_hash=user.name_hash,
        feed_hash=sf_template.feed_hash,
        name=sf_template.source_name,
        url=source_url,
        template_name_hash=source_template.name_hash,
        template_parameters=sf_template.parameters,
    )
    if source.exists():
        # add_source() silently no-ops on duplicates, which used to leave the
        # new source's items attributed to the old source of the same name
        raise HTTPException(
            status_code=409,
            detail=(
                f'A source named "{sf_template.source_name}" already exists '
                "in this feed. Pick a different name."
            ),
        )
    feed.add_source(source)

    # kick off the first ingest right away instead of waiting for the schedule
    background_tasks.add_task(ingest_source_now, source)

    return SourceRouteModel.from_db_model(source)


@source_template_router.get(
    "/search",
    summary="Search for a template",
    response_model=List[SourceTemplate],
)
def search_source_templates(
    query: str = "",
    skip: Union[int, None] = None,
    limit: Union[int, None] = None,
    user: User = Depends(authenticate),
) -> List[SourceTemplate]:
    source_templates = SourceTemplate.search(query, skip, limit)
    return source_templates
