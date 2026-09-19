import shutil
import socket
import subprocess
import threading
import time

import pytest
import uvicorn
import yaml
from fastapi import APIRouter

from papilio.api.application import create_app
from papilio.core.config import Settings
from papilio.scaffolding import project

BROWSER = (
    shutil.which("google-chrome")
    or shutil.which("chromium")
    or shutil.which("chromium-browser")
)


@pytest.mark.skipif(BROWSER is None, reason="Requires Chrome or Chromium")
@pytest.mark.parametrize("root_path", ["", "/gateway"])
@pytest.mark.parametrize("with_route", [False, True])
def test_browser_renders_openapi_31(tmp_path, root_path, with_route):
    assert BROWSER is not None
    settings = Settings.model_validate(
        yaml.safe_load(project.files("shop", "Shop")["config.yml"])
    )
    settings.app.modules = []
    router = APIRouter()

    @router.get("/echo")
    def echo(value: str | None = None) -> dict[str, str | None]:
        return {"value": value}

    app = create_app(
        settings,
        routers=(router,) if with_route else (),
        title="Browser contract",
        root_path=root_path,
        docs_url="/reference",
        openapi_url="/schema.json",
    )
    assert app.openapi()["openapi"] == "3.1.0"
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(app, log_level="error"))
        worker = threading.Thread(
            target=server.run, kwargs={"sockets": [listener]}, daemon=True
        )
        worker.start()
        try:
            deadline = time.monotonic() + 10
            while not server.started and time.monotonic() < deadline:
                time.sleep(0.01)
            assert server.started
            browser = subprocess.run(
                [
                    BROWSER,
                    "--headless",
                    "--no-sandbox",
                    "--disable-gpu",
                    "--disable-dev-shm-usage",
                    "--disable-background-networking",
                    "--no-first-run",
                    f"--user-data-dir={tmp_path / 'browser'}",
                    "--dump-dom",
                    "--virtual-time-budget=5000",
                    f"http://127.0.0.1:{port}{root_path}/reference",
                ],
                capture_output=True,
                text=True,
                timeout=30,
                check=True,
            )
            dom = browser.stdout
            assert "Unable to render this definition" not in dom
            assert '<div class="swagger-ui">' in dom
            assert 'class="title">Browser contract' in dom
            if with_route:
                assert 'class="opblock opblock-get' in dom
                assert 'data-path="/echo"' in dom
            else:
                assert "No operations defined in spec!" in dom
        finally:
            server.should_exit = True
            worker.join(timeout=10)
            assert not worker.is_alive()
