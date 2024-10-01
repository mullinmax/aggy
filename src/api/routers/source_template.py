from fastapi import APIRouter, HTTPException, Depends
from typing import Dict


from db.source_template import SourceTemplate
from db.source import Source
from route_models.source import SourceRouteModel
from route_models.source_from_template import SourceFromTemplate
from db.user import User
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
    ff_template: SourceFromTemplate,
    user: User = Depends(authenticate),
) -> SourceRouteModel:
    # source_template = SourceTemplate.read(name_hash=source_template_name_hash)
    source_template = SourceTemplate.read(
        name_hash=ff_template.source_template_name_hash
    )

    if not source_template:
        raise HTTPException(status_code=404, detail="Source template not found")

    source_url = source_template.create_rss_url(**ff_template.parameters)
    source = Source(
        user_hash=user.name_hash,
        feed_hash=ff_template.feed_hash,
        name=ff_template.source_name,
        url=source_url,
    )
    source.create()

    return SourceRouteModel.from_db_model(source)
