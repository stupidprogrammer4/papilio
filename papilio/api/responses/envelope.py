from typing import Any, ClassVar, Optional, Sequence, Union

from fastapi.exceptions import RequestValidationError as PydanticError
from pydantic import BaseModel, SerializerFunctionWrapHandler, model_serializer

from papilio.core import resources
from papilio.errors.base import APPException
from papilio.errors.outputs import (
    BaseErrorOut,
    ValidationErrorOut,
    errors_types,
)

ErrorType = Union[*errors_types]


class APIResponse[TOut: BaseModel | None, TMeta: BaseModel | None](BaseModel):
    success: bool
    message_code: Optional[str] = None
    data: Optional[Union[TOut, Sequence[TOut]]] = None
    meta: Optional[TMeta] = None
    error: Optional[ErrorType] = None
    errors: Optional[Sequence[ErrorType]] = None

    _optional_envelope: ClassVar[tuple[str, ...]] = (
        "message_code",
        "data",
        "meta",
        "error",
        "errors",
    )

    @model_serializer(mode="wrap")
    def _omit_empty_envelope(
        self, handler: SerializerFunctionWrapHandler
    ) -> Any:
        written = handler(self)
        return {
            key: value
            for key, value in written.items()
            if key not in self._optional_envelope or value is not None
        }

    @classmethod
    def from_data(
        cls,
        data: Union[TOut, Sequence[TOut]],
        message_code: Optional[str] = None,
        errors: Optional[Sequence[APPException]] = None,
    ):
        error_schemas = [e.as_schema() for e in errors] if errors else None
        return cls(
            success=True,
            data=data,
            message_code=message_code,
            errors=error_schemas,
        )

    @classmethod
    def from_external_error(cls, error: APPException):
        return cls(success=False, error=error.as_schema())

    @classmethod
    def from_pydantic_error(cls, error: PydanticError):
        errors = []
        for e in error.errors():
            errors.append(
                ValidationErrorOut(
                    message=e["msg"],
                    message_code=e["type"],
                    loc=e["loc"][1:] if e["loc"] else [],
                    ctx=cls._readable_context(e.get("ctx")),
                    input=e.get("input"),
                )
            )

        return cls(success=False, errors=errors)

    @staticmethod
    def _readable_context(
        context: Optional[dict[str, Any]],
    ) -> Optional[dict[str, Any]]:
        readable: Optional[dict[str, Any]] = None
        if context:
            readable = {
                key: value
                if isinstance(value, (str, int, float, bool, type(None)))
                else str(value)
                for key, value in context.items()
            }
        return readable

    @classmethod
    def get_server_error(cls):
        return cls(
            success=False,
            error=BaseErrorOut(
                message="Internal server error",
                message_code=resources.SERVER_ERROR,
            ),
        )
