# Changelog

## Unreleased

- Allow redis-py 8 alongside 7 so Redis extras can be installed with
  Papilio Tasks and taskiq-redis 1.2.3.

## 0.8.0

- Ship no application modules or predefined application scopes; CLI templates
  generate modules owned by the consuming application.
- Rename the distribution and import package to Papilio, with an application-owned
  FastAPI factory and separate API, schema, security and database modules.
- Remove task and projection runtime code from the web package. Infrastructure
  dependencies are optional extras with explicit provider wiring.
- Add CLI templates for CRUD, CQRS, context and plain modules, with optional
  HTTP gateways and exporter extension points.
- Add async file and CSV readers/writers, and use spawn workers with asynchronous
  cleanup for Excel operations.
- Add English learning guides, executable examples and backend API references.

## Earlier Fastamu development notes

The following unreleased notes describe the pre-split implementation. Task and
projection features described here are not part of the Papilio web package.


- Keep projection failures in Redis lists instead of a SQL table, one list per
  projection, and repair them by running their configured batch target rather
  than publishing it. Taking pops, so overlapping runs cannot receive the same
  record: reservation tokens, leases, correlation receipts and the migration step
  are all gone. Records hand back to the tail with one attempt spent, and
  `max_attempts` moves an exhausted record to a `:dead` list with a warning
  instead of retrying it forever. `max_pending` caps a list, `concurrency` bounds
  how many projections repair at once, and one unreachable queue no longer
  abandons the others.
- Let the bulk writer, not the framework, decide that a failed item is finished:
  `BulkItemResult.final` marks an operation that repeating cannot help, and
  `settled` is `succeeded or final`. No status code is interpreted, so an
  external-version conflict can be final while an `if_seq_no` conflict stays
  retryable. `succeeded` keeps its 2xx meaning.
- Split `messaging/projections` into `contracts` (the shapes an application
  implements) and `repair` (the optional failure capability, including its SQL
  store and table). Move pure settlement, receipt and orchestration logic out of
  the Taskiq layer; `Repair` now depends on a `RepairPublisher` protocol, and
  `tasks/projection` keeps only registration, publication, middleware and
  wiring. Taskiq middlewares live under `tasks/projection/middlewares/` and
  label names in `tasks/projection/labels.py`. An import test asserts the
  contract and repair packages load no SQLAlchemy, Taskiq or framework runtime.
- Add opt-in SQL projection failure storage, terminal-error middleware and a
  native scheduled repair task. Claim bounded records, group by source task name
  and publish application-selected batch tasks through the existing Register.
  Resolve only successful claimed records; newer failures and expired/reclaimed
  reservations survive old results. Support partial results and native retry
  without recording repair failures recursively. Schema migration is explicit.
  Repair scheduling uses LabelScheduleSource and can run without retry Redis.
- Add projection discovery through the bootstrapper and queue metadata on the
  projection classes. Keep the class-to-task `Register` and its protected
  Taskiq/Dishka task-construction methods in `tasks/projection/register.py`.
- Add an optional native RabbitMQ projection runtime, per-class queue routing,
  independent worker container and publication decorators using registered tasks.
  Decorators publish after function success without inspecting transactions;
  bulk task failures preserve their item results in `ProjectionBatchError`.
  Optional periodic repair and failure storage are configured independently.
- Add optional per-projection `RetryPolicy` with validated total attempts and
  fixed delay. Use native SmartRetry, ListRedisScheduleSource and an independent
  Taskiq scheduler; preserve immediate publication, task IDs and queue routing.
  No-policy classes explicitly disable retry. A small middleware translates
  delay labels without implementing a retry engine. Close the Redis source pool
  on shutdown and document native delivery/recovery limitations.
- Dispose the CoreProvider database pool when its application container closes.
- Add `AbstractConvertor` for reusable typed conversion.
- Remove the intermediate `SyncProjection`, `get_ids()` contract, publication
  decorator and no-argument task wrapper. Repair uses existing batch projections
  with caller-supplied IDs. Selection, grouping by source projection name and
  scheduling belong to a separate optional repair task.
- Add `AbstractProjection[TModel, TDocument].project(id: int)` with typed
  source lookup, conversion and destination-write hooks. The base runs those
  stages in order; application errors propagate without retry or registration.
- Add typed patch, delete, batch and fanout projection tools under messaging.
  Bulk operations return per-document results; patch batches keep target IDs
  attached to their models. Empty batches do no I/O and deletion needs no read.
- Remove the previous event/projection APIs and transports, outbox/inbox
  implementation, custom retry middleware, and their configuration, discovery,
  CLI and scaffold integration before rebuilding messaging in smaller steps.
- Keep SQL transactions, DB/ES repositories and Taskiq jobs/scheduling.
  Projection retry is opt-in; the removed retry API is not retained. Existing
  applications must stop using the removed APIs before adopting this checkout.
- Remove obsolete messaging tests while retaining SQL transaction, rollback,
  cancellation and scheduler/scaffold coverage. No database tables or broker
  queues are dropped by this source cleanup.

## 0.6.4

- Resolve a shared `Rollback` dependency before handled HTTP errors instead
  of repeating rollback calls in each handler. The dependency is not cached.
- Register the dependency in the runtime and shipped testing providers.

## 0.6.3

- Inject the request unit of work into handled HTTP error handlers with
  Dishka instead of looking up the container and catching missing factories.
- Dispatch global rate-limit refusals through the registered application
  error handler. Handled HTTP errors require a unit-of-work provider.

## 0.6.2

- Roll back the unit of work when Dishka sends an exception during scope
  cleanup, and always close the session after commit or rollback.
- Roll back handled application, validation, HTTP and CSRF errors before
  returning their HTTP responses. Await the error handler in rate limiting.
- Apply the same transaction lifecycle to the shipped testing provider.

## 0.6.1

- Import the projection registry at module level where it is used, and
  pass the broker to `ProjectionRegistry.build` instead of importing it
  inside the method.

## 0.6.0

- Remove `BaseService.commit()` and `fastamu.common.context`. A projection
  message carries an id and the worker reads the row back, so it is
  published inside the writing transaction and nothing has to happen after
  the commit.
- A projection whose source is not visible raises `ProjectionSourceMissing`
  instead of reporting success, so the delivery is retried once the write
  has committed.
- A delivery that never succeeds is logged and acknowledged rather than
  holding its queue, so one document left behind cannot stop the rest.

## 0.5.2

- Revert 0.5.1; the provider binds the unit of work, as in 0.5.0.
- Bind the unit of work the shipped `uow` test fixture opens, so a service
  that commits works under it.

## 0.5.1

- Bind the unit of work when it opens rather than in the provider, so a test
  fixture, a script and a seeder reach the same one a request does.
  Concurrent units of work stay apart because each task carries its own
  context.

## 0.5.0

- Remove `after_commit`. A caller commits and then publishes, in that order,
  instead of registering a coroutine for `commit` to drain.
- Bind the unit of work of the running scope to a context variable in
  `CoreProvider`; `BaseService.commit()` reads it back, and asking for one
  outside any scope raises.
- Add `FullSettings` for a project installed with every extra, so `es` and
  the three task sections need no None check.

## 0.4.1

- Add fan-out projections that accept one source ID, convert its related
  models into multiple documents, and write them together.

## 0.4.0

- Make task capabilities explicit through `app.features`; project scaffolding
  now emits the matching configuration sections and package extras from the
  same feature selection.
- Validate feature/configuration mismatches at startup, including the CQRS
  requirement for Elasticsearch.
- Let applications select a typed `Settings` subclass through `app.settings`,
  while keeping YAML loading and caching inside Fastamu.
- Add a reusable logging index setting.

## 0.3.3

- Discover projection classes directly from each module's
  `infra/projections.py`; CQRS scaffolding no longer creates import-only task
  modules.
- Add transport-aware event publishing with a configured RabbitMQ topic
  exchange or Redis channel.

## 0.3.2

- Add reusable query DTO aliases for list (`name[]`) and mapped-pair
  (`name{}`) parameters, including pair validation and grouping helpers.
- Add reusable sort and filter response metadata with localized sort orders.
- Add rial, mazane, exchange-rate and market-bubble conversion helpers.

## 0.3.1

- Preserve Python defaults, nullable values and database-generated values in
  field factories; string and enum server defaults accept bare literals.
- Preserve first-seen batch input order and report the original input and
  position for every missing item in linear time.
- Add read-free Elasticsearch patch and bulk-delete operations, and serialize
  full documents without dropping false or null values.
- Add optional JWT audience validation.
- Accept any Pydantic response payload and metadata, omit empty envelope fields
  and normalize validation context for JSON output.
- Run registered post-commit callbacks in `DBUnitOfWork` and discard them on
  rollback while retaining guaranteed session cleanup.

## 0.3.0

This release changes public import paths and configuration. Migrate consumers
before upgrading from 0.2.x; old paths are not compatibility aliases.

### Changes

- Split common models, schemas, security, types and projection contracts into
  dedicated packages. Schema responses use `outputs` modules.
- Replace `infra.postgres` with `infra.db`: shared repositories, connections and
  units of work, with SQL dialect adapters. Table names now split CamelCase before
  pluralizing the final word (`ProductVariantTable` -> `tbl_product_variants`).
- Separate optional events (FastStream), projections (Taskiq/RabbitMQ) and
  schedulers (Taskiq/Redis) under `fastamu.tasks`.
- Share one projection broker across domain queues. Each queue uses prefetch=1
  and a single active consumer. Multiple projection operations can share a queue.
  Failed deliveries retry in place with fresh Dishka scopes and a configured
  delay; an exhausted delivery pauses its queue until repair and worker restart.
- Add task discovery and CLI scaffolding for subscribers, publishers, schedulers
  and optional CQRS, plus the dedicated projection worker command.
- Replace the custom infra rate-limit wrapper/result classes with direct
  `throttled-py` objects in `fastamu.web.ratelimit`. Reuse the app's Redis pool.
  Independent HTTP quota checks run concurrently and finish before rejection.

### Consumer migration

- Change `postgresql` configuration to `db` and `PG*` repository/connection/UoW
  imports to the corresponding `DB*` classes in `fastamu.infra.db`.
- Update `common.bases` imports to `common.models`, `common.schemas`,
  `common.services` or `common.projections`; move security helpers to
  `common.security`, enums/constants/aliases to `common.types`.
- Move PostgreSQL-only `ArrayField` and `JSONBField` imports to
  `fastamu.infra.db.dialects.postgresql`. Use `JSONField` for portable JSON.
- Inspect generated Alembic changes for renamed multiword tables. Existing
  tables require an explicit rename migration, not drop-and-create.
- Configure only the task features needed under `tasks.events`,
  `tasks.projection`, and `tasks.schedulers`; omitted/null sections are disabled.
  Install matching extras: `fastamu[events,cqrs,scheduler]`.
- Replace old event/projection decorators with native FastStream routers and
  the new projection contracts. Publish projection work after the source commit.
- Import HTTP guards from `fastamu.web.ratelimit`. Custom FastAPI applications
  must add `RateLimitProvider()` to their Dishka container.

### Limits and validation

- Live repository checks cover PostgreSQL, MySQL and SQLite. MSSQL and Oracle
  receive SQL compilation checks, not live-server validation; their atomic
  upsert operation is explicitly unsupported. MariaDB has an adapter but has not
  been tested against a live server for this release.
- Projection ordering applies to delivery order within a queue, not database
  commit order across publishers. Delivery is at least once; handlers must be
  safe to retry. Source commits and message publication are not atomic.
- Sharing Redis with `throttled-py` currently uses one isolated private-backend
  assignment, covered by a compatibility test. Recheck it on dependency upgrades.
- The test suite includes real RabbitMQ ordering/retry checks, database CRUD,
  HTTP guard and rate-limit tests. Package build, lint and Pyright are checked
  before tagging. A dependency emits a Python generator `throw()` deprecation
  warning during Taskiq/Dishka retry tests.
