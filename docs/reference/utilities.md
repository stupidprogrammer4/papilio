# Security and utilities

Generated from this checkout. Code blocks show signatures; `...` replaces implementation bodies. These are reference declarations, not standalone executable modules.

Single-underscore methods are protected extension tools. For inherited methods, follow the base class reference. Localized string values use Unicode escapes.

## `papilio.security.crypto`

### `encrypt`

```python
def encrypt(plaintext: str, key: str) -> str:
    ...
```

### `decrypt`

```python
def decrypt(token: str, key: str) -> str:
    ...
```

### `hash_sha256`

```python
def hash_sha256(value: str) -> str:
    ...
```

### `secure_compare`

```python
def secure_compare(a: str, b: str) -> bool:
    ...
```

## `papilio.tools.ids`

### `IDEncryption`

```python
class IDEncryption:
    def __init__(self, mod: int, coff: int, offset: int=0) -> None:
        ...

    @property
    def capacity(self) -> int:
        ...

    @property
    def offset(self) -> int:
        ...

    @property
    def bounds(self) -> tuple[int, int]:
        ...

    def encode(self, id: int) -> int:
        ...

    def decode(self, public_id: int) -> int:
        ...

    def try_decode(self, public_id: int) -> int | None:
        ...

    @staticmethod
    def is_valid_coff(mod: int, coff: int) -> bool:
        ...
```

## `papilio.security.passwords`

```python
DEFAULT_BCRYPT_ROUNDS = 12
```

### `hash_password`

```python
def hash_password(password: str, *, pepper: str='', rounds: int=DEFAULT_BCRYPT_ROUNDS) -> str:
    ...
```

### `verify_password`

```python
def verify_password(password: str, hashed: str, *, pepper: str='') -> bool:
    ...
```

### `PasswordHasher`

```python
class PasswordHasher:
    def __init__(self, pepper: str) -> None:
        ...

    async def hash(self, password: str) -> str:
        ...

    async def verify(self, password: str, hashed: str) -> bool:
        ...
```

## `papilio.security.tokens`

```python
DEFAULT_ALGORITHM = 'HS256'
```

### `TokenType`

```python
class TokenType(StrEnum):
    ACCESS = 'access'
    REFRESH = 'refresh'
```

### `create_token`

```python
def create_token(subject: str, secret_key: str, *, expires_in: timedelta, token_type: TokenType=TokenType.ACCESS, algorithm: str=DEFAULT_ALGORITHM, extra_claims: Mapping[str, Any] | None=None) -> str:
    ...
```

### `create_access_token`

```python
def create_access_token(subject: str, secret_key: str, *, expires_minutes: int, algorithm: str=DEFAULT_ALGORITHM, extra_claims: Mapping[str, Any] | None=None) -> str:
    ...
```

### `create_refresh_token`

```python
def create_refresh_token(subject: str, secret_key: str, *, expires_minutes: int, algorithm: str=DEFAULT_ALGORITHM, extra_claims: Mapping[str, Any] | None=None) -> str:
    ...
```

### `decode_token`

```python
def decode_token(token: str, secret_key: str, *, algorithm: str=DEFAULT_ALGORITHM, expected_type: TokenType | None=None, audience: str | None=None) -> dict[str, Any]:
    ...
```

## `papilio.types.aliases`

```python
IdType = Annotated[int, Field(gt=0, le=INT64_MAX)]
```

```python
PageType = Annotated[int, Field(ge=1)]
```

```python
PerPageType = Annotated[int, Field(ge=1, le=100)]
```

```python
ListIdType = Annotated[list[Annotated[int, Field(gt=0, le=INT64_MAX)]], Field(min_length=1, max_length=100)]
```

```python
StrType = Annotated[str, Field(min_length=2, max_length=35)]
```

```python
MStrType = Annotated[str, Field(min_length=2, max_length=55)]
```

```python
LStrType = Annotated[str, Field(min_length=2, max_length=100)]
```

```python
ValueType = Annotated[str, Field(min_length=1, max_length=255)]
```

```python
ContentType = Annotated[str, Field()]
```

```python
UIntType = Annotated[int, Field(ge=0, le=UINT32_MAX)]
```

```python
IntType = Annotated[int, Field(ge=INT32_MIN, le=INT32_MAX)]
```

```python
BigIntType = Annotated[int, Field(ge=INT64_MIN, le=INT64_MAX)]
```

```python
UBigIntType = Annotated[int, Field(ge=0, le=UINT64_MAX)]
```

```python
RateType = Annotated[float, Field(ge=0, le=1)]
```

```python
RialType = Annotated[int, Field(ge=0, le=INT64_MAX)]
```

```python
SlugType = Annotated[
    str, Field(min_length=2, max_length=55, pattern=r"^[a-z0-9-]+$")
]
```

Slugs contain 2–55 ASCII lowercase letters, digits or hyphens. The entire string must match; no trimming or case conversion is performed. Leading, trailing and repeated hyphens remain allowed.

```python
ColorType = Annotated[str, Field(pattern='^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$')]
```

```python
KeyType = Annotated[str, Field(pattern='^[a-z_]+$', max_length=35)]
```

```python
MobileType = Annotated[str, Field(pattern='^09\\d{9}$')]
```

```python
PasswordType = Annotated[str, Field(min_length=8, max_length=72)]
```

```python
OtpCodeType = Annotated[str, Field(pattern='^\\d{5}$')]
```

```python
NationalIdType = Annotated[str, Field(pattern='^\\d{10}$')]
```

```python
MediaUrlType = Annotated[str, Field(pattern='^(https?://|/)\\S+$', max_length=255)]
```

## `papilio.types.constants`

```python
INT32_MAX = 2147483647
```

```python
INT32_MIN = -2147483648
```

```python
INT64_MAX = 9223372036854775807
```

```python
INT64_MIN = -9223372036854775808
```

```python
UINT32_MAX = 4294967295
```

```python
UINT64_MAX = 18446744073709551615
```

## `papilio.types.enums`

### `FaStrEnum`

```python
class FaStrEnum(StrEnum):
    fa: str
```

### `SortOrder`

```python
class SortOrder(FaStrEnum):
    ASC = ('asc', '\u0635\u0639\u0648\u062f\u06cc')
    DESC = ('desc', '\u0646\u0632\u0648\u0644\u06cc')
```

### `MediaType`

```python
class MediaType(StrEnum):
    EXCEL = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    PDF = 'application/pdf'
    JSON = 'application/json'
    XML = 'application/xml'
    HTML = 'text/html'
    TEXT = 'text/plain'
    CSV = 'text/csv'
    OCTET_STREAM = 'application/octet-stream'
    ZIP = 'application/zip'
    GZIP = 'application/gzip'
    PNG = 'image/png'
    JPEG = 'image/jpeg'
    JPG = 'image/jpg'
    GIF = 'image/gif'
    SVG = 'image/svg+xml'
    TIFF = 'image/tiff'
    BMP = 'image/bmp'
    WEBP = 'image/webp'
    AVIF = 'image/avif'
    MP4 = 'video/mp4'
    MOV = 'video/quicktime'
    MKV = 'video/x-matroska'
    FLV = 'video/x-flv'
    AVI = 'video/x-msvideo'
    WMV = 'video/x-ms-wmv'
    MP3 = 'audio/mpeg'
    WAV = 'audio/wav'
    OGG = 'audio/ogg'
    AAC = 'audio/aac'
    FLAC = 'audio/flac'
    WMA = 'audio/x-ms-wma'
    M4A = 'audio/x-m4a'
    AMR = 'audio/amr'
    MPG = 'audio/mpeg'
```

### `HTTPMethod`

```python
class HTTPMethod(StrEnum):
    POST = 'POST'
    PUT = 'PUT'
    GET = 'GET'
    DELETE = 'DELETE'
    PATCH = 'PATCH'
```

### `FilterType`

```python
class FilterType(StrEnum):
    SLIDER = 'slider'
    CHECKBOX = 'checkbox'
    RADIO = 'radio'
```

## `papilio.utils.currency`

```python
QuotedAmount = str | int | float | Decimal
```

```python
MAZANE_FACTOR = Decimal('4.331802')
```

```python
TROY_OUNCE_GRAMS = Decimal('31.1034768')
```

### `round_rial`

```python
def round_rial(amount: int | float | Decimal) -> int:
    ...
```

### `to_mazane`

```python
def to_mazane(per_gram: int) -> int:
    ...
```

### `from_mazane`

```python
def from_mazane(mazane: int) -> int:
    ...
```

### `from_usd`

```python
def from_usd(amount: Decimal, usd_rial: int) -> int:
    ...
```

### `with_bubble`

```python
def with_bubble(intrinsic: int, bubble: int) -> int:
    ...
```

### `to_rial`

```python
def to_rial(value: QuotedAmount) -> int:
    ...
```

Normalizes Persian digits and supported separators, then parses strings with `Decimal` to preserve their precision before rounding to whole rial. Exact halfway values round to the even integer (`"2.5"` → `2`, `"3.5"` → `4`). Native `int`, `float` and `Decimal` inputs retain their existing rounding behavior; precision already lost in a supplied float cannot be recovered. Malformed strings raise `ValueError`.

### `to_decimal`

```python
def to_decimal(value: QuotedAmount) -> Decimal:
    ...
```

### `to_cent`

```python
def to_cent(value: QuotedAmount) -> int:
    ...
```

## `papilio.utils.dates`

```python
DEFAULT_JALALI_FORMAT = '%Y/%m/%d %H:%M:%S'
```

### `utc_now`

```python
def utc_now() -> datetime:
    ...
```

### `ensure_aware`

```python
def ensure_aware(dt: datetime, tz: str | tzinfo=UTC) -> datetime:
    ...
```

### `convert_tz`

```python
def convert_tz(dt: datetime, tz: str | tzinfo, *, assume: str | tzinfo=UTC) -> datetime:
    ...
```

### `to_utc`

```python
def to_utc(dt: datetime, *, assume: str | tzinfo=UTC) -> datetime:
    ...
```

### `from_db`

```python
def from_db(dt: datetime, tz: str | tzinfo) -> datetime:
    ...
```

### `to_db`

```python
def to_db(dt: datetime, *, assume: str | tzinfo) -> datetime:
    ...
```

### `to_jalali`

```python
def to_jalali(dt: datetime, tz: str | tzinfo | None=None) -> jdatetime.datetime:
    ...
```

### `from_jalali`

```python
def from_jalali(jdt: jdatetime.datetime, *, as_utc: bool=True) -> datetime:
    ...
```

### `format_jalali`

```python
def format_jalali(dt: datetime, fmt: str=DEFAULT_JALALI_FORMAT, tz: str | tzinfo | None=None) -> str:
    ...
```

### `parse_jalali`

```python
def parse_jalali(value: str, fmt: str=DEFAULT_JALALI_FORMAT, *, tz: str | tzinfo | None=None, as_utc: bool=True) -> datetime:
    ...
```

## `papilio.utils.persian`

```python
THOUSANDS_SEP = '\u060c'
```

```python
DECIMAL_SEP = '\u066b'
```

```python
RIAL_UNIT = '\u0631\u06cc\u0627\u0644'
```

```python
TOMAN_UNIT = '\u062a\u0648\u0645\u0627\u0646'
```

```python
DEFAULT_DATETIME_FORMAT = '%A %d %B %Y - %H:%M'
```

```python
DEFAULT_DATE_FORMAT = '%d %B %Y'
```

```python
Number = int | float | Decimal
```

### `to_persian_digits`

```python
def to_persian_digits(value: str | int) -> str:
    ...
```

### `to_english_digits`

```python
def to_english_digits(value: str) -> str:
    ...
```

### `normalize_persian`

```python
def normalize_persian(text: str) -> str:
    ...
```

### `format_number`

```python
def format_number(value: Number, *, persian_digits: bool=True) -> str:
    ...
```

### `format_rial`

```python
def format_rial(amount: Number, *, with_unit: bool=True, persian_digits: bool=True) -> str:
    ...
```

### `format_toman`

```python
def format_toman(rial_amount: int, *, with_unit: bool=True, persian_digits: bool=True) -> str:
    ...
```

### `format_jalali_datetime`

```python
def format_jalali_datetime(dt: datetime, tz: str | tzinfo, fmt: str=DEFAULT_DATETIME_FORMAT) -> str:
    ...
```

### `format_jalali_date`

```python
def format_jalali_date(dt: datetime, tz: str | tzinfo, fmt: str=DEFAULT_DATE_FORMAT) -> str:
    ...
```

## `papilio.utils.strings`

### `snake_case`

```python
def snake_case(name: str) -> str:
    ...
```

### `pluralize`

```python
def pluralize(word: str) -> str:
    ...
```
