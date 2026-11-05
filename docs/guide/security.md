# Authentication, identifiers and rate limits

Papilio supplies security primitives and HTTP dependencies. Your application owns user lookup, credential verification, permission policy, token rotation and revocation. A generated CRUD module does not automatically require authentication.

## Hash passwords asynchronously

Install `papilio[passwords]`. Construct `PasswordHasher` directly or explicitly register `PasswordProvider(salt)` for application-scoped injection:

```python
from papilio.security.passwords import PasswordHasher

hasher = PasswordHasher(pepper="application-secret")
hashed = await hasher.hash("example-password")
assert await hasher.verify("example-password", hashed)
```

Hashing runs in a worker thread. Store the hash, keep the pepper stable and private, and inject the shared hasher into your identity service. The synchronous primitives also exist, but should not be called directly in an async request path for expensive hashing.

## Issue and decode a token

Install `papilio[auth]` (and `crypto` for asymmetric algorithms that require it). After authenticating a user and explicitly supplying JWT configuration:

```python
from papilio.security.tokens import (
    TokenType,
    create_access_token,
    decode_token,
)

assert settings.jwt is not None
token = create_access_token(
    subject="42",
    secret_key=settings.jwt.secret_key,
    expires_minutes=settings.jwt.access_token_expire_minutes,
    algorithm=settings.jwt.algorithm,
    extra_claims={"scopes": ["products:read"]},
)
payload = decode_token(
    token,
    settings.jwt.secret_key,
    algorithm=settings.jwt.algorithm,
    expected_type=TokenType.ACCESS,
)
```

Extra claims can overwrite existing claims in the current helper; do not pass an untrusted request dictionary. `decode_token` checks the requested token type only when `expected_type` is provided. Supply `audience` when your application uses an audience claim.

## Select an authenticator

```python
from fastapi import APIRouter, Depends
from papilio.api.dependencies.auth import bearer, require_access
from papilio.tools.auth import JWTAuth

assert settings.jwt is not None
jwt_auth = JWTAuth(settings.jwt.secret_key, algorithm=settings.jwt.algorithm)
current = bearer(jwt_auth.authenticate)
router = APIRouter()

@router.get("/me")
async def me(principal=Depends(current)):
    return {"subject": principal.subject}

@router.get("/protected", dependencies=[Depends(require_access(current, "products:read"))])
async def protected():
    return {"allowed": True}
```

`bearer` also accepts your own async authenticator returning your own identity
object; it does not import JWT or resolve Settings. The optional JWT implementation
requires a valid access token, nonempty subject and string-list scopes. A refresh
token is rejected. The optional scope guard retains the existing 401 response
for a missing scope; applications can supply a different authorization policy.

## Public identifiers

`IDEncryption` and `BaseIDOutput` provide encoded public IDs. `decode_path_id(encryption, entity, param="id")` builds a dependency for path decoding; decoding failure becomes 404. Encoding an ID does not authorize access to its entity. Refer to the [security signatures](../reference/utilities.md) for key construction and encryption methods before enabling this feature.

For JSON-configured resources, annotate an input with
`Annotated[IdType, IDInput("access/users")]` or an output with
`Annotated[int, IDOutput("access/users")]`, importing the metadata from
`papilio.types.ids`. This works with arbitrary foreign ID field names, list
items and optional references. Keep trusted app DTOs and persistence IDs plain.
Input metadata uses normal Pydantic 422 validation, including paths and queries.

`papilio.core.encryption.get_id_encryption_settings()` reads the private
`encryption.json` once; `PAPILIO_ENCRYPTION` selects a different file. Each JSON
resource entry contains `mod`, `coff`, optional `offset` and optional `entity`.
Pass `.entities` as `create_app(..., id_encryptions=...)` to encode configured
entities' native ID-not-found errors without exposing internal identifiers.
Missing configuration and incompatible parameters fail explicitly. Keep
coefficients stable; changing them invalidates previously issued public IDs.

## Configure rate limiting

Select memory or Redis as described in [ready tools](tools.md#choose-a-rate-limit-backend), and explicitly register the chosen provider. For HTTP limiting, configure:

```yaml
rate_limit:
  enabled: true
  trusted_proxies: []
  general:
    limit: 120
    window_seconds: 60
  rules:
    login:
      limit: 5
      window_seconds: 300
```

Attach a named dependency to a route:

```python
from papilio.api.dependencies.rate_limit import by_body_field, by_ip, rate_limit

login_limit = rate_limit(
    "login",
    parts=(by_ip, by_body_field("email")),
    closed_when_down=True,
)


@router.post("/login", dependencies=[login_limit])
async def login():
    return {"next": "Implement credential verification here"}
```

Each key part charges an **independent** bucket; this is not a combined IP-and-email key. A missing named rule or disabled rate-limit config skips that guard. The general limiter fails open when its backend is unavailable. Named guards can fail closed with `closed_when_down=True`.

Only explicitly trusted proxy peers allow `X-Forwarded-For` to affect the client key. Explicitly add `RateLimitMiddleware` to enable the general limiter; settings alone do not add it. Named route dependencies remain separate.

[Authentication and rate-limit signatures](../reference/api.md)
