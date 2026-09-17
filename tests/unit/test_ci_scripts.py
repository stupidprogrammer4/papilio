import copy
import io
import json
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.error import HTTPError, URLError

import pytest
import yaml

from scripts.ci import check_results, configure, telegram


@pytest.fixture
def event():
    return {
        "repository": {"full_name": "owner/project"},
        "workflow_run": {
            "id": 123,
            "run_number": 7,
            "run_attempt": 2,
            "conclusion": "success",
            "head_sha": "a" * 40,
            "head_branch": "main",
            "display_title": "Improve CLI startup",
            "event": "push",
            "actor": {"login": "original-author"},
            "triggering_actor": {"login": "rerun-author"},
            "run_started_at": "2026-09-17T09:00:00Z",
            "updated_at": "2026-09-17T09:02:05Z",
            "html_url": "https://untrusted.example/ignored",
        },
    }


@pytest.mark.parametrize(
    "conclusion,title,style",
    [
        ("success", "ALL CHECKS PASSED", "success"),
        ("failure", "CHECKS FAILED", "danger"),
        ("cancelled", "RUN CANCELLED", "primary"),
        ("timed_out", "RUN TIMED OUT", "danger"),
        ("action_required", "ACTION REQUIRED", "danger"),
        ("skipped", "RUN SKIPPED", "primary"),
        ("neutral", "CHECKS COMPLETED · NEUTRAL", "primary"),
        ("stale", "RUN IS STALE", "primary"),
        (None, "CI · UNKNOWN", "primary"),
    ],
)
def test_notification_status_and_action_links(event, conclusion, title, style):
    event["workflow_run"]["conclusion"] = conclusion
    before = copy.deepcopy(event)
    payload = telegram.message(event)
    assert event == before
    assert payload["parse_mode"] == "HTML"
    assert f"<b>{title}</b>" in payload["text"]
    assert "rerun-author" in payload["text"]
    assert "original-author" not in payload["text"]
    assert "2m 05s" in payload["text"]
    assert "#7 · Attempt 2" in payload["text"]
    buttons = payload["reply_markup"]["inline_keyboard"][0]
    assert buttons[0]["style"] == style
    assert buttons[0]["url"] == (
        "https://github.com/owner/project/actions/runs/123/attempts/2"
    )
    assert buttons[1]["url"] == (
        "https://github.com/owner/project/commit/" + "a" * 40
    )
    assert buttons[1]["style"] == "primary"
    assert payload["link_preview_options"] == {"is_disabled": True}


def test_untrusted_event_text_stays_bounded_plain_content(event):
    hostile = '<a href="https://example.com">&👋</a>\n' * 1000
    run = event["workflow_run"]
    run.update(
        head_branch=hostile,
        display_title=hostile,
        event=hostile,
        conclusion="<future&status>",
        triggering_actor={"login": hostile},
    )
    text = telegram.message(event)["text"]
    assert "<a " not in text and "</a>" not in text
    assert "&lt;" in text and "&amp;" in text
    assert "&LT;" not in text
    assert "…" in text
    assert len(text.encode("utf-16-le")) // 2 < 4096
    ET.fromstring(f"<message>{text}</message>")


@pytest.mark.parametrize(
    "field,value",
    [("id", 0), ("id", True), ("run_attempt", -1), ("head_sha", "not-a-sha")],
)
def test_invalid_link_identifiers_are_rejected(event, field, value):
    event["workflow_run"][field] = value
    with pytest.raises(ValueError):
        telegram.message(event)


def test_repository_cannot_inject_a_button_url(event):
    event["repository"]["full_name"] = "owner/project?url=bad"
    with pytest.raises(ValueError):
        telegram.message(event)


@pytest.mark.parametrize(
    "end,expected",
    [
        ("2026-09-17T09:00:03Z", "3s"),
        ("2026-09-17T10:02:03Z", "1h 02m 03s"),
        ("2026-09-17T08:59:59Z", None),
        ("2026-09-17T09:00:03", None),
        ("malformed", None),
        (None, None),
    ],
)
def test_duration_is_optional_and_uses_event_times(event, end, expected):
    run = event["workflow_run"]
    run["updated_at"] = end
    assert telegram.duration(run) == expected


def test_missing_optional_fields_use_actor_and_omit_empty_sections(event):
    run = event["workflow_run"]
    for field in ("triggering_actor", "display_title", "run_started_at"):
        run.pop(field)
    text = telegram.message(event)["text"]
    assert "original-author" in text
    assert "📝" not in text and "Duration" not in text


def test_transport_posts_html_and_keyboard_to_telegram(event, monkeypatch):
    requests = []

    def urlopen(request, timeout):
        requests.append((request, timeout))
        return io.BytesIO(b'{"ok": true, "result": {"message_id": 1}}')

    monkeypatch.setattr(telegram, "urlopen", urlopen)
    payload = telegram.message(event)
    telegram.send("test-token", "12345", payload)
    request, timeout = requests[0]
    assert request.full_url == (
        "https://api.telegram.org/bottest-token/sendMessage"
    )
    assert request.method == "POST" and timeout == 20
    assert json.loads(request.data) == {**payload, "chat_id": "12345"}
    assert "chat_id" not in payload


@pytest.fixture
def configured(event, tmp_path, monkeypatch):
    path = tmp_path / "event.json"
    path.write_text(json.dumps(event))
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(path))
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-secret")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "12345")
    return path


@pytest.mark.parametrize(
    "failure",
    [
        HTTPError("https://host/test-secret", 401, "secret", {}, None),
        URLError("https://host/test-secret"),
        TimeoutError("https://host/test-secret"),
    ],
)
def test_transport_errors_do_not_expose_credentials(
    configured, monkeypatch, capsys, failure
):
    def fail(*args, **kwargs):
        raise failure

    monkeypatch.setattr(telegram, "urlopen", fail)
    assert telegram.main() == 1
    output = capsys.readouterr().out
    assert "::error::" in output
    assert "test-secret" not in output and "https://" not in output


@pytest.mark.parametrize(
    "body", [b"[]", b'{"ok":false}', b'{"ok":1}', b"not json"]
)
def test_invalid_api_responses_fail_cleanly(
    configured, monkeypatch, capsys, body
):
    monkeypatch.setattr(telegram, "urlopen", lambda *a, **kw: io.BytesIO(body))
    assert telegram.main() == 1
    assert "::error::" in capsys.readouterr().out


@pytest.mark.parametrize("missing", ["TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"])
def test_missing_secrets_skip_before_reading_event(
    configured, monkeypatch, capsys, missing
):
    configured.unlink()
    monkeypatch.delenv(missing)
    assert telegram.main() == 0
    assert "::notice::" in capsys.readouterr().out


def test_malformed_event_is_sanitized(configured, capsys):
    configured.write_text("test-secret invalid JSON")
    assert telegram.main() == 1
    output = capsys.readouterr().out
    assert "invalid event" in output and "test-secret" not in output


def test_success_is_reported_only_after_accepted_delivery(
    configured, monkeypatch, capsys
):
    monkeypatch.setattr(
        telegram, "urlopen", lambda *a, **kw: io.BytesIO(b'{"ok":true}')
    )
    assert telegram.main() == 0
    assert capsys.readouterr().out == "Telegram notification sent.\n"


@pytest.fixture
def report(tmp_path):
    suite = ET.Element("testsuite")
    required = [
        (
            "integration.test_database",
            "test_database_is_migrated_and_reachable",
        ),
        (
            "unit.test_distribution",
            "test_distribution_excludes_local_copies_and_roundtrips",
        ),
    ]
    required += [
        (
            "integration.test_scaffold_runtime",
            f"test_generated_sql_routes_and_query_tools[{cqrs}]",
        )
        for cqrs in (False, True)
    ]
    required += [
        (
            "integration.test_cli_runtime",
            f"test_runner_serves_reloads_and_shuts_down[{mode}-{backend}]",
        )
        for mode in ("dev", "prod")
        for backend in ("uvicorn", "gunicorn", "fastapi")
    ]
    required += [
        ("unit.test_db_dialects", f"test_live_backend[{backend}]")
        for backend in ("postgresql", "mysql", "mariadb", "sqlite")
    ]
    for module, name in required:
        ET.SubElement(
            suite, "testcase", classname=f"tests.{module}", name=name
        )
    return tmp_path / "report.xml", suite


def test_report_guard_accepts_complete_coverage_and_documented_skip(report):
    path, suite = report
    case = ET.SubElement(
        suite,
        "testcase",
        classname="tests.unit.test_db_dialects",
        name="test_create[oracle]",
    )
    ET.SubElement(
        case,
        "skipped",
        message="Set FASTAMU_TEST_ORACLE for live backend tests",
    )
    ET.ElementTree(suite).write(path)
    check_results.check(str(path))


@pytest.mark.parametrize("defect", ["failure", "error", "skip", "missing"])
def test_report_guard_rejects_incomplete_or_failed_runs(report, defect):
    path, suite = report
    case = suite[0]
    if defect == "missing":
        suite.remove(case)
    else:
        ET.SubElement(
            case,
            "skipped" if defect == "skip" else defect,
            message="unexpected",
        )
    ET.ElementTree(suite).write(path)
    with pytest.raises(SystemExit):
        check_results.check(str(path))


def test_notification_executes_only_trusted_workflow_code():
    root = Path(__file__).resolve().parents[2]
    workflow = yaml.safe_load(
        (root / ".github/workflows/telegram.yml").read_text()
    )
    assert workflow["permissions"] == {"contents": "read"}
    job = workflow["jobs"]["notify"]
    assert "env" not in job and "env" not in workflow
    checkout, send = job["steps"]
    assert "secrets." not in json.dumps(checkout)
    assert checkout["with"]["ref"] == "${{ github.workflow_sha }}"
    assert checkout["with"]["persist-credentials"] is False
    assert checkout["with"]["sparse-checkout"] == "scripts/ci"
    assert send["run"] == "python3 scripts/ci/telegram.py"
    assert set(send["env"]) == {"TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"}
    assert "head_sha" not in json.dumps(workflow)


def test_configure_uses_disposable_dsn_and_never_overwrites(
    tmp_path, monkeypatch
):
    root = Path(__file__).resolve().parents[2]
    sample = (root / "docs/examples/minimal.yml").read_text()
    target = tmp_path / "docs/examples/minimal.yml"
    target.parent.mkdir(parents=True)
    target.write_text(sample)
    monkeypatch.chdir(tmp_path)
    dsn = "postgresql+asyncpg://postgres:test@127.0.0.1/papilio_test"
    monkeypatch.setenv("FASTAMU_TEST_POSTGRESQL", dsn)
    configure.main()
    content = Path("config.yml").read_bytes()
    config = yaml.safe_load(content)
    assert config["db"]["dsn"] == config["db"]["test_dsn"] == dsn
    assert config["redis"]["url"] == "redis://127.0.0.1:1/0"
    with pytest.raises(FileExistsError):
        configure.main()
    assert Path("config.yml").read_bytes() == content
