from typing import Annotated

from pydantic import Field

from papilio.types.constants import (
    INT32_MAX,
    INT32_MIN,
    INT64_MAX,
    INT64_MIN,
    UINT32_MAX,
    UINT64_MAX,
)

IdType = Annotated[int, Field(gt=0, le=INT64_MAX)]
# 1-based pagination params — shared by every paged query/router.
PageType = Annotated[int, Field(ge=1)]
PerPageType = Annotated[int, Field(ge=1, le=100)]
ListIdType = Annotated[
    list[Annotated[int, Field(gt=0, le=INT64_MAX)]],
    Field(min_length=1, max_length=100),
]
StrType = Annotated[str, Field(min_length=2, max_length=35)]
MStrType = Annotated[str, Field(min_length=2, max_length=55)]
LStrType = Annotated[str, Field(min_length=2, max_length=100)]
ValueType = Annotated[str, Field(min_length=1, max_length=255)]
ContentType = Annotated[str, Field()]
UIntType = Annotated[int, Field(ge=0, le=UINT32_MAX)]
IntType = Annotated[int, Field(ge=INT32_MIN, le=INT32_MAX)]
BigIntType = Annotated[int, Field(ge=INT64_MIN, le=INT64_MAX)]
UBigIntType = Annotated[int, Field(ge=0, le=UINT64_MAX)]
RateType = Annotated[float, Field(ge=0, le=1)]
RialType = Annotated[int, Field(ge=0, le=INT64_MAX)]
SlugType = Annotated[
    str, Field(min_length=2, max_length=55, pattern=r"^[a-z0-9-]+$")
]
# A variable-like machine name: lowercase letters and underscores only, <= 35.
ColorType = Annotated[
    str, Field(pattern=r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
]
KeyType = Annotated[str, Field(pattern=r"^[a-z_]+$", max_length=35)]
# Iranian mobile number, normalized to the 11-digit 09xxxxxxxxx form.
MobileType = Annotated[str, Field(pattern=r"^09\d{9}$")]
# A login password — length-bounded only; hashing happens in the service layer.
PasswordType = Annotated[str, Field(min_length=8, max_length=72)]
# A 5-digit one-time login code.
OtpCodeType = Annotated[str, Field(pattern=r"^\d{5}$")]
# Iranian national id — exactly 10 digits.
NationalIdType = Annotated[str, Field(pattern=r"^\d{10}$")]
MediaUrlType = Annotated[
    str, Field(pattern=r"^(https?://|/)\S+$", max_length=255)
]
