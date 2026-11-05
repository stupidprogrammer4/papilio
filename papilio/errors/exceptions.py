from __future__ import annotations

from http import HTTPStatus
from typing import Any, Sequence

from papilio.core import resources

from .base import APPException
from .outputs import (
    ConflictErrorOut,
    ForbiddenErrorOut,
    NotFoundErrorOut,
    TooManyRequestsErrorOut,
    UnAuthorizedErrorOut,
    ValidationErrorOut,
)


class ValidationException(APPException[ValidationErrorOut]):
    def __init__(
        self,
        message: str,
        message_code: str,
        loc: list[Any],
        input: Any | None = None,
        ctx: dict[str, Any] | None = None,
        childs: Sequence[ValidationException] | None = None,
    ) -> None:
        super().__init__(message, message_code, HTTPStatus.BAD_REQUEST)
        self.input = input
        self.loc = loc
        self.ctx = ctx
        self.childs = childs

    def as_schema(self) -> ValidationErrorOut:
        return ValidationErrorOut(
            message=self.message,
            message_code=self.message_code,
            loc=self.loc,
            input=self.input,
            ctx=self.ctx,
            errors=[child.as_schema() for child in self.childs]
            if self.childs
            else None,
        )

    @classmethod
    def get_invalid_input(
        cls, childs: Sequence[ValidationException]
    ) -> ValidationException:
        return cls(
            message="Check your input data",
            message_code=resources.INVALID_INPUT,
            loc=[],
            childs=childs,
        )


class UnAuthorizedException(APPException[UnAuthorizedErrorOut]):
    def __init__(self, message: str, message_code: str) -> None:
        super().__init__(message, message_code, HTTPStatus.UNAUTHORIZED)

    def as_schema(self) -> UnAuthorizedErrorOut:
        return UnAuthorizedErrorOut(
            message=self.message, message_code=self.message_code
        )


class ForbiddenException(APPException[ForbiddenErrorOut]):
    def __init__(
        self,
        message: str,
        message_code: str,
        user_id: int | None = None,
    ) -> None:
        super().__init__(message, message_code, HTTPStatus.FORBIDDEN)
        self.user_id = user_id

    def as_schema(self) -> ForbiddenErrorOut:
        return ForbiddenErrorOut(
            message=self.message,
            message_code=self.message_code,
            user_id=self.user_id,
        )


class NotFoundException(APPException[NotFoundErrorOut]):
    def __init__(
        self,
        message: str,
        message_code: str,
        entity: str,
        identifier: str,
        identifier_value: Any,
        *,
        identifier_is_public: bool = False,
    ) -> None:
        super().__init__(message, message_code, HTTPStatus.NOT_FOUND)
        self.entity = entity
        self.identifier = identifier
        self.identifier_value = identifier_value
        self.identifier_is_public = identifier_is_public

    def as_schema(self) -> NotFoundErrorOut:
        # identifier_value is Any (int ids, str slugs, …); the wire schema is
        # str.
        return NotFoundErrorOut(
            message_code=self.message_code,
            message=self.message,
            entity=self.entity,
            identifier=self.identifier,
            identifier_value=str(self.identifier_value),
        )


class ConflictException(APPException[ConflictErrorOut]):
    def __init__(
        self, message: str, message_code: str, unique_dict: dict[str, Any]
    ) -> None:
        super().__init__(message, message_code, HTTPStatus.CONFLICT)
        self.unique_dict = unique_dict

    def as_schema(self) -> ConflictErrorOut:
        return ConflictErrorOut(
            message=self.message,
            message_code=self.message_code,
            unique_dict=self.unique_dict,
        )


class TooManyRequestsException(APPException[TooManyRequestsErrorOut]):
    """A rate-limited call, answered with the budget the caller just spent.

    The body carries the same three numbers the ``RateLimit-*`` headers do, so
    a client that only reads JSON still learns how long to wait.
    """

    def __init__(
        self,
        message: str,
        message_code: str,
        limit: int,
        remaining: int,
        retry_after: int,
    ) -> None:
        super().__init__(message, message_code, HTTPStatus.TOO_MANY_REQUESTS)
        self.limit = limit
        self.remaining = remaining
        self.retry_after = retry_after

    def as_schema(self) -> TooManyRequestsErrorOut:
        return TooManyRequestsErrorOut(
            message=self.message,
            message_code=self.message_code,
            limit=self.limit,
            remaining=self.remaining,
            retry_after=self.retry_after,
        )
