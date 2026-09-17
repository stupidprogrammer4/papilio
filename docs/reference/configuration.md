# Configuration

JWT, crypto and CSRF configuration are optional. Rate-limit settings do not activate a backend or HTTP middleware.

## `papilio.core.config`

### `Feature`

```python
class Feature(StrEnum):
    CQRS = 'cqrs'
```

### `AppConfig`

```python
class AppConfig(BaseModel):
    modules: list[str] = Field(default_factory=list)
    features: set[Feature] = Field(default_factory=set)
    settings: str | None = None
```

### `FastAPIConfig`

```python
class FastAPIConfig(BaseModel):
    title: str
    description: str
    version: str
```

### `RunBackend`, `RunMode` and `RunConfig`

```python
class RunBackend(StrEnum):
    UVICORN = 'uvicorn'
    GUNICORN = 'gunicorn'
    FASTAPI = 'fastapi'

class RunMode(StrEnum):
    DEV = 'dev'
    PROD = 'prod'

class RunConfig(BaseModel):
    model_config = ConfigDict(extra='forbid')
    entrypoint: str | None = None
    backend: RunBackend = RunBackend.UVICORN
    mode: RunMode = RunMode.DEV
    host: str | None = Field(default=None, min_length=1)
    port: int = Field(default=8000, ge=1, le=65535)
    workers: int = Field(default=1, ge=1)
    reload: bool | None = None
```

The CLI resolves omitted host/reload values after applying overrides and validates mode/worker combinations. See [operations](../guide/operations.md).

### `DatabaseConfig`

```python
class DatabaseConfig(BaseModel):
    test_dsn: str
    dsn: str
    pool_timeout: int = Field(ge=0)
    pool_recycle: int = Field(ge=0)
    pool_size: int
    max_overflow: int
```

### `CryptoConfig`

```python
class CryptoConfig(BaseModel):
    encryption_key: str
    password_salt: str
```

### `RedisConfig`

```python
class RedisConfig(BaseModel):
    url: str
    max_connections: int = Field(ge=1)
    socket_timeout: float = Field(ge=0)
    socket_connect_timeout: float = Field(ge=0)
    health_check_interval: int = Field(ge=0)
```

### `HTTPConfig`

```python
class HTTPConfig(BaseModel):
    max_connections: int = Field(ge=1)
    max_keepalive_connections: int = Field(ge=0)
    keepalive_expiry: float = Field(ge=0)
    timeout: float = Field(gt=0)
    connect_timeout: float = Field(gt=0)
    follow_redirects: bool = True
```

### `JWTConfig`

```python
class JWTConfig(BaseModel):
    algorithm: str
    secret_key: str
    access_token_expire_minutes: int = Field(ge=1)
    refresh_token_expire_minutes: int = Field(default=60 * 24 * 14, ge=1)
    api_secret: str
```

### `StorageConfig`

```python
class StorageConfig(BaseModel):
    path: str
    temp_dir: str
    max_file_size: int = Field(ge=1)
    allowed_extensions: list[str]
```

### `CSRFConfig`

```python
class CSRFConfig(BaseModel):
    secret_key: str
```

### `ESConfig`

```python
class ESConfig(BaseModel):
    hosts: list[str]
    username: str | None = None
    password: str | None = None
    api_key: str | None = None
    verify_certs: bool = True
    ca_certs: str | None = None
```

### `LoggingConfig`

```python
class LoggingConfig(BaseModel):
    level: str
    format: Literal['console', 'json']
    service: str
    index: str = Field(default='logs', min_length=1)
```

### `Settings`

```python
class Settings(BaseModel):
    model_config = ConfigDict(extra='forbid')
    app: AppConfig = AppConfig()
    run: RunConfig = Field(default_factory=RunConfig)
    fastapi: FastAPIConfig
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

    @model_validator(mode='after')
    def validate_features(self):
        ...
```

### `FullSettings`

```python
class FullSettings(Settings):
    crypto: CryptoConfig = Field(...)
    jwt: JWTConfig = Field(...)
    csrf: CSRFConfig = Field(...)
    db: DatabaseConfig = Field(...)
    redis: RedisConfig = Field(...)
    http: HTTPConfig = Field(...)
    es: ESConfig = Field(...)
```

### `get_settings`

```python
@overload
def get_settings() -> Settings:
    ...
```

### `get_settings`

```python
@overload
def get_settings(model: type[SettingsT]) -> SettingsT:
    ...
```

### `get_settings`

```python
@lru_cache
def get_settings(model: type[SettingsT] | None=None) -> SettingsT | Settings:
    ...
```

Reads `PAPILIO_CONFIG` or defaults to `config.yml`. Results are cached by the `model` argument; changing the environment or file does not invalidate the cache. Custom `app.settings` resolution remains supported.

## `papilio.tools.rate_limit.config`

### `RateLimitRule`

```python
class RateLimitRule(BaseModel):
    limit: int = Field(gt=0)
    window_seconds: int = Field(gt=0)
```

### `RateLimitConfig`

```python
class RateLimitConfig(BaseModel):
    enabled: bool = False
    trusted_proxies: list[str] = Field(default_factory=list)
    general: RateLimitRule = RateLimitRule(limit=120, window_seconds=60)
    rules: dict[str, RateLimitRule] = Field(default_factory=dict)
```
