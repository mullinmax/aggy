from pathlib import Path
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))

web_router = APIRouter()


@web_router.get("/login", response_class=HTMLResponse, include_in_schema=False)
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})


@web_router.get("/app", response_class=HTMLResponse, include_in_schema=False)
async def app_page(request: Request):
    return templates.TemplateResponse("app.html", {"request": request})
