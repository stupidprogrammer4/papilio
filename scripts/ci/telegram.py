"""Send a styled English CI summary without importing application code."""

import json
import os
import re
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

STATUSES = {
    "success": ("🟢", "ALL CHECKS PASSED", "success"),
    "failure": ("🔴", "CHECKS FAILED", "danger"),
    "cancelled": ("⚪", "RUN CANCELLED", "primary"),
    "timed_out": ("🟠", "RUN TIMED OUT", "danger"),
    "action_required": ("🟡", "ACTION REQUIRED", "danger"),
    "skipped": ("⏭️", "RUN SKIPPED", "primary"),
    "neutral": ("🔵", "CHECKS COMPLETED · NEUTRAL", "primary"),
    "stale": ("🟣", "RUN IS STALE", "primary"),
}


def label(value: object, limit: int = 80) -> str:
    """Bound and escape event text before placing it in Telegram HTML."""
    plain = " ".join(str(value or "unknown").split())
    if len(plain) > limit:
        plain = plain[: limit - 1] + "…"
    return escape(plain)


def duration(run: dict[str, Any]) -> str | None:
    """Use event timestamps; omit missing, naive or reversed times."""
    try:
        start = datetime.fromisoformat(run["run_started_at"])
        end = datetime.fromisoformat(run["updated_at"])
        if start.tzinfo is None or end.tzinfo is None:
            return None
        seconds = int((end - start).total_seconds())
    except (KeyError, TypeError, ValueError, OverflowError):
        return None
    if seconds < 0:
        return None
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    if hours:
        return f"{hours}h {minutes:02}m {seconds:02}s"
    if minutes:
        return f"{minutes}m {seconds:02}s"
    return f"{seconds}s"


def message(event: dict[str, Any]) -> dict[str, Any]:
    """Build the API payload; event strings never become executable markup."""
    run = event["workflow_run"]
    repository = event["repository"]["full_name"]
    if not isinstance(repository, str) or not re.fullmatch(
        r"[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}", repository
    ):
        raise ValueError("Invalid repository")
    run_id = run["id"]
    number = run["run_number"]
    attempt = run.get("run_attempt", 1)
    if any(
        type(v) is not int or not 1 <= v < 2**63
        for v in (run_id, number, attempt)
    ):
        raise ValueError("Invalid run identifiers")
    sha = run["head_sha"]
    if not isinstance(sha, str) or not re.fullmatch(
        r"[0-9a-fA-F]{40}(?:[0-9a-fA-F]{24})?", sha
    ):
        raise ValueError("Invalid commit")

    conclusion = run.get("conclusion") or "unknown"
    icon, title, style = STATUSES.get(
        conclusion,
        ("🔔", f"CI · {label(str(conclusion).upper(), 32)}", "primary"),
    )
    actor = run.get("triggering_actor") or run.get("actor") or {}
    lines = [
        "🦋 <b>PAPILIO · CI</b>",
        "<i>Build · Test · Deliver</i>",
        "━━━━━━━━━━━━━━━━━━",
        f"{icon} <b>{title}</b>",
        "",
    ]
    if run.get("display_title"):
        lines += [f"📝 <b>{label(run['display_title'], 140)}</b>", ""]
    lines += [
        f"📦 <code>{repository}</code>",
        f"🌿 <b>Branch</b>  <code>{label(run.get('head_branch'))}</code>",
        f"🔖 <b>Commit</b>  <code>{sha[:12]}</code>",
        f"👤 <b>By</b>  {label(actor.get('login'))}"
        f" · <code>{label(run.get('event'), 32)}</code>",
    ]
    if elapsed := duration(run):
        lines.append(f"⏱ <b>Duration</b>  {elapsed}")
    lines += [
        f"🔁 <b>Run</b>  #{number} · Attempt {attempt}",
        "━━━━━━━━━━━━━━━━━━",
        "<i>Logs &amp; artifacts are one tap away ↓</i>",
    ]
    base = f"https://github.com/{repository}"
    run_url = f"{base}/actions/runs/{run_id}/attempts/{attempt}"
    return {
        "text": "\n".join(lines),
        "parse_mode": "HTML",
        "link_preview_options": {"is_disabled": True},
        "reply_markup": {
            "inline_keyboard": [
                [
                    {
                        "text": "🔎 View CI run",
                        "url": run_url,
                        "style": style,
                    },
                    {
                        "text": "🔖 View commit",
                        "url": f"{base}/commit/{sha}",
                        "style": "primary",
                    },
                ],
            ],
        },
    }


def send(token: str, chat_id: str, payload: dict[str, Any]) -> None:
    request = Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=json.dumps({**payload, "chat_id": chat_id}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=20) as response:
            result = json.load(response)
    except HTTPError as exc:
        raise RuntimeError(
            f"Telegram notification failed (HTTP {exc.code})."
        ) from None
    except (URLError, OSError, ValueError):
        raise RuntimeError(
            "Telegram notification failed: network error or invalid response."
        ) from None
    if not isinstance(result, dict) or result.get("ok") is not True:
        raise RuntimeError("Telegram API did not accept the notification.")


def main() -> int:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        print(
            "::notice::Telegram notification skipped: configure "
            "TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID."
        )
        return 0
    try:
        event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
        payload = message(event)
    except (KeyError, OSError, TypeError, ValueError, AttributeError):
        print("::error::Cannot build Telegram notification: invalid event.")
        return 1
    try:
        send(token, chat_id, payload)
    except RuntimeError as exc:
        print(f"::error::{exc}")
        return 1
    print("Telegram notification sent.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
