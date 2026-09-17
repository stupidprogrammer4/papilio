"""Write configuration for disposable CI services in a fresh checkout."""

import os
from pathlib import Path

import yaml

from papilio.core.config import Settings


def main() -> None:
    config = yaml.safe_load(Path("docs/examples/minimal.yml").read_text())
    dsn = os.environ["PAPILIO_TEST_POSTGRESQL"]
    config["db"] = dict(
        dsn=dsn,
        test_dsn=dsn,
        pool_size=2,
        max_overflow=0,
        pool_timeout=5,
        pool_recycle=1800,
    )
    # Shared-client tests mock Redis commands but require its config.
    config["redis"] = dict(
        url="redis://127.0.0.1:1/0",
        max_connections=2,
        socket_timeout=1,
        socket_connect_timeout=1,
        health_check_interval=0,
    )
    Settings.model_validate(config)
    with Path("config.yml").open("x") as stream:
        yaml.safe_dump(config, stream)


if __name__ == "__main__":
    main()
