# CI scripts

Workflow YAML in `.github/workflows/` owns triggers, permissions, services and
step ordering. These scripts own the executable checks and notification code.
They are repository tooling, not part of the installed Papilio package.

| Script | Input | Result |
| --- | --- | --- |
| `configure.py` | `docs/examples/minimal.yml`, `FASTAMU_TEST_POSTGRESQL` | Creates `config.yml` exclusively for disposable CI services; refuses to overwrite a file. |
| `check_results.py REPORT.xml` | Pytest JUnit XML | Rejects failed or missing required tests and unexpected skips. |
| `smoke_wheel.py` | Base-only wheel environment | Checks installed package provenance, result containers, CLI, generated app and lifespan. Run from outside the checkout. |
| `telegram.py` | `GITHUB_EVENT_PATH`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | Sends one English HTML summary with status-colored URL buttons; missing secrets skip successfully. |

The notifier uses only the Python standard library. The other scripts use the
dependencies already installed by their CI steps. No bot server, callback
handler or additional service is needed: the buttons open GitHub pages.

The notification workflow checks out only `scripts/ci` from
`github.workflow_sha`, with read-only contents permission and without persisting
credentials. It never executes the triggering pull request's commit or reads
its artifacts. Telegram credentials are available only to the send step.

Event titles, actors and branch names are length-limited and HTML-escaped.
Button URLs are constructed from validated repository/run/commit identifiers;
event-provided URLs are not used. API/network errors are sanitized. A failed
notification does not change the original CI result.

Run the regression checks from the repository root:

```bash
python -m pytest tests/unit/test_ci_scripts.py tests/unit/test_distribution.py
ruff check papilio tests scripts
ruff format --check papilio tests scripts
```

Install the declared test/build dependencies for these checks. Scripts and
workflows are included in the source archive so its tests have their inputs;
the wheel includes only the `papilio` package and distribution metadata.
