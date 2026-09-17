# Testing and database migrations

Test application behavior through public boundaries, and test backend-specific SQL against the selected database. SQLite tests do not establish PostgreSQL, MySQL or Oracle compatibility.

## Test an app without infrastructure

Install `test`. This test imports the runnable application by adding `docs/examples` to the import path, and uses a fresh app:

```python
import pytest
from httpx import ASGITransport, AsyncClient
from plain_app import build_app


@pytest.mark.asyncio
async def test_greeting():
    app = build_app()
    async with app.router.lifespan_context(app):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post("/greetings", json={"name": "Sara"})
    assert response.status_code == 200
    assert response.json() == {
        "success": True,
        "data": {"text": "Hello, Sara!"},
    }
```

HTTPX's ASGI transport does not run lifespan for you. The explicit context initializes resources and closes the container afterward. Avoid reusing an app whose container has already been closed.

## Generated project tests

The project template creates an `anonymous` fixture that builds a fresh app, disables rate limiting, switches SQL to `db.test_dsn`, enters lifespan and yields an HTTP client. It does not automatically create the database or migrate it.

For the product tutorial, apply migrations to the separate test database before testing. Run this from the generated project root in a standalone process:

```python
from alembic import command
from alembic.config import Config
from papilio.core.config import get_settings

settings = get_settings()
assert settings.db is not None
config = Config("alembic.ini")
config.set_main_option("sqlalchemy.url", settings.db.test_dsn.replace("%", "%%"))
command.upgrade(config, "head")
```

Then add a feature test:

```python
from uuid import uuid4


async def test_product_roundtrip(anonymous):
    response = await anonymous.post(
        "/products",
        json={"sku": uuid4().hex, "title": "Notebook", "quantity": 2},
    )
    assert response.status_code == 201
    product_id = response.json()["data"]["id"]
    try:
        response = await anonymous.patch(
            f"/products/{product_id}", json={"quantity": 5}
        )
        assert response.status_code == 200
        response = await anonymous.get(f"/products/{product_id}")
        assert response.json()["data"]["quantity"] == 5
    finally:
        await anonymous.delete(f"/products/{product_id}")
```

Run `python -m pytest` from the generated root. This checks separate requests and persistence after commit. Also test invalid input, missing entities, database constraints and rollback after a failed multi-write operation.

## Framework test helpers

`papilio.testing.plugin` is the lightweight automatically loaded pytest plugin. It adds markers based on test folders. `papilio.testing.fixtures` is a separate opt-in infrastructure harness for application-owned modules; importing it is not required for a plain project. Install `test`, `postgresql`, `es`, `redis`, `http`, `rate-limit` and `passwords` to use that harness. Its database preparation can modify a test database, so read its configuration before adopting it.

## Maintain migrations

Use `alembic revision --autogenerate` to propose schema changes, review the revision, then `alembic upgrade head`. The generated migration environment imports configured module tables and uses SQLModel metadata. Explicit Alembic URL overrides take precedence over the application's normal DSN.

Check both migration-from-empty and upgrade-from-previous-schema paths. Index creation, column renames and data backfills deserve separate review. Application startup is not migration management.

## Test the documentation examples

From the framework checkout:

```bash
python docs/examples/sqlite_repository.py
python docs/examples/file_pipeline.py
python docs/examples/excel_roundtrip.py
python -m mkdocs build --strict
```

These commands need the `docs`, `sqlite`, `files`, `csv` and `excel` extras. The examples check SQLite persistence, file/CSV processing and Excel roundtrips without external services. Use the HTTP test above with the `test` extra. Update reference signatures alongside API changes and build the site in strict mode to catch broken documentation links.

## Framework CI

The repository's `.github/workflows/ci.yml` runs on pushes, pull requests and manual dispatch. Each Ubuntu job tests Python 3.13 or 3.14 with disposable PostgreSQL 17, MySQL 8.4 and MariaDB 11.4 services; SQLite runs locally. It installs the `dev` and `docs` extras plus the build tools, checks dependencies, Ruff, Pyright and the strict documentation build, then runs the complete test suite. Workflow YAML owns orchestration; executable checks live in `scripts/ci/`.

| Script | Responsibility |
| --- | --- |
| `configure.py` | Create validated configuration for disposable test services without overwriting an existing file |
| `check_results.py REPORT.xml` | Require integration coverage and reject failures or unexpected skips |
| `smoke_wheel.py` | Verify the base-only installed wheel from outside the checkout |
| `telegram.py` | Format and send the CI completion message using the standard library |

Scripts and workflow files are included in the source archive so their tests remain runnable. They are not installed in the wheel. Script regression tests run with the regular suite, and Ruff checks both application and script code.

CI writes its own `config.yml` in the fresh checkout and sets the existing `PAPILIO_TEST_POSTGRESQL`, `PAPILIO_TEST_POSTGRESQL_URL`, `PAPILIO_TEST_MYSQL` and `PAPILIO_TEST_MARIADB` variables. These point only at disposable test databases. To reproduce locally, use your own disposable databases and configure the migration fixture's `db.test_dsn` as well as those variables; the migration fixture resets the test schema. Do not run the CI configuration step over an existing application configuration.

The report checker requires migration, scaffold, distribution and all six runner backend/mode cases to pass and rejects unexpected skips. Runner tests launch actual servers, check HTTP responses and selected configuration, exercise development reload and production workers, then verify lifespan shutdown. Oracle and MSSQL live tests are explicitly outside this workflow, as are unsupported native-upsert and PostgreSQL-only combinations. Installing all extras does not establish live Oracle, MSSQL, Elasticsearch or Redis coverage; ES/Redis tests currently use isolated test doubles.

Each job builds a wheel and source distribution, checks package metadata, and installs the wheel with only its base dependencies into a separate environment. The smoke check runs outside the checkout and exercises the installed CLI, packaged scaffold, application lifecycle and result containers. The distribution regression also rebuilds a wheel from the source archive and checks its contents. Reports, resolved dependencies, service logs and distributions are retained for seven days. CI does not publish packages or create releases.

### Telegram CI notifications

`.github/workflows/telegram.yml` sends the overall result after each `CI` workflow finishes, including failures and cancellations. English messages use a butterfly header, status emoji, bold sections, code-formatted identifiers and colored buttons for the CI run and commit. They include the run title, repository, branch, commit, triggering user, run attempt and elapsed time when event timestamps are available. The CI button opens the specific attempt and is green for success, red for failure/timeout/action required, and blue for other results. Text colors follow the user's Telegram theme; button colors depend on client support.

It sends once per completed run attempt, after the matrix finishes, rather than once per Python job. Re-running the notification workflow manually can send the message again. Buttons open GitHub pages directly; no always-running bot or callback handler is needed.

To enable it:

1. Create a bot through [BotFather](https://t.me/BotFather) and start a conversation with it, or add it to your destination group/channel with permission to send messages.
2. In the repository, open **Settings → Secrets and variables → Actions → New repository secret** and set `TELEGRAM_BOT_TOKEN` to the bot token and `TELEGRAM_CHAT_ID` to the destination chat ID (including a negative sign if present). You can obtain the chat ID from a bot update using Telegram's [getUpdates](https://core.telegram.org/bots/api#getupdates) method after messaging the bot; do not commit the token.
3. Put both workflows on the default branch, then run CI. GitHub's [`workflow_run` trigger](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#workflow_run) requires the notification workflow to exist on the default branch.

Missing secrets produce a notice and no message. A Telegram/network error fails only the notification workflow; the original CI result stays unchanged. Delivery uses Telegram's [sendMessage](https://core.telegram.org/bots/api#sendmessage) API with HTML formatting and an inline keyboard. Event text is escaped and bounded, and button URLs are constructed from validated GitHub identifiers. Errors never print the bot token or request URL.

The notification workflow uses read-only repository contents permission to fetch `scripts/ci/` from `github.workflow_sha`, the commit containing the notification workflow itself. It does not check out the triggering PR's commit or consume its artifacts. Checkout does not persist credentials; Telegram secrets are passed only to the sending step.
