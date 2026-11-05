import subprocess
import sys
from collections.abc import AsyncGenerator
from dataclasses import dataclass

import pytest
import yaml
from dishka import Provider, Scope, provide

from papilio.api.application import create_app
from papilio.core.config import Settings
from papilio.scaffolding import project


@dataclass
class Resource:
    name: str
    closed: bool = False


class Resources(Provider):
    @provide(scope=Scope.APP)
    async def resource(self, settings: Settings) -> AsyncGenerator[Resource]:
        resource = Resource(settings.fastapi.title)
        try:
            yield resource
        finally:
            resource.closed = True


def test_factory_and_cli_import_without_configuration(tmp_path):
    subprocess.run(
        [
            sys.executable,
            "-c",
            "from papilio.api.application import create_app; "
            "import papilio.cli.app",
        ],
        cwd=tmp_path,
        check=True,
    )


async def test_application_instances_own_settings_and_resource_lifetimes(
    monkeypatch,
):
    monkeypatch.setattr(
        "papilio.api.application.logger.setup", lambda config: None
    )
    config = Settings.model_validate(
        yaml.safe_load(project.files("shop", "Shop")["config.yml"])
    )
    config.app.modules = []
    other = config.model_copy(deep=True)
    other.fastapi.title = "Other"
    first = create_app(config, providers=(Resources(),))
    second = create_app(other, providers=(Resources(),))
    assert first.state.dishka_container is not second.state.dishka_container
    async with second.router.lifespan_context(second):
        resource_b = await second.state.dishka_container.get(Resource)
        async with first.router.lifespan_context(first):
            resource_a = await first.state.dishka_container.get(Resource)
            assert resource_a.name == "Shop"
            assert resource_b.name == "Other"
        assert resource_a.closed
        assert not resource_b.closed
    assert resource_b.closed


async def test_public_id_error_bindings_belong_to_the_application(
    app_settings: Settings,
) -> None:
    from fastapi import APIRouter
    from httpx import ASGITransport, AsyncClient

    from papilio.core import resources
    from papilio.errors.exceptions import NotFoundException
    from papilio.tools.ids import IDEncryption

    router = APIRouter()
    error = NotFoundException(
        entity="User",
        identifier="id",
        identifier_value=42,
        message="Missing internal user 42",
        message_code=resources.NOT_FOUND_ERROR,
    )

    @router.get("/missing")
    async def missing() -> None:
        raise error

    first_codec = IDEncryption(97, 7, 500)
    second_codec = IDEncryption(97, 11, 1000)
    for codec in (first_codec, second_codec):
        app = create_app(
            app_settings,
            routers=(router,),
            middleware=(),
            docs_url=None,
            id_encryptions={"User": codec},
        )
        async with app.router.lifespan_context(app):
            async with AsyncClient(
                transport=ASGITransport(app), base_url="http://test"
            ) as client:
                response = await client.get("/missing")
        assert response.status_code == 404
        assert response.json()["error"]["identifier_value"] == str(
            codec.encode(42)
        )
    assert error.identifier_value == 42


async def test_startup_failure_closes_acquired_resources(monkeypatch):
    from contextlib import asynccontextmanager

    from papilio.infra.es.client import ESClient

    class Search(Provider):
        @provide(scope=Scope.APP)
        def es(self, resource: Resource) -> ESClient:
            raise RuntimeError("search startup failed")

    monkeypatch.setattr(
        "papilio.api.application.logger.setup", lambda config: None
    )
    config = Settings.model_validate(
        yaml.safe_load(project.files("shop", "Shop", cqrs=True)["config.yml"])
    )
    config.app.modules = []

    @asynccontextmanager
    async def lifespan(app):
        await app.state.dishka_container.get(ESClient)
        yield

    app = create_app(
        config, providers=(Resources(), Search()), lifespan=lifespan
    )
    resource = await app.state.dishka_container.get(Resource)
    with pytest.raises(RuntimeError, match="search startup failed"):
        async with app.router.lifespan_context(app):
            pytest.fail("Startup must fail before serving")
    assert resource.closed


@pytest.fixture
def app_settings(monkeypatch):
    monkeypatch.setattr(
        "papilio.api.application.logger.setup", lambda config: None
    )
    settings = Settings.model_validate(
        yaml.safe_load(project.files("shop", "Shop")["config.yml"])
    )
    settings.app.modules = []
    return settings


async def test_custom_http_components_and_lifespans(app_settings):
    from contextlib import asynccontextmanager

    from fastapi import APIRouter, FastAPI, Request
    from httpx import ASGITransport, AsyncClient
    from starlette.middleware import Middleware
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.responses import JSONResponse

    events = []

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        resource = await app.state.dishka_container.get(Resource)
        events.append("app-start")
        try:
            yield {"resource_name": resource.name}
        finally:
            assert not resource.closed
            events.append("app-stop")

    @asynccontextmanager
    async def router_lifespan(app: FastAPI):
        events.append("router-start")
        try:
            yield
        finally:
            events.append("router-stop")

    class HeaderMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            response = await call_next(request)
            response.headers["X-Custom"] = "yes"
            return response

    async def failure_handler(request: Request, error: Exception):
        return JSONResponse({"custom_error": str(error)}, status_code=409)

    router = APIRouter(lifespan=router_lifespan)

    @router.get("/custom")
    async def custom():
        raise ValueError("application failure")

    app = create_app(
        app_settings,
        providers=(Resources(),),
        routers=(router,),
        middleware=(Middleware(HeaderMiddleware),),
        lifespan=lifespan,
        exception_handlers={ValueError: failure_handler},
        title="Custom title",
        root_path="/gateway",
        docs_url=None,
    )
    assert app.title == "Custom title"
    assert app.root_path == "/gateway"
    async with app.router.lifespan_context(app) as state:
        assert state == {"resource_name": "Shop"}
        resource = await app.state.dishka_container.get(Resource)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/custom")
            assert response.status_code == 409
            assert response.json() == {"custom_error": "application failure"}
            assert response.headers["X-Custom"] == "yes"
            missing = await client.get("/missing")
            assert missing.json()["error"]["message_code"] == "route_not_found"
    assert resource.closed
    assert events == ["app-start", "router-start", "router-stop", "app-stop"]


@pytest.mark.parametrize("fail_on_exit", [False, True])
async def test_user_lifespan_failure_closes_container(
    app_settings, fail_on_exit
):
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def lifespan(app):
        if not fail_on_exit:
            raise RuntimeError("user startup")
        yield
        raise RuntimeError("user shutdown")

    app = create_app(app_settings, providers=(Resources(),), lifespan=lifespan)
    resource = await app.state.dishka_container.get(Resource)
    with pytest.raises(RuntimeError, match="user"):
        async with app.router.lifespan_context(app):
            assert not resource.closed
    assert resource.closed


async def test_custom_docs_respect_fastapi_options(app_settings):
    from httpx import ASGITransport, AsyncClient

    app = create_app(
        app_settings,
        middleware=(),
        title="Custom docs",
        root_path="/gateway",
        docs_url="/reference",
        openapi_url="/schema.json",
        swagger_ui_oauth2_redirect_url=None,
        swagger_ui_parameters={"displayRequestDuration": True},
    )
    async with app.router.lifespan_context(app):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/reference")
            assert response.status_code == 200
            assert "Custom docs" in response.text
            assert "/gateway/schema.json" in response.text
            assert (
                "/gateway/static/swagger/swagger-ui-bundle.js" in response.text
            )
            assert '"displayRequestDuration": true' in response.text
            assert "oauth2RedirectUrl" not in response.text
            assert (await client.get("/docs")).status_code == 404
            schema = await client.get("/schema.json")
            assert schema.json()["openapi"] == app.openapi_version


@pytest.mark.parametrize(
    "options", [{"docs_url": None}, {"openapi_url": None}]
)
async def test_documentation_can_be_disabled(app_settings, options):
    from httpx import ASGITransport, AsyncClient

    app = create_app(app_settings, middleware=(), **options)
    async with app.router.lifespan_context(app):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            assert (await client.get("/docs")).status_code == 404
            assert (
                await client.get("/docs/oauth2-redirect")
            ).status_code == 404
            assert (
                await client.get("/static/swagger/favicon-32x32.png")
            ).status_code == 404
