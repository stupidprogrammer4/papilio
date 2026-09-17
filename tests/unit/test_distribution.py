import shutil
import tarfile
import zipfile
from pathlib import Path

import pytest

build = pytest.importorskip(
    "hatchling.build", reason="Requires the project's declared build backend"
)


def wheel_contents(path):
    with zipfile.ZipFile(path) as archive:
        return {name: archive.read(name) for name in archive.namelist()}


def test_distribution_excludes_local_copies_and_roundtrips(
    tmp_path, monkeypatch
):
    root = Path(__file__).resolve().parents[2]
    project = tmp_path / "project"
    project.mkdir()
    for name in ("papilio", "tests", "docs"):
        ignored = ["__pycache__", "*.pyc"]
        if name == "docs":
            ignored.append("plans")  # Already excluded by .gitignore.
        shutil.copytree(
            root / name,
            project / name,
            ignore=shutil.ignore_patterns(*ignored),
        )
    root_files = {
        "pyproject.toml",
        "README.md",
        "LICENSE",
        "pytest.ini",
        "mkdocs.yml",
        ".gitignore",
    }
    for name in root_files:
        shutil.copy2(root / name, project / name)

    expected = {
        path.relative_to(project).as_posix(): path.read_bytes()
        for path in project.rglob("*")
        if path.is_file()
    }
    assert "papilio/py.typed" in expected
    assert "papilio/scaffolding/templates/project/main.tpl" in expected
    assert "tests/unit/test_distribution.py" in expected
    assert "docs/guide/api.md" in expected

    # Local excludes protect Git, but must not substitute for build selection.
    nested = project / ".local-review" / "backup"
    for folder in ("papilio", "tests", "docs"):
        (nested / folder).mkdir(parents=True)
        (nested / folder / "local.txt").write_text("local-only fixture\n")
    for name in root_files:
        (nested / name).write_text("local-only fixture\n")
    for name in ("AGENTS.md", "WORK.md"):
        (project / name).write_text("local-only record\n")
    info = project / ".git" / "info"
    info.mkdir(parents=True)
    (info / "exclude").write_text(".local-review/\nAGENTS.md\nWORK.md\n")

    output = tmp_path / "dist"
    output.mkdir()
    monkeypatch.chdir(project)
    direct = wheel_contents(output / build.build_wheel(str(output)))
    sdist = output / build.build_sdist(str(output))
    package = {
        name: data
        for name, data in expected.items()
        if name.startswith("papilio/")
    }
    assert {
        name: data
        for name, data in direct.items()
        if name.startswith("papilio/")
    } == package
    assert all(
        name.startswith("papilio/")
        or name.split("/", 1)[0].endswith(".dist-info")
        for name in direct
    )

    unpacked = tmp_path / "unpacked"
    with tarfile.open(sdist) as archive:
        files = {
            member.name.split("/", 1)[1]: archive.extractfile(member).read()
            for member in archive.getmembers()
            if member.isfile()
        }
        assert set(files) == set(expected) | {"PKG-INFO"}
        assert {name: files[name] for name in expected} == expected
        archive.extractall(unpacked, filter="data")

    monkeypatch.chdir(next(unpacked.iterdir()))
    rebuilt_dir = tmp_path / "rebuilt"
    rebuilt_dir.mkdir()
    rebuilt = wheel_contents(rebuilt_dir / build.build_wheel(str(rebuilt_dir)))
    assert rebuilt == direct
