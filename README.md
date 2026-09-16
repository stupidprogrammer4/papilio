<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/assets/logo-dark.png">
    <source media="(prefers-color-scheme: light)" srcset="docs/assets/logo-light.png">
    <img src="docs/assets/logo-light.png" alt="Papilio" width="480">
  </picture>
</p>
<p align="center"><em>A modular foundation for production Python APIs.</em></p>
<p align="center">
  <img src="https://img.shields.io/badge/python-3.13%2B-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python 3.13+">
  <img src="https://img.shields.io/badge/typed-py.typed-D94A28?style=flat-square" alt="Typed package">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-202020?style=flat-square" alt="MIT License"></a>
</p>

---

**[Documentation](docs/index.md)** — step-by-step guides, runnable examples and API reference.


A modular web API framework built on FastAPI, Dishka and SQLAlchemy.

Papilio provides module discovery, dependency injection, HTTP responses,
validation, database repositories, transactions and application scaffolding.
Task execution and messaging belong to the independent **Papilio Tasks** project.

This is the local rename and extraction of Fastamu, not a published release.
Install this checkout with `pip install -e ".[dev]"` and use `papilio` as the
CLI command. Python imports use `papilio`.

## Table of contents

- [The stack: what each tool does](#the-stack-what-each-tool-does)
- [Quickstart](#quickstart)
- [Project layout](#project-layout)
- [Application construction](#application-construction)
- [The core idea: a module](#the-core-idea-a-module)
- [The discovery contract](#the-discovery-contract)
- [Scaffolding a module](#scaffolding-a-module)
- [Tutorial: building a feature end to end](#tutorial-building-a-feature-end-to-end)
- [Dependency injection](#dependency-injection)
- [The data layer](#the-data-layer)
- [Responses and errors](#responses-and-errors)
- [Authentication and scopes](#authentication-and-scopes)
- [Rate limiting](#rate-limiting)
- [Other infrastructure](#other-infrastructure)
- [Migrations](#migrations)
- [Testing](#testing)
- [Configuration reference](#configuration-reference)
- [House rules](#house-rules)

---

## The stack: what each tool does

Papilio is deliberately not a from-scratch framework. Each concern is delegated
to a mature library; Papilio's value is the **integration layer** that makes them
behave as one thing.

| Concern | Tool | What Papilio adds on top |
|---|---|---|
| HTTP, validation, OpenAPI | **FastAPI** | Auto-included routers, a uniform response envelope, typed error handlers, offline (CDN-free) Swagger UI |
| Dependency injection | **dishka** | A small `CoreProvider` plus explicit optional infrastructure providers; per-module providers discovered and merged automatically; `APP`/`REQUEST` scopes for the web application |
| Write side / ORM | **SQLModel** + **SQLAlchemy 2.0** (async) | Explicit repositories for each database and entity shape, native writes, paging/streaming helpers, and a request-scoped `UnitOfWork` |
| Read side / search | **Elasticsearch DSL** (async) | `ESStore` and optional application-owned index initialization |
| Migrations | **Alembic** | Metadata pulled straight from the bootstrapper, so `--autogenerate` sees every module without imports |
| Cache / broker | **Redis** | Pooled async client, injectable |
| Outbound HTTP | **httpx** | One pooled client for the process, plus a `BaseGateway` that owns base url, headers and per-API timeouts |
| Logging | **Rich / orjson** | One switch between Rich console output and ECS-shaped JSON lines, a request id on every record, and uvicorn/gunicorn adopted into the same handler |
| Spreadsheets | **openpyxl / xlsxwriter** | Async reader/writer that offloads to a `ProcessPool` so a large workbook never blocks the event loop |
| Validation vocabulary | **pydantic v2** | A shared library of semantic type aliases (`RialType`, `SlugType`, `MobileType`, …) |
| Scaffolding | **typer** | A CLI that generates a complete, correctly-layered module |
| Tests | **pytest** + pytest-asyncio | Async-by-default, real-database fixtures, and a DI container that discovers modules exactly like production does |

---

## Installation and optional infrastructure

Until publication, install from this checkout. The base package has no SQL,
Elasticsearch, Redis or spreadsheet dependency. Select extras explicitly:

```bash
pip install -e ".[server]"
pip install -e ".[postgresql,es,redis,rate-limit]"
pip install -e ".[files,csv,excel,http]"
pip install -e ".[test]"
```

| Extra | Capability |
|---|---|
| `server` | Uvicorn |
| `db` | SQLModel, SQLAlchemy and Alembic, without a database driver |
| `postgresql`, `mysql`, `mariadb`, `sqlite`, `mssql`, `oracle` | SQL tools plus the selected driver |
| `es` | Elasticsearch client, documents and store |
| `redis` | Redis client |
| `rate-limit` | Rate-limit tools and memory backend |
| `rate-limit-redis` | Rate-limit tools with Redis |
| `passwords` / `auth` / `crypto` / `csrf` | Optional security tools/adapters |
| `http` | Outbound HTTP client and gateway |
| `excel` | Spreadsheet reader/writer; no pandas or NumPy |
| `files`, `csv` | Async file and CSV tools using AnyIO worker threads |
| `persian` | Jalali/Persian utility functions |
| `test` | Pytest, async testing and HTTP test client |
| `all` / `dev` | All optional runtime tools / runtime plus development tools |

Installing an extra makes its imports available. Run `papilio providers` to see
installation availability and `papilio providers NAME` for a usage suggestion.
Ready providers live in `papilio.providers`. Add your selected provider to
`create_app(providers=...)` to manage its resources. CoreProvider provides only
settings. Password hashing has a separate optional provider. `db`, `redis`, `http` and `es` configuration may
be absent; rate limiting is off by default. Module discovery defaults to an
empty list; only application-selected packages are discovered.

```bash
papilio new minimal
papilio new shop --infra postgresql --infra redis --infra rate-limit
papilio new reporting --infra es --infra csv --infra files
papilio new catalog --cqrs
```

`--infra` is repeatable. The generator writes the selected extras into project
metadata and explicit provider wiring into `main.py`. `--cqrs` is a project
preset selecting PostgreSQL and Elasticsearch. Database migrations are emitted
only when PostgreSQL is selected. Other database drivers and repositories remain
available as extras; the current CLI SQL templates target PostgreSQL.

| Module command | Generated behavior |
|---|---|
| `papilio module product` | SQL CRUD service and HTTP endpoints |
| `papilio module product --cqrs` | CRUD, SQL create command, ES search query and search endpoint |
| `papilio module pricing --plain` | DTO, output, service, provider and endpoint; no SQL or ES imports |
| `papilio module pricing --context` | A custom SQL reader and calculation skeleton to implement |
| `--http`, `--excel` | Additional gateway/exporter extension files |

CRUD models start with persistence fields; add your domain fields to the model
and input DTOs. The plain service starts with an empty output for you to fill.
Context reading/calculation is application-specific and intentionally unfinished.
CQRS writes and search are separate tools: no automatic publication, projection,
retry, outbox or SQL-to-ES synchronization is installed. Module generation prints
the required extras; add them to your project's dependencies and wire providers.

## Quickstart

**Runtime requirement:** Python **3.13+**. The SQL example below explicitly
selects PostgreSQL; other infrastructure is optional.

```bash
# 1) From this checkout, install the framework and start a project
python3.13 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
papilio new shop --infra postgresql && cd shop

# 2) Config — config.yml is gitignored; it holds your secrets
#    fill in: db.dsn, db.test_dsn, redis.url,
#             jwt.secret_key, crypto.encryption_key
pip install -e ".[dev]"

# 3) Schema
alembic upgrade head

# 4) API — the entry point generated in your project
uvicorn shop.main:app --reload

```

`papilio new` writes only what is yours — a package for your modules, the config
the framework reads, alembic wiring and a test suite. **The framework stays in
the installed package**: there is no vendored copy to keep in step. Until the
first release, update the local checkout and reinstall it in editable mode.

Working *on* Papilio itself instead? Clone it and `pip install -e ".[dev]"`.
The framework ships no application modules; configure your own package roots
or pass routers and providers directly to `create_app()`.

Swagger UI is served at **`/docs`**, self-hosted from `/static/swagger` — no CDN,
so it works on an air-gapped box.

> **`config.yml` is resolved relative to the current working directory.** Always
> launch from the project root. There is no `.env` / environment-variable override
> layer: the YAML file is the single source of configuration.

---

## Project layout

Two trees: the framework you installed, and the project you generated.

```
# your project — everything here is yours
shop/
├── config.yml       # what the framework reads; app.modules points at yours
├── alembic.ini  migrations/
├── tests/           # the fixtures arrive with the package (see Testing)
└── shop/
    └── modules/     # your features — one folder each
        └── catalog/products/…
```

```
# the installed package — `import papilio`
papilio/
├── schemas/         # Validated inputs, outputs and application results
├── errors/          # Typed exceptions and error schemas
├── security/        # Token, hashing and encryption primitives
├── types/           # Shared aliases, enums and numeric constants
├── utils/           # Date, text and currency helpers
├── tools/           # Checks, auth, ID mapping and rate-limit backends
├── providers/       # Optional ready providers selected by the application
├── core/            # Settings, discovery and logging
├── infra/
│   ├── db/          # SQL schemas, repositories, connections and UoWs
│   ├── es/          # Search client and DSL store
│   ├── redis/       # Shared Redis client
│   ├── http/        # Outbound HTTP connection and gateways
│   ├── excel/       # Spreadsheet readers and writers
│   ├── files/       # Async text and binary file tools
│   └── csv/         # Async streaming CSV reader/writer
├── api/
│   ├── application.py  # App factory and resource lifetime
│   ├── dependencies/   # Optional auth, ID and rate-limit adapters
│   ├── requests/       # Query models
│   ├── responses/      # Envelope, metadata and exception handlers
│   ├── middlewares/    # Request logging and optional rate limiting
│   └── docs.py         # Offline Swagger UI
├── cli/             # Project/module commands
├── scaffolding/     # Renderers and packaged template files
└── testing/         # Pytest fixtures
```

Select your own module package in `config.yml`:

```yaml
app:
  modules:
    - "shop.modules"
```

**Dependency direction is strictly inward.** `routers` / `app` / `infra`
all depend on `domain`; `domain` knows nothing about HTTP, SQL or Elasticsearch.

---

## Application construction

The application belongs to your project. `papilio new shop` generates
`shop/main.py`; run it with `uvicorn shop.main:app`. The framework has no global
ASGI application.

```python
from papilio.api.application import create_app

app = create_app(
    title="Shop API",
    root_path="/gateway",
    docs_url="/reference",
)
```

Pass `settings` to supply an explicit settings instance. `providers` and
`routers` add to discovered modules. `middleware` replaces the default stack
when supplied; `middleware=()` disables the defaults. Dishka's request-scope
middleware is always installed. `exception_handlers` overrides individual
framework handlers. Other keyword options go directly to FastAPI.

Supply an async context manager as `lifespan` for application resources. It
starts after framework startup and exits before the container closes, so its
cleanup can still use dependencies. Its yielded state is preserved for requests.
Use lifespan for startup/shutdown work rather than the legacy event arguments.

Local Swagger UI defaults to `/docs`; `docs_url=None` disables it. Custom schema
paths, Swagger options and `root_path` are respected. Disabling `openapi_url`
also disables Swagger UI.

Each factory call creates a separate container. Startup configures logging and runs the application lifespan; shutdown closes owned resources, including
when startup fails. Importing the factory and CLI does not read `config.yml`.

## The core idea: a module

A feature is a **module**: `papilio/modules/<name>/`. Modules may be filed under a
**group** — `papilio/modules/<group>/<name>/` — but a group is nothing more than a
namespace folder, and it is entirely optional. `modules/pricing/` and
`modules/catalog/products/` are both perfectly ordinary modules; group things
when grouping earns its keep, not because the layout demands it.

```
modules/[<group>/]<name>/
├── domain/         # The inward core — no I/O, and no idea one exists
│   ├── entities.py     # SQLModel schemas, without table mapping
│   ├── dtos.py         # BaseDTO                     (validated input)
│   ├── enums.py
│   └── documents.py    # AsyncDocument  (CQRS only)  (ES read model)
├── app/            # Business logic
│   ├── services.py
│   ├── helpers.py
│   ├── commands.py     # (CQRS only) write commands
│   └── queries.py      # (CQRS only) reads that hit Elasticsearch
├── infra/          # This module's adapters
│   ├── tables.py       # the SQLModel tables carrying domain/entities.py
│   ├── repository.py
│   ├── gateways.py     # (--http)  outbound HTTP clients
│   └── exporters.py    # (--excel) file/spreadsheet exporters
├── routers/        # One file per concern (admin.py, public.py, …)
├── interfaces.py   # I*Service Protocols — the module's public contract
├── providers.py    # The module's dishka Provider
└── resources.py    # Module-scoped message codes (add by hand when you need them)
```

Everything except `domain/` or `app/` is optional — a module with no table, no
router is perfectly legal.

### Context modules: when the module owns logic, not rows

Some modules own no data at all. A pricing engine reads a handful of fields —
today's metal rate, a margin, a tax band — and turns them into a number. It has
no table to write, nothing to project into Elasticsearch, and no CRUD surface;
what it has is **rules**. Modelling it as a resource with a `*Model` and a
repository would be inventing a row that never existed.

Such a module replaces its write model with a **context**: a frozen dataclass in
`domain/context.py` holding exactly the facts the logic runs on.

```
modules/pricing/
├── domain/
│   ├── context.py   # PricingContext — the facts, frozen
│   ├── dtos.py      # PricingInput
│   └── enums.py
├── app/services.py  # the engine
├── infra/readers.py # PricingReader — pulls only the columns it needs
├── routers/  interfaces.py  providers.py
```

The reader extends `PGReader` — a repository base
with no model or table bound to it. It receives its typed UoW and session and
returns the context its logic needs. The service splits in
two: `run()` sits at the edge and does the reading, `calculate()` stays pure.

```python
class PricingService:
    def __init__(self, reader: PricingReader) -> None:
        self.reader = reader

    async def run(self, data: PricingInput) -> PricingOut:
        context = await self.reader.read()
        return self.calculate(context, data)

    def calculate(self, context: PricingContext, data: PricingInput) -> PricingOut:
        ...
```

That seam is the whole point: `calculate` is a pure function of a context and an
input, so the rules that actually matter are unit-testable without a database,
a container or a running app. Scaffold one with `--context`.

**Modules never import each other directly.** Cross-module collaboration goes
through an `I*Service` `Protocol` declared in `interfaces.py` and injected by
dishka. That is what keeps a modular monolith from quietly becoming a big ball of
mud — and what makes any module extractable into its own service later.

---

## The discovery contract

This is the single most important section. There is **no registration anywhere**;
the bootstrapper ([papilio/core/bootstrap.py](papilio/core/bootstrap.py)) finds your code
by walking the app's modules package and looking for four paths.

A package under `papilio/modules/` is recognised as a **module** if — and only if — it
contains a `domain/` or an `app/` sub-package. Anything else is treated as a
**group** and scanned one level deeper. That's the whole rule — and it is why a
group is optional: `modules/pricing/` is found by the same rule that finds
`modules/catalog/products/`.

| What | Where the bootstrapper looks | What it collects |
|---|---|---|
| **Routers** | `<module>/routers/*.py` | Every module-level `APIRouter` instance (deduped), then `app.include_router(...)` |
| **Providers** | `<module>/providers.py` | `dishka.Provider` subclasses defined in that module, instantiated and merged into the container |
| **Tables** | `<module>/infra/tables.py` | Imported so the `table=True` classes register on the shared metadata (this is what Alembic autogenerate sees). Only this file — a `domain/entities.py` maps to nothing |
| **ES documents** | `<module>/domain/documents.py` | Every `AsyncDocument` subclass; optional index initialization is called from the application lifespan |

Consequences worth internalising:

- **`routers/` are packages whose `__init__.py` stays empty.** The
  bootstrapper imports each *file* inside them. Re-exporting from `__init__.py`
  is not just unnecessary, it is against the convention.
- **`providers.py`, `domain/entities.py` and `infra/tables.py` are single files**, not packages.
- **Every one of these is optional.** A module may provide only the layers it needs. A missing file is skipped silently; a file that *exists but fails to
  import* raises loudly (for routers), so typos don't silently unmount your API.
- **The bootstrapper does not invent prefixes or tags.** Your router declares its
  own `prefix=` and `tags=`. The scaffolder writes the pluralised convention for
  you.
- The bootstrapper is shared by the web application, migrations and test
  fixtures. Worker discovery belongs to Papilio Tasks.

---

## Scaffolding a module

Run from the repo root. Pass the name as `<singular-name>`, or as
`<group>.<singular-name>` to file it under a group; the CLI pluralises the
folder, the router prefix, the tags and the table name, while class names stay
singular.

```bash
papilio module product                   # CRUD, no group
papilio module catalog.product           # CRUD, filed under catalog/
papilio module catalog.product --cqrs    # + ES read model, commands/queries
papilio module pricing --context         # pure logic: context + reader, no models
papilio module catalog.product --http    # + infra/gateways.py
papilio module catalog.product --excel   # + infra/exporters.py
```

Flags compose freely (`--cqrs --excel`); `--context` is the one exclusion
— a module with no table cannot have a read side to project into, so it rejects
`--cqrs`. The console script `papilio` is also installed by `pip install -e .`,
so `papilio module catalog.product` works too.

What `catalog.product` produces:

| | |
|---|---|
| Folder | `papilio/modules/catalog/products/` |
| Classes | `ProductModel`, `ProductCreate`, `ProductUpdate`, `ProductOut`, `ProductRepository`, `ProductService`, `IProductService`, `ProductProvider` |
| Table | `tbl_products` |
| Router | `APIRouter(prefix="/products", tags=["products"])` |

What `pricing --context` produces:

| | |
|---|---|
| Folder | `papilio/modules/pricing/` — **not** pluralised; an engine is not a collection |
| Classes | `PricingContext`, `PricingInput`, `PricingOut`, `PricingReader`, `PricingService`, `IPricingService`, `PricingProvider` |
| Table | none — no `infra/tables.py`, no `domain/documents.py` |
| Router | `APIRouter(prefix="/pricing", tags=["pricing"])` |

The group folder is created on first use. Generated files are correctly layered
and cross-imported, with method bodies left as `raise NotImplementedError` — the
wiring is done, the logic is yours.

---

## Tutorial: building a feature end to end

Let's build `catalog.brand` as a plain CRUD module. Start with the scaffold:

```bash
papilio module catalog.brand
```

### 1. The model — `domain/entities.py`

A model declares **fields and nothing else**. It is not the table: no `table=True`,
no table mapping or `__tablename__`. These SQLModel schemas describe
what a brand *is*, and knows nothing about where brands are kept.

```python
from papilio.infra.db.schema.entity import PersistenceEntity
from papilio.infra.db.schema.fields import BoolField, CharField


class BrandModel(PersistenceEntity):
    name: str = CharField(35, index=True)
    slug: str = CharField(55, unique=True)
    is_active: bool = BoolField(default=True)
```

`PersistenceEntity` contributes `id`, `created_at` and `updated_at`. Columns use
the **field factories** from
[papilio/infra/db/schema/fields.py](papilio/infra/db/schema/fields.py), which default to
`NOT NULL`. Common options are direct named arguments:

```python
name: str = CharField(100, unique=True, db_column="display_name")
metadata: dict = JSONField(default_factory=dict)
note: str | None = TextField(default=None, nullable=True)
```

`default` and `default_factory` declare model defaults. `nullable` and
`server_default` do not implicitly add a model default. A callable factory is
passed as `default_factory`, never inferred from `default`. Strings supplied
as `server_default` remain literal strings; pass `text(...)` or a SQLAlchemy
expression when SQL should run. For example, use `server_default="pending"`
for a string and `server_default=func.current_timestamp()` for a timestamp.
`db_column` renames the physical column without changing the model field.
`onupdate`, `server_onupdate`, `index`, `unique` and `comment` are also direct
options. Advanced SQLAlchemy column options can use `sa_column_kwargs`.
The helpers neither inspect nor modify the supplied options per query.

`JSONField(none_as_null=False)` stores Python `None` as JSON `null`;
`none_as_null=True` selects SQL `NULL`. MySQL ORM inserts follow SQLAlchemy's
native omission rules for scalar columns with defaults; use an explicit SQL
`null()` in a custom statement when required. Repositories never rewrite None.
`VersionField` stores a version number; choose its default and update
expression explicitly. `VersionEntity` starts at database version 1 and does
not install an implicit increment.

Bases: `BaseEntity` (bare), `IdentifiedEntity`, `TimestampEntity`,
`PersistenceEntity`.

Field factories: `IDField`, `SmallIntField`, `IntField`, `BigIntField`, `BoolField`,
`FloatField`, `NumericField`, `CharField`, `TextField`, `DateField`,
`TimestampField` (timezone-aware), `JSONBField`, `ArrayField` (optional GIN index),
`EnumField` (native PG enum), `ComputedField` (generated column), `ForeignKeyField`.

### 1b. The table — `infra/tables.py`

One line maps the model onto a real table. This file is the *only* place that
knows a database exists, and the only one the bootstrapper imports for metadata:

```python
from papilio.infra.db.table import BaseTable
from shop.modules.catalog.brands.domain.entities import BrandModel


class BrandTable(BrandModel, BaseTable, table=True):
    pass
```

Constraints and indexes that span columns live here too — `__table_args__`, a
`UniqueConstraint`, an explicit `__tablename__`. Repositories are still declared
against the **model** (`PGIdentifiedRepository[BrandModel]`) and bind
`table = BrandTable` explicitly in `infra/`.

> **Table naming.** The class name becomes snake case and its final word is
> pluralized: `ProductTagTable` becomes `tbl_product_tags`. Set `__tablename__`
> explicitly when your application uses a different convention.

### 2. Validated input — `domain/dtos.py`

DTOs are **plain pydantic**, never SQLModel: input validation must not depend on
the ORM. Draw the field types from [papilio/types/aliases.py](papilio/types/aliases.py) so
validation rules stay consistent across the codebase.

```python
from papilio.schemas.inputs import BaseDTO
from papilio.types.aliases import SlugType, StrType


class BrandCreate(BaseDTO):
    name: StrType
    slug: SlugType


class BrandUpdate(BaseDTO):
    name: StrType | None = None
    is_active: bool | None = None
```

`BaseDTO.to_row()` turns a DTO into a column dict. It defaults to
`exclude_unset=True`, which is what gives `BrandUpdate` correct **PATCH
semantics** — a field the client never sent is never written. Pass
`exclude_unset=False` on create to let defaults materialise.

### 3. Wire output — `routers/schemas.py`

The shape a client sees is an HTTP concern, so it sits with the routes that
serialise it. An unmapped SQLModel schema can also be reused as an output base
instead of restating its fields:

```python
from shop.modules.catalog.brands.domain.entities import BrandModel


class BrandOut(BrandModel):
    pass
```

Add computed fields, or narrow to a subset by declaring only what you want — a
schema that must differ from the model still starts from `BaseOutput`:

```python
from papilio.schemas.outputs import BaseOutput


class BrandSummaryOut(BaseOutput):
    id: int
    name: str
```

`BaseOutput` is `from_attributes=True` and ships `from_obj()`, `from_objs()`,
`from_dict()`, `from_dicts()`.

### 4. Queries — `infra/repository.py`

**A repository is one statement per method. No branching, no business rules.**
Inherit and you get the whole CRUD surface for free.

```python
from sqlmodel import col, select

from papilio.schemas.results import PagedType
from papilio.infra.db.repositories.backends.postgresql import PGIdentifiedRepository
from papilio.infra.db.tools.read import fetch_page
from shop.modules.catalog.brands.domain.entities import BrandModel
from shop.modules.catalog.brands.infra.tables import BrandTable


class BrandRepository(PGIdentifiedRepository[BrandModel]):
    table = BrandTable

    async def get_by_slug(self, slug: str) -> BrandModel | None:
        stmt = select(BrandModel).where(col(BrandModel.slug) == slug)
        result = await self.uow.execute(stmt)
        return result.scalar_one_or_none()

    async def get_paged(self, page: int, per_page: int) -> PagedType[BrandModel]:
        stmt = select(self.table).order_by(col(self.table.id).desc())
        return await fetch_page(self.uow, stmt, offset=(page - 1) * per_page, limit=per_page)
```

`fetch_page` returns the page **and** the total match count. The count is its own
statement (the filters wrapped in a subquery, ordering dropped), which costs a
round-trip and buys a paginator that behaves the same whatever select you hand it —
a window function riding along on the page would have to be added to your statement,
breaking `scalars()` and mis-counting anything that is not a plain `select(Model)`.

### 5. Logic — `app/services.py`

Application services own business rules. Optional `IDChecks` supplies validation
and existence checks with an explicit entity label; it does not select a SQL model.

```python
from papilio.tools.checks import IDChecks
from papilio.infra.db.tools.decorators import transactional
from papilio.errors.exceptions import ConflictException
from papilio.core import resources
from shop.modules.catalog.brands.domain.dtos import BrandCreate, BrandUpdate
from shop.modules.catalog.brands.domain.entities import BrandModel
from shop.modules.catalog.brands.infra.repository import BrandRepository


class BrandService(IDChecks[BrandModel]):
    entity = "Brand"

    def __init__(self, repo: BrandRepository) -> None:
        self.repo = repo

    @transactional
    async def create(self, data: BrandCreate) -> BrandModel:
        if await self.repo.get_by_slug(data.slug):
            raise ConflictException(
                message=f"brand with slug {data.slug} already exists",
                message_code=resources.CONFILICT_ERROR.format("brand"),
                unique_dict={"slug": data.slug},
            )
        return await self.repo.create(BrandModel(**data.to_row(exclude_unset=False)))

    @transactional
    async def update(self, id: int, data: BrandUpdate) -> BrandModel:
        row = self._check_not_empty_dict(data.to_row())
        brand = await self.repo.update_by_id(id, row)
        return self._check_for_id_existence(id, brand)

    async def get_by_id(self, id: int) -> BrandModel:
        return self._check_for_id_existence(id, await self.repo.get_by_id(id))

    async def remove(self, id: int) -> BrandModel:
        record = await self.repo.remove_by_id(id)
        return self._check_for_id_existence(id, record)
```

Guards on `Checks` / `IDChecks`:

| Guard | Raises when |
|---|---|
| `_check_for_id_existence(id, obj)` | `obj` is `None` → `NotFoundException` (404), message uses the explicit entity label |
| `_check_for_existence(identifier, value, obj)` | same, for a non-id lookup key |
| `_check_not_empty_dict(d)` / `_check_not_empty_list(ls)` | empty input → `ValidationException` (400) |
| `_check_batch_data(input_ids, founded_objs)` | returns a `BatchResultType` splitting found items from per-index `ValidationException`s; raises only if **nothing** was found — this is how partial-success batch endpoints are built |

### 6. The public contract — `interfaces.py`

Other modules may only ever see this.

```python
from typing import Protocol

from shop.modules.catalog.brands.domain.dtos import BrandCreate, BrandUpdate
from shop.modules.catalog.brands.domain.entities import BrandModel


class IBrandService(Protocol):
    async def create(self, data: BrandCreate) -> BrandModel: ...
    async def update(self, id: int, data: BrandUpdate) -> BrandModel: ...
    async def get_by_id(self, id: int) -> BrandModel: ...
    async def remove(self, id: int) -> BrandModel: ...
```

### 7. Wiring — `providers.py`

```python
from dishka import Provider, Scope, provide

from shop.modules.catalog.brands.app.services import BrandService
from shop.modules.catalog.brands.infra.repository import BrandRepository
from shop.modules.catalog.brands.interfaces import IBrandService


class BrandProvider(Provider):
    scope = Scope.REQUEST

    brand_repo = provide(BrandRepository)
    brand_service = provide(BrandService, provides=IBrandService)
```

`provide(BrandService, provides=IBrandService)` binds the implementation to the
`Protocol`. Callers depend on `IBrandService`; only this line knows the concrete
class. `BrandRepository`'s `PGUnitOfWork` argument is resolved by `PGProvider`
— you never construct it.

**This file is the entire registration.** No import into a central module, no list
to append to.

### 8. The endpoint — `routers/admin.py`

```python
from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Depends

from papilio.types.aliases import IdType
from shop.modules.catalog.brands.domain.dtos import BrandCreate
from shop.modules.catalog.brands.routers.schemas import BrandOut
from shop.modules.catalog.brands.interfaces import IBrandService
from papilio.api.dependencies.auth import require_access
from shop.auth import current_principal
from papilio.api.responses.envelope import APIResponse

router = APIRouter(
    prefix="/brands",
    tags=["Brands"],
    route_class=DishkaRoute,
    dependencies=[Depends(require_access(current_principal, "brands"))],
)

BrandResponse = APIResponse[BrandOut, None]


@router.post("", response_model=BrandResponse)
async def create_brand(
    data: BrandCreate,
    service: FromDishka[IBrandService],
) -> BrandResponse:
    brand = await service.create(data)
    return APIResponse.from_data(BrandOut.from_obj(brand))


@router.get("/{id}", response_model=BrandResponse)
async def get_brand(
    id: IdType,
    service: FromDishka[IBrandService],
) -> BrandResponse:
    brand = await service.get_by_id(id)
    return APIResponse.from_data(BrandOut.from_obj(brand))
```

Two things make this work: **`route_class=DishkaRoute`** (required for
`FromDishka[...]` in handlers) and the fact that a module-level `router` in
`routers/*.py` is all the bootstrapper needs.

### 9. Migrate and run

Create `main.py` in your application with `app = create_app()` as shown above.

```bash
alembic revision --autogenerate -m "add brands"
alembic upgrade head
uvicorn main:app --reload
```

`POST /brands` is live. At no point did you edit a file outside
`papilio/modules/catalog/brands/`.

---

## Dependency injection

dishka is the spine. Two scopes matter:

- **`Scope.APP`** — created once per process (connection pools, clients).
- **`Scope.REQUEST`** — created per HTTP request.

`CoreProvider` supplies settings. Select `PasswordProvider(salt)` for password hashing. Infrastructure providers
are explicit: `PGProvider(settings.db)`, `ESProvider(settings.es)`,
`RedisProvider(settings.redis)` and `HTTPProvider(settings.http)` live under
`papilio.providers`. The `db` module provides typed providers for all six
backends, not only PG. Custom application providers remain ordinary Dishka
providers. See [ready providers](docs/guide/providers.md) for the catalog, import
migration, multiple database components and explicit startup hooks.
After registering them, these types are available:

| Inject this | Scope | What you get |
|---|---|---|
| `Settings` | APP | The parsed `config.yml` |
| `DBConnection[PGUnitOfWork]` | APP | The explicitly selected PostgreSQL engine + session factory |
| `PGUnitOfWork` | **REQUEST** | An open PostgreSQL session; operations own commit/rollback |
| `ESClient` | APP | Async Elasticsearch client |
| `RedisClient` | APP | Pooled async Redis client |

**The transaction boundary is an application operation.** Dishka opens a
backend-specific UoW when it is first resolved and closes it at scope exit. Scope exit
never commits. SQLAlchemy discards any outstanding transaction when the session
closes. Repositories execute SQL through `uow.execute()`; they do not own the transaction.

Use `@transactional` on a writing application method. It requires an open UoW,
commits before returning, and rolls back on an exception or cancellation before
commit. Nested decorated calls join the outer operation; only its owner commits.
A failed nested operation marks the outer transaction rollback-only even if its
exception is caught. Do not manually commit/rollback inside this boundary.
Use `unit.savepoint()` to isolate a SQL failure and catch it outside the
savepoint scope. A decorated operation cannot start inside a savepoint.
Concurrent operations need separate UoWs; a child task cannot
borrow an inherited application transaction.

```python
from papilio.infra.db.tools.decorators import transactional
from papilio.infra.db.transaction import transaction

@transactional
async def rename_product(repo, product_id, title):
    return await repo.update_by_id(product_id, {"title": title})

# Outside Dishka, open a session and use an explicit operation boundary:
async with database.uow() as unit:
    async with unit.transaction():
        await unit.execute(statement)
```

The UoW tools are explicit:

| Tool | Behavior |
|---|---|
| `open()` / `close()` | Own the session lifetime; also used by `async with` |
| `transaction()` | Commit on success, roll back on failure; select this UoW explicitly |
| `commit()` / `rollback()` | Manually manage a transaction boundary |
| `flush()` | Send pending ORM changes without committing |
| `refresh(instance, attributes=...)` | Explicitly reload an object or chosen fields |
| `savepoint()` | SQLAlchemy nested transaction; entering flushes pending ORM changes |
| `is_open` / `in_transaction` | Inspect session lifetime / active SQL transaction state |
| `now()` | Read the database timestamp |
| `execute(stmt, params, ...)` | Return the buffered SQLAlchemy `Result`, preserving its row types |
| `stream(stmt, params, ...)` | Return a raw `AsyncResult`; the caller closes the cursor |
| `session` | Access SQLAlchemy directly, including ORM `add` / `add_all` |

`open()` replaces the old session-opening `begin()` method, with no deprecated
alias. Closing permanently closes that session; reopening a UoW creates a new
one. Repositories from an expired scope cannot silently reuse its session.
Cancellation during close is propagated after session cleanup finishes,
including when the caller is cancelled repeatedly.
When several databases are open, use `unit.transaction()` or
`transaction(unit)` to choose the boundary explicitly. Each repository uses
the UoW injected into it; selecting a transaction does not redirect repositories.

The UoW has no message callbacks, version allocation or broker operations.
HTTP error handlers only format errors; they never resolve a database session
or perform rollback. This also covers errors translated into HTTP responses:
uncommitted work is discarded at session close.

A sub-section of settings can be re-provided as its own type, so a service can
depend on exactly what it needs:

```python
class StorageProvider(Provider):
    scope = Scope.REQUEST

    @provide
    def storage_config(self, settings: Settings) -> StorageConfig:
        return settings.storage

    media_repository = provide(MediaRepository)
    media_service = provide(MediaService, provides=IMediaService)
```

The web application owns this container. Other processes own their own resource
lifetimes and dependency wiring.

---

## The data layer

### Model bases

In `papilio.infra.db.schema.entity` — all pure, none of them a table:

| Base | Adds |
|---|---|
| `Base` | `to_row()`, `to_dict()`, `to_json()`, `patch()`, `from_obj()`, `from_objs()`, … |
| `BaseModel` | nothing — the plain entity base |
| `IdentifiedEntity` | `id` |
| `TimestampEntity` | `created_at`, `updated_at` (DB-managed) |
| `PersistenceEntity` | all of the above — the usual choice |

`BaseTable`, in `papilio.infra.db.table`, is what turns one into a
table, and it is the only base that carries a `__tablename__`.

### Explicit repositories

Choose both the database and the entity shape. Declare the table directly;
there is no repository factory, table discovery or runtime generic inspection.

```python
from papilio.infra.db.repositories.backends.postgresql import (
    PGPersistenceRepository,
)
from shop.modules.catalog.products.domain.entities import ProductEntity
from shop.modules.catalog.products.infra.tables import ProductTable


class ProductRepository(PGPersistenceRepository[ProductEntity]):
    table = ProductTable
```

Each database provides four entity repository shapes and a reader.
Replace the `PG` class prefix with `MySQL`,
`MariaDB`, `SQLite`, `MSSQL` or `Oracle` and import from its corresponding file
under `papilio.infra.db.repositories.backends`.

| Shape | Example | Methods |
|---|---|---|
| Reader | `PGReader` | Typed UoW for custom joins, aggregates and reports; no bound table |
| Base | `PGRepository[T]` | Explicit-column SQL builders; create/upsert/bulk writes; `get_one`, `get_all`, `get_all_stream`, `exists`, `count`, `get_page`, conditional `update` and `remove` |
| ID | `PGIdentifiedRepository[T]` | Base methods plus `get_by_id`, `get_by_ids`, `get_paged`, `update_by_id`, `update_by_ids`, `update_row_by_id`, `remove_by_id`, `remove_by_ids` |
| Timestamp | `PGTimestampRepository[T]` | Base methods plus `get_stream_range`, `get_paged_range` and `gt`, `ge`, `lt`, `le` stream/page variants |
| ID + timestamp | `PGPersistenceRepository[T]` | Combines the ID and timestamp methods |

Reusable database tools live together, separate from session and transaction ownership:

```text
db/
├── connection.py
├── uow.py
├── transaction.py       # transaction scope and ownership
├── schema/
│   ├── entity.py        # SQLModel entity definitions
│   └── fields.py        # SQL field declarations
├── tools/
│   ├── read.py          # scalar/model pagination and streaming
│   └── decorators.py    # @transactional
├── dialects/            # backend behavior, SQL types and database-specific tools
└── repositories/
```

Import `transactional` from `papilio.infra.db.tools.decorators`, reading helpers
from `papilio.infra.db.tools.read`. Database-specific helpers stay in
`dialects`: PostgreSQL fields, `reset_schema` and `truncate_tables` are in
`papilio.infra.db.dialects.postgresql`.

Repositories are separated into declarations and executable tools:

```text
repositories/
├── base.py             # implemented common reads and paging
├── contracts/
│   ├── base.py         # common abstract obligations and reader contract
│   ├── postgresql.py   # PostgreSQL contracts for all four shapes
│   └── ...             # one contract module per database
└── backends/
    ├── postgresql.py   # native PostgreSQL statements and execution
    └── ...             # one implementation module per database
```

Each implementation inherits its database's abstract contract. Incomplete
implementations cannot be instantiated. `contracts/base.py` declares only
shared operations; database contracts specify their native write results and
supported tools. For example, MySQL/MariaDB ID updates return `int`, while
PostgreSQL ID updates return models. Oracle/MSSQL contracts expose no upsert.
All six databases have Base, Identified, Timestamp and Persistence contracts.
Insert, update and delete operations belong to backend contracts, including their result
types and protected builders. The common contract requires no mutations.

Database families inherit the executable classes in `repositories/base.py`:
`Repository`, `IdentifiedRepository`, `TimestampRepository` and
`PersistenceRepository` share reads, paging and timestamp filters.
Persistence ordering uses both `created_at` and `id`. `Reader` shares only the
execution context. Native writes stay in `backends`; there are no common
upsert methods or protected upsert stubs. PostgreSQL retains its additional
filtered query methods and override hooks. Backend constructors take
backend-specific UoWs: `PGRepository` takes `PGUnitOfWork`,
`MySQLRepository` takes `MySQLUnitOfWork`, and likewise for the other backends.
A single `DBConnection[U]` takes `uow_factory` and creates that UoW type.
There is no repository
`validate()` or custom binding registry. Static type checking rejects the wrong
UoW argument; Dishka rejects a missing typed dependency when building the
container. A DSN is configuration data, so its correctness is checked by the
database driver when connecting.

Application providers use native Dishka registration:

```python
from dishka import Provider, Scope, provide
from papilio.infra.db.repositories.contracts.postgresql import (
    PGPersistenceRepositoryContract,
)

class CatalogProvider(Provider):
    products = provide(
        ProductRepository,
        provides=PGPersistenceRepositoryContract[ProductEntity],
        scope=Scope.REQUEST,
    )
```

`PGProvider` configures its connection explicitly:

```python
connection = DBConnection(
    dsn=settings.db.dsn,
    pool_size=settings.db.pool_size,
    max_overflow=settings.db.max_overflow,
    pool_timeout=settings.db.pool_timeout,
    pool_recycle=settings.db.pool_recycle,
    uow_factory=PGUnitOfWork,
)
# Inferred type: DBConnection[PGUnitOfWork]
# connection.uow() returns PGUnitOfWork.
```

For another backend, pass its UoW class as the factory and register it in the
application's ordinary Dishka provider. There are no per-database connection
classes or automatic backend selection. A custom provider opens the unit directly:

```python
@provide(scope=Scope.REQUEST)
async def uow(
    self, connection: DBConnection[PGUnitOfWork]
) -> AsyncIterator[PGUnitOfWork]:
    async with connection.uow() as unit:
        yield unit
```

For several connections of the same type, register their connection, UoW and
repositories in matching Dishka components. The factory is chosen explicitly
at configuration time; no backend discovery occurs in repository operations.

The example modules and scaffold explicitly choose PostgreSQL. Changing the
DSN does not change their repository or dependency types.

```python
# database is a DBConnection[PGUnitOfWork].
async with database.uow() as uow:
    repo = ProductRepository(uow)
    async with uow.transaction():
        product = await repo.create(ProductEntity(name="Example"))
        product = await repo.update_by_id(product.id, {"name": "Updated"})
```

Writes never commit implicitly. MySQL `create` uses ORM `add`,
`flush` and `refresh`; native returning implementations use SQLAlchemy DML with
`RETURNING` or the database equivalent. MySQL/MariaDB update methods execute
only UPDATE and return the affected-row count. PostgreSQL, SQLite, Oracle and
MSSQL return rows from the write statement.
Update methods never issue a SELECT; callers read explicitly when needed.
Bulk updates join a typed input relation: PostgreSQL and MSSQL use VALUES,
SQLite uses a VALUES CTE, and MySQL/MariaDB use a UNION ALL derived table.
Oracle uses a correlated multi-column assignment from a UNION ALL input
relation, retaining native RETURNING without requiring UPDATE FROM.
Each backend exposes `_values_grid(rows, *, columns, name="incoming")` for
custom queries. PostgreSQL takes its existing sequence of SQL columns; the
other backends take an explicit input-name-to-column mapping. No builder
discovers fields or executes SQL.

MySQL provides `bulk_insert(data, *, insert_columns) -> int` for a native
batch INSERT without loading or refreshing ORM objects. `insert_columns` maps
input field names to SQL columns, just as for `bulk_upsert`; every selected
field must be supplied in every row. The result is the driver's affected-row
count (zero for empty input). Failed inserts raise; the caller owns rollback.
`_bulk_insert_stmt(rows, *, insert_columns)` exposes the same native SQL builder.
MySQL no longer exposes `bulk_create`: migrate batch calls to `bulk_insert`
with explicit insertion columns and consume a count. If a caller needs saved
models, it must issue its own read. The other five backend contracts retain
`bulk_create(data) -> Sequence[T]` through their native returning statements.

```python
columns = ProductTable.__table__.c
count = await repo.bulk_insert(
    products,
    insert_columns={"name": columns.name, "price": columns.price},
)
```

Delete results are backend-owned too. MySQL `remove_by_id(s)` returns the
driver's affected-row count. PostgreSQL, SQLite, MariaDB, Oracle and MSSQL use
native DELETE RETURNING/OUTPUT: `remove_by_id` returns `T | None`, and
`remove_by_ids` returns `Sequence[T]` with the deleted rows. Missing rows return
`None` or an empty sequence; batch output order is not tied to input order.
No deletion path adds a SELECT or commits. These are deleted-row values, not
records that remain in the database. MariaDB UPDATE still returns a count;
its DELETE RETURNING support does not imply UPDATE RETURNING support.

`update_by_id(s)` accepts a field mapping. An omitted field stays untouched;
explicit `None` follows the column's SQLAlchemy type semantics. Callers supply
a nonempty change mapping without primary-key changes. `update_row_by_id`
accepts a partial entity; its `id` argument identifies the target row.
`bulk_update` accepts a nonempty batch with distinct IDs, at least one change field, and the
values for every explicitly selected update field. SQLite, MySQL, MariaDB,
Oracle and MSSQL take `update_columns={"field_name": column}`. PostgreSQL
accepts raw row mappings and its own explicit match/update columns. Callers
validate their inputs before calling the repository; it performs no batch validation or fallback reads.
Returned rows from bulk writes are not guaranteed to match input order;
use their IDs. Timestamp
ranges use `created_at`, inclusive endpoints, and UTC datetimes. Persistence
pages use `(created_at, id)` ordering; timestamp-only repositories order by
`created_at` and applications can override `_time_query` to break ties with
their own key.

### PostgreSQL tools and prepared operations

PostgreSQL builders live on `PGRepository[T: BaseEntity]` and have no
ID convention. They accept row mappings and explicit SQLAlchemy columns
(`Table.__table__.c`), rather than deriving columns from an entity or the first
row. All four builders perform no I/O and leave RETURNING and execution
options to the caller:

| Builder | Explicit inputs | Result |
|---|---|---|
| `_values_grid(rows, *, columns, name="incoming")` | Ordered columns and their SQL types | `Values`, usable in joins and CTEs |
| `_upsert_stmt(row, *, conflict_columns, update_columns, changes=None)` | Conflict keys, fields copied from `excluded`, optional column-to-expression assignments | PostgreSQL `Insert` |
| `_bulk_upsert_stmt(rows, *, insert_columns, conflict_columns, update_columns, changes=None)` | Exact insertion columns and native conflict/update expressions | PostgreSQL `Insert` |
| `_bulk_update_stmt(rows, *, key_columns, update_columns)` | Match keys (including composite keys) and fields copied from the grid | `Update` |

Upsert input mappings use model/data field names. `insert_columns` maps each
input field name to its SQLAlchemy column. PostgreSQL VALUES and bulk-update
row mappings use the supplied column keys. Batches must be nonempty; the caller supplies
valid conflict/match keys and the required row values. Batch update keys must
be unique and disjoint from update columns. An upsert needs at least one update
column or explicit change expression. Builders do not validate application
input, discover fields, exclude `id`, or synthesize fallback updates.

```python
# Inside a custom repository; rows are mappings, not model instances.
columns = ProductTable.__table__.c
stmt = self._bulk_upsert_stmt(
    rows,
    insert_columns={"code": columns.code, "name": columns.name, "price": columns.price},
    conflict_columns=[columns.code],
    update_columns=[columns.name, columns.price],
    changes={columns.version: columns.version + 1},
)
stmt = stmt.returning(columns.id, columns.version)
result = await self.uow.execute(stmt)
return result.all()
```

For ready operations, `upsert(data, ...)` accepts one entity and
`bulk_upsert(items, ...)` accepts a sequence. Both require `conflict_columns`
and `update_columns` and return the model(s) from native RETURNING.
`bulk_upsert` additionally requires an `insert_columns` field-to-column mapping.
Every item must explicitly
supply every selected insertion column; use explicit `None` for SQL NULL where
the column allows it. A missing selected value raises `KeyError` before SQL
execution. Extra fields outside `insert_columns` are deliberately excluded.
For different insertion shapes, the caller submits separate batches. Column
selection never depends on the first item or assumes matching SQL/model names. Single upsert uses `_upsert_stmt`
and bulk upsert uses `_bulk_upsert_stmt`; neither routes through the other.
PostgreSQL `bulk_update(rows, *, key_columns, update_columns)` accepts mappings,
returns updated models, and works without an `id` column. Custom repository
methods choose their columns; services need not know SQLAlchemy tables.

`get_one(*conditions)` raises if several records match. `get_all(*conditions)`,
`exists(*conditions)` and `count(*conditions)` accept SQLAlchemy expressions.
`get_page(order_by=..., limit=..., offset=..., where=...)` requires explicit
ordering. `get_all_stream(batch_size, where=...)` streams filtered models.
`update(where, changes)` returns written models; `remove(where)` returns a
sequence of deleted models. Both require an explicit predicate and execute only a
write statement. ID repositories add convenience operations with fixed ID
predicates; timestamp repositories add their time-range operations.

Repository reads follow normal ORM identity-map behavior and preserve pending
model changes. Query helpers preserve the caller's execution options. For an
explicit refresh, build a select with
`.execution_options(populate_existing=True)` and execute it with the session;
this deliberately replaces the loaded state, including unflushed changes.
Public returning writes populate models from their own write results.
This also replaces unflushed changes on those returned models, just like an
explicit refresh. UPDATE and DELETE disable automatic session synchronization;
they do not issue a SELECT to synchronize other loaded objects.
Count-returning writes do not reload existing ORM objects; call
`await uow.refresh(record)` explicitly when you need their database state.

Every backend's protected `_bulk_update_stmt` returns an `Update` without
RETURNING or execution options. Custom methods choose their own result columns
and session policy. Public `bulk_update` applies the backend's result and
synchronization policy after building the statement, including when a subclass
replaces the builder.

### Other backends and optional upsert

Native upsert tools live on the database repository itself, so all four
entity shapes can use them without an `id` convention. PostgreSQL and SQLite
use `ON CONFLICT`; MySQL and MariaDB use `ON DUPLICATE KEY UPDATE`. Oracle and
MSSQL expose no upsert methods in this API. The shared base contract and
readers do not require or provide upsert.

```python
columns = ProductTable.__table__.c

# SQLite: the caller chooses the conflict target and copied columns.
product = await repo.upsert(
    data,
    conflict_columns=[columns.code],
    update_columns=[columns.name],
)
products = await repo.bulk_upsert(
    items,
    insert_columns={"code": columns.code, "name": columns.name},
    conflict_columns=[columns.code],
    update_columns=[columns.name],
)

# MySQL / MariaDB: conflicts use the database's unique indexes.
result = await repo.upsert(data, update_columns=[columns.name])
results = await repo.bulk_upsert(
    items,
    insert_columns={"code": columns.code, "name": columns.name},
    update_columns=[columns.name],
)
```

Each supported backend supplies independent `_upsert_stmt(row, ...)` and
`_bulk_upsert_stmt(rows, *, insert_columns, ...)` builders. Both return the
native dialect's `Insert` without executing, adding RETURNING, or selecting
execution options. Subclasses can extend the statement before execution.
SQLite and MariaDB public upserts return models from the native write result.
MySQL returns the affected-row count, which is not the number of input items;
read records explicitly when needed. All supported backends accept optional
`changes={column: expression}`; these explicit assignments override copied
update columns. Upsert does not infer `Column.onupdate` values; supply those
explicitly. No primary-key fields are implicitly selected or excluded.

Constraint errors remain SQLAlchemy exceptions. Translate them at the
application boundary if an HTTP/domain error is required; repositories do not
parse driver errors on every write.

### Queries without a table repository

Each database has its own reader: `PGReader`,
`MySQLReader`, `MariaDBReader`, `SQLiteReader`,
`OracleReader`, and `MSSQLReader`. Each implements its own
reader contract and takes the matching UoW. These readers can query several
tables. Each contract provides a typed UoW; it requires no `table`,
entity model or predefined query methods. A reader defines its own methods,
constructs its joins/CTEs/aggregates, and maps the full result into its context
or report type.

```python
from sqlalchemy import func, select
from sqlmodel import col
from papilio.infra.db.repositories.backends.postgresql import (
    PGReader,
)

class CatalogReader(PGReader):
    async def counts_by_category(self) -> dict[str, int]:
        stmt = (
            select(CategoryTable.name, func.count(ProductTable.id))
            .join(ProductTable, col(ProductTable.category_id) == CategoryTable.id)
            .group_by(CategoryTable.name)
        )
        result = await self.uow.execute(stmt)
        return {name: count for name, count in result}
```

Register the reader with Dishka's ordinary `provide(CatalogReader)`; its
constructor receives `PGUnitOfWork`. Choose `result.mappings()` for
named report fields, iterate full rows for joined columns/entities, or use
`result.scalars()` when the query deliberately selects a single value/model.
The base does not collapse results to their first column. `uow.execute()` and
`uow.stream()` forward parameters, execution options and bind arguments to
SQLAlchemy. They do not map results, refresh objects or commit. Result
consumption and conversion belong to the reader or repository.

Standalone `fetch_page(uow, stmt, ...)` and `stream(uow, stmt, ...)`
remain optional helpers for **single-value/model** queries. They are not
requirements of the reader contract. Streaming closes the result when the
generator is closed; use `aclosing` when stopping early.

---

## Responses and errors

Every endpoint returns the same envelope, `APIResponse[Data, Meta]`:

```json
{
  "success": true,
  "message_code": null,
  "data": { "id": 1, "name": "Acme" },
  "meta": { "pager": { "total_items": 57, "total_pages": 3, "has_prev": false, "has_next": true } },
  "error": null,
  "errors": null
}
```

Declare it once per router and reuse:

```python
BrandResponse      = APIResponse[BrandOut, None]      # single or list, no meta
PagedBrandResponse = APIResponse[BrandOut, BaseMeta]  # with pager / filters
```

`data` accepts one item *or* a sequence — the same generic covers both. Helpers:

- `APIResponse.from_data(data, message_code=None, errors=None)` — the success path
  (pass `errors=` for a partial-success batch result).
- `APIResponse.from_external_error(exc)`, `.from_pydantic_error(exc)`,
  `.get_server_error()` — used by the handlers.

Paged responses:

```python
paged = await service.get_paged(page, per_page)
return APIResponse(
    success=True,
    data=BrandOut.from_objs(paged.items),
    meta=BaseMeta(pager=PagerMeta.from_total(page, per_page, paged.total_items)),
)
```

### Errors are raised, never returned

Throw a typed exception from anywhere in the stack; the registered handlers
serialise it into the same envelope with the right status code. Handlers dump with
`exclude_defaults=True`, so an error body carries no `data: null` noise.

| Exception | Status | Carries |
|---|---|---|
| `ValidationException` | 400 | `loc`, `input`, `ctx`, nested child errors |
| `UnAuthorizedException` | 401 | — |
| `ForbiddenException` | 403 | `user_id` |
| `NotFoundException` | 404 | `entity`, `identifier`, `identifier_value` |
| `ConflictException` | 409 | `unique_dict` |
| `TooManyRequestsException` | 429 | `limit`, `remaining`, `retry_after` |

**Every** error leaves in this envelope — there is no second shape for a client to
handle. FastAPI's own `RequestValidationError` is remapped to a 422 (dumped in JSON
mode, so a rejected `Decimal` or date can't break serialisation); Starlette's own
404 and 405 — an unmatched path and a wrong method, which never reach a router —
get the codes `route_not_found` and `method_not_allowed` instead of a bare
`{"detail": ...}`, keeping their headers (a 405 without `Allow` is not really a
405); and any unhandled `Exception` is logged and returned as a generic 500, so
internals never leak.

`message_code` is a stable, machine-readable string that clients switch on. Global
codes live in [papilio/core/resources.py](papilio/core/resources.py); each module ships its
own `resources.py` for module-specific codes.

Every log line inside a request is stamped with a request id (taken from an inbound
`X-Request-ID` or generated), and the same id comes back on the response header —
so a 500 in your logs maps to the exact client call.

---

## Authentication and scopes

Authentication is explicitly selected. `papilio.api.dependencies.auth.bearer`
accepts an application-owned async authenticator and preserves its identity type.
`papilio.tools.auth.JWTAuth` is an optional access-token implementation;
`require_access(principal_dependency, scope)` is an optional scope policy.
No JWT/crypto configuration or identity model is required to create an app.
See the [security guide](docs/guide/security.md) and [tool boundaries](docs/guide/tools.md).

---

## Rate limiting

Reusable limiting lives in `papilio.tools.rate_limit`; HTTP adapters are separate.
Select `MemoryRateProvider()` with `papilio[rate-limit]` for per-process counters,
or `RedisRateProvider()` plus `RedisProvider(settings.redis)` with
`papilio[rate-limit-redis]` for shared counters. Config alone never registers a
provider or middleware. See [backend selection and contracts](docs/guide/tools.md).

**The floor.** `RateLimitMiddleware` charges `rate_limit.general` against every
request, on every route — including the ones nobody remembered to guard. Successful
responses carry the `RateLimit-Limit` / `RateLimit-Remaining` / `RateLimit-Reset`
headers, so a client can pace itself instead of discovering the wall.

**The named rule.** Anything expensive or brute-forceable declares its own budget and
asks for it by name, like any other dependency:

```python
from papilio.api.dependencies.rate_limit import by_ip, rate_limit

router = APIRouter(prefix="/auth", dependencies=[rate_limit("login")])   # whole router

@router.post("/token", dependencies=[rate_limit("login", (by_ip, by_username))])
async def login(...): ...                                               # …or one route
```

```yaml
rate_limit:
  enabled: true
  trusted_proxies: []          # peers whose X-Forwarded-For may be believed
  general:                     # the blanket rule
    limit: 120
    window_seconds: 60
  rules:                       # what rate_limit("<name>") looks up
    login:   { limit: 5,  window_seconds: 300 }
    refresh: { limit: 20, window_seconds: 60 }
```

A name with no rule in the config is simply **not limited** — a budget is switched
off by deleting it, not by editing a handler. `enabled: false` turns off both layers,
which is what a test suite wants.

**Every key part is charged.** A part maps a request to a bucket; `rate_limit` takes
a sequence of them and checks their selected backend's buckets concurrently. All checks finish
before a refusal is returned; this is not an all-or-nothing multi-bucket transaction:

```python
from papilio.api.dependencies.rate_limit import by_body_field, by_ip, rate_limit

login_rate_limit = rate_limit(
    "login", (by_ip, by_body_field("username")), closed_when_down=True
)
```

`by_body_field` covers the common case; write your own `KeyPart` for anything else
(an admin id, an API key, a tenant) — it is just `async (Request) -> str`.

`by_ip` alone lets a botnet spread one account's password guesses across a thousand
addresses; `by_username` alone lets one address walk a user list. Charging both meters
both, and the same helper composes any other dimension you need — an admin id, an API
key, a tenant.

**Which way to fail.** When the selected backend is unavailable, the limiter cannot check its counters. It fails **open** by default, because losing the cache should not take the API
down with it; a guard on something worth brute-forcing passes `closed_when_down=True`
and gets a refusal instead. Either way the outage is logged, not swallowed.

**Trust nothing you did not put there.** `by_ip` believes `X-Forwarded-For` only
when the immediate peer is listed in `trusted_proxies`. Leave that list empty when
nothing sits in front of the app: an unvetted header is a free way to buy a fresh
bucket per call. Behind a proxy, list the proxy — otherwise every caller in the world
shares one bucket, which is its own kind of outage.

A refusal is a `TooManyRequestsException` (429) carrying `limit`, `remaining` and
`retry_after`, in the same envelope as every other error, with `Retry-After` on the
response. The route guard raises it; the middleware, which sits outside the exception
handlers, assembles the identical body itself.

A route guard reads its budgets from **the container serving the request**, falling
back to `config.yml` when there is none (the middleware, which runs outside the
request scope). So a test app built on other settings is limited by *its* rules:
override `rate_limit` in a test provider and the guard follows, no patching. Limiters
are kept per Redis url in `_limiters` — clear it between tests that swap stores.

---

## Other infrastructure

**Redis** — inject `RedisClient` and use `.client` for the full async Redis API
(cache, locks, counters). Responses are decoded to `str`.

**Excel** — `ExcelReader` / `ExcelWriter` run openpyxl on a `ProcessPool`, because
parsing or generating a workbook is blocking CPU work that must never touch the event
loop. Rows are typed: declare an `ExcelRow` and columns map by field order.

```python
from papilio.infra.excel.row import ExcelRow, Row


class BrandRow(ExcelRow):
    name: str = Row(title="Name")
    slug: str = Row(title="Slug")


rows = await reader.read_rows("in.xlsx", BrandRow, start_row=2)      # validated by pydantic
await writer.write_rows("template.xlsx", "out.xlsx", rows, start_row=2, with_titles=True)
```

Reading stops at the first blank row; writing **fills a template** rather than
creating a workbook from scratch. Scaffold with `--excel` to get an
`infra/exporters.py` to house this per module.

**Logging** — `logging.format` picks the handler: `console` gives Rich tracebacks
while you develop, `json` emits one ECS-shaped line per record (`log.level`,
`service.name`, `error.stack_trace`, …) that an ES/Kibana pipeline ingests with no
mapping of its own. Either way the handler is installed on the **root** logger and
uvicorn and gunicorn are made to propagate into it, so a server request line
and a service line look alike and carry the same request id. Anything you attach with
`extra=` rides along as its own field:

```python
logger.info("charged %s", order.id, extra={"amount": order.total})
```

**Outbound HTTP** — `HTTPConnection` is one pooled `httpx.AsyncClient` for the whole
process, injected like any other infra. A gateway that builds its own client per
call re-runs DNS and the TLS handshake every time and leaks sockets on the way out,
which is how a third-party API that was fine in development starts timing out under
load. Both timeouts come from `http` in `config.yml` — `connect_timeout` separately
from the total, because a dead host holding a task before it is even talking is the
failure a total timeout notices far too late.

Scaffold with `--http` to get an `infra/gateways.py` with a `BaseGateway` subclass
ready to fill in:

```python
class RatesGateway(BaseGateway):
    __base_url__ = "https://api.example.com/v1"
    default_timeout = 5.0          # this API only; otherwise the config default

    async def rate(self, symbol: str) -> Rate:
        resp = await self.get("/rates", params={"symbol": symbol})
        resp.raise_for_status()
        return Rate(**resp.json())          # ← map before it crosses into app/
```

The base owns the base url (an absolute path is left alone, so an API that hands
back full `next` links keeps working), the header layering, and the timeout. It does
not own what a response *means*: map it into **your** domain types in the gateway, so
nothing above `infra/` ends up parsing a third party's JSON shape.

### Security helpers

[papilio/security/tokens.py](papilio/security/tokens.py) and
[papilio/security/crypto.py](papilio/security/crypto.py) are
**config-agnostic on purpose**: the caller passes the secret, the algorithm and the
expiry (wire them from `JWTConfig` / `CryptoConfig`). That keeps the security helpers free of a
`core.config` import and leaves both files unit-testable without a `config.yml`.

**`security.tokens`** — `create_access_token` / `create_refresh_token` / `decode_token`.
Every token carries `sub`, `iat`, `exp`, a `jti` and a `type`, and `decode_token`
takes an `expected_type`, so a refresh token cannot be replayed as an access token
against a route that forgot to look. Failures come out as the framework's
`UnAuthorizedException` with `token_expired` / `invalid_token` — a raw `PyJWTError`
never escapes, so an expired token answers 401 in the standard envelope rather than
500.

```python
token = create_access_token(str(admin.id), cfg.secret_key,
                            expires_minutes=cfg.access_token_expire_minutes,
                            extra_claims={"scopes": ["brands"]})
payload = decode_token(token, cfg.secret_key, expected_type=TokenType.ACCESS)
```

**`security.passwords` and `security.crypto`** — three jobs that are easy to
confuse and must not be, so they sit in two files rather than one:

| For | Use | Why that one |
|---|---|---|
| Passwords | `passwords.hash_password` / `verify_password`, or the injectable `PasswordHasher` | bcrypt, deliberately slow. The configured salt is applied as an HMAC **pepper**, which also pre-hashes the input and so sidesteps bcrypt's silent 72-byte truncation. `PasswordHasher` runs both on a worker thread, because "slow" on the event loop means *stopped* |
| Payloads you must read back | `crypto.encrypt` / `decrypt` | Fernet — authenticated, so a tampered ciphertext raises instead of decrypting to garbage. Any passphrase is stretched to a valid key |
| Opaque tokens (refresh tokens, API keys) | `crypto.hash_sha256` + `secure_compare` | Fast and deterministic, so it can be indexed; compared in constant time, so the check leaks no prefix |

A malformed stored hash is a non-match, never an exception — a legacy row cannot take
a login endpoint down.

**`IDEncryption`** ([papilio/tools/ids.py](papilio/tools/ids.py))
— exposes a serial primary key as a public id that doesn't announce your row count
(`/orders/42` says how many orders exist; `/orders/43` is a valid guess). It is a
modular multiplication, so it is reversible, stateless and needs no extra column:

```python
public = IDEncryption(mod=10_000_019, coff=387_241, offset=100_000)
public.encode(42)          # -> the id you put in the URL
public.try_decode(value)   # -> None for a malformed id, so the route can 404
```

Obfuscation, not authorisation — keep checking access on every read. It raises rather
than colliding once the table outgrows `mod`, so pick `mod` well above any row count
you expect to reach.

Both ends of the round trip are wired for you, so no handler has to remember either:

```python
ORDER_IDS = IDEncryption(mod=10_000_019, coff=387_241, offset=100_000)

class OrderOut(BaseIDOutput):          # outbound: the serialiser encodes `id`
    __encryption__ = ORDER_IDS

OrderID = Annotated[int, Depends(decode_path_id(ORDER_IDS, "Order"))]

@router.get("/{id}", response_model=APIResponse[OrderOut, None])
async def get(id: OrderID, service: FromDishka[IOrderService]):   # inbound: a row id
    ...
```

The route speaks public ids, the service speaks row ids, and a public id that does
not decode answers **404** — a forged id must be indistinguishable from one that
never existed, or the endpoint becomes an oracle for valid ids.

### Other utilities

`utils.dates` (timezone-aware UTC helpers plus Jalali conversion), `utils.persian`
(digit normalisation, rial/toman formatting), `utils.currency` (parses a quoted
amount — Persian digits, separators, float or `Decimal` — into a storable integer or
exact `Decimal`, and raises on anything that is not a number instead of quietly
returning `0`), `utils.strings`.

---

## Migrations

Alembic reads its metadata from the bootstrapper, so autogenerate sees every model
in every module with no imports to maintain:

```python
# migrations/env.py
get_bootstrapper().boot_sqlmodels()
target_metadata = SQLModel.metadata
```

```bash
alembic revision --autogenerate -m "add brands"   # after adding/changing a model
alembic upgrade head
alembic downgrade -1
```

The URL comes from `db.dsn` in `config.yml` unless it was set
programmatically (which is how the test suite points it at `test_dsn`). Leave the
placeholder `sqlalchemy.url` in `alembic.ini` alone — it is the sentinel that tells
`env.py` to fall back to the config file.

> The template ships with **no revisions** in `migrations/versions/`. Your first
> `--autogenerate` creates the baseline for whatever modules you have.

---

## Testing

`pytest.ini` sets `asyncio_mode = auto` — every `async def` test just runs, no
marker needed. Tests are auto-marked by folder: `tests/unit` → `unit`,
`tests/integration` → `integration`, `tests/api` → `api`.

```bash
pytest                      # everything
pytest -m unit              # fast, no external services
pytest -m integration       # against the real test database
pytest -m api               # drives the live ASGI app
```

The automatically loaded `papilio.testing.plugin` only marks test folders and
imports no optional infrastructure. Generated projects own an `anonymous`
HTTP-client fixture using a fresh app and its lifespan; install `papilio[test]`
for it. SQL uses `db.test_dsn` and rate limiting is disabled in that fixture.
The infrastructure harness is opt-in: install its dependencies
(`papilio[test,postgresql,es,redis,http,rate-limit,passwords,auth,crypto,csrf]`) and declare
`pytest_plugins = ["papilio.testing.fixtures"]` in your test conftest. The table
below describes that optional harness, not a base installation.

| Fixture | Gives you |
|---|---|
| `migrated_test_db` (session) | Drops and recreates the `public` schema of `db.test_dsn`, then runs `alembic upgrade head`. **Refuses to run against a database whose name lacks `test`.** Skips cleanly if the DB is unreachable — but a migration that fails *after* connecting is still reported as a failure. |
| `pg` | A `DBConnection[PGUnitOfWork]` on the test DSN |
| `uow` | An open `PGUnitOfWork`; use `uow.transaction()` for writes that must commit |
| `clean_db` | Empties every discovered table **and read-model index** between tests |
| `es` | An `ESClient` on the configured hosts |
| `dishka_container` / `dishka_request` | The **real** DI container, with module providers auto-discovered exactly as in production, but pointed at the test DB and explicit test resource configuration |
| `anonymous` (in `tests/api`) | An `AsyncClient` over the live app — bootstrapped routers, the framework's error handlers, the same container — with no credentials |

`test_settings_of()` and `core_provider_of()` are plain functions, not fixtures, so
a suite can build its own container from the same wiring in its application
conftest. Test settings turn
rate limiting **off**: a suite hits a route far faster than any real client, and a
test failing on a budget it never meant to exercise teaches nothing. A test *about*
limiting turns it back on for itself, since the guards read whichever settings their
own container holds.

Because the container discovers providers through the same bootstrapper, a new
module is testable through DI with **no edit to `conftest.py`** — and for the same
reason `clean_db` empties your new module's table and read-model index without being
told about either. That second half matters: a projected document outlives the row
it came from, so clearing only Postgres would leave a stale document to answer the
next test's search.

---

## Configuration reference

`config.yml` (written by `papilio new`, and gitignored — it holds your secrets).
The scaffold writes only the optional sections selected at project creation.

| Section | Keys |
|---|---|
| `app` | `modules` — packages the bootstrapper scans; `features` — enabled optional backends; `settings` — optional dotted path to an application `Settings` subclass |
| `fastapi` | `title`, `description`, `version` |
| `db` | `dsn`, `test_dsn`, `pool_size`, `max_overflow`, `pool_timeout`, `pool_recycle` |
| `redis` | `url`, `max_connections`, `socket_timeout`, `socket_connect_timeout`, `health_check_interval` |
| `rate_limit` | `enabled`, `trusted_proxies`, `general` (`limit`, `window_seconds`), `rules` (name → rule) |
| `es` | `hosts`, `username`, `password`, `api_key`, `verify_certs`, `ca_certs` |
| `http` | `max_connections`, `max_keepalive_connections`, `keepalive_expiry`, `timeout`, `connect_timeout`, `follow_redirects` |
| `jwt` | `algorithm`, `secret_key`, `access_token_expire_minutes`, `refresh_token_expire_minutes`, `api_secret` |
| `crypto` | `encryption_key`, `password_salt` |
| `storage` | `path`, `temp_dir`, `max_file_size`, `allowed_extensions` |
| `csrf` | `secret_key` |
| `logging` | `level`, `format` (`console` \| `json`), `service`, `index` |

---

## House rules

These are the conventions the framework and the codebase assume. Breaking them
usually means something silently stops being discovered.

1. **Absolute imports from `papilio...` and your own app package** — always.
2. **Every `__init__.py` is empty.** Import from the specific file, never from a
   package root. The bootstrapper relies on this for `routers/`.
3. **Modules talk through `I*Service` Protocols, never by importing each other.**
4. **A repository holds one statement per method.** All branching, all rules, all
   guards belong in the service.
5. **Input DTOs are `BaseDTO`** (pure pydantic). A repository accepts a model or a
   column dict — never a DTO.
6. **`domain/` imports nothing from `infra/`.** A model declares fields; the table
   that stores them is `infra/tables.py`'s business, and only a repository names
   it.
7. **What crosses a module boundary belongs to that module's domain** (its model,
   its `*Out`, its dataclass) — never another module's type.
8. **Raise typed exceptions; never return an error shape.** The handlers own
   serialisation.
9. **Mark writing application methods `@transactional`.** Its outermost call owns
   commit/rollback; request scope owns only the session lifetime.
10. **New feature = new module.** If you find yourself editing framework code under
   `papilio/core` or `papilio/api` to add a feature, stop and reconsider.
11. **Type parameters are declared inline** — `class Repo[T: BaseModel]`, not a
    module-level `TypeVar` plus `Generic[T]`. The bound belongs at the class that
    enforces it.
12. **The line is 79 columns.** `ruff check` and `ruff format` are the arbiters
    (config in `pyproject.toml`); the scaffolder's output already satisfies both.

---

## License

MIT.

Event router discovery only returns routers; the event consumer application
includes them before startup. Keep package
`__init__.py` files empty and declare routers in the leaf Python files.

## Database backends

Configure the async driver in `db.dsn`; select the matching repository class
explicitly. Install the relevant extras (`mysql`, `sqlite`, `mssql`, `oracle`).
The core connection supplies sessions and never chooses a repository.

| Backend | Write implementation | Upsert API |
|---|---|---|
| PostgreSQL | INSERT/UPDATE RETURNING; VALUES-based bulk update | ON CONFLICT, returns models |
| MySQL | ORM create; count-returning bulk_insert; derived-table bulk update | ON DUPLICATE KEY UPDATE, returns affected-row count |
| MariaDB 10.5+ | INSERT RETURNING; derived-table bulk update, returns count | Native upsert RETURNING |
| SQLite 3.35+ | INSERT/UPDATE RETURNING; VALUES CTE bulk update | ON CONFLICT, returns models |
| SQL Server | Native OUTPUT and VALUES-based bulk update | Not exposed |
| Oracle | Native RETURNING, executemany insert and correlated input-relation bulk update | Not exposed |

Portable field helpers remain available. `JSONField` uses JSONB on PostgreSQL,
native JSON where supported, and serialized text on Oracle. PostgreSQL-only
`JSONBField` and `ArrayField` are in `papilio.infra.db.dialects.postgresql`.

Repository tests exercise SQLite and the ORM flush/refresh path on SQLite.
Native SQL compilation tests cover the database families. Set
`FASTAMU_TEST_POSTGRESQL`, `FASTAMU_TEST_MYSQL`, `FASTAMU_TEST_MARIADB`,
`FASTAMU_TEST_ORACLE`, or `FASTAMU_TEST_MSSQL` to run the same behavioral suite
against actual servers. Compilation and SQLite tests do not establish live
compatibility with those servers.

The [database benchmark report](benchmarks/results/REPORT.md) records live
measurements on all six backends and includes reproduction scripts. Large
bulk updates still have measured limitations: Oracle timed out at 1,000 rows,
and SQL Server rejected statements exceeding its parameter budget. Successful
smaller batches do not establish a universal safe batch size; column count
also affects the number of parameters.

## Async files and CSV

The tools live in separate infrastructure packages. Text/binary reads and writes
use worker threads; CSV parsing and serialization also run there. No model-field
discovery, schema inference, header policy or automatic retries are involved.

```python
from papilio.infra.files.reader import FileReader
from papilio.infra.files.writer import FileWriter

reader, writer = FileReader(), FileWriter()
await writer.write_text("notes.txt", "Papilio\n", mode="x")
text = await reader.read_text("notes.txt")
async with reader.open_bytes("archive.bin") as stream:
    while chunk := await stream.read(64 * 1024):
        await consume(chunk)
```

`read_text`/`read_bytes` load the complete file. Use the open contexts to read or
write incrementally. Write modes are explicit: `w` replaces, `a` appends, `x`
requires a new file; binary modes are `wb`, `ab`, `xb`. Whole-file writes return
the number of characters or bytes written. Parent directories are caller-owned.

```python
from papilio.infra.csv.reader import CSVReader
from papilio.infra.csv.writer import CSVWriter

async with CSVWriter().open("report.csv", delimiter=";") as writer:
    await writer.write_row(["name", "description"])
    count = await writer.write_rows([
        ["Papilio", "first line\nsecond line"],
        ["Butterfly", 'quoted "text"'],
    ])

async with CSVReader().rows("report.csv", delimiter=";", batch_size=1000) as rows:
    async for row in rows:
        await consume(row)
```

CSV uses the standard parser with `newline=""`, so quoted multiline records,
quotes and CRLF work. The reader yields lists of strings and keeps one batch
in memory; the first row is ordinary data unless you choose to treat it as a
header. `write_row` returns characters written; `write_rows` returns record count
and consumes a synchronous iterable on the worker thread. Keep calls on one
open writer sequential. To write an asynchronous source, iterate it yourself and
await each row or batch. Context exit closes resources even on failure or early
exit; file and parse errors propagate.

Excel jobs use spawn-based process workers with serializable job arguments.
Call `await reader.close()` and `await writer.close()` on shutdown. Excel column
names and titles are prepared at model definition time, not discovered per row.
