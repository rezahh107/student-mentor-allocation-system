from fastapi import FastAPI
from fastapi.templating import Jinja2Templates
from starlette.requests import Request
from starlette.staticfiles import StaticFiles


def test_rtl_language_and_vazir_font_present(tmp_path) -> None:
    app = FastAPI()
    app.mount("/static", StaticFiles(directory="assets"), name="static")
    templates = Jinja2Templates(directory="src/phase6_import_to_sabt/templates")
    scope = {"type": "http", "method": "GET", "path": "/", "headers": [], "app": app, "router": app.router}
    request = Request(scope)
    template = templates.get_template("base.html")
    html = template.render({"request": request, "title": "آزمایش"})
    assert "lang=\"fa-IR\"" in html
    assert "dir=\"rtl\"" in html
    assert "font-family: 'Vazir'" in html
