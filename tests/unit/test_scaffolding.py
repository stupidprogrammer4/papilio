import ast
import itertools
import subprocess
import sys
import tomllib

import pytest
import yaml

from papilio.scaffolding import modules, project


@pytest.mark.parametrize(
    "mode,http,excel,mcp,function_tools",
    tuple(
        itertools.product(
            ("crud", "cqrs", "context", "plain"),
            (False, True),
            (False, True),
            (False, True),
            (False, True),
        )
    ),
)
def test_generated_module_variants_have_valid_sources(
    mode, http, excel, mcp, function_tools
):
    files = modules.files(
        "shop.modules",
        "catalog.product",
        cqrs=mode == "cqrs",
        context=mode == "context",
        plain=mode == "plain",
        http=http,
        excel=excel,
        mcp=mcp,
        function_tools=function_tools,
    )
    for name, source in files.items():
        assert "<<" not in source
        if name.endswith(".py"):
            tree = ast.parse(source, filename=name)
            if (
                name.startswith(("app/", "tools/", "function_tools/"))
                or name == "interfaces.py"
            ):
                assert not any(
                    isinstance(node, ast.ImportFrom)
                    and ".routers." in (node.module or "")
                    for node in ast.walk(tree)
                )
    assert ("tools/operations.py" in files) == mcp
    assert ("function_tools/operations.py" in files) == function_tools
    if mode == "context":
        assert "app/results.py" in files
        assert "infra/tables.py" not in files


@pytest.mark.parametrize("cqrs", [False, True])
def test_project_templates_preserve_names_and_are_parseable(cqrs):
    name = 'فروشگاه "Papilio"'
    files = project.files("shop", name, cqrs=cqrs)
    assert "README.md" in files
    assert "'project/readme.tpl'.md" not in files
    assert name in files["README.md"]
    assert yaml.safe_load(files["config.yml"])["fastapi"]["title"] == name
    metadata = tomllib.loads(files["pyproject.toml"])
    assert metadata["project"]["description"] == f"{name}, built on Papilio"
    for path, source in files.items():
        assert "<<" not in source
        if path.endswith(".py"):
            ast.parse(source, filename=path)


@pytest.mark.parametrize(
    "name", ["../escape", "class", "group..item", "1item"]
)
def test_invalid_module_names_write_nothing(tmp_path, name):
    with pytest.raises(ValueError):
        modules.write(tmp_path / "modules", "shop.modules", name)
    assert list(tmp_path.iterdir()) == []


def test_generators_do_not_overwrite_existing_work(tmp_path):
    root = tmp_path / "shop"
    project.write(root, "shop", "Shop")
    target = modules.write(root / "shop/modules", "shop.modules", "product")
    source = target / "app/services.py"
    source.write_text("# application changes\n")
    with pytest.raises(FileExistsError):
        modules.write(root / "shop/modules", "shop.modules", "product")
    with pytest.raises(FileExistsError):
        project.write(root, "shop", "Shop")
    assert source.read_text() == "# application changes\n"


def test_cli_generates_mcp_module_and_preserves_existing_files(tmp_path):
    project.write(tmp_path, "shop", "Shop")
    command = [
        sys.executable,
        "-m",
        "papilio.cli",
        "module",
        "assistant",
        "--plain",
        "--mcp",
    ]
    result = subprocess.run(
        command, cwd=tmp_path, check=True, capture_output=True, text=True
    )
    assert "papilio[mcp]" in result.stdout
    assert "create_app(mcp=True)" in result.stdout
    tool = tmp_path / "shop/modules/assistant/tools/operations.py"
    assert tool.is_file()
    tool.write_text("# user's tool\n")
    repeated = subprocess.run(command, cwd=tmp_path, capture_output=True)
    assert repeated.returncode != 0
    assert tool.read_text() == "# user's tool\n"


def test_cli_generates_function_tools_without_optional_extras(tmp_path):
    project.write(tmp_path, "shop", "Shop")
    command = [
        sys.executable,
        "-m",
        "papilio.cli",
        "module",
        "assistant",
        "--plain",
        "--function-tools",
    ]
    result = subprocess.run(
        command, cwd=tmp_path, check=True, capture_output=True, text=True
    )
    assert "Required extras" not in result.stdout
    assert "boot_function_tools" in result.stdout
    assert "authorization policy" in result.stdout
    tool = tmp_path / "shop/modules/assistant/function_tools/operations.py"
    assert tool.is_file()
    tool.write_text("# user's Function Tool\n")
    repeated = subprocess.run(command, cwd=tmp_path, capture_output=True)
    assert repeated.returncode != 0
    assert tool.read_text() == "# user's Function Tool\n"


def test_cli_generates_importable_modules_without_installing_the_app(tmp_path):
    root = tmp_path / "shop"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "papilio.cli",
            "new",
            "shop",
            "--dir",
            str(root),
            "--cqrs",
        ],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    for name, options in (
        ("catalog.product", ["--cqrs"]),
        ("pricing", ["--context"]),
    ):
        subprocess.run(
            [
                sys.executable,
                "-m",
                "papilio.cli",
                "module",
                name,
                *options,
            ],
            cwd=root,
            check=True,
            capture_output=True,
        )
    subprocess.run(
        [
            sys.executable,
            "-c",
            "from shop.main import app; assert app.title == 'shop'",
        ],
        cwd=root,
        check=True,
        capture_output=True,
    )


@pytest.mark.parametrize(
    "name",
    [
        "es",
        "redis",
        "http",
        "excel",
        "files",
        "csv",
        "postgresql",
        "rate-limit",
    ],
)
def test_project_records_only_selected_infrastructure(name):
    from papilio.scaffolding.options import Infrastructure

    files = project.files("shop", "Shop", infra=(Infrastructure(name),))
    config = yaml.safe_load(files["config.yml"])
    metadata = tomllib.loads(files["pyproject.toml"])
    dependency = metadata["project"]["dependencies"][0]
    assert name in dependency
    assert ("db" in config) == (name == "postgresql")
    assert ("es" in config) == (name == "es")
    assert ("redis" in config) == (name == "redis")
    assert ("http" in config) == (name == "http")
    assert ("alembic.ini" in files) == (name == "postgresql")
    for path, source in files.items():
        assert "<<" not in source
        if path.endswith(".py"):
            ast.parse(source, filename=path)
