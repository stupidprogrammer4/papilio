from __future__ import annotations

import os
from enum import StrEnum
from functools import lru_cache
from importlib import import_module
from pathlib import Path
from typing import Literal, TypeVar, overload

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from papilio.tools.rate_limit.config import RateLimitConfig


class Feature(StrEnum):
    CQRS = "cqrs"


class AppConfig(BaseModel):
    """Application-owned module roots and feature settings."""

    modules: list[str] = Field(default_factory=list)
    features: set[Feature] = Field(default_factory=set)
    settings: str | None = None


class FastAPIConfig(BaseModel):
    title: str
    description: str
    version: str


class RunBackend(StrEnum):
    UVICORN = "uvicorn"
    GUNICORN = "gunicorn"
    FASTAPI = "fastapi"


class RunMode(StrEnum):
    DEV = "dev"
    PROD = "prod"


class RunConfig(BaseModel):
    """Launcher options; omitted host/reload follow the selected mode."""

    model_config = ConfigDict(extra="forbid")

    entrypoint: str | None = None
    backend: RunBackend = RunBackend.UVICORN
    mode: RunMode = RunMode.DEV
    host: str | None = Field(default=None, min_length=1)
    port: int = Field(default=8000, ge=1, le=65535)
    workers: int = Field(default=1, ge=1)
    reload: bool | None = None


class DatabaseConfig(BaseModel):
    test_dsn: str
    dsn: str
    pool_timeout: int = Field(ge=0)
    pool_recycle: int = Field(ge=0)
    pool_size: int
    max_overflow: int


class CryptoConfig(BaseModel):
    encryption_key: str
    password_salt: str


class RedisConfig(BaseModel):
    url: str
    max_connections: int = Field(ge=1)
    socket_timeout: float = Field(ge=0)
    socket_connect_timeout: float = Field(ge=0)
    health_check_interval: int = Field(ge=0)


class HTTPConfig(BaseModel):
    """The outbound client's pool and timeouts — see `HTTPConnection`."""

    max_connections: int = Field(ge=1)
    max_keepalive_connections: int = Field(ge=0)
    keepalive_expiry: float = Field(ge=0)
    timeout: float = Field(gt=0)
    connect_timeout: float = Field(gt=0)
    follow_redirects: bool = True


class JWTConfig(BaseModel):
    algorithm: str
    secret_key: str
    access_token_expire_minutes: int = Field(ge=1)
    # long-lived refresh token; trades for a fresh access token at
    # /auth/*/refresh
    refresh_token_expire_minutes: int = Field(default=60 * 24 * 14, ge=1)
    api_secret: str


class StorageConfig(BaseModel):
    path: str
    temp_dir: str
    max_file_size: int = Field(ge=1)
    allowed_extensions: list[str]


class CSRFConfig(BaseModel):
    secret_key: str


class ESConfig(BaseModel):
    hosts: list[str]
    username: str | None = None
    password: str | None = None
    api_key: str | None = None
    verify_certs: bool = True
    ca_certs: str | None = None


class LoggingConfig(BaseModel):
    """`console` for a readable terminal, `json` for one ECS object per
    line."""

    level: str
    format: Literal["console", "json"]
    service: str
    index: str = Field(default="logs", min_length=1)


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    app: AppConfig = AppConfig()
    fastapi: FastAPIConfig
    run: RunConfig = Field(default_factory=RunConfig)
    db: DatabaseConfig | None = None
    crypto: CryptoConfig | None = None
    redis: RedisConfig | None = None
    rate_limit: RateLimitConfig = RateLimitConfig()
    jwt: JWTConfig | None = None
    storage: StorageConfig
    csrf: CSRFConfig | None = None
    es: ESConfig | None = None
    http: HTTPConfig | None = None
    logging: LoggingConfig

    @model_validator(mode="after")
    def validate_features(self):
        if Feature.CQRS in self.app.features and self.es is None:
            raise ValueError("CQRS requires es configuration")
        return self


class FullSettings(Settings):
    """Every optional subsystem present, for a project installed with all
    the extras. Narrows the shapes the base leaves optional so a caller
    reads them without a None check."""

    crypto: CryptoConfig = Field(...)  # pyright: ignore[reportGeneralTypeIssues]
    jwt: JWTConfig = Field(...)  # pyright: ignore[reportGeneralTypeIssues]
    csrf: CSRFConfig = Field(...)  # pyright: ignore[reportGeneralTypeIssues]
    db: DatabaseConfig = Field(...)  # pyright: ignore[reportGeneralTypeIssues]
    redis: RedisConfig = Field(...)  # pyright: ignore[reportGeneralTypeIssues]
    http: HTTPConfig = Field(...)  # pyright: ignore[reportGeneralTypeIssues]
    es: ESConfig = Field(...)  # pyright: ignore[reportGeneralTypeIssues]


SettingsT = TypeVar("SettingsT", bound=Settings)


def _settings_model(raw: object) -> type[Settings]:
    model: type[Settings] = Settings
    app = raw.get("app") if isinstance(raw, dict) else None
    dotted = app.get("settings") if isinstance(app, dict) else None
    if dotted:
        if not isinstance(dotted, str) or "." not in dotted:
            raise ValueError("app.settings must be a dotted model path")
        module_name, class_name = dotted.rsplit(".", 1)
        selected = getattr(import_module(module_name), class_name)
        if not isinstance(selected, type) or not issubclass(
            selected, Settings
        ):
            raise TypeError("app.settings must reference a Settings subclass")
        model = selected
    return model


@overload
def get_settings() -> Settings: ...


@overload
def get_settings(model: type[SettingsT]) -> SettingsT: ...


@lru_cache
def get_settings(model: type[SettingsT] | None = None) -> SettingsT | Settings:
    path = Path(os.environ.get("PAPILIO_CONFIG", "config.yml"))
    with path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    selected = model or _settings_model(raw)
    if model is None and selected is not Settings:
        settings: SettingsT | Settings = get_settings(selected)
    else:
        settings = selected.model_validate(raw)
    return settings
