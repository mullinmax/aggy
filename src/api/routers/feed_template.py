from fastapi import APIRouter, HTTPException, Depends
from typing import Dict


from db.feed_template import FeedTemplate
from db.feed import Feed
from route_models.feed import FeedRouteModel
from db.user import User
from routers.auth import authenticate

feed_template_router = APIRouter()


@feed_template_router.get(
    "/list_all", summary="List all feed templates", response_model=Dict[str, str]
)
def list_feed_templates(
    user: User = Depends(authenticate),
) -> Dict[str, str]:  # TODO add response model
    feed_templates = FeedTemplate.read_all()
    # TODO alphabetize?
    return {t.name_hash: t.user_friendly_name for t in feed_templates}


@feed_template_router.get(
    "/get",
    summary="Get a feed template",
    response_model=FeedTemplate,
)
def get_feed_template(
    name_hash: str, user: User = Depends(authenticate)
) -> FeedTemplate:
    feed_template = FeedTemplate.read(name_hash)
    if feed_template:
        return feed_template
    else:
        raise HTTPException(status_code=404, detail="Feed template not found")


# create a feed from a template
@feed_template_router.post(
    "/create",
    summary="Create a feed from a template",
    response_model=FeedTemplate,
)
def create_feed_from_template(
    feed_template_name_hash: str,
    category_hash: str,
    feed_name: str,
    parameters: Dict[str, str],
    user: User = Depends(authenticate),
) -> FeedRouteModel:
    feed_template = FeedTemplate.read(name_hash=feed_template_name_hash)

    if not feed_template:
        raise HTTPException(status_code=404, detail="Feed template not found")

    feed_url = feed_template.create_rss_url(**parameters)
    feed = Feed(
        user_hash=user.user_hash,
        category_hash=category_hash,
        name=feed_name,
        url=feed_url,
    )
    feed.create()

    return FeedRouteModel.from_db_model(feed)
