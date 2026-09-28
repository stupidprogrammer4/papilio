# MCP server tools

Install the optional server integration in your application:

```bash
pip install 'papilio[mcp]'
papilio module assistant --plain --mcp
```

Enable it in your application factory call:

```python
from papilio.api.application import create_app

app = create_app(mcp=True)
```

Run the app normally with `papilio run`. MCP clients connect to
`http://localhost:8000/mcp/`. The endpoint uses Streamable HTTP with stateless
requests and JSON responses by default. Papilio manages the SDK lifespan with
the host application; no separate MCP process or container is needed.

## Define a tool

Put tool definitions inside a selected module's `tools/` package. Keep its
`__init__.py` empty, as with `routers/`. For example, an application whose service
provides `get_by_id` can expose this tool in `tools/products.py`:

```python
from dishka import FromDishka

from papilio.mcp.router import MCPRouter
from shop.modules.products.domain.entities import ProductModel
from shop.modules.products.interfaces import IProductService

tools = MCPRouter()


@tools.tool(name="products_get")
async def get_product(
    product_id: int,
    service: FromDishka[IProductService],
) -> ProductModel:
    """Find a product by its identifier."""
    return await service.get_by_id(product_id)
```

The client supplies `product_id`. Dishka supplies `service`, which is omitted
from the tool's public input schema. The SDK validates inputs and converts typed
outputs into MCP results. Tool handlers are async functions returning completed
values; finish any work using their dependencies before returning.

Use the existing module `providers.py` to register the service. Infrastructure
providers still come from `create_app(providers=[...])`. `APP` resources are
shared with HTTP handlers in that app. Each tool invocation opens an independent
`REQUEST` scope from the root container; its dependencies close on completion,
failure or cancellation. The MCP session does not own a database transaction.
Service methods retain their existing `@transactional` commit/rollback behavior.

Application `APPException` errors are reported as MCP tool errors containing the
error schema as JSON text. Unexpected exceptions receive the SDK's generic tool
error. HTTP response envelopes and FastAPI exception handlers do not wrap MCP
results.

## Discovery and generation

`Bootstrapper.boot_mcp_tools()` collects `MCPRouter` instances from direct Python
files in `<module>.tools`, across the same `app.modules` roots and optional group
level used for HTTP discovery. Only explicitly decorated tools are registered.
Missing tool packages are ignored; errors importing an existing tool module
surface at startup. Repeated references to one router register it once. Distinct
registrations with the same public tool name fail at application construction.

`--mcp` adds `tools/__init__.py` and `tools/operations.py` to the selected module
preset:

```bash
papilio module product --mcp
papilio module catalog.product --cqrs --mcp
papilio module pricing --context --mcp
papilio module assistant --plain --mcp
```

CRUD and CQRS modules get a read tool calling `get_by_id`. Plain and context
modules get a tool calling `run`; the context reader/calculation still needs
application implementation. Generated names include the group and module to
avoid collisions. The flag adds to the normal module layout, including its HTTP
routers. It does not install dependencies, enable MCP in `main.py`, or overwrite
an existing module.

For tools outside discovery, pass `create_app(mcp=[tools])`. Explicit routers
are added to discovered ones. Passing an empty sequence still enables discovery.
The default `mcp=False` leaves tool modules and the optional SDK unimported.

## Transport and application access

Use `mcp_path="/agent"` for the endpoint `/agent/`. A deployment prefix supplied
through `root_path` is added outside that path. The SDK remains responsible for
transport security, host/origin checks and protocol handling. Configure its
native Streamable HTTP options through `mcp_http_options`, for example:

```python
from mcp.server.transport_security import TransportSecuritySettings

app = create_app(
    mcp=True,
    mcp_http_options={
        "transport_security": TransportSecuritySettings(
            allowed_hosts=["api.example.com"],
            allowed_origins=["https://assistant.example.com"],
        ),
    },
)
```

The SDK's default allowlist targets local development addresses. Set the actual
deployment hosts/origins when serving remotely. `streamable_http_path` is reserved;
use `mcp_path` to change the endpoint. Native options can also select stateful
sessions or SSE responses; their deployment and routing requirements remain
those of the SDK.

Enabling MCP does not add an authentication policy. Application middleware can
protect the MCP endpoint, and services must enforce their application access
rules. FastAPI route dependencies such as `Depends(require_access(...))` do not
execute for MCP tools. Providers requiring an HTTP `Request` are not automatically
given one in the tool scope; keep shared services independent of that HTTP
dependency or provide an explicit application adapter.

The host app exposes its SDK server as `app.state.mcp_server`. Papilio owns the
root container shutdown, after the user and MCP lifespans exit. Do not close that
container separately from an MCP tool or SDK lifespan.
