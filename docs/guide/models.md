# SQL models and fields

An entity defines stored data, a table maps it to SQL, a DTO validates input, and an output schema defines the public response. Keeping these roles separate prevents a new internal column from changing your API accidentally.

## Entity shapes

| Entity | Built-in fields | Matching repository shape |
| --- | --- | --- |
| `BaseEntity` | Conversion tools only | `BackendRepository` |
| `IdentifiedEntity` | `id` | `BackendIdentifiedRepository` |
| `TimestampEntity` | `created_at`, `updated_at` | `BackendTimestampRepository` |
| `PersistenceEntity` | ID and timestamps | `BackendPersistenceRepository` |

Replace `Backend` with `PostgreSQL`, `SQLite`, or the selected database name. `VersionEntity` separately provides `version_num`. Incrementing it and implementing optimistic concurrency are application responsibilities.

## Define an entity and table

```python
from papilio.infra.db.schema.fields import CharField, IntField, JSONField
from papilio.infra.db.schema.entity import IdentifiedEntity
from papilio.infra.db.table import BaseTable


class ProductModel(IdentifiedEntity):
    sku: str = CharField(40, unique=True)
    title: str = CharField(200, index=True)
    quantity: int = IntField(default=0)
    attributes: dict = JSONField(default_factory=dict)


class ProductTable(ProductModel, BaseTable, table=True):
    __tablename__ = "products"
```

You can set the table name explicitly; otherwise BaseTable applies its naming convention. Use SQLAlchemy constraints and indexes in `__table_args__` for composite or specialized definitions.

## Choose a field helper

| Data | Helper |
| --- | --- |
| Identifier | `IDField` |
| Integer | `SmallIntField`, `IntField`, `BigIntField` |
| Boolean | `BoolField` |
| Approximate / exact decimal | `FloatField` / `NumericField` |
| Bounded / unbounded text | `CharField` / `TextField` |
| Date / time of day / timestamp | `DateField` / `TimeField` / `TimestampField` |
| JSON document | `JSONField` |
| Enum | `EnumField` |
| Relationship key | `ForeignKeyField` |
| Computed column | `ComputedField` |

Pass options such as `nullable`, `unique`, `index`, `default`, `default_factory`, and `server_default` directly. `db_column` sets a different SQL column name. See the [field reference](../reference/models.md) for exact helper signatures and the lower-level escape hatch `sa_column_kwargs`.

Use `default_factory=list` or `dict` for independent mutable defaults. A Python default and SQL `server_default` have different jobs. `to_row()` includes explicitly supplied values by default; SQL/column defaults can supply omitted values.

## Backend-specific fields

PostgreSQL `JSONBField` and `ArrayField` live in `papilio.infra.db.dialects.postgresql`. Dialect tools express database-specific types and options; they are not automatically portable to SQLite or MySQL. Consult the [dialect reference](../reference/sql-tools.md) for array element types, index options and defaults.

## Serialization and partial updates

```python
product = ProductModel(sku="BOOK", title="Notebook", quantity=2)
row = product.to_row()
full = product.to_dict()
patch = ProductModel.patch(quantity=5)
changes = patch.to_changes()
assert changes == {"quantity": 5}
```

`patch()` deliberately creates an **unvalidated partial model**. Validate external input through a DTO first. `to_changes()` excludes the ID. An omitted field differs from an explicitly supplied `None`: the former is absent from the update, while the latter remains.

`from_dict`, `from_json` and `from_obj` validate their input. `carried` only decodes JSON. Database constraints remain necessary alongside input validation; concurrent requests can both pass an application-level precheck.
