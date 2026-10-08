"""Validate and invoke tools in independent native Dishka scopes."""

import inspect
import sys
from collections.abc import Mapping, Sequence
from contextvars import ContextVar
from typing import Any, get_type_hints

from anyio import CancelScope
from dishka import AsyncContainer, Scope
from dishka.integrations.base import wrap_injection
from pydantic import ConfigDict, TypeAdapter
from pydantic.experimental.arguments_schema import generate_arguments_schema
from pydantic.json_schema import GenerateJsonSchema
from pydantic_core import SchemaValidator

from papilio.function_tools.registry import (
    FunctionTool,
    FunctionTools,
    ToolEffect,
)


class BoundFunctionTool:
    """Own a tool's native input/output contracts and invocation scope."""

    def __init__(
        self, definition: FunctionTool, container: AsyncContainer
    ) -> None:
        self.definition = definition
        self.container = container
        self.current: ContextVar[AsyncContainer] = ContextVar(
            "function_tool_container"
        )
        parameters = inspect.signature(definition.function).parameters
        if any(
            parameter.kind
            in {
                inspect.Parameter.POSITIONAL_ONLY,
                inspect.Parameter.VAR_POSITIONAL,
            }
            for parameter in parameters.values()
        ):
            raise TypeError("Function tools require named arguments")
        self.function = wrap_injection(
            func=definition.function,
            container_getter=lambda args, kwargs: self.current.get(),
            is_async=True,
        )
        self.signature = inspect.signature(self.function)
        self.injected_names = (
            parameters.keys() - self.signature.parameters.keys()
        )
        if any(
            parameter.annotation is inspect.Parameter.empty
            for parameter in self.signature.parameters.values()
        ):
            raise TypeError("Function tool inputs require type annotations")
        hints = get_type_hints(definition.function, include_extras=True)
        if "return" not in hints:
            raise TypeError("Function tool outputs require a type annotation")
        schema = generate_arguments_schema(
            self.function,
            schema_type="arguments",
            config=ConfigDict(extra="forbid"),
        )
        self.validator = SchemaValidator(schema)
        self.input_schema = GenerateJsonSchema().generate(schema)
        self.output_type = hints["return"]
        self.output = TypeAdapter(self.output_type)
        self.output_schema = self.output.json_schema(mode="serialization")

    async def invoke(
        self, arguments: Mapping[str, Any], *, context: Any
    ) -> Any:
        if self.injected_names.intersection(arguments):
            raise ValueError(
                "Injected function tool arguments cannot be supplied"
            )
        args, kwargs = self.validator.validate_python(dict(arguments))
        bound = self.signature.bind(*args, **kwargs)
        bound.apply_defaults()
        definition = self.definition
        permitted = await definition.authorize(context, bound.arguments)
        if permitted is not True:
            raise PermissionError("Function tool access denied")
        if definition.effect == ToolEffect.WRITE:
            approval = definition.approve
            if approval is None:
                raise PermissionError("Function tool approval required")
            approved = await approval(context, bound.arguments)
            if approved is not True:
                raise PermissionError("Function tool approval required")
        scope = self.container(
            scope=Scope.REQUEST, context={type(context): context}
        )
        child = await scope.__aenter__()
        token = self.current.set(child)
        try:
            try:
                result = await self.function(*args, **kwargs)
                validated = self.output.validate_python(result)
            finally:
                with CancelScope(shield=True):
                    await scope.__aexit__(*sys.exc_info())
        finally:
            self.current.reset(token)
        return validated


class FunctionToolExecutor:
    """Compose tool definitions without owning the application container."""

    def __init__(
        self,
        collections: Sequence[FunctionTools],
        container: AsyncContainer,
    ) -> None:
        definitions = [
            tool
            for collection in dict.fromkeys(collections)
            for tool in collection.tools
        ]
        if len({tool.name for tool in definitions}) != len(definitions):
            raise ValueError("Duplicate function tool name")
        if len({tool.key for tool in definitions}) != len(definitions):
            raise ValueError("Duplicate function tool key")
        self._tools = {
            tool.name: BoundFunctionTool(tool, container)
            for tool in definitions
        }

    @property
    def tools(self) -> tuple[BoundFunctionTool, ...]:
        return tuple(self._tools.values())

    async def invoke(
        self, name: str, arguments: Mapping[str, Any], *, context: Any
    ) -> Any:
        result = await self._tools[name].invoke(arguments, context=context)
        return result
