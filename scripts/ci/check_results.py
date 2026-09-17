"""Reject missing integration coverage and unexpected skips in CI."""

import xml.etree.ElementTree as ET


def check(path: str) -> None:
    cases = list(ET.parse(path).getroot().iter("testcase"))
    if not cases:
        raise SystemExit("No test cases reported")
    passed = set()
    skipped = 0
    for case in cases:
        module = case.get("classname", "")
        name = case.get("name", "")
        identity = f"{module}::{name}"
        if case.find("failure") is not None or case.find("error") is not None:
            raise SystemExit(f"Failed test: {identity}")
        skip = case.find("skipped")
        if skip is None:
            passed.add(identity)
            continue
        reason = skip.get("message", "")
        allowed = False
        if module == "tests.unit.test_db_dialects":
            for backend in ("oracle", "mssql"):
                allowed |= name.endswith(f"[{backend}]") and reason == (
                    f"Set PAPILIO_TEST_{backend.upper()} "
                    "for live backend tests"
                )
            allowed |= (
                name
                in {
                    "test_native_upsert_and_explicit_update_expressions[mysql-orm]",
                    "test_upsert_batch_preserves_explicit_nullable_values[mysql-orm]",
                }
                and reason == "This path does not implement native upsert"
            )
            allowed |= (
                name.startswith(
                    "test_postgresql_values_grid_supports_custom_join_without_id["
                )
                and name.endswith(
                    ("[sqlite]", "[mysql-orm]", "[mysql]", "[mariadb]")
                )
                and reason == "PostgreSQL VALUES relation"
            )
        if module == "tests.unit.test_repository_fields":
            allowed |= (
                name
                == (
                    "test_upserts_and_batch_updates_use_explicit_field_names"
                    "[field_store1]"
                )
                and reason
                == "Only the ORM create path runs on SQLite for MySQL"
            )
            allowed |= (
                name.startswith(
                    "test_mysql_bulk_insert_uses_column_mapping_and_rolls_back["
                )
                and name.endswith(
                    ("[field_store0]", "[field_store2]", "[field_store4]")
                )
                and reason == "MySQL count-returning INSERT"
            )
        if not allowed:
            raise SystemExit(f"Unexpected skip: {identity}: {reason}")
        skipped += 1
    required = {
        "tests.integration.test_database::test_database_is_migrated_and_reachable",
        "tests.unit.test_distribution::test_distribution_excludes_local_copies_and_roundtrips",
        "tests.integration.test_scaffold_runtime::test_generated_sql_routes_and_query_tools[False]",
        "tests.integration.test_scaffold_runtime::test_generated_sql_routes_and_query_tools[True]",
    }
    required.update(
        "tests.integration.test_cli_runtime::"
        f"test_runner_serves_reloads_and_shuts_down[{mode}-{backend}]"
        for mode in ("dev", "prod")
        for backend in ("uvicorn", "gunicorn", "fastapi")
    )
    if missing := required - passed:
        raise SystemExit(f"Required tests did not pass: {sorted(missing)}")
    for backend in ("postgresql", "mysql", "mariadb", "sqlite"):
        if not any(
            name.startswith("tests.unit.test_db_dialects::")
            and name.endswith(f"[{backend}]")
            for name in passed
        ):
            raise SystemExit(f"No live database tests passed for {backend}")
    print(f"{len(passed)} passed; {skipped} explicitly allowed backend skips")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", help="Pytest JUnit XML report")
    check(parser.parse_args().path)
