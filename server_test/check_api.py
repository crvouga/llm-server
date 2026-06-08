#!/usr/bin/env python3
"""Unified OpenAI-compatible API check: smoke tests + throughput benchmark.

Usage:
  pip install -r server_test/requirements.txt
  python3 server_test/check_api.py
  LLM_BASE_URL=http://localhost:8888 python3 server_test/check_api.py --json
  python3 server_test/check_api.py --smoke-only
  python3 server_test/check_api.py --bench-only
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

try:
    from openai import OpenAI
except ImportError:
    print(
        "Missing openai package. Install with: pip install -r server_test/requirements.txt",
        file=sys.stderr,
    )
    sys.exit(1)

from benchmark import (
    BenchmarkConfig,
    BenchmarkSummary,
    benchmark_to_json,
    benchmark_to_markdown_section,
    print_benchmark,
    run_benchmark,
)
from model_info import (
    ModelInfo,
    fetch_model_info,
    model_info_to_json,
    model_info_to_markdown_section,
    print_model_info,
    probe_runtime_info,
)
from smoke import (
    RunSummary,
    TestContext,
    info,
    print_summary,
    resolve_model,
    run_tests,
    section,
    summary_to_json,
    summary_to_markdown_section,
)

DEFAULT_BASE_URL = "https://llm-proxy.chrisvouga.dev"
DEFAULT_API_KEY = "sk-local"
DEFAULT_TIMEOUT = 120.0
DEFAULT_USER_AGENT = "llm-server-check/1.0"


def env_first(*names: str, default: str = "") -> str:
    for name in names:
        value = os.environ.get(name)
        if value is not None and value != "":
            return value
    return default


def env_first_float(*names: str, default: float) -> float:
    raw = env_first(*names, default=str(default))
    return float(raw)


def env_first_int(*names: str, default: int) -> int:
    raw = env_first(*names, default=str(default))
    return int(raw)


def env_first_bool(*names: str, default: bool) -> bool:
    raw = env_first(*names, default="1" if default else "0").lower()
    return raw in ("1", "true", "yes", "on")


def normalize_base_url(url: str) -> str:
    base = url.rstrip("/")
    if not base.endswith("/v1"):
        base = f"{base}/v1"
    return base


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check an OpenAI-compatible API: smoke tests and throughput benchmark.",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--smoke-only",
        action="store_true",
        help="Run smoke tests only",
    )
    mode.add_argument(
        "--bench-only",
        action="store_true",
        help="Run throughput benchmark only",
    )
    parser.add_argument(
        "--base-url",
        default=env_first("LLM_BASE_URL", "BENCH_URL", default=DEFAULT_BASE_URL),
        help=f"API base URL (default: {DEFAULT_BASE_URL})",
    )
    parser.add_argument(
        "--model",
        default=env_first("LLM_MODEL", "BENCH_MODEL"),
        help="Model id (default: first from /v1/models)",
    )
    parser.add_argument(
        "--api-key",
        default=env_first("OPENAI_API_KEY", default=DEFAULT_API_KEY),
        help="API key (default: sk-local)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=env_first_float("LLM_TIMEOUT", "BENCH_TIMEOUT", default=DEFAULT_TIMEOUT),
        help=f"Request timeout in seconds (default: {DEFAULT_TIMEOUT})",
    )
    parser.add_argument(
        "--user-agent",
        default=env_first(
            "LLM_USER_AGENT",
            "BENCH_USER_AGENT",
            default=DEFAULT_USER_AGENT,
        ),
        help=f"HTTP User-Agent (default: {DEFAULT_USER_AGENT})",
    )
    parser.add_argument(
        "--skip-tools",
        action="store_true",
        help="Skip tool-calling tests when the model does not support them",
    )
    parser.add_argument(
        "--bench-runs",
        type=int,
        default=env_first_int("LLM_BENCH_RUNS", "BENCH_RUNS", default=3),
        help="Benchmark timed runs (default: 3)",
    )
    parser.add_argument(
        "--bench-max-tokens",
        type=int,
        default=env_first_int("LLM_BENCH_MAX_TOKENS", "BENCH_MAX_TOKENS", default=512),
        help="Benchmark completion token cap per run (default: 512)",
    )
    parser.add_argument(
        "--bench-stream",
        type=int,
        choices=[0, 1],
        default=1 if env_first_bool("LLM_BENCH_STREAM", "BENCH_STREAM", default=True) else 0,
        help="1 = streaming decode metrics, 0 = end-to-end (default: 1)",
    )
    parser.add_argument(
        "--bench-depth",
        type=int,
        default=env_first_int("LLM_BENCH_DEPTH", "BENCH_DEPTH", default=0),
        help="Prompt-depth padding in ~tokens (default: 0)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON summary to stdout",
    )
    parser.add_argument(
        "--json-out",
        metavar="PATH",
        help="Write JSON summary to a file",
    )
    parser.add_argument(
        "--markdown-out",
        metavar="PATH",
        help="Write GitHub-friendly Markdown report to a file",
    )
    return parser.parse_args(argv)


def build_client(
    base_url: str,
    api_key: str,
    timeout: float,
    user_agent: str = DEFAULT_USER_AGENT,
) -> OpenAI:
    bench_timeout = max(DEFAULT_TIMEOUT, timeout)
    return OpenAI(
        base_url=base_url,
        api_key=api_key,
        timeout=bench_timeout,
        default_headers={"User-Agent": user_agent},
    )


def combined_to_json(
    base_url: str,
    model: str,
    smoke: RunSummary | None,
    benchmark: BenchmarkSummary | None,
    model_info: ModelInfo | None = None,
) -> dict[str, Any]:
    smoke_ok = smoke is None or smoke.failed == 0
    bench_ok = benchmark is None or benchmark.ok
    payload: dict[str, Any] = {
        "base_url": base_url,
        "model": model,
        "ok": smoke_ok and bench_ok,
    }
    if model_info is not None:
        payload["model_info"] = model_info_to_json(model_info)
    if smoke is not None:
        payload["smoke"] = summary_to_json(smoke)
    if benchmark is not None:
        payload["benchmark"] = benchmark_to_json(benchmark)
    return payload


def _apply_smoke_capabilities(model_info: ModelInfo | None, smoke: RunSummary | None) -> None:
    if model_info is None or smoke is None:
        return
    passed = {r.name for r in smoke.results if r.passed and not r.skipped}
    if "tool_calling" in passed or "tool_round_trip" in passed:
        model_info.supports_tools = True


def combined_to_markdown(
    base_url: str,
    model: str,
    smoke: RunSummary | None,
    benchmark: BenchmarkSummary | None,
    model_info: ModelInfo | None = None,
) -> str:
    smoke_ok = smoke is None or smoke.failed == 0
    bench_ok = benchmark is None or benchmark.ok
    ok_overall = smoke_ok and bench_ok
    status_line = "✅ **All checks passed**" if ok_overall else "❌ **Some checks failed**"
    lines = [
        "# OpenAI-compatible API check",
        "",
        status_line,
        "",
        "| | |",
        "|---|---|",
        f"| **Target** | `{base_url}` |",
        f"| **Model** | `{model}` |",
    ]
    if smoke is not None:
        lines.append(f"| **Smoke passed** | {smoke.passed} |")
        lines.append(f"| **Smoke failed** | {smoke.failed} |")
        lines.append(f"| **Smoke skipped** | {smoke.skipped} |")
    if benchmark is not None and benchmark.ok:
        lines.append(f"| **Overall tok/s** | {benchmark.overall_tps:.1f} |")
        if benchmark.server_tps is not None:
            lines.append(f"| **Server-reported tok/s** | {benchmark.server_tps:.1f} |")
        if benchmark.ttft_s is not None:
            lines.append(f"| **TTFT (client)** | {benchmark.ttft_s:.2f}s |")
    lines.append("")
    if model_info is not None:
        lines.extend(model_info_to_markdown_section(model_info))
    if smoke is not None:
        lines.extend(summary_to_markdown_section(smoke))
    if benchmark is not None:
        lines.extend(benchmark_to_markdown_section(benchmark))
    lines.extend(["---", "", "*Harness compatibility + throughput for Cursor, Claude Code, and similar clients.*"])
    return "\n".join(lines) + "\n"


def print_overall_summary(
    base_url: str,
    model: str,
    smoke: RunSummary | None,
    benchmark: BenchmarkSummary | None,
    model_info: ModelInfo | None = None,
) -> None:
    section("Overall")
    print(f"Target: {base_url}")
    print(f"Model:  {model}")
    if model_info is not None and model_info.context_window is not None:
        from model_info import format_context_window

        print(f"Context: {format_context_window(model_info)}")
    if smoke is not None:
        print(
            f"Smoke: {smoke.passed} passed, {smoke.failed} failed, "
            f"{smoke.skipped} skipped"
        )
    if benchmark is not None:
        if benchmark.ok:
            line = f"Throughput: {benchmark.overall_tps:.1f} tok/s overall"
            if benchmark.server_tps is not None:
                line += f", {benchmark.server_tps:.1f} server-reported"
            if benchmark.ttft_s is not None:
                line += f", TTFT {benchmark.ttft_s:.2f}s"
            print(line)
        else:
            print(f"Benchmark: failed ({benchmark.error})")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    base_url = normalize_base_url(args.base_url)
    run_smoke = not args.bench_only
    run_bench = not args.smoke_only
    quiet = args.json or bool(args.json_out) or bool(args.markdown_out)

    client = build_client(base_url, args.api_key, args.timeout, args.user_agent)
    model = args.model.strip()

    smoke_summary: RunSummary | None = None
    bench_summary: BenchmarkSummary | None = None
    model_info: ModelInfo | None = None

    if model == "" and (run_smoke or run_bench):
        model = resolve_model(client, "")

    if model:
        model_info = fetch_model_info(client, model)
        probe_runtime_info(client, model, model_info)
        if not quiet:
            print_model_info(model_info)

    if run_smoke:
        if not quiet:
            section("OpenAI-compatible API smoke tests")
            info(f"Target: {base_url}")
        ctx = TestContext(
            client=client,
            model=model,
            skip_tools=args.skip_tools,
            quiet=quiet,
        )
        smoke_summary = run_tests(ctx)
        model = smoke_summary.model
        if model_info is None or model_info.id != model:
            model_info = fetch_model_info(client, model)
        _apply_smoke_capabilities(model_info, smoke_summary)
        if not quiet and not run_bench:
            print_summary(smoke_summary)

    if run_bench:
        if smoke_summary is not None and smoke_summary.failed > 0:
            if not quiet:
                section("Throughput benchmark")
                print("Skipped benchmark because smoke tests failed.")
        else:
            if model == "":
                model = resolve_model(client, "")
            bench_summary = run_benchmark(
                client,
                model,
                BenchmarkConfig(
                    max_tokens=args.bench_max_tokens,
                    runs=args.bench_runs,
                    stream=bool(args.bench_stream),
                    depth=args.bench_depth,
                ),
            )
            if bench_summary.model:
                model = bench_summary.model
            if model_info is not None and bench_summary.reasoning_tokens > 0:
                model_info.supports_reasoning = True
            if not quiet:
                print_benchmark(bench_summary)

    payload = combined_to_json(base_url, model, smoke_summary, bench_summary, model_info)

    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)
            fh.write("\n")

    if args.markdown_out:
        with open(args.markdown_out, "w", encoding="utf-8") as fh:
            fh.write(
                combined_to_markdown(
                    base_url, model, smoke_summary, bench_summary, model_info
                )
            )

    if args.json:
        print(json.dumps(payload, indent=2))
    elif not quiet:
        if run_smoke and run_bench:
            print_overall_summary(
                base_url, model, smoke_summary, bench_summary, model_info
            )
        elif run_smoke and smoke_summary is not None:
            print_summary(smoke_summary)

    smoke_ok = smoke_summary is None or smoke_summary.failed == 0
    bench_ok = bench_summary is None or bench_summary.ok
    return 0 if smoke_ok and bench_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
