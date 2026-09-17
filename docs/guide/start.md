# Installation and your first application

## Requirements

Use Python 3.13 or newer. The commands below start in the framework checkout. This guide uses a local install and does not assume a package has been published to PyPI under this name.

```bash
python3.13 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[server]'
```

On PowerShell, activate with `.venv\Scripts\Activate.ps1`. Run `python` and `papilio` from the same virtual environment.

## Choose your dependencies

| Extra | Includes |
| --- | --- |
| `server` | Uvicorn ASGI server |
| `server-gunicorn` | Gunicorn 26.2+ and native ASGI worker (Unix) |
| `server-fastapi` | FastAPI CLI and Uvicorn |
| `db` | SQLAlchemy, SQLModel and Alembic, without a database driver |
| `postgresql` | SQL support and PostgreSQL drivers |
| `mysql` / `mariadb` | SQL support and asyncmy |
| `sqlite` | SQL support and aiosqlite |
| `mssql` | SQL support and aioodbc; a system ODBC driver is also needed |
| `oracle` | SQL support and oracledb |
| `es` | Async Elasticsearch |
| `redis` | Async Redis |
| `rate-limit` | Rate-limit tools and the memory backend |
| `rate-limit-redis` | Rate-limit tools and Redis dependencies |
| `auth` / `passwords` / `crypto` / `csrf` | Optional security tools and adapters |
| `http` | HTTPX client |
| `files` / `csv` | Async file operations using AnyIO |
| `excel` | Excel tools using openpyxl |
| `persian` | Optional localized date and text utilities |
| `test` | pytest, pytest-asyncio and HTTPX |
| `docs` | This documentation site tooling |
| `all` / `dev` | All runtime extras / development and test environment |

For example:

```bash
python -m pip install -e '.[server,postgresql,csv,test]'
```

Installing a dependency does not connect its service. Register its provider in the application. The CLI can generate that wiring for supported selections.

## A working application without a database

This example validates a request, injects a service and returns a response envelope:

```python
--8<-- "examples/plain_app.py"
```

Its complete configuration lives beside the script. It requires no authentication, crypto or CSRF settings.

```yaml
--8<-- "examples/minimal.yml"
```

Run from the framework checkout:

```bash
python -m uvicorn plain_app:app --app-dir docs/examples --reload
```

Open `http://127.0.0.1:8000/docs`, or send a request:

```bash
curl -X POST http://127.0.0.1:8000/greetings \
  -H 'Content-Type: application/json' \
  -d '{"name":"Sara"}'
```

Expected response:

```json
{"success":true,"data":{"text":"Hello, Sara!"}}
```

An empty name produces HTTP 422. The service is resolved in request scope; provider discovery does not run again for each request.

## Generate your own project

```bash
papilio new garden --dir /tmp/papilio-learning/garden
cd /tmp/papilio-learning/garden
python -m pip install -e .
papilio module greeting --plain
papilio run
```

Run the server from the generated project root, where `config.yml` lives. The plain template provides structure; implement its service behavior yourself. Continue with the [complete SQL feature tutorial](tutorial.md).

Set the listening address with `papilio run --host 127.0.0.1 --port 8080` or `run.host` / `run.port` in YAML. See [operations](operations.md) for backend selection, modes and alternate configuration files.
