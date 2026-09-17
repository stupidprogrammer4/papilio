"""Resolve runner settings and hand process ownership to a native server."""

import os
import subprocess
import sys
import tomllib
from importlib.util import find_spec
from pathlib import Path
from typing import Any

import typer
import yaml
from pydantic import ValidationError

from papilio.core.config import RunBackend, RunConfig, RunMode

from .display import details, error


def resolve(path: Path, overrides: dict[str, Any]) -> RunConfig:
    """Read only runner options; application settings load in the server."""
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("Configuration must be a YAML mapping")
    options = raw.get("run", {})
    if not isinstance(options, dict):
        raise ValueError("run must be a YAML mapping")
    options = {
        **options,
        **{k: v for k, v in overrides.items() if v is not None},
    }
    if not options.get("entrypoint"):
        project = Path("pyproject.toml")
        if project.exists():
            metadata = tomllib.loads(project.read_text(encoding="utf-8"))
            tool = metadata.get("tool", {})
            if not isinstance(tool, dict):
                raise ValueError("pyproject.toml tool must be a table")
            fastapi = tool.get("fastapi", {})
            if not isinstance(fastapi, dict):
                raise ValueError("pyproject.toml tool.fastapi must be a table")
            options["entrypoint"] = fastapi.get("entrypoint")
    selected = RunConfig.model_validate(options)
    if not selected.entrypoint:
        raise ValueError(
            "Set run.entrypoint, pass --app module:app, or configure "
            "[tool.fastapi].entrypoint in pyproject.toml"
        )
    module, colon, attribute = selected.entrypoint.partition(":")
    if not colon or not all(
        part.isidentifier()
        for path_part in (module, attribute)
        for part in path_part.split(".")
    ):
        raise ValueError("Entrypoint must be module:app (an ASGI app object)")
    if selected.host is None:
        selected.host = (
            "127.0.0.1" if selected.mode == RunMode.DEV else "0.0.0.0"
        )
    if selected.host.strip() != selected.host or any(
        char.isspace() for char in selected.host
    ):
        raise ValueError("Host must not contain whitespace")
    if selected.reload is None:
        selected.reload = selected.mode == RunMode.DEV
    if selected.mode == RunMode.DEV and selected.workers != 1:
        raise ValueError(
            "Development mode requires one worker; use --mode prod"
        )
    if selected.reload and selected.workers != 1:
        raise ValueError("Reload cannot be combined with multiple workers")
    return selected


def command(selected: RunConfig) -> list[str]:
    """Build native CLI arguments without importing any optional server."""
    if selected.backend == RunBackend.GUNICORN and os.name == "nt":
        raise ValueError(
            "Gunicorn requires Unix; select uvicorn or fastapi on Windows"
        )
    modules, extra = {
        RunBackend.UVICORN: (("uvicorn",), "server"),
        RunBackend.GUNICORN: (("gunicorn",), "server-gunicorn"),
        RunBackend.FASTAPI: (("fastapi_cli", "uvicorn"), "server-fastapi"),
    }[selected.backend]
    missing = [module for module in modules if find_spec(module) is None]
    if missing:
        raise ValueError(
            f"Missing dependencies: {', '.join(missing)}\n"
            f"Install: {sys.executable} -m pip install 'papilio[{extra}]'"
        )
    assert selected.entrypoint is not None and selected.host is not None
    args = [sys.executable, "-m"]
    if selected.backend == RunBackend.GUNICORN:
        host = selected.host
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        args += [
            "gunicorn",
            selected.entrypoint,
            "--worker-class",
            "asgi",
            "--bind",
            f"{host}:{selected.port}",
            "--workers",
            str(selected.workers),
        ]
        if selected.reload:
            args.append("--reload")
    else:
        if selected.backend == RunBackend.FASTAPI:
            args += [
                "fastapi",
                "dev" if selected.mode == RunMode.DEV else "run",
                "--entrypoint",
                selected.entrypoint,
            ]
        else:
            args += ["uvicorn", selected.entrypoint]
        args += ["--host", selected.host, "--port", str(selected.port)]
        if (
            selected.backend != RunBackend.FASTAPI
            or selected.mode == RunMode.PROD
        ):
            args += ["--workers", str(selected.workers)]
        if selected.reload:
            args.append("--reload")
        elif selected.backend == RunBackend.FASTAPI:
            args.append("--no-reload")
    return args


def launch(args: list[str], path: Path) -> None:
    env = {**os.environ, "PAPILIO_CONFIG": str(path)}
    if os.name != "nt":
        os.execvpe(args[0], args, env)
    else:
        process = subprocess.Popen(args, env=env)
        try:
            code = process.wait()
        except KeyboardInterrupt:
            # Windows delivers Ctrl+C to the attached console processes.
            try:
                code = process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.terminate()
                try:
                    code = process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    code = process.wait()
        raise typer.Exit(code)


def run(
    entrypoint: str | None = typer.Option(
        None, "--app", help="ASGI import path: module:app"
    ),
    backend: RunBackend | None = typer.Option(
        None,
        metavar="BACKEND",
        help="Launcher: uvicorn, gunicorn or fastapi",
    ),
    mode: RunMode | None = typer.Option(
        None, help="Development or production defaults"
    ),
    host: str | None = typer.Option(
        None, help="Bind address; overrides run.host"
    ),
    port: int | None = typer.Option(
        None, min=1, max=65535, help="Listen port"
    ),
    workers: int | None = typer.Option(
        None, min=1, help="Worker count (production mode)"
    ),
    reload: bool | None = typer.Option(
        None, "--reload/--no-reload", help="Restart on code changes"
    ),
    config: Path | None = typer.Option(
        None,
        "--config",
        help="YAML configuration (default: config.yml or PAPILIO_CONFIG)",
    ),
) -> None:
    """Run your application with settings from config.yml."""
    path = (
        config or Path(os.environ.get("PAPILIO_CONFIG", "config.yml"))
    ).resolve()
    try:
        selected = resolve(
            path,
            dict(
                entrypoint=entrypoint,
                backend=backend,
                mode=mode,
                host=host,
                port=port,
                workers=workers,
                reload=reload,
            ),
        )
        args = command(selected)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        if isinstance(exc, ValidationError):
            message = "\n".join(
                f"run.{'.'.join(map(str, item['loc']))}: {item['msg']}"
                for item in exc.errors()
            )
        else:
            message = str(exc)
        error(message)
        raise typer.Exit(2) from exc
    details(
        "Papilio · Run",
        [
            ("Application", selected.entrypoint or ""),
            ("Backend", selected.backend.value),
            ("Mode", selected.mode.value),
            ("Listen", f"{selected.host}:{selected.port}"),
            ("Workers", str(selected.workers)),
            ("Reload", "on" if selected.reload else "off"),
            ("Config", str(path)),
        ],
    )
    sys.stdout.flush()
    sys.stderr.flush()
    try:
        launch(args, path)
    except OSError as exc:
        error(str(exc))
        raise typer.Exit(1) from exc
