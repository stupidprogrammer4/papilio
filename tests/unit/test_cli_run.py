import importlib
import os
import re
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import yaml
from typer.testing import CliRunner

from papilio.cli.app import app
from papilio.core.config import RunBackend, RunMode, get_settings
from papilio.scaffolding.project import files

runner = importlib.import_module("papilio.cli.run")


@pytest.fixture
def configuration(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("PAPILIO_CONFIG", raising=False)
    path = tmp_path / "config.yml"
    path.write_text("run:\n  entrypoint: unimportable.main:app\n")
    return path


def test_defaults_and_mode_overrides(configuration):
    dev = runner.resolve(configuration, {})
    assert (dev.host, dev.port, dev.workers, dev.reload) == (
        "127.0.0.1",
        8000,
        1,
        True,
    )
    prod = runner.resolve(configuration, {"mode": "prod", "workers": 3})
    assert prod.host == "0.0.0.0" and prod.reload is False
    assert prod.workers == 3


def test_cli_overrides_yaml_without_importing_application(
    configuration, monkeypatch
):
    configuration.write_text(
        yaml.safe_dump(
            {
                "app": {"settings": "must_not_import.Settings"},
                "run": {
                    "entrypoint": "must_not_import:app",
                    "host": "192.0.2.1",
                    "port": 8100,
                    "mode": "prod",
                    "workers": 2,
                },
            }
        )
    )
    launch = Mock()
    monkeypatch.setattr(runner, "launch", launch)
    monkeypatch.setattr(runner, "find_spec", lambda name: object())
    result = CliRunner().invoke(
        app,
        [
            "run",
            "--host",
            "127.0.0.1",
            "--port",
            "8200",
            "--app",
            "also_not_imported:app",
            "--mode",
            "dev",
            "--workers",
            "1",
            "--no-reload",
        ],
    )
    assert result.exit_code == 0, result.output
    args, path = launch.call_args.args
    assert args[:4] == [
        sys.executable,
        "-m",
        "uvicorn",
        "also_not_imported:app",
    ]
    assert args[args.index("--host") + 1] == "127.0.0.1"
    assert args[args.index("--port") + 1] == "8200"
    assert "--reload" not in args and path == configuration


def test_yaml_host_survives_mode_change(configuration):
    configuration.write_text(
        "run:\n  entrypoint: main:app\n  host: 192.0.2.1\n"
    )
    assert runner.resolve(configuration, {"mode": "prod"}).host == "192.0.2.1"


def test_entrypoint_falls_back_to_pyproject(configuration):
    configuration.write_text("{}")
    Path("pyproject.toml").write_text(
        '[tool.fastapi]\nentrypoint="shop.main:app"'
    )
    assert runner.resolve(configuration, {}).entrypoint == "shop.main:app"
    assert (
        runner.resolve(configuration, {"entrypoint": "other:app"}).entrypoint
        == "other:app"
    )


@pytest.mark.parametrize("content", ['tool="wrong"', "[tool]\nfastapi=1"])
def test_invalid_pyproject_is_a_cli_error(configuration, content):
    configuration.write_text("{}")
    Path("pyproject.toml").write_text(content)
    result = CliRunner().invoke(app, ["run"])
    assert result.exit_code == 2 and "must be a table" in result.output


def test_missing_config_is_a_cli_error(configuration):
    configuration.unlink()
    result = CliRunner().invoke(app, ["run"])
    assert result.exit_code == 2 and "config.yml" in result.output


@pytest.mark.parametrize(
    "options",
    [
        {"workers": 2},
        {"mode": "prod", "reload": True, "workers": 2},
        {"port": 0},
        {"port": 65536},
        {"workers": 0},
        {"host": " "},
        {"entrypoint": "main:create()"},
        {"entrypoint": "main"},
        {"backend": "missing"},
        {"mode": "missing"},
        {"typo": True},
    ],
)
def test_invalid_configuration_never_launches(
    configuration, monkeypatch, options
):
    configuration.write_text(
        yaml.safe_dump({"run": {"entrypoint": "main:app", **options}})
    )
    launch = Mock()
    monkeypatch.setattr(runner, "launch", launch)
    result = CliRunner().invoke(app, ["run"])
    assert result.exit_code == 2, result.output
    launch.assert_not_called()


@pytest.mark.parametrize("content", ["[]", "run: []", "run: [", "{}"])
def test_malformed_configuration_is_a_cli_error(configuration, content):
    configuration.write_text(content)
    result = CliRunner().invoke(app, ["run"])
    assert result.exit_code == 2 and "Error" in result.output


@pytest.mark.parametrize(
    "backend,extra",
    [
        ("uvicorn", "server"),
        ("gunicorn", "server-gunicorn"),
        ("fastapi", "server-fastapi"),
    ],
)
def test_missing_backend_has_install_hint(
    configuration, monkeypatch, backend, extra
):
    monkeypatch.setattr(runner, "find_spec", lambda name: None)
    result = CliRunner().invoke(app, ["run", "--backend", backend])
    assert result.exit_code == 2
    assert f"papilio[{extra}]" in result.output


@pytest.mark.parametrize("backend", list(RunBackend))
@pytest.mark.parametrize("mode", list(RunMode))
def test_native_arguments(configuration, monkeypatch, backend, mode):
    monkeypatch.setattr(runner, "find_spec", lambda name: object())
    settings = runner.resolve(
        configuration, {"backend": backend, "mode": mode}
    )
    args = runner.command(settings)
    if backend == RunBackend.GUNICORN:
        assert args[args.index("--worker-class") + 1] == "asgi"
        assert "--bind" in args
    elif backend == RunBackend.FASTAPI:
        assert args[2:4] == [
            "fastapi",
            "dev" if mode == RunMode.DEV else "run",
        ]
        assert ("--workers" in args) == (mode == RunMode.PROD)
    assert ("--reload" in args) == (mode == RunMode.DEV)


def test_gunicorn_ipv6_binding(configuration, monkeypatch):
    monkeypatch.setattr(runner, "find_spec", lambda name: object())
    settings = runner.resolve(
        configuration, {"backend": "gunicorn", "host": "::1"}
    )
    args = runner.command(settings)
    assert args[args.index("--bind") + 1] == "[::1]:8000"


def test_gunicorn_does_not_require_uvicorn(configuration, monkeypatch):
    monkeypatch.setattr(
        runner,
        "find_spec",
        lambda name: object() if name == "gunicorn" else None,
    )
    settings = runner.resolve(configuration, {"backend": "gunicorn"})
    assert runner.command(settings)[2] == "gunicorn"


def test_explicit_config_overrides_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("PAPILIO_CONFIG", str(tmp_path / "missing.yml"))
    path = tmp_path / "chosen.yml"
    path.write_text("run:\n  entrypoint: main:app\n")
    launch = Mock()
    monkeypatch.setattr(runner, "launch", launch)
    monkeypatch.setattr(runner, "find_spec", lambda name: object())
    result = CliRunner().invoke(app, ["run", "--config", str(path)])
    assert result.exit_code == 0, result.output
    assert launch.call_args.args[1] == path


def test_config_environment_selects_runner_file(tmp_path, monkeypatch):
    path = tmp_path / "chosen.yml"
    path.write_text("run:\n  entrypoint: main:app\n")
    monkeypatch.setenv("PAPILIO_CONFIG", str(path))
    launch = Mock()
    monkeypatch.setattr(runner, "launch", launch)
    monkeypatch.setattr(runner, "find_spec", lambda name: object())
    result = CliRunner().invoke(app, ["run"])
    assert result.exit_code == 0, result.output
    assert launch.call_args.args[1] == path


def test_windows_rejects_gunicorn(configuration, monkeypatch):
    selected = runner.resolve(configuration, {"backend": "gunicorn"})
    monkeypatch.setattr(runner, "os", SimpleNamespace(name="nt"))
    with pytest.raises(ValueError, match="requires Unix"):
        runner.command(selected)


def test_windows_launcher_preserves_exit_status(tmp_path, monkeypatch):
    import typer

    process = Mock()
    process.wait.return_value = 7
    spawn = Mock(return_value=process)
    monkeypatch.setattr(runner, "os", SimpleNamespace(name="nt", environ={}))
    monkeypatch.setattr(runner.subprocess, "Popen", spawn)
    args = [sys.executable, "-m", "uvicorn", "main:app"]
    path = tmp_path / "chosen.yml"
    with pytest.raises(typer.Exit) as error:
        runner.launch(args, path)
    assert error.value.exit_code == 7
    spawn.assert_called_once_with(args, env={"PAPILIO_CONFIG": str(path)})


def test_windows_interrupt_cleans_up_unresponsive_server(
    tmp_path, monkeypatch
):
    import typer

    process = Mock()
    process.wait.side_effect = [
        KeyboardInterrupt(),
        subprocess.TimeoutExpired("server", 10),
        subprocess.TimeoutExpired("server", 5),
        1,
    ]
    monkeypatch.setattr(runner, "os", SimpleNamespace(name="nt", environ={}))
    monkeypatch.setattr(runner.subprocess, "Popen", Mock(return_value=process))
    with pytest.raises(typer.Exit):
        runner.launch([sys.executable], tmp_path / "chosen.yml")
    process.terminate.assert_called_once()
    process.kill.assert_called_once()


def test_settings_loader_honors_config_environment(tmp_path, monkeypatch):
    config = yaml.safe_load(files("shop", "Shop")["config.yml"])
    config["fastapi"]["title"] = "Selected"
    path = tmp_path / "selected.yml"
    path.write_text(yaml.safe_dump(config))
    monkeypatch.setenv("PAPILIO_CONFIG", str(path))
    get_settings.cache_clear()
    try:
        assert get_settings().fastapi.title == "Selected"
    finally:
        get_settings.cache_clear()


@pytest.mark.skipif(os.name == "nt", reason="POSIX exec contract")
def test_exec_uses_same_interpreter_and_exports_config(monkeypatch, tmp_path):
    execute = Mock()
    monkeypatch.setattr(runner.os, "execvpe", execute)
    args = [sys.executable, "-m", "uvicorn", "main:app"]
    path = tmp_path / "chosen.yml"
    runner.launch(args, path)
    executable, command, env = execute.call_args.args
    assert executable == sys.executable and command == args
    assert env["PAPILIO_CONFIG"] == str(path)


@pytest.mark.parametrize("color", [False, True])
def test_help_lists_commands_and_runner_options_without_servers(
    monkeypatch, color
):
    monkeypatch.setattr(
        runner,
        "find_spec",
        lambda name: pytest.fail("server inspected during help"),
    )
    env = (
        {"COLUMNS": "120", "TERM": "xterm", "FORCE_COLOR": "1"}
        if color
        else {"NO_COLOR": "1", "TERM": "dumb"}
    )
    for args, expected in [
        ([], ["new", "module", "providers", "run"]),
        (["run", "--help"], ["--host", "--config", "--backend", "--workers"]),
    ]:
        result = CliRunner().invoke(
            app, args or ["--help"], color=color, env=env
        )
        assert result.exit_code == 0
        plain = re.sub(r"\x1b\[[0-9;]*m", "", result.output)
        assert all(value in plain for value in expected)


def test_project_success_and_error_are_readable(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(app, ["new", "shop"])
    assert result.exit_code == 0 and "papilio run" in result.output
    config = yaml.safe_load((tmp_path / "shop/config.yml").read_text())
    assert config["run"]["host"] == "127.0.0.1"
    result = CliRunner().invoke(app, ["new", "shop"])
    assert result.exit_code == 1 and "already exists" in result.output
