# Modules and scaffolding

The CLI generates ordinary Python files. You own them after generation; no code generation runs during requests.

## Generate a project

```bash
papilio new shop --dir /tmp/papilio-learning/shop \
  --infra postgresql --infra redis --infra http --infra csv
```

Repeat `--infra` to select dependencies. Supported CLI selections are `postgresql`, `es`, `redis`, `rate-limit`, `http`, `excel`, `files` and `csv`. Other SQL backends exist at runtime but do not yet have dedicated project templates.

`--dir` names the project destination itself, not its parent directory. The target must be empty or absent.

With no infra selection, the project does not connect to external services. Project-level `--cqrs` selects PostgreSQL and Elasticsearch. Selecting `rate-limit` also selects Redis. Migration files are generated only for PostgreSQL projects.

## Choose a module shape

Run these commands from your generated project root:

| Command | Generated tools and work left to you |
| --- | --- |
| `papilio module product` | PostgreSQL CRUD; define entity and DTO fields |
| `papilio module catalog --cqrs` | SQL commands and ES queries; implement synchronization |
| `papilio module pricing --context` | Reader, context and calculation service; implement read and calculate methods |
| `papilio module greeting --plain` | Service and endpoint without SQL; implement the operation |
| `papilio module sales.order --http` | Grouped module with an HTTP gateway template |
| `papilio module report --plain --excel` | Exporter extension placeholder; no complete export implementation |
| `papilio module assistant --plain --mcp` | MCP tool calling the same service through Dishka; enable `create_app(mcp=True)` |

CRUD is the default, not a `--crud` flag. `--cqrs`, `--context` and `--plain` are mutually exclusive. The generator refuses to overwrite an existing module.

`--mcp` works with each preset and adds a `tools/` package. See
[MCP server tools](mcp.md) for installation, discovery and scope contracts.

## Where code belongs

```text
shop/
  main.py
  modules/
    products/
      domain/
        entities.py
        dtos.py
      app/
        services.py
      infra/
        tables.py
        repository.py
      routers/
        admin.py
        schemas.py
      interfaces.py
      providers.py
```

Additional files depend on the selected shape. `domain` contains entity and input definitions. `app` coordinates operations and transaction boundaries. `infra` implements persistence and external access. `routers` adapts those operations to HTTP. `interfaces.py` declares service contracts, and `providers.py` connects implementations.

## Startup discovery

```yaml
app:
  modules:
    - shop.modules
  features: []
```

The first module root is the CLI generation target. Packages must be importable and contain `__init__.py`. Discovery recognizes packages containing `domain` or `app`, including one group level. It imports `infra.tables` before providers, collects `APIRouter` objects from router files, and provider classes from `providers.py`.

Only provider classes defined in that `providers.py` are instantiated.
Imported base classes and providers re-exported from another module are not
registered there. To use an external provider directly, pass its configured
instance through `create_app(providers=[...])`.

For a different structure, pass routers and providers directly to [create_app](application.md), leaving `app.modules` empty if you do not want discovery.

## Application-owned modules

Papilio ships no application modules or predefined application scope vocabulary. Use the CLI to generate modules inside your own package, or create them manually. You choose their names, fields, routes, authorization and behavior. Only roots you supply through `app.modules` participate in discovery.

To generate files from your own developer tool, use the render/write functions in the [scaffolding reference](../reference/scaffolding.md).
