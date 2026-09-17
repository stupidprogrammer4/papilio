"""Exercise native servers, config inheritance and graceful shutdown."""

import importlib.util
import json
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

import pytest
import yaml

from papilio.scaffolding.project import files


@pytest.mark.parametrize("backend", ["uvicorn", "gunicorn", "fastapi"])
@pytest.mark.parametrize("mode", ["dev", "prod"])
def test_runner_serves_reloads_and_shuts_down(tmp_path, backend, mode):
    needed = {
        "uvicorn": "uvicorn",
        "gunicorn": "gunicorn",
        "fastapi": "fastapi_cli",
    }[backend]
    if importlib.util.find_spec(needed) is None:
        pytest.skip(f"Install the {backend} server extra for runner tests")
    if backend == "gunicorn" and os.name == "nt":
        pytest.skip("Gunicorn is Unix-only")
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    config = yaml.safe_load(files("sample", "Selected config")["config.yml"])
    config["app"] = {"modules": [], "settings": "custom.CustomSettings"}
    config["marker"] = "custom setting"
    config["run"].update(
        entrypoint="main:app",
        backend=backend,
        mode=mode,
        host="127.0.0.1",
        port=port,
        workers=1 if mode == "dev" else 2,
    )
    selected = tmp_path / "selected.yml"
    selected.write_text(yaml.safe_dump(config))
    # An incorrect selection fails loudly instead of looking like success.
    (tmp_path / "config.yml").write_text("wrong: configuration\n")
    (tmp_path / "custom.py").write_text(
        "from papilio.core.config import Settings\n"
        "class CustomSettings(Settings):\n"
        "    marker: str\n"
    )
    source = """
import os
from pathlib import Path
from contextlib import asynccontextmanager
from papilio.api.application import create_app
from papilio.core.config import get_settings
VERSION = "first"
settings = get_settings()
def event(kind):
    with Path("events.txt").open("a") as stream:
        stream.write(f"{kind}:{os.getpid()}\\n")
@asynccontextmanager
async def lifespan(app):
    event("start")
    yield
    event("stop")
app = create_app(settings, lifespan=lifespan)
@app.get("/probe")
async def probe():
    return dict(title=settings.fastapi.title, marker=settings.marker,
                config=os.environ["PAPILIO_CONFIG"], version=VERSION)
"""
    target = tmp_path / "main.py"
    target.write_text(source)
    env = {
        **os.environ,
        "PYTHONPATH": str(Path(__file__).resolve().parents[2]),
        "NO_COLOR": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    events = tmp_path / "events.txt"
    logfile = tmp_path / "server.log"
    with logfile.open("w") as log:
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "papilio.cli",
                "run",
                "--config",
                str(selected),
            ],
            cwd=tmp_path,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=os.name != "nt",
        )

        def ready(version):
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                assert process.poll() is None, logfile.read_text()
                try:
                    with urlopen(
                        f"http://127.0.0.1:{port}/probe", timeout=1
                    ) as response:
                        body = json.load(response)
                    if body["version"] == version:
                        assert body["title"] == "Selected config"
                        assert body["marker"] == "custom setting"
                        assert body["config"] == str(selected)
                        return
                except (URLError, TimeoutError, ConnectionError):
                    pass
                time.sleep(0.1)
            pytest.fail(logfile.read_text())

        try:
            ready("first")
            deadline = time.monotonic() + 10
            expected = 1 if mode == "dev" else 2
            while time.monotonic() < deadline:
                starts = [
                    s
                    for s in events.read_text().splitlines()
                    if s.startswith("start:")
                ]
                if len(set(starts)) >= expected:
                    break
                time.sleep(0.1)
            assert len(set(starts)) >= expected, logfile.read_text()
            if mode == "dev":
                # Serving HTTP can precede the watcher's initial file scan.
                time.sleep(2)
                # Polling reloaders need a new mtime on coarse filesystems.
                stamp = target.stat().st_mtime + 2
                target.write_text(
                    source.replace('VERSION = "first"', 'VERSION = "second"')
                )
                os.utime(target, (stamp, stamp))
                ready("second")
            process.send_signal(signal.SIGTERM)
            process.wait(timeout=20)
            rows = events.read_text().splitlines()
            started = {
                row.split(":")[1] for row in rows if row.startswith("start:")
            }
            stopped = {
                row.split(":")[1] for row in rows if row.startswith("stop:")
            }
            assert started == stopped, logfile.read_text()
        finally:
            if process.poll() is None:
                if os.name != "nt":
                    os.killpg(process.pid, signal.SIGKILL)
                else:
                    process.kill()
                process.wait(timeout=10)
