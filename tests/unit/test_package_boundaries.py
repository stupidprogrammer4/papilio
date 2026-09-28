import subprocess
import sys
import tomllib
from pathlib import Path

from papilio.scaffolding import project as scaffold
from papilio.scaffolding.modules import files as module_files


def test_distribution_does_not_require_task_frameworks():
    metadata = tomllib.loads(Path("pyproject.toml").read_text())
    dependencies = metadata["project"]["dependencies"]
    assert not any(
        "taskiq" in dep.lower() or "apscheduler" in dep.lower()
        for dep in dependencies
    )
    assert metadata["project"]["name"] == "papilio"
    assert metadata["project"]["scripts"] == {"papilio": "papilio.cli.app:app"}
    assert "ops" not in metadata["project"]["optional-dependencies"]


def test_web_scaffold_does_not_create_task_packages():
    files = module_files("shop.modules", "product", cqrs=True)
    assert "domain/documents.py" in files
    assert "infra/repository.py" in files
    assert not any(path.startswith("tasks/") for path in files)


def test_generated_app_imports_with_task_imports_blocked(tmp_path):
    scaffold.write(tmp_path, "probe", "Probe")
    script = """
import importlib.abc
import sys
class BlockTasks(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        blocked = {'taskiq', 'taskiq_redis', 'taskiq_fastapi',
                   'papilio_tasks', 'fastamu', 'papilio_api'}
        if fullname.split('.')[0] in blocked:
            raise AssertionError(f'Web imported {fullname}')
sys.meta_path.insert(0, BlockTasks())
from probe.main import app
assert app.title == 'Probe'
assert not any(name.startswith('papilio.tasks') for name in sys.modules)
"""
    subprocess.run([sys.executable, "-c", script], cwd=tmp_path, check=True)


def test_plain_application_does_not_import_optional_infrastructure(tmp_path):
    from papilio.scaffolding import modules

    scaffold.write(tmp_path, "probe", "Probe")
    modules.write(
        tmp_path / "probe/modules", "probe.modules", "health", plain=True
    )
    script = """
import importlib.abc
import sys
class BlockInfrastructure(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        blocked = {'sqlalchemy', 'sqlmodel', 'elasticsearch', 'redis',
                   'openpyxl', 'throttled', 'asyncpg', 'aiofiles'}
        if fullname.split('.')[0] in blocked:
            raise AssertionError(f'Optional import: {fullname}')
sys.meta_path.insert(0, BlockInfrastructure())
from probe.main import app
assert app.title == 'Probe'
assert '/health' in app.openapi()['paths']
"""
    subprocess.run([sys.executable, "-c", script], cwd=tmp_path, check=True)


def test_unused_config_and_catalog_do_not_activate_infrastructure(tmp_path):
    script = """
import asyncio
import importlib.abc
import sys
import yaml

class BlockInfrastructure(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {
            'sqlalchemy', 'sqlmodel', 'elasticsearch', 'redis', 'httpx',
            'throttled', 'asyncpg', 'asyncmy', 'oracledb', 'aioodbc',
        }:
            raise AssertionError(f'Unexpected optional import: {fullname}')

sys.meta_path.insert(0, BlockInfrastructure())
from papilio.providers.catalog import PROVIDERS
for spec in PROVIDERS:
    spec.missing()
from papilio.api.application import create_app
from papilio.core.config import Settings
from papilio.scaffolding.project import files
from papilio.scaffolding.options import Infrastructure
import papilio.api.application as application
application.logger.setup = lambda config: None
config = Settings.model_validate(yaml.safe_load(files(
    'shop', 'Shop', infra=[Infrastructure.POSTGRESQL, Infrastructure.ES,
                          Infrastructure.REDIS, Infrastructure.HTTP]
)['config.yml']))
config.app.modules = []
app = create_app(config)
async def run():
    async with app.router.lifespan_context(app):
        pass
asyncio.run(run())
"""
    subprocess.run([sys.executable, "-c", script], cwd=tmp_path, check=True)


def test_mcp_is_optional_even_for_generated_tool_modules(tmp_path):
    from papilio.scaffolding import modules

    scaffold.write(tmp_path, "probe", "Probe")
    modules.write(
        tmp_path / "probe/modules",
        "probe.modules",
        "health",
        plain=True,
        mcp=True,
    )
    script = """
import importlib.abc
import sys

class BlockMCP(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'mcp', 'mcp_types', 'httpx2'}:
            raise ModuleNotFoundError('MCP is not installed', name=fullname)

sys.meta_path.insert(0, BlockMCP())
from probe.main import app
assert '/health' in app.openapi()['paths']
assert not any(n.startswith('probe.modules.health.tools') for n in sys.modules)
from papilio.api.application import create_app
try:
    create_app(mcp=True)
except ImportError as exc:
    assert 'papilio[mcp]' in str(exc), str(exc)
else:
    raise AssertionError('Missing MCP should report its extra')
"""
    subprocess.run([sys.executable, "-c", script], cwd=tmp_path, check=True)


def test_sqlite_provider_does_not_require_other_backends(tmp_path):
    script = """
import asyncio
import importlib.abc
import sys
class OnlySQLite(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {
            'asyncpg', 'psycopg2', 'psycopg', 'asyncmy', 'pymysql', 'MySQLdb',
            'oracledb', 'cx_Oracle', 'aioodbc', 'pyodbc', 'elasticsearch',
            'redis', 'throttled',
        }:
            raise AssertionError(f'Unselected dependency: {fullname}')
sys.meta_path.insert(0, OnlySQLite())
from dishka import Scope, make_async_container
from sqlalchemy import select
from papilio.core.config import DatabaseConfig
from papilio.providers.db import SQLiteProvider
from papilio.infra.db.uow import SQLiteUnitOfWork
config = DatabaseConfig(dsn='sqlite+aiosqlite:///:memory:', test_dsn='',
                        pool_size=1, max_overflow=0, pool_timeout=5,
                        pool_recycle=1800)
async def run():
    container = make_async_container(SQLiteProvider(config))
    try:
        async with container(scope=Scope.REQUEST) as scope:
            unit = await scope.get(SQLiteUnitOfWork)
            assert (await unit.execute(select(1))).scalar_one() == 1
    finally:
        await container.close()
asyncio.run(run())
"""
    subprocess.run([sys.executable, "-c", script], cwd=tmp_path, check=True)
