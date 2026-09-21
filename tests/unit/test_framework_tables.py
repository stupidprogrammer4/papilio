import subprocess
import sys


def test_bootstrap_has_no_application_modules_tables_or_routers():
    script = """
import sys
from importlib.util import find_spec
from sqlmodel import SQLModel
from papilio.core.bootstrap import Bootstrapper
from papilio.core.config import AppConfig
assert find_spec("papilio.modules") is None
assert AppConfig().modules == []
assert "papilio_projection_versions" not in SQLModel.metadata.tables
bootstrap = Bootstrapper()
bootstrap.boot_sqlmodels()
bootstrap.boot_sqlmodels()
assert not SQLModel.metadata.tables
assert bootstrap.boot_providers() == []
assert bootstrap.boot_routers() == []
assert "papilio.tasks.projection.broker" not in sys.modules
"""
    subprocess.run([sys.executable, "-c", script], check=True)


def test_explicit_table_name_preserves_default_convention():
    script = """
from typing import ClassVar
from papilio.infra.db.schema.entity import PersistenceEntity
from papilio.infra.db.table import BaseTable

class MediaTable(PersistenceEntity, BaseTable, table=True):
    table_name: ClassVar[str | None] = "tbl_media"

class ProductCategoryTable(PersistenceEntity, BaseTable, table=True):
    pass

assert MediaTable.__table__.name == "tbl_media"
assert ProductCategoryTable.__table__.name == "tbl_product_categories"
assert "table_name" not in MediaTable.model_fields
assert "table_name" not in MediaTable.__table__.c
assert BaseTable.table_name is None
"""
    subprocess.run([sys.executable, "-c", script], check=True)
