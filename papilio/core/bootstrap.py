from __future__ import annotations

import importlib
import inspect
import pkgutil
from collections.abc import Sequence
from functools import cached_property, lru_cache
from typing import TYPE_CHECKING

from dishka import Provider
from fastapi import APIRouter

from papilio.core.config import get_settings
from papilio.core.logger import logger

if TYPE_CHECKING:
    from elasticsearch import AsyncElasticsearch
    from elasticsearch.dsl import AsyncDocument

    from papilio.function_tools.registry import FunctionTools
    from papilio.mcp.router import MCPRouter


class Bootstrapper:
    """Finds everything a running app is made of, by walking packages.

    `base_pkgs` contains application-selected package roots. Modules are
    discovered from their layout; the framework supplies none of its own.
    """

    def __init__(self, base_pkgs: Sequence[str] = ()) -> None:
        self.base_pkgs = tuple(base_pkgs)
        self.providers_path = "providers"
        self.tables_path = "infra.tables"
        self.routers_path = "routers"
        self.tools_path = "tools"
        self.function_tools_path = "function_tools"
        self.doc_path = "domain.documents"

    @cached_property
    def submodules(self) -> list:
        """
        Scan and import submodules ONLY ONCE.
        Returns a list of imported modules instead of yielding them repeatedly.

        Children of ``base_pkg`` are domain groups (catalog, market, …); a
        package counts as a module when it has a ``domain``/``app`` layer,
        so a group placed directly under ``base_pkg`` is scanned one level in.
        """
        modules = []
        for base_pkg in self.base_pkgs:
            base = importlib.import_module(base_pkg)
            for _, name, is_pkg in pkgutil.iter_modules(
                base.__path__, prefix=base_pkg + "."
            ):
                if not is_pkg:
                    continue
                if self._is_module(name):
                    modules.append(name)
                    continue
                group = importlib.import_module(name)
                for _, sub_name, sub_is_pkg in pkgutil.iter_modules(
                    group.__path__, prefix=name + "."
                ):
                    if sub_is_pkg and self._is_module(sub_name):
                        modules.append(sub_name)
        return modules

    def _is_module(self, name: str) -> bool:
        """Tell a feature module apart from a group folder.

        Args:
            name (str): Dotted package path under ``base_pkg``.
        Returns:
            (bool): True when the package has a ``domain`` or ``app`` layer.
        """
        pkg = importlib.import_module(name)
        layers = {
            sub
            for _, sub, is_pkg in pkgutil.iter_modules(pkg.__path__)
            if is_pkg
        }
        return bool(layers & {"domain", "app"})

    def import_module(self, path: str, *, raise_nested: bool = False):
        module = None
        try:
            module = importlib.import_module(path)
        except ModuleNotFoundError as e:
            missing_package = e.name and (
                e.name == path or path.startswith(e.name + ".")
            )
            if raise_nested and not missing_package:
                raise
        return module

    def import_package_modules(
        self, path: str, *, raise_nested: bool = False
    ) -> list:
        """Import a package and every file inside it — packages keep an empty
        ``__init__.py``, so the members live in the files.

        Args:
            path (str): Dotted path of the package (e.g.
                ``...listings.routers``).
            raise_nested (bool): Re-raise import errors coming from inside a
                file.
        Returns:
            (list): The imported file modules; empty when the package is
                absent.
        """
        modules = []
        package = self.import_module(path, raise_nested=raise_nested)
        if package is not None and hasattr(package, "__path__"):
            for _, name, is_pkg in pkgutil.iter_modules(
                package.__path__, prefix=path + "."
            ):
                if not is_pkg:
                    module = self.import_module(
                        name, raise_nested=raise_nested
                    )
                    if module is not None:
                        modules.append(module)
        return modules

    def boot_routers(self) -> list[APIRouter]:
        """Find all instances of fastapi.APIRouter in each module's routers
        files."""
        routers = []
        for module_name in self.submodules:
            files = self.import_package_modules(
                f"{module_name}.{self.routers_path}", raise_nested=True
            )
            for module in files:
                for _, obj in inspect.getmembers(module):
                    if isinstance(obj, APIRouter) and not any(
                        obj is seen for seen in routers
                    ):
                        routers.append(obj)
        return routers

    def boot_mcp_tools(self) -> list[MCPRouter]:
        """Collect explicit tool routers from each selected module's tools."""
        from papilio.mcp.router import MCPRouter

        routers: list[MCPRouter] = []
        for module_name in self.submodules:
            files = self.import_package_modules(
                f"{module_name}.{self.tools_path}", raise_nested=True
            )
            for module in files:
                for _, obj in inspect.getmembers(module):
                    if isinstance(obj, MCPRouter) and not any(
                        obj is seen for seen in routers
                    ):
                        routers.append(obj)
        return routers

    def boot_function_tools(self) -> list[FunctionTools]:
        """Collect explicit Function Tool collections from selected modules."""
        from papilio.function_tools.registry import FunctionTools

        collections: list[FunctionTools] = []
        for module_name in self.submodules:
            files = self.import_package_modules(
                f"{module_name}.{self.function_tools_path}", raise_nested=True
            )
            for module in files:
                for _, obj in inspect.getmembers(module):
                    if isinstance(obj, FunctionTools) and not any(
                        obj is seen for seen in collections
                    ):
                        collections.append(obj)
        return collections

    def boot_sqlmodels(self) -> None:
        """Import every module's ``infra/tables.py``, which is what registers
        its tables on ``SQLModel.metadata``.

        Only the table files: an entity declares fields and maps to nothing,
        so importing `domain/entities.py` would add no metadata. This is
        what alembic autogenerate and the test schema both read.
        """
        for module_name in self.submodules:
            self.import_module(
                f"{module_name}.{self.tables_path}", raise_nested=True
            )

    def boot_providers(self) -> list[Provider]:
        """Instantiate providers defined in each feature's providers module.

        Tables are imported first; concrete repositories name their table
        explicitly, and providers import those repositories. Imported provider
        classes are not registered implicitly.
        """
        self.boot_sqlmodels()
        providers = []
        for module_name in self.submodules:
            module = self.import_module(
                f"{module_name}.{self.providers_path}", raise_nested=True
            )
            if module:
                for _, obj in inspect.getmembers(module):
                    if (
                        inspect.isclass(obj)
                        and issubclass(obj, Provider)
                        and obj is not Provider
                        and obj.__module__ == module.__name__
                    ):
                        providers.append(obj())
        return providers

    def boot_documents(self) -> list[type[AsyncDocument]]:
        """Find all AsyncDocument subclasses."""
        from elasticsearch.dsl import AsyncDocument

        es_documents = []
        for module_name in self.submodules:
            module = self.import_module(
                f"{module_name}.{self.doc_path}", raise_nested=True
            )
            if module:
                for _, obj in inspect.getmembers(module):
                    if (
                        inspect.isclass(obj)
                        and issubclass(obj, AsyncDocument)
                        and obj is not AsyncDocument
                    ):
                        es_documents.append(obj)
        return es_documents

    async def boot_es_indices(self, es: AsyncElasticsearch) -> None:
        """Create each ES read-model index (with its mapping) if it's missing.

        Safe to run on startup: a missing or unreachable Elasticsearch is
        logged and skipped so the app still boots. A document marked
        ``__external__`` is read, never created — its index belongs to
        something else (a log shipper, another service), and initialising it
        here would impose our mapping on data we do not own.

        Args:
            es (AsyncElasticsearch): The client to create the indices with.
        Returns:
            (None)
        """
        for document in self.boot_documents():
            if getattr(document, "__external__", False):
                continue
            index_name = document._index._name
            try:
                if not await es.indices.exists(index=index_name):
                    await document.init(using=es)
            except Exception as exc:  # noqa: BLE001 — boot must survive a down ES
                logger.warning(
                    "skipping ES index init for %s: %s",
                    index_name,
                    exc,
                    exc_info=exc,
                )


@lru_cache
def get_bootstrapper() -> Bootstrapper:
    """The bootstrapper for this app, reading `app.modules` from config.yml."""
    return Bootstrapper(get_settings().app.modules)
