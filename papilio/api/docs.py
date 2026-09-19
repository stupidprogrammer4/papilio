"""Swagger UI served from local assets."""

from fastapi import FastAPI, Request
from fastapi.openapi.docs import (
    get_swagger_ui_html,
    get_swagger_ui_oauth2_redirect_html,
)
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles


def setup_docs(
    app: FastAPI,
    *,
    docs_url: str = "/docs",
    static_url: str = "/static/swagger",
) -> None:
    """Register local docs on an app created with docs_url=None."""
    if app.openapi_url is None:
        return
    openapi_url = app.openapi_url
    redirect_url = app.swagger_ui_oauth2_redirect_url
    app.docs_url = docs_url
    app.mount(
        static_url,
        StaticFiles(packages=[("swagger_ui", "static")]),
        name="swagger",
    )

    @app.get(docs_url, include_in_schema=False)
    async def swagger_ui(request: Request) -> HTMLResponse:
        root = request.scope.get("root_path", "").rstrip("/")
        return get_swagger_ui_html(
            openapi_url=f"{root}{openapi_url}",
            title=f"{app.title} — API docs",
            oauth2_redirect_url=(
                f"{root}{redirect_url}" if redirect_url else None
            ),
            swagger_js_url=f"{root}{static_url}/swagger-ui-bundle.js",
            swagger_css_url=f"{root}{static_url}/swagger-ui.css",
            swagger_favicon_url=f"{root}{static_url}/favicon-32x32.png",
            init_oauth=app.swagger_ui_init_oauth,
            swagger_ui_parameters=app.swagger_ui_parameters,
        )

    if redirect_url is not None:

        @app.get(redirect_url, include_in_schema=False)
        async def swagger_ui_redirect() -> HTMLResponse:
            return get_swagger_ui_oauth2_redirect_html()
