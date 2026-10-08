# Function Tools

Function Tools invoke typed application services in the same Python process.
The base package includes registration, discovery and Dishka execution; no
model SDK is required.

## Define a tool

Put collections in a selected module's `function_tools/*.py` files and keep
`function_tools/__init__.py` empty. Authorization belongs to your application:

```python
from collections.abc import Mapping
from typing import Any

from dishka import FromDishka

from papilio.function_tools.registry import FunctionTools, ToolEffect
from shop.modules.products.domain.entities import ProductModel
from shop.modules.products.interfaces import IProductService

tools = FunctionTools()


async def authorize_product(context: Any, arguments: Mapping[str, Any]) -> bool:
    return context.can_read_product(arguments["product_id"])


@tools.tool(
    key="products.get",
    name="get_product",
    title="Find product",
    description="Read an authorized product by its identifier.",
    effect=ToolEffect.READ,
    authorize=authorize_product,
)
async def get_product(
    product_id: int, service: FromDishka[IProductService]
) -> ProductModel:
    result = await service.get_by_id(product_id)
    return result
```

The stable key identifies the capability; `name` is the caller-facing tool name.
The application supplies the trusted context and implements `can_read_product`.
Inputs are validated before the authorization hook. Tools accept named
arguments; positional-only parameters and `*args` fail at composition. Core
execution and Pydantic AI support typed `**kwargs`. Injected parameters are
excluded from the input schema and cannot be supplied by callers. Services
remain responsible for business rules, record access and transactions.

Every tool declares its effect and authorization hook. A `ToolEffect.WRITE`
tool also requires `approve`, an async hook with the same context/arguments
signature. It checks the application's approval for the exact validated
arguments; selection or model prose is not approval. Returning `False` prevents
execution. Exceptions from hooks or services propagate to the application.

## Discover and invoke

Use the application's existing root Dishka container:

```python
from papilio.core.bootstrap import Bootstrapper
from papilio.function_tools.execution import FunctionToolExecutor

bootstrap = Bootstrapper(["shop.modules"])
executor = FunctionToolExecutor(bootstrap.boot_function_tools(), container)
product = await executor.invoke(
    "get_product", {"product_id": 12}, context=authenticated_actor
)
```

Each invocation opens its own `REQUEST` scope. Existing `APP` dependencies
remain shared within that application; request dependencies close on success,
failure and cancellation. The caller owns the root lifecycle and must not close
it from a tool. The executor returns the typed result without an HTTP envelope.
It does not implicitly commit transactions or resolve FastAPI `Depends`.

Discovery follows the existing direct/grouped module layout. Missing
`function_tools` packages are ignored; nested import failures surface. Repeated
references to one collection are included once. Only decorated tools are exposed.
The executor rejects duplicate public names and capability keys.

## Generate a module

```bash
papilio module product --function-tools
papilio module catalog.product --cqrs --function-tools
papilio module pricing --context --function-tools
papilio module assistant --plain --function-tools
```

The flag adds `function_tools/__init__.py` and `function_tools/operations.py`.
CRUD/CQRS tools call the existing `get_by_id` service. Plain/context tools call
the existing `run` service and conservatively declare a write effect. Implement
their application authorization and approval hooks before invocation: generated
hooks raise `NotImplementedError` until configured. Change the effect only when
the completed service contract establishes that the operation is read-only.

The flag does not install dependencies, enable a runtime, change HTTP/MCP
registration or overwrite an existing module. It can be combined with `--mcp`.
Process boundaries remain explicit: a separate agent service requires its
existing transport or a separately configured embedded application runtime.

## Optional Pydantic AI adapter

Install `papilio[function-tools-pydantic-ai]` when your application uses
Pydantic AI. Adapt an
executor to its native toolset instead of implementing a second invocation path:

```python
from pydantic_ai import Agent, DeferredToolRequests

from papilio.function_tools.pydantic_ai import build_toolset

agent = Agent(
    model,
    deps_type=Actor,
    output_type=[str, DeferredToolRequests],
    toolsets=[build_toolset(executor)],
)
result = await agent.run("Inspect the product", deps=authenticated_actor)
```

`Actor`, `model` and `authenticated_actor` are application-owned. Only supply
the permitted tool definitions for the current actor. Pydantic AI manages
messages and deferred write requests; your application handles the approval UI
and resumption. The application's authorization and exact-argument approval
hooks still run when an approved write resumes. The base executor and discovery
do not import this optional adapter.

## Optional MCP adapter

With `papilio[mcp]`, expose the selected definitions through the same executor:

```python
from papilio.function_tools.mcp import build_server

server = build_server(
    executor,
    current_context=authenticated_context,
    name="Product tools",
)
mcp_app = server.streamable_http_app(stateless_http=True, json_response=True)
```

`authenticated_context` is an application-supplied synchronous function that
returns the authenticated invocation context. Configure authentication and
actor-filtered discovery using the native server middleware before serving the
app. Authorization and write approval still run in the shared executor on every
call. A model argument cannot supply the context or injected dependencies.
Mount and enter the native MCP application's lifespan using your host's existing
lifecycle; the host retains ownership of the root Dishka container.

This adapter requires explicit named parameters and additionally rejects
`**kwargs` at composition because the MCP SDK's callable schema differs from
its native Function Tool contract. Unexpected top-level MCP arguments are rejected;
DTO fields retain their own Pydantic extra-field policy. Existing `MCPRouter`
tools and `create_app(mcp=...)` behavior are unchanged.

Function Tools do not provide business idempotency or durable execution. An
exception after a service commits, including output validation failure, does
not prove that the business effect was rolled back. Reconcile uncertain outcomes
through application records before retrying.
