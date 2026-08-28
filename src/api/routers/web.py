from pathlib import Path
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, FileResponse, Response
from fastapi.templating import Jinja2Templates

import extension_bundle

BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def static_url(path: str) -> str:
    """Static asset URL with a cache-busting version derived from the file's
    mtime, so browsers pick up new assets after a deploy instead of serving
    stale cached scripts (which can break the page, e.g. duplicate globals
    from an old app.js alongside a new core.js)."""
    file = BASE_DIR / "static" / path.lstrip("/")
    try:
        version = int(file.stat().st_mtime)
    except OSError:
        version = 0
    return f"/static/{path.lstrip('/')}?v={version}"


templates.env.globals["static_url"] = static_url

web_router = APIRouter()


@web_router.get("/login", response_class=HTMLResponse, include_in_schema=False)
async def login_page(request: Request):
    return templates.TemplateResponse(request=request, name="login.html")


@web_router.get("/app", response_class=HTMLResponse, include_in_schema=False)
async def app_page(request: Request):
    return templates.TemplateResponse(request=request, name="app.html")


@web_router.get(
    "/browser-extension", response_class=HTMLResponse, include_in_schema=False
)
async def browser_extension_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="extension.html",
        context={
            "available": extension_bundle.is_available(),
            "version": extension_bundle.version(),
        },
    )


@web_router.get("/extension.zip", include_in_schema=False)
async def browser_extension_zip(request: Request):
    """The extension, zipped for "Load unpacked".

    Deliberately unauthenticated: it is the same open-source files as the
    repository, and the only thing this build adds is the address of the
    instance the user just downloaded it from.
    """
    instance_url = str(request.base_url).rstrip("/")

    try:
        data = extension_bundle.build_zip(instance_url)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

    return Response(
        content=data,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{extension_bundle.filename()}"',
            # the bundle carries this instance's URL, so a shared cache must
            # not hand it to someone who asked a different host
            "Cache-Control": "private, no-cache",
        },
    )


@web_router.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return FileResponse(BASE_DIR / "static" / "favicon.svg", media_type="image/svg+xml")


@web_router.get("/sw.js", include_in_schema=False)
async def service_worker():
    # Served from the site root so the worker's scope covers the whole app
    # (a worker at /static/sw.js could only control /static/*). No-cache so
    # clients pick up a new worker on deploy instead of an old cached one.
    return FileResponse(
        BASE_DIR / "static" / "sw.js",
        media_type="application/javascript",
        headers={
            "Cache-Control": "no-cache",
            "Service-Worker-Allowed": "/",
        },
    )


@web_router.get("/manifest.webmanifest", include_in_schema=False)
async def manifest():
    # No-cache so a changed manifest (e.g. orientation) is re-read on the next
    # visit instead of a stale copy lingering — installed PWAs otherwise keep
    # the manifest captured at install time until the browser refreshes it.
    return FileResponse(
        BASE_DIR / "static" / "manifest.webmanifest",
        media_type="application/manifest+json",
        headers={"Cache-Control": "no-cache"},
    )
