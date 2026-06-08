"""Throughput benchmark for OpenAI-compatible APIs."""

from __future__ import annotations

import statistics
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


@dataclass
class BenchmarkSample:
    model: str
    stream: bool
    latency_s: float
    ttft_s: float | None
    decode_tps: float
    e2e_tps: float
    completion_tokens: int
    prompt_tokens: int
    total_tokens: int


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
    decode_tps: float
    e2e_tps: float
    completion_tokens: int
    prompt_tokens: int
    total_tokens: int
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


def bench_once_blocking(client: OpenAI, model: str, prompt: str, max_tokens: int) -> BenchmarkSample:
    started = time.perf_counter()
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=max_tokens,
        temperature=0.2,
    )
    elapsed = time.perf_counter() - started

    usage = resp.usage
    completion_tokens = int(usage.completion_tokens or 0) if usage else 0
    prompt_tokens = int(usage.prompt_tokens or 0) if usage else 0
    total_tokens = int(usage.total_tokens or (prompt_tokens + completion_tokens)) if usage else 0
    response_model = str(resp.model or model)
    tps = (completion_tokens / elapsed) if elapsed > 0 else 0.0
    return BenchmarkSample(
        model=response_model,
        stream=False,
        latency_s=elapsed,
        ttft_s=None,
        decode_tps=tps,
        e2e_tps=tps,
        completion_tokens=completion_tokens,
        prompt_tokens=prompt_tokens,
        total_tokens=total_tokens,
    )


def bench_once_stream(client: OpenAI, model: str, prompt: str, max_tokens: int) -> BenchmarkSample:
    started = time.perf_counter()
    tok_times: list[float] = []
    first_tok: float | None = None
    response_model = model
    usage_completion = 0
    usage_prompt = 0
    usage_total = 0

    stream = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=max_tokens,
        temperature=0.2,
        stream=True,
        stream_options=cast(Any, {"include_usage": True}),
    )
    for chunk in stream:
        if chunk.model:
            response_model = str(chunk.model)
        if chunk.usage is not None:
            usage_completion = int(chunk.usage.completion_tokens or 0)
            usage_prompt = int(chunk.usage.prompt_tokens or 0)
            usage_total = int(chunk.usage.total_tokens or 0)
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta
        piece = _content_text(getattr(delta, "content", None))
        if piece:
            now = time.perf_counter()
            if first_tok is None:
                first_tok = now
            tok_times.append(now)

    end = time.perf_counter()
    if first_tok is None:
        raise RuntimeError("Stream produced no content tokens")

    ttft = first_tok - started
    inter = [t2 - t1 for t1, t2 in zip(tok_times, tok_times[1:], strict=False)]
    median_inter = statistics.median(inter) if inter else 0.0
    decode_tps = (1.0 / median_inter) if median_inter > 0 else 0.0

    completion_tokens = usage_completion or len(tok_times)
    prompt_tokens = usage_prompt
    total_tokens = usage_total or (prompt_tokens + completion_tokens)
    decode_window = end - first_tok
    e2e_tps = (completion_tokens / decode_window) if decode_window > 0 else 0.0

    return BenchmarkSample(
        model=response_model,
        stream=True,
        latency_s=end - started,
        ttft_s=ttft,
        decode_tps=decode_tps,
        e2e_tps=e2e_tps,
        completion_tokens=completion_tokens,
        prompt_tokens=prompt_tokens,
        total_tokens=total_tokens,
    )


def _avg(samples: list[BenchmarkSample], key: str) -> float:
    vals = [getattr(s, key) for s in samples if getattr(s, key) is not None]
    return (sum(vals) / len(vals)) if vals else 0.0


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
        latency_s=0.0,
        ttft_s=None,
        decode_tps=0.0,
        e2e_tps=0.0,
        completion_tokens=0,
        prompt_tokens=0,
        total_tokens=0,
    )
    try:
        samples: list[BenchmarkSample] = []
        current_model = model
        for _ in range(config.runs):
            if config.stream:
                sample = bench_once_stream(client, current_model, prompt, config.max_tokens)
            else:
                sample = bench_once_blocking(client, current_model, prompt, config.max_tokens)
            samples.append(sample)
            current_model = sample.model

        last = samples[-1]
        summary.model = last.model
        summary.samples = samples
        summary.latency_s = _avg(samples, "latency_s")
        summary.ttft_s = _avg(samples, "ttft_s") if config.stream else None
        summary.decode_tps = _avg(samples, "decode_tps")
        summary.e2e_tps = _avg(samples, "e2e_tps")
        summary.completion_tokens = last.completion_tokens
        summary.prompt_tokens = last.prompt_tokens
        summary.total_tokens = last.total_tokens
    except Exception as exc:
        summary.error = str(exc)
    return summary


def print_benchmark(summary: BenchmarkSummary) -> None:
    section("Throughput benchmark")
    if summary.error:
        print(f"Benchmark failed: {summary.error}")
        return

    mode = "streaming (true decode)" if summary.stream else "non-streaming (end-to-end)"
    print(f"Target: {summary.base_url}")
    print(
        f"Mode: {mode}  |  runs: {summary.runs}  |  "
        f"max_tokens: {summary.max_tokens}  |  depth: {summary.depth_tokens}"
    )
    print("")
    if summary.stream:
        print(f"{'Model':<28} {'Decode tok/s':>13} {'TTFT':>9} {'Compl':>7} {'Prompt':>8}")
        print(f"{'-' * 28} {'-' * 13} {'-' * 9} {'-' * 7} {'-' * 8}")
        ttft = summary.ttft_s if summary.ttft_s is not None else 0.0
        print(
            f"{summary.model:<28} "
            f"{summary.decode_tps:>13.1f} "
            f"{ttft:>8.2f}s "
            f"{summary.completion_tokens:>7} "
            f"{summary.prompt_tokens:>8}"
        )
        print("")
        print(
            f"decode tok/s = 1/median(inter-token); end-to-end decode tok/s = "
            f"{summary.e2e_tps:.1f}"
        )
    else:
        print(f"{'Model':<28} {'Tok/s':>10} {'Latency':>10} {'Compl':>7} {'Prompt':>8}")
        print(f"{'-' * 28} {'-' * 10} {'-' * 10} {'-' * 7} {'-' * 8}")
        print(
            f"{summary.model:<28} "
            f"{summary.e2e_tps:>10.1f} "
            f"{summary.latency_s:>9.2f}s "
            f"{summary.completion_tokens:>7} "
            f"{summary.prompt_tokens:>8}"
        )
    if summary.runs > 1:
        print("")
        print(f"Averaged over {summary.runs} runs.")


def benchmark_to_json(summary: BenchmarkSummary) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "stream": summary.stream,
        "runs": summary.runs,
        "max_tokens": summary.max_tokens,
        "depth_tokens": summary.depth_tokens,
        "latency_s": round(summary.latency_s, 3),
        "ttft_s": round(summary.ttft_s, 3) if summary.ttft_s is not None else None,
        "decode_tps": round(summary.decode_tps, 1),
        "e2e_tps": round(summary.e2e_tps, 1),
        "completion_tokens": summary.completion_tokens,
        "prompt_tokens": summary.prompt_tokens,
        "total_tokens": summary.total_tokens,
        "ok": summary.ok,
        "samples": [
            {
                "model": s.model,
                "stream": s.stream,
                "latency_s": round(s.latency_s, 3),
                "ttft_s": round(s.ttft_s, 3) if s.ttft_s is not None else None,
                "decode_tps": round(s.decode_tps, 1),
                "e2e_tps": round(s.e2e_tps, 1),
                "completion_tokens": s.completion_tokens,
                "prompt_tokens": s.prompt_tokens,
                "total_tokens": s.total_tokens,
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

    mode = "streaming (true decode)" if summary.stream else "non-streaming (end-to-end)"
    lines.extend(
        [
            "| | |",
            "|---|---|",
            f"| **Mode** | {mode} |",
            f"| **Runs** | {summary.runs} |",
            f"| **max_tokens** | {summary.max_tokens} |",
            f"| **Depth** | {summary.depth_tokens} |",
            f"| **Decode tok/s** | {summary.decode_tps:.1f} |",
            f"| **TTFT** | {summary.ttft_s:.2f}s |" if summary.ttft_s is not None else "| **TTFT** | — |",
            f"| **End-to-end decode tok/s** | {summary.e2e_tps:.1f} |",
            f"| **Completion tokens** | {summary.completion_tokens} |",
            f"| **Prompt tokens** | {summary.prompt_tokens} |",
            "",
        ]
    )
    return lines
