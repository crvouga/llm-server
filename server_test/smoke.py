"""Smoke-test helpers for OpenAI-compatible API harness compatibility."""

from __future__ import annotations

import json
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, cast

from openai import OpenAI

# ANSI colours (mirrors server/spark/console.py)
R = "\033[0;31m"
G = "\033[0;32m"
Y = "\033[1;33m"
C = "\033[0;36m"
B = "\033[1m"
X = "\033[0m"

DEFAULT_MODEL = "atlas"

WEATHER_TOOL = {
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": "Get the current weather for a city.",
        "parameters": {
            "type": "object",
            "properties": {
                "location": {
                    "type": "string",
                    "description": "City name, e.g. San Francisco",
                },
            },
            "required": ["location"],
        },
    },
}


def info(msg: str) -> None:
    print(f"{C}[•]{X} {msg}", flush=True)


def ok(msg: str) -> None:
    print(f"{G}[✓]{X} {msg}", flush=True)


def warn(msg: str) -> None:
    print(f"{Y}[!]{X} {msg}", flush=True)


def err(msg: str) -> None:
    print(f"{R}[✗]{X} {msg}", file=sys.stderr, flush=True)


def section(msg: str) -> None:
    print(f"\n{B}━━━  {msg}  ━━━{X}", flush=True)


class SkipTest(Exception):
    """Non-fatal skip for optional capabilities."""


@dataclass
class TestContext:
    client: OpenAI
    model: str
    skip_tools: bool = False
    resolved_model: str | None = None
    quiet: bool = False


@dataclass
class TestResult:
    name: str
    passed: bool
    skipped: bool = False
    error: str | None = None
    duration_s: float = 0.0


@dataclass
class RunSummary:
    base_url: str
    model: str
    results: list[TestResult] = field(default_factory=list)

    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r.passed and not r.skipped)

    @property
    def failed(self) -> int:
        return sum(1 for r in self.results if not r.passed and not r.skipped)

    @property
    def skipped(self) -> int:
        return sum(1 for r in self.results if r.skipped)


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _content_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict):
                text = block.get("text")
                if isinstance(text, str):
                    parts.append(text)
            else:
                text = getattr(block, "text", None)
                if isinstance(text, str):
                    parts.append(text)
        return "".join(parts)
    return str(content)


def _message_text(message: Any) -> str:
    parts = [_content_text(getattr(message, "content", None))]
    reasoning = getattr(message, "reasoning_content", None)
    if reasoning:
        parts.append(_content_text(reasoning))
    return "".join(parts)


def _assistant_payload(message: Any) -> dict[str, Any]:
    """Build a minimal assistant message dict safe to replay (no model_dump dupes)."""
    payload: dict[str, Any] = {"role": "assistant"}
    content = getattr(message, "content", None)
    if content is not None:
        payload["content"] = content
    tool_calls = getattr(message, "tool_calls", None) or []
    if tool_calls:
        payload["tool_calls"] = [
            {
                "id": call.id,
                "type": call.type,
                "function": {
                    "name": call.function.name,
                    "arguments": call.function.arguments,
                },
            }
            for call in tool_calls
        ]
    return payload


def resolve_model(client: OpenAI, model_override: str) -> str:
    if model_override:
        return model_override
    models = client.models.list()
    data = getattr(models, "data", None) or []
    if not data:
        warn(f"No models from /v1/models; falling back to {DEFAULT_MODEL}")
        return DEFAULT_MODEL
    model_id = data[0].id
    _assert(bool(model_id), "Model list missing id field")
    return str(model_id)


def test_list_models(ctx: TestContext) -> None:
    models = ctx.client.models.list()
    data = getattr(models, "data", None) or []
    _assert(len(data) >= 1, f"Expected >=1 model, got {len(data)}")
    ctx.resolved_model = resolve_model(ctx.client, ctx.model)
    if not ctx.quiet:
        info(f"Using model: {ctx.resolved_model}")


def test_basic_completion(ctx: TestContext) -> None:
    model = ctx.resolved_model or ctx.model
    resp = ctx.client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": "Say hello in one short sentence."}],
        max_tokens=64,
        temperature=0.2,
    )
    choice = resp.choices[0]
    content = _content_text(choice.message.content)
    _assert(bool(content.strip()), "Expected non-empty completion content")
    _assert(choice.finish_reason == "stop", f"Expected finish_reason=stop, got {choice.finish_reason}")
    usage = resp.usage
    if usage is None:
        raise AssertionError("Expected usage block in response")
    completion_tokens = usage.completion_tokens or 0
    _assert(completion_tokens > 0, "Expected completion_tokens > 0")


def test_system_prompt(ctx: TestContext) -> None:
    model = ctx.resolved_model or ctx.model
    resp = ctx.client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": "Reply with only the number, no other text."},
            {"role": "user", "content": "What is 2+2?"},
        ],
        max_tokens=16,
        temperature=0.0,
    )
    content = _content_text(resp.choices[0].message.content).strip()
    _assert("4" in content, f"Expected '4' in response, got: {content!r}")


def test_multi_turn_context(ctx: TestContext) -> None:
    model = ctx.resolved_model or ctx.model
    resp = ctx.client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "system",
                "content": "Answer directly in one short sentence. Do not explain your reasoning.",
            },
            {"role": "user", "content": "My name is Ada."},
            {"role": "assistant", "content": "Nice to meet you, Ada."},
            {"role": "user", "content": "What is my name?"},
        ],
        max_tokens=64,
        temperature=0.0,
    )
    content = _message_text(resp.choices[0].message).lower()
    _assert("ada" in content, f"Expected 'ada' in response, got: {content!r}")


def test_streaming(ctx: TestContext) -> None:
    model = ctx.resolved_model or ctx.model
    stream = ctx.client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": "Count from 1 to 5, one number per line."}],
        max_tokens=64,
        temperature=0.2,
        stream=True,
    )
    chunks = 0
    parts: list[str] = []
    for chunk in stream:
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta
        piece = _content_text(getattr(delta, "content", None))
        if piece:
            chunks += 1
            parts.append(piece)
    content = "".join(parts)
    _assert(chunks >= 1, f"Expected >=1 content chunks, got {chunks}")
    _assert(bool(content.strip()), "Expected non-empty streamed content")


def test_tool_calling(ctx: TestContext) -> None:
    model = ctx.resolved_model or ctx.model
    resp = ctx.client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": "What's the weather in Paris?"}],
        tools=cast(Any, [WEATHER_TOOL]),
        max_tokens=128,
        temperature=0.0,
    )
    message = resp.choices[0].message
    tool_calls = message.tool_calls or []
    if not tool_calls:
        if ctx.skip_tools:
            raise SkipTest("Model returned no tool_calls (--skip-tools)")
        raise AssertionError("Expected tool_calls in response")
    call = tool_calls[0]
    fn = getattr(call, "function", None)
    if fn is None:
        raise AssertionError("Expected function on tool_call")
    _assert(fn.name == "get_weather", f"Expected get_weather, got {fn.name!r}")
    args = json.loads(fn.arguments)
    _assert(
        "location" in args,
        f"Expected location in tool arguments, got {args!r}",
    )


def test_tool_round_trip(ctx: TestContext) -> None:
    model = ctx.resolved_model or ctx.model
    first = ctx.client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": "What's the weather in Tokyo?"}],
        tools=cast(Any, [WEATHER_TOOL]),
        max_tokens=128,
        temperature=0.0,
    )
    assistant_msg = first.choices[0].message
    tool_calls = assistant_msg.tool_calls or []
    if not tool_calls:
        if ctx.skip_tools:
            raise SkipTest("Model returned no tool_calls (--skip-tools)")
        raise AssertionError("Expected tool_calls in first response")

    call = tool_calls[0]
    second = ctx.client.chat.completions.create(
        model=model,
        messages=cast(
            Any,
            [
                {"role": "user", "content": "What's the weather in Tokyo?"},
                _assistant_payload(assistant_msg),
                {
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": json.dumps({"temperature_f": 72, "condition": "sunny"}),
                },
            ],
        ),
        tools=cast(Any, [WEATHER_TOOL]),
        max_tokens=128,
        temperature=0.0,
    )
    choice = second.choices[0]
    content = _content_text(choice.message.content)
    _assert(bool(content.strip()), "Expected non-empty final answer after tool result")
    _assert(
        choice.finish_reason == "stop",
        f"Expected finish_reason=stop, got {choice.finish_reason}",
    )


def test_max_tokens_cap(ctx: TestContext) -> None:
    model = ctx.resolved_model or ctx.model
    resp = ctx.client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "user",
                "content": "Write a long essay about the history of computing.",
            },
        ],
        max_tokens=8,
        temperature=0.2,
    )
    choice = resp.choices[0]
    content = _content_text(choice.message.content)
    _assert(bool(content.strip()), "Expected some completion content")
    _assert(
        choice.finish_reason == "length",
        f"Expected finish_reason=length, got {choice.finish_reason}",
    )
    if resp.usage is not None:
        # Allow tokenizer overhead; backends may count special tokens above max_tokens.
        _assert(
            resp.usage.completion_tokens <= 24,
            f"Expected short completion, got {resp.usage.completion_tokens} tokens",
        )


TEST_ORDER: list[tuple[str, Callable[[TestContext], None]]] = [
    ("list_models", test_list_models),
    ("basic_completion", test_basic_completion),
    ("system_prompt", test_system_prompt),
    ("multi_turn_context", test_multi_turn_context),
    ("streaming", test_streaming),
    ("tool_calling", test_tool_calling),
    ("tool_round_trip", test_tool_round_trip),
    ("max_tokens_cap", test_max_tokens_cap),
]

TEST_LABELS: dict[str, str] = {
    "list_models": "List models",
    "basic_completion": "Basic completion",
    "system_prompt": "System prompt",
    "multi_turn_context": "Multi-turn context",
    "streaming": "Streaming",
    "tool_calling": "Tool calling",
    "tool_round_trip": "Tool round-trip",
    "max_tokens_cap": "max_tokens cap",
}


def run_tests(ctx: TestContext) -> RunSummary:
    summary = RunSummary(base_url=str(ctx.client.base_url), model=ctx.model)
    for name, fn in TEST_ORDER:
        started = time.perf_counter()
        result = TestResult(name=name, passed=False)
        try:
            fn(ctx)
            result.passed = True
            if not ctx.quiet:
                ok(f"{name} ({time.perf_counter() - started:.1f}s)")
        except SkipTest as exc:
            result.skipped = True
            result.passed = True
            result.error = str(exc)
            if not ctx.quiet:
                warn(f"{name} SKIPPED: {exc}")
        except Exception as exc:
            result.error = str(exc)
            if not ctx.quiet:
                err(f"{name} FAILED: {exc}")
        result.duration_s = time.perf_counter() - started
        summary.results.append(result)
    if ctx.resolved_model:
        summary.model = ctx.resolved_model
    return summary


def print_summary(summary: RunSummary) -> None:
    section("Smoke test summary")
    print(f"Target: {summary.base_url}")
    print(f"Model:  {summary.model}")
    print(
        f"Results: {summary.passed} passed, {summary.failed} failed, "
        f"{summary.skipped} skipped"
    )
    if summary.failed:
        print("")
        for r in summary.results:
            if not r.passed and not r.skipped:
                print(f"  {R}✗{X} {r.name}: {r.error}")


def summary_to_json(summary: RunSummary) -> dict[str, Any]:
    return {
        "passed": summary.passed,
        "failed": summary.failed,
        "skipped": summary.skipped,
        "ok": summary.failed == 0,
        "tests": [
            {
                "name": r.name,
                "passed": r.passed,
                "skipped": r.skipped,
                "error": r.error,
                "duration_s": round(r.duration_s, 3),
            }
            for r in summary.results
        ],
    }


def summary_to_markdown_section(summary: RunSummary) -> list[str]:
    lines = [
        "## Smoke tests",
        "",
        "| Test | Status | Duration | Details |",
        "| --- | --- | ---: | --- |",
    ]
    for r in summary.results:
        label = TEST_LABELS.get(r.name, r.name)
        if r.skipped:
            status = "⏭️ skipped"
            details = r.error or ""
        elif r.passed:
            status = "✅ pass"
            details = ""
        else:
            status = "❌ fail"
            details = (r.error or "unknown error").replace("|", "\\|").replace("\n", " ")
        lines.append(
            f"| {label} | {status} | {r.duration_s:.1f}s | {details} |"
        )
    lines.append("")
    lines.append(
        f"**Passed:** {summary.passed} · **Failed:** {summary.failed} · "
        f"**Skipped:** {summary.skipped}"
    )
    return lines
