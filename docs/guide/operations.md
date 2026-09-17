# Operations and troubleshooting

## Run the application you own

From a generated project root:

```bash
papilio run
papilio run --mode prod --host 0.0.0.0 --port 8000 --workers 4
```

Development mode uses one worker and reloads Python code changes. Production defaults to one worker without reload. Configure process count and connection pool limits together: each worker owns its own pools, so worker count multiplies possible database and outbound connections.

### Choose a launcher

| Backend | Install | Command |
| --- | --- | --- |
| Uvicorn (default) | `pip install 'papilio[server]'` | `papilio run --backend uvicorn` |
| Gunicorn native ASGI worker (Unix) | `pip install 'papilio[server-gunicorn]'` | `papilio run --backend gunicorn --mode prod --workers 4` |
| FastAPI CLI | `pip install 'papilio[server-fastapi]'` | `papilio run --backend fastapi --mode dev` |

FastAPI's `dev` and `run` commands use Uvicorn internally. Papilio maps `--mode prod` to FastAPI's `run`. Each backend runs in the current Python environment; missing dependencies produce an installation hint. Gunicorn requires version 26.2 or newer within the 26.x series, uses its native `asgi` worker in both modes, and is unavailable on Windows. Its extra does not require Uvicorn or `uvicorn-worker`.

Use `papilio run --backend gunicorn --mode dev` for Gunicorn's development reload. Gunicorn owns file watching and worker restarts; production mode disables reload by default.

### Configure the runner

Add this optional section to your application's `config.yml`:

```yaml
run:
  entrypoint: shop.main:app
  backend: uvicorn
  mode: dev
  host: 127.0.0.1
  port: 8000
  workers: 1
```

Explicit CLI options override YAML values. Mode defaults apply only to omitted values: `dev` chooses host `127.0.0.1` and reload on; `prod` chooses `0.0.0.0` and reload off. An explicit YAML `host` therefore survives `--mode prod`; pass `--host 0.0.0.0` to change it. Use `--reload` / `--no-reload` or YAML `reload: true` / `false`. Multiple workers cannot be combined with reload, and development mode requires one worker.

`--app shop.main:app` overrides `run.entrypoint`. If neither is provided, the runner reads `[tool.fastapi].entrypoint` in `pyproject.toml`. Entrypoints refer to ASGI application objects; factory expressions and arbitrary server flags are not supported. There is no framework-owned global ASGI app.

```bash
papilio run --config deployment.yml --mode prod --host 0.0.0.0
papilio run --backend fastapi --no-reload
```

Configuration path priority is `--config`, then `PAPILIO_CONFIG`, then `config.yml`. The runner passes the selected absolute path to workers and reload processes through `PAPILIO_CONFIG`. The normal `get_settings()` loader honors it, including `app.settings` subclasses. The working directory and relative storage paths stay unchanged. CLI options control the launcher; they do not rewrite the file or the application's `Settings.run` values. Applications that construct Settings themselves remain responsible for loading their chosen configuration.

## Logs and API documentation

`logging.format` accepts `console` or `json`. `logging.service` identifies the application. Default middleware records request activity. The logger is configured during lifespan, so enter lifespan in integration tests too.

Swagger assets are served locally under `/static/swagger`. `docs_url` changes the UI path, and `root_path` supports a proxy mount prefix. Disable Swagger with `docs_url=None` or disable the schema as well with `openapi_url=None`.

## Resource and performance boundaries

| Operation | Cost or lifetime to account for |
| --- | --- |
| App/module discovery | Startup imports and dependency graph construction |
| Request UoW | One session per operation; not shared across concurrent tasks |
| `fetch_page` | A count query and a page query |
| MySQL `bulk_insert` | Native batch INSERT returning a count, without model reloads; replaces MySQL `bulk_create` |
| Streamed SQL | Cursor and UoW remain open until consumption completes |
| Whole-file reads / Excel row reads | Complete result held in memory |
| CSV batches | Worker transfer per batch, plus individual record memory |
| ES refresh requested by caller | Additional search-visibility work |

There is no universal best batch size. Measure query count, latency and memory using your schema, indexes, network and input sizes. Generated interfaces do not replace backend integration tests.

## Troubleshoot common failures

| Symptom | Check |
| --- | --- |
| `ModuleNotFoundError` for SQL/ES/Redis tools | Install the matching extra in the environment running the server |
| Missing `config.yml` | Run from the project root, use `papilio run --config path.yml`, or pass Settings explicitly |
| Settings reject an unknown field | Define a Settings subclass and configure `app.settings` |
| Dishka cannot find a dependency | Register its provider under the exact requested type |
| New routes do not appear | Check `app.modules`, package imports and router placement |
| Changes disappear after a request | Open an explicit transaction; closing a UoW does not commit |
| `TransactionRollbackOnly` | An inner transactional operation failed, even if caught |
| A transaction belongs to another task | Stop sharing the UoW across concurrent operations |
| SQL write succeeds but search misses it | SQL-to-ES synchronization is not automatic; also consider ES refresh |
| Default rate limiting vanished | A custom middleware list replaces the default list |
| Excel subprocess startup fails | Use an importable script and a guarded main entry point |
| CSV header treated as data | Consume and validate the header explicitly |
| Second lifespan fails after a test | Build a fresh app; the previous container was closed |

## Current feature limits

Runtime SQL implementations cover six backends, while SQL scaffolding currently targets PostgreSQL. Oracle and SQL Server repositories do not expose upsert. `--context` leaves application-specific methods unimplemented, and `--excel` adds an exporter extension placeholder.

The CQRS template does not provide event delivery, projections, outbox, repair, retry or scheduling. Authentication helpers do not provide a complete identity system; consult the [token-type behavior](security.md) before combining access and refresh tokens.

A service responding to HTTP does not prove that migrations are current or ES indexes initialized successfully. Add health/readiness checks for the dependencies your application actually requires.
