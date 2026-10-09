"""Function tools execute native typed services with application guards."""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from collections.abc import AsyncGenerator, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

import anyio
import pytest
from dishka import (
    FromDishka,
    Provider,
    Scope,
    from_context,
    make_async_container,
    provide,
)
from pydantic import BaseModel, ValidationError
from sqlalchemy import text

from papilio.core.config import DatabaseConfig
from papilio.function_tools.execution import FunctionToolExecutor
from papilio.function_tools.registry import FunctionTools, ToolEffect
from papilio.infra.db.connection import DBConnection
from papilio.infra.db.tools.decorators import transactional
from papilio.infra.db.uow import SQLiteUnitOfWork, UnitOfWork
from papilio.providers.db import SQLiteProvider


@dataclass
class Actor:
    id: int = 1
    allowed: bool = True
    approved_value: int | None = None


class Input(BaseModel):
    value: int


class Output(BaseModel):
    value: int
    actor_id: int


async def authorize(context: Actor, arguments: Mapping[str, Any]) -> bool:
    return context.allowed


async def approve(context: Actor, arguments: Mapping[str, Any]) -> bool:
    return context.approved_value == arguments["data"].value


@dataclass
class Calls:
    opened: list[SQLiteUnitOfWork] = field(default_factory=list)
    session_ids: list[int] = field(default_factory=list)
    waiting: int = 0
    both_started: asyncio.Event = field(default_factory=asyncio.Event)
    finalized: list[SQLiteUnitOfWork] = field(default_factory=list)
    started: asyncio.Event = field(default_factory=asyncio.Event)
    release: asyncio.Event = field(default_factory=asyncio.Event)


class Records:
    def __init__(self, unit: SQLiteUnitOfWork, calls: Calls) -> None:
        self.unit = unit
        self.calls = calls

    @transactional
    async def write(self, value: int, actor_id: int, fail: bool) -> Output:
        assert UnitOfWork.current() is self.unit
        await self.unit.execute(
            text("INSERT INTO records (value, actor_id) VALUES (:v, :a)"),
            {"v": value, "a": actor_id},
        )
        if fail:
            raise ValueError("business rejection")
        return Output(value=value, actor_id=actor_id)

    async def wait(self, value: int, actor_id: int) -> Output:
        await self.unit.execute(text("SELECT 1"))
        self.calls.started.set()
        self.calls.waiting += 1
        if self.calls.waiting == 2:
            self.calls.both_started.set()
        await self.calls.release.wait()
        assert UnitOfWork.current() is self.unit
        return Output(value=value, actor_id=actor_id)


class RecordsProvider(Provider):
    actor = from_context(provides=Actor, scope=Scope.REQUEST)

    def __init__(self) -> None:
        super().__init__()
        self.calls = Calls()

    @provide(scope=Scope.APP)
    def tracking(self) -> Calls:
        return self.calls

    @provide(scope=Scope.REQUEST)
    async def records(
        self, unit: SQLiteUnitOfWork, calls: Calls
    ) -> AsyncGenerator[Records]:
        calls.opened.append(unit)
        calls.session_ids.append(id(unit.session))
        try:
            yield Records(unit, calls)
        finally:
            await anyio.sleep(0)
            calls.finalized.append(unit)


@pytest.fixture
async def native(tmp_path):
    provider = RecordsProvider()
    config = DatabaseConfig(
        dsn=f"sqlite+aiosqlite:///{tmp_path / 'function-tools.sqlite'}",
        test_dsn="",
        pool_size=2,
        max_overflow=0,
        pool_timeout=5,
        pool_recycle=1800,
    )
    container = make_async_container(SQLiteProvider(config), provider)
    connection = await container.get(DBConnection[SQLiteUnitOfWork])
    async with connection.uow() as unit:
        async with unit.transaction():
            await unit.execute(
                text("CREATE TABLE records (value INTEGER, actor_id INTEGER)")
            )
    try:
        yield container, connection, provider.calls
    finally:
        await container.close()


def write_tools() -> FunctionTools:
    tools = FunctionTools()

    @tools.tool(
        key="records.write",
        name="write_record",
        title="Write record",
        description="Save one record after exact approval.",
        effect=ToolEffect.WRITE,
        authorize=authorize,
        approve=approve,
    )
    async def write(
        data: Input,
        records: FromDishka[Records],
        actor: FromDishka[Actor],
        fail: bool = False,
    ) -> Output:
        result = await records.write(data.value, actor.id, fail)
        return result

    return tools


def read_tools() -> FunctionTools:
    tools = FunctionTools()

    @tools.tool(
        key="records.read",
        name="read_record",
        title="Read record",
        description="Read in an independent native database scope.",
        effect=ToolEffect.READ,
        authorize=authorize,
        sequential=False,
    )
    async def read(
        data: Input, records: FromDishka[Records], actor: FromDishka[Actor]
    ) -> Output:
        result = await records.wait(data.value, actor.id)
        return result

    return tools


async def persisted(connection: DBConnection[SQLiteUnitOfWork]):
    async with connection.uow() as fresh:
        result = await fresh.execute(
            text("SELECT value, actor_id FROM records")
        )
        return result.all()


async def test_native_schema_exact_guards_and_committed_service(native):
    container, connection, calls = native
    executor = FunctionToolExecutor([write_tools()], container)
    tool = executor.tools[0]
    assert set(tool.input_schema["properties"]) == {"data", "fail"}
    assert set(tool.output_schema["properties"]) == {"value", "actor_id"}
    actor = Actor(id=7, approved_value=9)
    result = await executor.invoke(
        "write_record",
        {"data": {"value": "9", "ignored": True}},
        context=actor,
    )
    assert result == Output(value=9, actor_id=7)
    assert await persisted(connection) == [(9, 7)]
    assert len(calls.opened) == 1
    assert calls.finalized == calls.opened
    assert not calls.opened[0].is_open


@pytest.mark.parametrize(
    "arguments",
    [
        {"data": {"value": "invalid"}},
        {"data": {"value": 9}, "actor": {"id": 123}},
        {"data": {"value": 9}, "records": "forged"},
        {"data": {"value": 9}, "context": {"approved_value": 9}},
    ],
)
async def test_invalid_and_forged_inputs_never_enter_services(
    native, arguments
):
    container, connection, calls = native
    executor = FunctionToolExecutor([write_tools()], container)
    with pytest.raises(ValueError):
        await executor.invoke(
            "write_record", arguments, context=Actor(approved_value=9)
        )
    assert calls.opened == []
    assert await persisted(connection) == []


@pytest.mark.parametrize(
    "actor,message",
    [
        (Actor(allowed=False, approved_value=9), "access denied"),
        (Actor(approved_value=8), "approval required"),
        (Actor(), "approval required"),
    ],
)
async def test_current_authorization_and_exact_approval_deny_before_effect(
    native, actor, message
):
    container, connection, calls = native
    executor = FunctionToolExecutor([write_tools()], container)
    with pytest.raises(PermissionError, match=message):
        await executor.invoke(
            "write_record", {"data": {"value": 9}}, context=actor
        )
    assert calls.opened == []
    assert await persisted(connection) == []


async def test_native_transaction_rolls_back_failure_and_closes(native):
    container, connection, calls = native
    executor = FunctionToolExecutor([write_tools()], container)
    with pytest.raises(ValueError, match="business rejection"):
        await executor.invoke(
            "write_record",
            {"data": {"value": 9}, "fail": True},
            context=Actor(approved_value=9),
        )
    assert await persisted(connection) == []
    assert calls.finalized == calls.opened
    assert not calls.opened[0].is_open


async def test_concurrent_calls_keep_native_sessions_and_actors_separate(
    native,
):
    container, _, calls = native
    executor = FunctionToolExecutor([read_tools()], container)
    tasks = [
        asyncio.create_task(
            executor.invoke(
                "read_record",
                {"data": {"value": value}},
                context=Actor(id=value),
            )
        )
        for value in (3, 8)
    ]
    await asyncio.wait_for(calls.both_started.wait(), timeout=5)
    calls.release.set()
    results = await asyncio.wait_for(asyncio.gather(*tasks), timeout=5)
    assert results == [
        Output(value=3, actor_id=3),
        Output(value=8, actor_id=8),
    ]
    assert len(set(calls.session_ids)) == 2
    assert len(calls.opened) == 2
    assert calls.opened[0] is not calls.opened[1]
    assert set(calls.finalized) == set(calls.opened)
    assert all(not unit.is_open for unit in calls.opened)


async def test_anyio_cancellation_finalizes_native_request_scope(native):
    container, _, calls = native
    executor = FunctionToolExecutor([read_tools()], container)

    async def invoke() -> None:
        await executor.invoke(
            "read_record", {"data": {"value": 2}}, context=Actor()
        )

    async with anyio.create_task_group() as group:
        group.start_soon(invoke)
        with anyio.fail_after(5):
            await calls.started.wait()
        group.cancel_scope.cancel()
    assert calls.finalized == calls.opened
    assert len(calls.opened) == 1
    assert not calls.opened[0].is_open


async def test_output_contract_is_validated_and_scope_closes(native):
    container, _, calls = native
    tools = FunctionTools()

    @tools.tool(
        key="records.invalid",
        name="invalid_output",
        title="Invalid output",
        description="Exercise output validation.",
        effect=ToolEffect.READ,
        authorize=authorize,
    )
    async def invalid(records: FromDishka[Records]) -> Output:
        assert records.unit.is_open
        return cast(Output, {"value": "invalid", "actor_id": 1})

    executor = FunctionToolExecutor([tools], container)
    with pytest.raises(ValidationError):
        await executor.invoke("invalid_output", {}, context=Actor())
    assert calls.finalized == calls.opened
    assert not calls.opened[0].is_open


@pytest.mark.parametrize(
    "field,value", [("effect", "read"), ("authorize", None), ("title", "")]
)
def test_registration_requires_explicit_effect_authorization_and_metadata(
    field, value
):
    tools = FunctionTools()
    options: dict[str, Any] = dict(
        key="read",
        name="read",
        title="Read",
        description="Read a value.",
        effect=ToolEffect.READ,
        authorize=authorize,
    )
    options[field] = value

    async def read(value: int) -> int:
        return value

    with pytest.raises((TypeError, ValueError)):
        tools.tool(**options)(read)


def test_write_registration_requires_approval_and_async_function():
    tools = FunctionTools()
    options: dict[str, Any] = dict(
        key="write",
        name="write",
        title="Write",
        description="Write a value.",
        effect=ToolEffect.WRITE,
        authorize=authorize,
    )

    async def write(value: int) -> int:
        return value

    with pytest.raises(TypeError, match="approval hook"):
        tools.tool(**options)(write)
    with pytest.raises(TypeError, match="async function"):
        tools.tool(**options, approve=approve)(lambda value: value)


@pytest.mark.parametrize("key,name", [("same", "other"), ("other", "same")])
async def test_duplicate_stable_keys_and_names_fail_composition(
    native, key, name
):
    container, _, _ = native
    tools = FunctionTools()

    async def read(value: int) -> int:
        return value

    tools.tool(
        key="same",
        name="same",
        title="Read",
        description="Read value.",
        effect=ToolEffect.READ,
        authorize=authorize,
    )(read)
    tools.tool(
        key=key,
        name=name,
        title="Read",
        description="Read value.",
        effect=ToolEffect.READ,
        authorize=authorize,
    )(read)
    with pytest.raises(ValueError, match="Duplicate function tool"):
        FunctionToolExecutor([tools], container)


def test_base_only_import_and_optional_adapter_diagnostic(tmp_path):
    source = """
import importlib.abc
import sys
class BlockOptional(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        package = fullname.split('.')[0]
        if package in {'pydantic_ai', 'mcp'}:
            raise ModuleNotFoundError(name=package)
sys.meta_path.insert(0, BlockOptional())
from papilio.function_tools.registry import FunctionTools
from papilio.function_tools.execution import FunctionToolExecutor
assert 'pydantic_ai' not in sys.modules
assert 'mcp' not in sys.modules
try:
    import papilio.function_tools.pydantic_ai
except ImportError as error:
    assert 'papilio[function-tools-pydantic-ai]' in str(error)
else:
    raise AssertionError('Optional dependency should be missing')
"""
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [sys.executable, "-c", source],
        cwd=tmp_path,
        env={**os.environ, "PYTHONPATH": str(root)},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


async def test_native_pydantic_ai_defers_write_and_keeps_executor_guards(
    native,
):
    from pydantic_ai import Agent, DeferredToolRequests, DeferredToolResults
    from pydantic_ai.messages import (
        ModelResponse,
        TextPart,
        ToolCallPart,
        ToolReturnPart,
    )
    from pydantic_ai.models.function import FunctionModel

    from papilio.function_tools.pydantic_ai import build_toolset

    container, connection, _ = native
    executor = FunctionToolExecutor([write_tools()], container)
    toolset = build_toolset(executor)

    def respond(messages, info):
        assert info.function_tools[0].name == "write_record"
        assert set(
            info.function_tools[0].parameters_json_schema["properties"]
        ) == {"data", "fail"}
        if any(
            isinstance(part, ToolReturnPart)
            for message in messages
            for part in message.parts
        ):
            return ModelResponse(parts=[TextPart("Recorded.")])
        return ModelResponse(
            parts=[
                ToolCallPart(
                    "write_record",
                    {"data": {"value": 6}},
                    tool_call_id="approved-call",
                )
            ]
        )

    agent = Agent(
        FunctionModel(respond),
        toolsets=[toolset],
        output_type=[str, DeferredToolRequests],
    )
    pending = await agent.run("Write six", deps=Actor())
    assert isinstance(pending.output, DeferredToolRequests)
    assert pending.output.approvals[0].tool_call_id == "approved-call"
    assert await persisted(connection) == []
    done = await agent.run(
        message_history=pending.all_messages(),
        deferred_tool_results=DeferredToolResults(
            approvals={"approved-call": True}
        ),
        deps=Actor(id=5, approved_value=6),
    )
    assert done.output == "Recorded."
    assert await persisted(connection) == [(6, 5)]


async def test_variadic_inputs_cannot_forge_injected_parameters(native):
    container, _, calls = native
    tools = FunctionTools()

    @tools.tool(
        key="records.variadic",
        name="variadic",
        title="Read extra values",
        description="Read typed values with trusted actor context.",
        effect=ToolEffect.READ,
        authorize=authorize,
    )
    async def read(
        value: int, actor: FromDishka[Actor], **extra: int
    ) -> Output:
        return Output(value=value + sum(extra.values()), actor_id=actor.id)

    executor = FunctionToolExecutor([tools], container)
    with pytest.raises(ValueError, match="Injected function tool arguments"):
        await executor.invoke(
            "variadic", {"value": 1, "actor": 123}, context=Actor()
        )
    assert calls.opened == []
    result = await executor.invoke(
        "variadic", {"value": 1, "other": 2}, context=Actor(id=7)
    )
    assert result == Output(value=3, actor_id=7)


async def test_direct_definition_cannot_bypass_effect_contract(native):
    from papilio.function_tools.registry import FunctionTool

    async def read(value: int) -> int:
        return value

    with pytest.raises(TypeError, match="explicit ToolEffect"):
        FunctionTool(
            read,
            "read",
            "read",
            "Read",
            "Read value.",
            cast(ToolEffect, "write"),
            authorize,
        )


async def test_native_approval_does_not_bypass_application_approval(native):
    from pydantic_ai import Agent, DeferredToolRequests, DeferredToolResults
    from pydantic_ai.messages import ModelResponse, ToolCallPart
    from pydantic_ai.models.function import FunctionModel

    from papilio.function_tools.pydantic_ai import build_toolset

    container, connection, calls = native
    executor = FunctionToolExecutor([write_tools()], container)

    def respond(messages, info):
        return ModelResponse(
            parts=[
                ToolCallPart(
                    "write_record",
                    {"data": {"value": 6}},
                    tool_call_id="pending-write",
                )
            ]
        )

    agent = Agent(
        FunctionModel(respond),
        toolsets=[build_toolset(executor)],
        output_type=[str, DeferredToolRequests],
    )
    pending = await agent.run("Write six", deps=Actor())
    with pytest.raises(PermissionError, match="approval required"):
        await agent.run(
            message_history=pending.all_messages(),
            deferred_tool_results=DeferredToolResults(
                approvals={"pending-write": True}
            ),
            deps=Actor(approved_value=5),
        )
    assert calls.opened == []
    assert await persisted(connection) == []


async def test_mcp_adapter_uses_same_executor_schema_and_application_guards(
    native,
):
    import httpx2
    from mcp import Client
    from mcp.client.streamable_http import streamable_http_client
    from mcp_types import TextContent

    from papilio.function_tools.mcp import build_server

    container, connection, calls = native
    from papilio.errors.exceptions import ForbiddenException

    tools = write_tools()

    @tools.tool(
        key="records.reject",
        name="reject_record",
        title="Reject record",
        description="Expose a native application rejection.",
        effect=ToolEffect.READ,
        authorize=authorize,
    )
    async def reject(data: Input, records: FromDishka[Records]) -> Output:
        assert records.unit.is_open
        raise ForbiddenException("Business rejected", "business_rejected")

    executor = FunctionToolExecutor([tools], container)
    actor = Actor()
    server = build_server(
        executor, current_context=lambda: actor, name="Function tools"
    )
    app = server.streamable_http_app(stateless_http=True, json_response=True)
    async with app.router.lifespan_context(app):
        async with httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app)
        ) as http:
            async with Client(
                streamable_http_client(
                    "http://localhost:8000/mcp", http_client=http
                )
            ) as client:
                listing = await client.list_tools()
                assert set(listing.tools[0].input_schema["properties"]) == {
                    "data",
                    "fail",
                }
                denied = await client.call_tool(
                    "write_record", {"data": {"value": 6}}
                )
                assert denied.is_error
                assert calls.opened == []
                from mcp.shared.exceptions import MCPError

                with pytest.raises(
                    MCPError, match="Unexpected function tool arguments"
                ):
                    await client.call_tool(
                        "write_record",
                        {"data": {"value": 6}, "actor": "forged"},
                    )
                assert calls.opened == []
                assert listing.tools[0].annotations is not None
                assert listing.tools[0].annotations.read_only_hint is False
                actor = Actor(id=5, approved_value=6)
                created = await client.call_tool(
                    "write_record", {"data": {"value": 6}}
                )
                assert not created.is_error
                assert created.structured_content == {
                    "value": 6,
                    "actor_id": 5,
                }
                rejected = await client.call_tool(
                    "reject_record", {"data": {"value": 1}}
                )
                assert rejected.is_error
                assert isinstance(rejected.content[0], TextContent)
                assert "business_rejected" in rejected.content[0].text
    assert await persisted(connection) == [(6, 5)]
    assert calls.finalized == calls.opened


async def test_mcp_named_parameter_contract_rejects_variadic_composition(
    native,
):
    from papilio.function_tools.mcp import build_server

    container, _, _ = native
    tools = FunctionTools()

    @tools.tool(
        key="variadic",
        name="variadic",
        title="Read",
        description="Read extra values.",
        effect=ToolEffect.READ,
        authorize=authorize,
    )
    async def variadic(value: int, **extra: int) -> int:
        return value + sum(extra.values())

    executor = FunctionToolExecutor([tools], container)
    direct = await executor.invoke(
        "variadic", {"value": 1, "other": 2}, context=Actor()
    )
    assert direct == 3
    with pytest.raises(TypeError, match="named parameters"):
        build_server(executor, current_context=Actor, name="Named tools")


async def test_pydantic_ai_adapter_preserves_native_variadic_contract(native):
    from pydantic_ai import Agent
    from pydantic_ai.messages import (
        ModelResponse,
        TextPart,
        ToolCallPart,
        ToolReturnPart,
    )
    from pydantic_ai.models.function import FunctionModel

    from papilio.function_tools.pydantic_ai import build_toolset

    container, _, _ = native
    tools = FunctionTools()

    @tools.tool(
        key="variadic",
        name="variadic",
        title="Read",
        description="Read extra values.",
        effect=ToolEffect.READ,
        authorize=authorize,
    )
    async def variadic(value: int, **extra: int) -> int:
        return value + sum(extra.values())

    def respond(messages, info):
        returned = [
            part
            for message in messages
            for part in message.parts
            if isinstance(part, ToolReturnPart)
        ]
        if returned:
            assert returned[0].content == 3
            return ModelResponse(parts=[TextPart("Three.")])
        return ModelResponse(
            parts=[ToolCallPart("variadic", {"value": 1, "other": 2})]
        )

    agent = Agent(
        FunctionModel(respond),
        toolsets=[build_toolset(FunctionToolExecutor([tools], container))],
    )
    result = await agent.run("Add values", deps=Actor())
    assert result.output == "Three."


@pytest.mark.parametrize("mode", ["positional_only", "var_positional"])
async def test_named_invocation_rejects_incompatible_positional_contracts(
    native, mode
):
    container, _, calls = native
    tools = FunctionTools()

    async def positional_only(value: int, /) -> int:
        return value

    async def var_positional(*values: int) -> int:
        return sum(values)

    function = {
        "positional_only": positional_only,
        "var_positional": var_positional,
    }[mode]
    tools.tool(
        key="positional",
        name="positional",
        title="Read",
        description="Read explicit values.",
        effect=ToolEffect.READ,
        authorize=authorize,
    )(function)
    with pytest.raises(TypeError, match="named arguments"):
        FunctionToolExecutor([tools], container)
    assert calls.opened == []


@pytest.mark.parametrize("effect", [ToolEffect.READ, ToolEffect.WRITE])
@pytest.mark.parametrize(
    "arguments",
    [
        {"data": {"value": "private-secret-17"}},
        {"data": {"value": 17}, "private-secret-17": 17},
    ],
)
async def test_sdk_invalid_input_fails_before_guards_and_deferred_approval(
    native, effect, arguments
):
    from pydantic_ai import Agent, DeferredToolRequests
    from pydantic_ai.messages import (
        ModelResponse,
        TextPart,
        ToolCallPart,
        ToolReturnPart,
    )
    from pydantic_ai.models.function import FunctionModel

    from papilio.function_tools.pydantic_ai import build_toolset

    container, _, calls = native
    guarded: list[bool] = []
    tools = FunctionTools()

    async def guard(context, arguments):
        guarded.append(True)
        return True

    @tools.tool(
        key="typed",
        name="typed",
        title="Typed operation",
        description="Receive an integer.",
        effect=effect,
        authorize=guard,
        approve=guard if effect == ToolEffect.WRITE else None,
    )
    async def typed(data: Input) -> int:
        raise AssertionError("Invalid input must not execute")

    def respond(messages, info):
        returns = [
            part
            for message in messages
            for part in message.parts
            if isinstance(part, ToolReturnPart)
        ]
        if returns:
            assert returns[0].outcome == "failed"
            assert "Invalid tool arguments" in str(returns[0].content)
            assert "private-secret-17" not in str(returns[0].content)
            assert len(str(returns[0].content)) < 200
            return ModelResponse(parts=[TextPart("Input was rejected.")])
        return ModelResponse(
            parts=[
                ToolCallPart(
                    "typed",
                    arguments,
                    tool_call_id="invalid-input",
                )
            ]
        )

    agent = Agent(
        FunctionModel(respond),
        toolsets=[build_toolset(FunctionToolExecutor([tools], container))],
        output_type=[str, DeferredToolRequests],
        retries=0,
    )
    result = await agent.run("Use a typed operation", deps=Actor())
    assert result.output == "Input was rejected."
    assert guarded == []
    assert calls.opened == []


@pytest.mark.parametrize("effect", [ToolEffect.READ, ToolEffect.WRITE])
async def test_sdk_injected_arguments_fail_before_guards_and_approval(
    native, effect
):
    from pydantic_ai import Agent, DeferredToolRequests
    from pydantic_ai.messages import (
        ModelResponse,
        TextPart,
        ToolCallPart,
        ToolReturnPart,
    )
    from pydantic_ai.models.function import FunctionModel

    from papilio.function_tools.pydantic_ai import build_toolset

    container, _, calls = native
    guarded: list[bool] = []
    tools = FunctionTools()

    async def guard(context, arguments):
        guarded.append(True)
        return True

    @tools.tool(
        key="variadic",
        name="variadic",
        title="Typed operation",
        description="Receive typed extra values with trusted actor context.",
        effect=effect,
        authorize=guard,
        approve=guard if effect == ToolEffect.WRITE else None,
    )
    async def variadic(
        value: int, actor: FromDishka[Actor], **extra: int
    ) -> int:
        raise AssertionError("Injected arguments must not execute")

    def respond(messages, info):
        returns = [
            part
            for message in messages
            for part in message.parts
            if isinstance(part, ToolReturnPart)
        ]
        if returns:
            assert returns[0].outcome == "failed"
            assert "Invalid tool arguments" in str(returns[0].content)
            return ModelResponse(parts=[TextPart("Input was rejected.")])
        return ModelResponse(
            parts=[
                ToolCallPart(
                    "variadic",
                    {"value": 1, "actor": 123},
                    tool_call_id="forged-actor",
                )
            ]
        )

    agent = Agent(
        FunctionModel(respond),
        toolsets=[build_toolset(FunctionToolExecutor([tools], container))],
        output_type=[str, DeferredToolRequests],
        retries=0,
    )
    result = await agent.run("Use a typed operation", deps=Actor())
    assert result.output == "Input was rejected."
    assert guarded == []
    assert calls.opened == []


async def test_sdk_validation_preserves_original_wire_arguments(native):
    from typing import Annotated

    from pydantic import BeforeValidator
    from pydantic_ai import Agent
    from pydantic_ai.messages import (
        ModelResponse,
        TextPart,
        ToolCallPart,
        ToolReturnPart,
    )
    from pydantic_ai.models.function import FunctionModel

    from papilio.function_tools.pydantic_ai import build_toolset

    container, _, _ = native
    decoded: list[Any] = []

    def decode(value):
        decoded.append(value)
        if not isinstance(value, str) or not value.startswith("encoded-"):
            raise ValueError("Encoded identifier required")
        return int(value.removeprefix("encoded-"))

    class EncodedInput(BaseModel):
        value: Annotated[int, BeforeValidator(decode)]

    tools = FunctionTools()

    async def read(data) -> int:
        return data.value

    read.__annotations__["data"] = EncodedInput
    tools.tool(
        key="encoded",
        name="encoded",
        title="Read encoded identifier",
        description="Decode a wire identifier once for execution.",
        effect=ToolEffect.READ,
        authorize=authorize,
    )(read)

    def respond(messages, info):
        returns = [
            part
            for message in messages
            for part in message.parts
            if isinstance(part, ToolReturnPart)
        ]
        if returns:
            assert returns[0].content == 7
            assert returns[0].outcome == "success"
            return ModelResponse(parts=[TextPart("Seven.")])
        return ModelResponse(
            parts=[ToolCallPart("encoded", {"data": {"value": "encoded-7"}})]
        )

    agent = Agent(
        FunctionModel(respond),
        toolsets=[build_toolset(FunctionToolExecutor([tools], container))],
        retries=0,
    )
    result = await agent.run("Read an encoded identifier", deps=Actor())
    assert result.output == "Seven."
    assert decoded == ["encoded-7", "encoded-7"]


@pytest.mark.parametrize(
    "arguments, expected",
    [
        ({"sort_by": None}, "data.sort_by: enum"),
        (
            {"values": {"private-key-17": "private-input-17"}},
            "data.values: int_parsing",
        ),
        (
            {"custom_value": "private-type-17"},
            "data.custom_value: validation_error",
        ),
        (
            {
                "values": {
                    f"private-key-{i}": "private-input-17" for i in range(10)
                }
            },
            "data.values: int_parsing",
        ),
    ],
)
async def test_sdk_validation_feedback_is_actionable_bounded_and_private(
    native, arguments, expected
):
    from enum import Enum

    from pydantic import field_validator
    from pydantic_ai import Agent
    from pydantic_ai.messages import (
        ModelResponse,
        TextPart,
        ToolCallPart,
        ToolReturnPart,
    )
    from pydantic_ai.models.function import FunctionModel
    from pydantic_core import PydanticCustomError

    from papilio.function_tools.pydantic_ai import build_toolset

    class SortBy(str, Enum):
        TITLE = "title"

    class FeedbackInput(BaseModel):
        sort_by: SortBy = SortBy.TITLE
        values: dict[str, int] = {}
        custom_value: str | None = None

        @field_validator("custom_value")
        @classmethod
        def reject_custom(cls, value):
            raise PydanticCustomError(
                value, "private-message-17", {"secret": "private-context-17"}
            )

    container, _, calls = native
    guarded: list[bool] = []
    tools = FunctionTools()

    async def guard(context, arguments):
        guarded.append(True)
        return True

    async def read(data) -> int:
        raise AssertionError("Invalid input must not execute")

    read.__annotations__["data"] = FeedbackInput
    tools.tool(
        key="feedback",
        name="feedback",
        title="Read sorted data",
        description="Read a typed sorting request.",
        effect=ToolEffect.READ,
        authorize=guard,
    )(read)

    def respond(messages, info):
        returns = [
            part
            for message in messages
            for part in message.parts
            if isinstance(part, ToolReturnPart)
        ]
        if returns:
            feedback = str(returns[0].content)
            assert returns[0].outcome == "failed"
            assert expected in feedback
            assert "private-" not in feedback
            assert len(feedback) <= 512
            assert feedback.count(";") <= 2
            return ModelResponse(parts=[TextPart("Input was rejected.")])
        return ModelResponse(
            parts=[ToolCallPart("feedback", {"data": arguments})]
        )

    agent = Agent(
        FunctionModel(respond),
        toolsets=[build_toolset(FunctionToolExecutor([tools], container))],
        retries=0,
    )
    result = await agent.run("Read sorted data", deps=Actor())
    assert result.output == "Input was rejected."
    assert guarded == []
    assert calls.opened == []
