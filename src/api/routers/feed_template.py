from fastapi import APIRouter, HTTPException

from typing import Dict


from db.feed_template import FeedTemplate

feed_template_router = APIRouter()


# list all feed templates
@feed_template_router.get(
    "/list_all", summary="List all feed templates", response_model=Dict[str, str]
)
def list_feed_templates() -> Dict[str, str]:  # TODO add response model
    feed_templates = FeedTemplate.read_all()
    # TODO alphabetize?
    return {t.name_hash: t.user_friendly_name for t in feed_templates}


# get a feed template
@feed_template_router.get(
    "/get",
    summary="Get a feed template",
    response_model=FeedTemplate,
)
def get_feed_template(name_hash: str) -> FeedTemplate:
    feed_template = FeedTemplate.read(name_hash)
    if feed_template:
        return feed_template
    else:
        raise HTTPException(status_code=404, detail="Feed template not found")
