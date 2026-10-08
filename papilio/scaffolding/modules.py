"""Generate a module's source files."""

import keyword
from collections.abc import Mapping
from pathlib import Path

from papilio.utils.strings import pluralize

from .templates import render


def _layout(
    values: Mapping[str, str],
    *,
    cqrs: bool,
    context: bool,
    plain: bool,
    http: bool,
    excel: bool,
    mcp: bool,
    function_tools: bool,
) -> dict[str, str]:
    """The files a module is made of, as ``relative path -> template``."""
    if context or plain:
        files = {
            "__init__.py": "",
            "interfaces.py": "module/context_interfaces.tpl",
            "providers.py": "module/context_providers.tpl",
            "domain/__init__.py": "",
            "domain/context.py": "module/context.tpl",
            "domain/dtos.py": "module/context_dtos.tpl",
            "app/results.py": "module/context_schemas.tpl",
            "domain/enums.py": "module/enums.tpl",
            "app/__init__.py": "",
            "app/services.py": "module/context_services.tpl",
            "app/helpers.py": "module/helpers.tpl",
            "infra/__init__.py": "",
            "infra/readers.py": "module/context_readers.tpl",
            "routers/__init__.py": "",
            "routers/admin.py": "module/run_router.tpl",
        }
        if plain:
            files.pop("infra/readers.py")
            files.pop("domain/context.py")
            files["app/services.py"] = "module/plain_services.tpl"
            files["providers.py"] = "module/plain_providers.tpl"
    else:
        files = {
            "__init__.py": "",
            "interfaces.py": "module/interfaces.tpl",
            "providers.py": "module/providers_cqrs.tpl"
            if cqrs
            else "module/providers.tpl",
            "domain/__init__.py": "",
            "domain/entities.py": "module/models.tpl",
            "infra/tables.py": "module/tables.tpl",
            "domain/dtos.py": "module/dtos.tpl",
            "routers/schemas.py": "module/schemas.tpl",
            "domain/enums.py": "module/enums.tpl",
            "app/__init__.py": "",
            "app/services.py": "module/services.tpl",
            "app/helpers.py": "module/helpers.tpl",
            "infra/__init__.py": "",
            "infra/repository.py": "module/repository_cqrs.tpl"
            if cqrs
            else "module/repository.tpl",
            "routers/__init__.py": "",
            "routers/admin.py": "module/crud_router.tpl",
        }
        if cqrs:
            files["domain/documents.py"] = "module/documents.tpl"
            files["app/commands.py"] = "module/commands.tpl"
            files["app/queries.py"] = "module/queries.tpl"
            files["routers/search.py"] = "module/search_router.tpl"
    if http:
        files["infra/gateways.py"] = "module/gateways.tpl"
    if excel:
        files["infra/exporters.py"] = "module/exporters.tpl"
    if mcp:
        files["tools/__init__.py"] = ""
        files["tools/operations.py"] = (
            "module/run_tool.tpl"
            if context or plain
            else "module/read_tool.tpl"
        )
    if function_tools:
        files["function_tools/__init__.py"] = ""
        files["function_tools/operations.py"] = (
            "module/run_function_tool.tpl"
            if context or plain
            else "module/read_function_tool.tpl"
        )
    return {
        path: render(template, values) if template else ""
        for path, template in files.items()
    }


def _names(name: str, context: bool) -> tuple[str, str, str]:
    parts = name.strip().replace("/", ".").split(".")
    if not 1 <= len(parts) <= 2:
        raise ValueError("expected <name> or <group>.<name>")
    normalized = [
        part.lower().replace("-", "_").replace(" ", "_") for part in parts
    ]
    if any(
        not part.isidentifier() or keyword.iskeyword(part)
        for part in normalized
    ):
        raise ValueError("module and group names must be Python identifiers")
    group = normalized[0] if len(normalized) == 2 else ""
    singular = normalized[-1]
    words = singular.split("_")
    words[-1] = pluralize(words[-1])
    folder = singular if context else "_".join(words)
    return group, singular, folder


def files(
    package: str,
    name: str,
    *,
    cqrs: bool = False,
    context: bool = False,
    plain: bool = False,
    http: bool = False,
    excel: bool = False,
    mcp: bool = False,
    function_tools: bool = False,
) -> dict[str, str]:
    if sum((cqrs, context, plain)) > 1:
        raise ValueError("choose only one of CQRS, context or plain")
    group, singular, folder = _names(name, context or plain)
    dotted = f"{group}.{folder}" if group else folder
    values = {
        "PKG": package,
        "M": dotted,
        "S": singular,
        "PL": folder,
        "P": "".join(part.capitalize() for part in singular.split("_")),
        "TOOL_PREFIX": dotted.replace(".", "_"),
    }
    return _layout(
        values,
        cqrs=cqrs,
        context=context,
        plain=plain,
        http=http,
        excel=excel,
        mcp=mcp,
        function_tools=function_tools,
    )


def write(
    root: Path,
    package: str,
    name: str,
    *,
    cqrs: bool = False,
    context: bool = False,
    plain: bool = False,
    http: bool = False,
    excel: bool = False,
    mcp: bool = False,
    function_tools: bool = False,
) -> Path:
    rendered = files(
        package,
        name,
        cqrs=cqrs,
        context=context,
        plain=plain,
        http=http,
        excel=excel,
        mcp=mcp,
        function_tools=function_tools,
    )
    group, _, folder = _names(name, context or plain)
    parent = root / group if group else root
    target = parent / folder
    if target.exists():
        raise FileExistsError(f"module {name!r} already exists at {target}")
    parent.mkdir(parents=True, exist_ok=True)
    (root / "__init__.py").touch(exist_ok=True)
    (parent / "__init__.py").touch(exist_ok=True)
    for relative, body in rendered.items():
        path = target / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
    return target
