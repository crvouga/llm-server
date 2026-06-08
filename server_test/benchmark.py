"""Throughput benchmark for OpenAI-compatible APIs."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, cast

from openai import OpenAI

from smoke import _content_text, section

QUESTION = (
    "Write a Python function that computes the nth Fibonacci number "
    "iteratively. Include a short docstring and a brief explanation "
    "of time and space complexity."
)


@dataclass
class BenchmarkConfig:
    max_tokens: int = 512
    runs: int = 3
    stream: bool = True
    depth: int = 0
    thinking: bool = False


def completion_extra_body(thinking: bool) -> dict[str, Any] | None:
    if thinking:
        return None
    return {"chat_template_kwargs": {"enable_thinking": False}}


@dataclass
class BenchmarkSample:
    model: str
    stream: bool
    latency_s: float
    ttft_s: float | None
    overall_tps: float
    generation_tps: float | None
    server_tps: float | None
    server_ttft_ms: float | None
    completion_tokens: int
    prompt_tokens: int
    total_tokens: int
    reasoning_tokens: int = 0
    stream_chunks: int = 0


@dataclass
class BenchmarkSummary:
    base_url: str
    model: str
    stream: bool
    runs: int
    max_tokens: int
    depth_tokens: int
    latency_s: float
    ttft_s: float | None
    overall_tps: float
    generation_tps: float | None
    server_tps: float | None
    server_ttft_ms: float | None
    completion_tokens: int
    prompt_tokens: int
    total_tokens: int
    thinking: bool = False
    reasoning_tokens: int = 0
    stream_chunks: int = 0
    samples: list[BenchmarkSample] = field(default_factory=list)
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


def build_prompt(depth: int) -> str:
    if depth <= 0:
        return QUESTION
    filler_line = (
        "def process(record):  # legacy helper, do not change signature\n"
        "    return {k: v for k, v in record.items() if v is not None}\n"
    )
    approx_tokens_per_line = 24
    n_lines = max(1, depth // approx_tokens_per_line)
    preamble = filler_line * n_lines
    return (
        "Here is a large codebase excerpt for context:\n\n"
        + preamble
        + "\n\nNow, ignoring the excerpt above, answer this:\n"
        + QUESTION
    )


def _usage_metrics(usage: Any) -> tuple[int, int, int, int, float | None, float | None]:
    if usage is None:
        return 0, 0, 0, 0, None, None
    completion_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
    prompt_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
    total_tokens = int(getattr(usage, "total_tokens", 0) or (prompt_tokens + completion_tokens))
    reasoning_tokens = 0
    details = getattr(usage, "completion_tokens_details", None)
    if details is not None:
        reasoning_tokens = int(getattr(details, "reasoning_tokens", 0) or 0)
    server_tps = getattr(usage, "response_token/s", None)
    if server_tps is None:
        server_tps = getattr(usage, "response_tokens_per_second", None)
    server_ttft_ms = getattr(usage, "time_to_first_token_ms", None)
    return (
        completion_tokens,
        prompt_tokens,
        total_tokens,
        reasoning_tokens,
        float(server_tps) if server_tps is not None else None,
        float(server_ttft_ms) if server_ttft_ms is not None else None,
    )


def _sample_from_timings(
    *,
    model: str,
    stream: bool,
    started: float,
    end: float,
    first_tok: float | None,
    usage: Any,
    stream_chunks: int = 0,
) -> BenchmarkSample:
    latency_s = end - started
    completion_tokens, prompt_tokens, total_tokens, reasoning_tokens, server_tps, server_ttft_ms = (
        _usage_metrics(usage)
    )
    ttft_s = (first_tok - started) if first_tok is not None else None
    overall_tps = (completion_tokens / latency_s) if latency_s > 0 and completion_tokens else 0.0
    generation_tps = None
    if ttft_s is not None and completion_tokens:
        gen_window = latency_s - ttft_s
        if gen_window > 0:
            generation_tps = completion_tokens / gen_window
    elif not stream and completion_tokens:
        generation_tps = overall_tps

    return BenchmarkSample(
        model=model,
        stream=stream,
        latency_s=latency_s,
        ttft_s=ttft_s,
        overall_tps=overall_tps,
        generation_tps=generation_tps,
        server_tps=server_tps,
        server_ttft_ms=server_ttft_ms,
        completion_tokens=completion_tokens,
        prompt_tokens=prompt_tokens,
        total_tokens=total_tokens,
        reasoning_tokens=reasoning_tokens,
        stream_chunks=stream_chunks,
    )


def bench_once_blocking(
    client: OpenAI,
    model: str,
    prompt: str,
    max_tokens: int,
    *,
    thinking: bool = False,
) -> BenchmarkSample:
    started = time.perf_counter()
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=max_tokens,
        temperature=0.2,
        extra_body=completion_extra_body(thinking),
    )
    end = time.perf_counter()
    return _sample_from_timings(
        model=str(resp.model or model),
        stream=False,
        started=started,
        end=end,
        first_tok=None,
        usage=resp.usage,
    )


def bench_once_stream(
    client: OpenAI,
    model: str,
    prompt: str,
    max_tokens: int,
    *,
    thinking: bool = False,
) -> BenchmarkSample:
    started = time.perf_counter()
    first_tok: float | None = None
    response_model = model
    usage: Any = None
    stream_chunks = 0

    stream = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=max_tokens,
        temperature=0.2,
        stream=True,
        stream_options=cast(Any, {"include_usage": True}),
        extra_body=completion_extra_body(thinking),
    )
    for chunk in stream:
        if chunk.model:
            response_model = str(chunk.model)
        if chunk.usage is not None:
            usage = chunk.usage
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta
        piece = _content_text(getattr(delta, "content", None))
        if piece:
            if first_tok is None:
                first_tok = time.perf_counter()
            stream_chunks += 1

    end = time.perf_counter()
    if first_tok is None:
        raise RuntimeError("Stream produced no content tokens")

    return _sample_from_timings(
        model=response_model,
        stream=True,
        started=started,
        end=end,
        first_tok=first_tok,
        usage=usage,
        stream_chunks=stream_chunks,
    )


def _avg(samples: list[BenchmarkSample], key: str) -> float:
    vals = [getattr(s, key) for s in samples if getattr(s, key) is not None]
    return (sum(vals) / len(vals)) if vals else 0.0


def _avg_optional(samples: list[BenchmarkSample], key: str) -> float | None:
    vals = [getattr(s, key) for s in samples if getattr(s, key) is not None]
    return (sum(vals) / len(vals)) if vals else None


def run_benchmark(
    client: OpenAI,
    model: str,
    config: BenchmarkConfig,
) -> BenchmarkSummary:
    prompt = build_prompt(config.depth)
    summary = BenchmarkSummary(
        base_url=str(client.base_url),
        model=model,
        stream=config.stream,
        runs=config.runs,
        max_tokens=config.max_tokens,
        depth_tokens=config.depth,
        thinking=config.thinking,
        latency_s=0.0,
        ttft_s=None,
        overall_tps=0.0,
        generation_tps=None,
        server_tps=None,
        server_ttft_ms=None,
        completion_tokens=0,
        prompt_tokens=0,
        total_tokens=0,
    )
    try:
        samples: list[BenchmarkSample] = []
        current_model = model
        for _ in range(config.runs):
            if config.stream:
                sample = bench_once_stream(
                    client,
                    current_model,
                    prompt,
                    config.max_tokens,
                    thinking=config.thinking,
                )
            else:
                sample = bench_once_blocking(
                    client,
                    current_model,
                    prompt,
                    config.max_tokens,
                    thinking=config.thinking,
                )
            samples.append(sample)
            current_model = sample.model

        last = samples[-1]
        summary.model = last.model
        summary.samples = samples
        summary.latency_s = _avg(samples, "latency_s")
        summary.ttft_s = _avg_optional(samples, "ttft_s") if config.stream else None
        summary.overall_tps = _avg(samples, "overall_tps")
        summary.generation_tps = _avg_optional(samples, "generation_tps")
        summary.server_tps = _avg_optional(samples, "server_tps")
        summary.server_ttft_ms = _avg_optional(samples, "server_ttft_ms")
        summary.completion_tokens = int(_avg(samples, "completion_tokens"))
        summary.prompt_tokens = last.prompt_tokens
        summary.total_tokens = last.total_tokens
        summary.reasoning_tokens = int(_avg(samples, "reasoning_tokens"))
        summary.stream_chunks = int(_avg(samples, "stream_chunks"))
    except Exception as exc:
        summary.error = str(exc)
    return summary


def _fmt_tps(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value:.1f}"


def _reliable_generation_tps(summary: BenchmarkSummary) -> float | None:
    if summary.generation_tps is None or summary.ttft_s is None:
        return None
    decode_window = summary.latency_s - summary.ttft_s
    if decode_window < 2.0:
        return None
    return summary.generation_tps


def print_benchmark(summary: BenchmarkSummary) -> None:
    section("Throughput")
    if summary.error:
        print(f"Benchmark failed: {summary.error}")
        return

    mode = "streaming" if summary.stream else "non-streaming"
    thinking_mode = "on" if summary.thinking else "off (production default)"
    print(f"Target: {summary.base_url}")
    print(
        f"Mode: {mode}  |  thinking: {thinking_mode}  |  runs: {summary.runs}  |  "
        f"max_tokens: {summary.max_tokens}  |  depth: {summary.depth_tokens}"
    )
    print("")
    print(f"{'Metric':<28} {'Value':>14}")
    print(f"{'-' * 28} {'-' * 14}")
    print(f"{'Overall tok/s':<28} {_fmt_tps(summary.overall_tps):>14}")
    generation_tps = _reliable_generation_tps(summary)
    if generation_tps is not None:
        print(f"{'Generation tok/s':<28} {_fmt_tps(generation_tps):>14}")
    if summary.server_tps is not None:
        print(f"{'Server-reported tok/s':<28} {_fmt_tps(summary.server_tps):>14}")
    if summary.ttft_s is not None:
        print(f"{'TTFT (client)':<28} {summary.ttft_s:>13.2f}s")
    if summary.server_ttft_ms is not None:
        print(f"{'TTFT (server)':<28} {summary.server_ttft_ms:>12.0f}ms")
    print(f"{'Total latency':<28} {summary.latency_s:>13.2f}s")
    print(f"{'Completion tokens':<28} {summary.completion_tokens:>14}")
    print(f"{'Prompt tokens':<28} {summary.prompt_tokens:>14}")
    if summary.reasoning_tokens:
        print(f"{'Reasoning tokens':<28} {summary.reasoning_tokens:>14}")
    if summary.stream:
        print(f"{'Stream chunks':<28} {summary.stream_chunks:>14}")
    print("")
    print("Overall tok/s = completion_tokens / total wall time (best single-stream estimate).")
    if summary.server_tps is not None:
        print("Server-reported tok/s comes from the API usage block (Atlas/vLLM).")
    if summary.stream and summary.ttft_s is not None and (summary.latency_s - summary.ttft_s) < 2.0:
        print("Note: output batched after TTFT — overall/server tok/s are the reliable metrics.")
    if summary.runs > 1:
        print(f"Averaged over {summary.runs} runs.")


def benchmark_to_json(summary: BenchmarkSummary) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "stream": summary.stream,
        "thinking": summary.thinking,
        "runs": summary.runs,
        "max_tokens": summary.max_tokens,
        "depth_tokens": summary.depth_tokens,
        "latency_s": round(summary.latency_s, 3),
        "ttft_s": round(summary.ttft_s, 3) if summary.ttft_s is not None else None,
        "overall_tps": round(summary.overall_tps, 1),
        "generation_tps": round(summary.generation_tps, 1) if summary.generation_tps is not None else None,
        "server_tps": round(summary.server_tps, 1) if summary.server_tps is not None else None,
        "server_ttft_ms": round(summary.server_ttft_ms, 1) if summary.server_ttft_ms is not None else None,
        "completion_tokens": summary.completion_tokens,
        "prompt_tokens": summary.prompt_tokens,
        "total_tokens": summary.total_tokens,
        "reasoning_tokens": summary.reasoning_tokens,
        "stream_chunks": summary.stream_chunks,
        "ok": summary.ok,
        "samples": [
            {
                "model": s.model,
                "stream": s.stream,
                "latency_s": round(s.latency_s, 3),
                "ttft_s": round(s.ttft_s, 3) if s.ttft_s is not None else None,
                "overall_tps": round(s.overall_tps, 1),
                "generation_tps": round(s.generation_tps, 1) if s.generation_tps is not None else None,
                "server_tps": round(s.server_tps, 1) if s.server_tps is not None else None,
                "server_ttft_ms": round(s.server_ttft_ms, 1) if s.server_ttft_ms is not None else None,
                "completion_tokens": s.completion_tokens,
                "prompt_tokens": s.prompt_tokens,
                "total_tokens": s.total_tokens,
                "reasoning_tokens": s.reasoning_tokens,
                "stream_chunks": s.stream_chunks,
            }
            for s in summary.samples
        ],
    }
    if summary.error:
        payload["error"] = summary.error
    return payload


def benchmark_to_markdown_section(summary: BenchmarkSummary) -> list[str]:
    lines = ["## Throughput", ""]
    if summary.error:
        lines.append(f"Benchmark failed: {summary.error}")
        lines.append("")
        return lines

    mode = "streaming" if summary.stream else "non-streaming"
    lines.extend(
        [
            "| | |",
            "|---|---|",
            f"| **Mode** | {mode} |",
            f"| **Thinking** | {'on' if summary.thinking else 'off'} |",
            f"| **Runs** | {summary.runs} |",
            f"| **max_tokens** | {summary.max_tokens} |",
            f"| **Depth** | {summary.depth_tokens} |",
            f"| **Overall tok/s** | {summary.overall_tps:.1f} |",
            f"| **Generation tok/s** | {_fmt_tps(_reliable_generation_tps(summary))} |",
            f"| **Server-reported tok/s** | {_fmt_tps(summary.server_tps)} |",
            f"| **TTFT (client)** | {summary.ttft_s:.2f}s |" if summary.ttft_s is not None else "| **TTFT (client)** | — |",
            f"| **TTFT (server)** | {summary.server_ttft_ms:.0f}ms |" if summary.server_ttft_ms is not None else "| **TTFT (server)** | — |",
            f"| **Total latency** | {summary.latency_s:.2f}s |",
            f"| **Completion tokens** | {summary.completion_tokens} |",
            f"| **Prompt tokens** | {summary.prompt_tokens} |",
            f"| **Reasoning tokens** | {summary.reasoning_tokens or '—'} |",
            "",
        ]
    )
    return lines
