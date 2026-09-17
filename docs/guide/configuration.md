# Configuration

Settings are validated with Pydantic at application startup. `get_settings()` reads the path in `PAPILIO_CONFIG`, falling back to `config.yml` relative to the process working directory, and caches the result. Editing the file does not reload a running process automatically. `papilio run --config path.yml` selects the same file for the launcher and application workers.

## Required and optional sections

| Section | Required? | Purpose |
| --- | --- | --- |
| `fastapi` | Yes | Title, description, version |
| `crypto` | No | Encryption key and password pepper |
| `jwt` | No | Algorithm, secrets and token expiry |
| `csrf` | No | CSRF configuration secret |
| `storage` | Yes | Paths, allowed extensions and maximum size |
| `logging` | Yes | Level, service, console/json format |
| `app` | Defaults provided | Module roots, features, custom Settings type |
| `run` | Defaults provided | CLI backend, entrypoint, mode, host, port, workers and reload |
| `db`, `es`, `redis`, `http` | No | Optional client configuration |
| `rate_limit` | Disabled by default | General and named request budgets |

A complete minimal configuration appears in [installation](start.md). The required storage and logging sections must exist. Authentication, crypto and CSRF settings can be omitted. Configuring `csrf` does not automatically protect every endpoint, and configuring `storage` does not install upload routes.

See [runner configuration and precedence](operations.md#configure-the-runner) for `papilio run`. Existing files without `run` remain valid.

Unknown top-level keys are rejected. `FullSettings` requires `db`, `es`, `redis`, `http`, `crypto`, `jwt` and `csrf`, and narrows their types; it does not register providers.

## Add application settings

In `shop/config.py`:

```python
from pydantic import BaseModel, Field
from papilio.core.config import Settings as PapilioSettings


class BillingConfig(BaseModel):
    currency: str = "USD"
    timeout: float = Field(default=5, gt=0)


class Settings(PapilioSettings):
    billing: BillingConfig
```

Add to your complete configuration:

```yaml
app:
  modules: [shop.modules]
  settings: shop.config.Settings
billing:
  currency: USD
  timeout: 5
```

The loader resolves the configured class once during settings loading. For a statically typed call:

```python
from papilio.core.config import get_settings
from shop.config import Settings

settings = get_settings(Settings)
```

CoreProvider registers the object under the framework's base Settings type. If a service requests `shop.config.Settings`, register that type too. Inheritance alone is not a DI registration:

```python
from dishka import Provider, Scope, provide
from papilio.core.config import Settings as PapilioSettings
from shop.config import Settings


class AppSettingsProvider(Provider):
    @provide(scope=Scope.APP)
    def typed(self, settings: PapilioSettings) -> Settings:
        return Settings.model_validate(settings.model_dump())
```

## Environment variables and secret stores

The YAML loader does not interpolate `${ENV_VAR}`. Construct Settings in your composition root if values come from the environment or a secret store, then pass the object to `create_app`:

```python
import os
from pathlib import Path
import yaml
from papilio.core.config import Settings

raw = yaml.safe_load(Path("config.yml").read_text(encoding="utf-8"))
raw["jwt"]["secret_key"] = os.environ["SHOP_JWT_SECRET"]
settings = Settings.model_validate(raw)
```

Use real deployment secrets instead of example values. In tests that intentionally replace the configuration file, call `get_settings.cache_clear()` before and after the test; do not clear the cache per request.

[All configuration fields](../reference/configuration.md)
