# <<NAME>>

Built on Papilio. Modules are
discovered, not registered — add one and its router, service, table
are live.

## Running

```bash
python3.13 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

cp config.yml.sample config.yml     # configure the selected services and secrets
<<MIGRATE>>

papilio run
```

Swagger UI is at `/docs`.

The `run` section of `config.yml` selects the entrypoint, backend, mode, host
and port. CLI options override it, for example
`papilio run --mode prod --host 0.0.0.0 --workers 4`.
Install `papilio[server-gunicorn]` or `papilio[server-fastapi]` to select
`--backend gunicorn` (Unix) or `--backend fastapi`. `--config PATH` selects
the same YAML file for both the launcher and application workers.

Writing application methods use `@transactional` from
`papilio.infra.db.tools.decorators`. Request scope only manages session
lifetime; it does not commit automatically.

## Adding a feature

```bash
papilio module catalog.product<<MODULE_FLAGS>>
```

Modules live under `<<PKG>>/modules/`; `app.modules` selects discovery roots.
CRUD is the default; `--cqrs` adds SQL commands and ES queries; `--plain`
creates a module without a database; `--context` creates a custom SQL reader
and calculation skeleton.

Required extras are recorded in `pyproject.toml`. After adding infrastructure,
select its extra there and register its provider in `<<PKG>>/main.py`.
Use `papilio providers` to inspect installed dependencies and
`papilio providers NAME` for ready-provider imports and usage. Ready providers
are in `papilio.providers`; you can also supply your own Dishka providers.
ES startup and rate-limit registration are explicit in the generated entry point. SQL
changes require `alembic revision --autogenerate` followed by `alembic upgrade head`.
CQRS does not automatically synchronize SQL writes to Elasticsearch.

## Tests

```bash
pytest -m unit           # fast, no services
pytest -m integration    # against db.test_dsn
pytest -m api            # drives the live app
```
