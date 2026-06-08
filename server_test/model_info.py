"""Fetch and format model / server metadata for API check reports."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote, urljoin

import httpx
from openai import OpenAI

# Documented server default when the API does not expose context length.
DEFAULT_ATLAS_CONTEXT_TOKENS = 131_072


@dataclass
class ModelInfo:
    id: str
    owned_by: str | None = None
    created: int | None = None
    health_status: str | None = None
    health_model: str | None = None
    system_fingerprint: str | None = None
    quantization: str | None = None
    parameter_hint: str | None = None
    context_window: int | None = None
    context_window_source: str | None = None
    supports_reasoning: bool | None = None
    supports_tools: bool | None = None
    extra: dict[str, Any] = field(default_factory=dict)


def _api_origin(client: OpenAI) -> str:
    base = str(client.base_url).rstrip("/")
    if base.endswith("/v1"):
        return base[: -len("/v1")]
    return base


def _client_headers(client: OpenAI) -> dict[str, str]:
    headers = dict(getattr(client, "default_headers", None) or {})
    api_key = getattr(client, "api_key", None)
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


def _get_json(client: OpenAI, path: str) -> dict[str, Any] | None:
    origin = _api_origin(client)
    url = urljoin(origin + "/", path.lstrip("/"))
    try:
        with httpx.Client(timeout=30.0, headers=_client_headers(client)) as http:
            resp = http.get(url)
            if resp.status_code == 200:
                data = resp.json()
                return data if isinstance(data, dict) else None
    except Exception:
        return None
    return None


def _parse_model_hints(model_id: str) -> tuple[str | None, str | None]:
    quant = None
    for pattern in (r"-(NVFP4|FP8|FP16|BF16|INT8|INT4)\b", r"_(NVFP4|FP8|FP16|BF16|INT8|INT4)\b"):
        if match := re.search(pattern, model_id, re.IGNORECASE):
            quant = match.group(1).upper()
            break
    param = None
    if match := re.search(r"(\d+(?:\.\d+)?[BMK])(?:-A\d+B)?", model_id, re.IGNORECASE):
        param = match.group(0)
    return quant, param


def _apply_context_from_payload(info: ModelInfo, payload: dict[str, Any], source: str) -> None:
    ctx = payload.get("max_model_len") or payload.get("context_length") or payload.get("max_seq_len")
    if ctx is not None:
        info.context_window = int(ctx)
        info.context_window_source = source


def fetch_model_info(client: OpenAI, model_id: str) -> ModelInfo:
    info = ModelInfo(id=model_id)
    info.quantization, info.parameter_hint = _parse_model_hints(model_id)

    try:
        models = client.models.list()
        for item in getattr(models, "data", None) or []:
            if item.id == model_id:
                info.owned_by = getattr(item, "owned_by", None)
                info.created = getattr(item, "created", None)
                if hasattr(item, "model_dump"):
                    raw = item.model_dump()
                    if isinstance(raw, dict):
                        _apply_context_from_payload(info, raw, "/v1/models")
                        info.extra.update(
                            {
                                k: v
                                for k, v in raw.items()
                                if k not in {"id", "object", "created", "owned_by"}
                            }
                        )
                break
    except Exception:
        pass

    if info.context_window is None:
        encoded = quote(model_id, safe="")
        detail = _get_json(client, f"/v1/models/{encoded}")
        if detail:
            _apply_context_from_payload(info, detail, f"/v1/models/{model_id}")
            info.extra.update(
                {k: v for k, v in detail.items() if k not in {"id", "object", "created", "owned_by"}}
            )

    health = _get_json(client, "/health")
    if health:
        info.health_status = health.get("status")
        info.health_model = health.get("model")
        _apply_context_from_payload(info, health, "/health")
        for key in ("engine", "backend", "kv_cache_dtype", "max_seq_len", "gpu"):
            if key in health:
                info.extra[key] = health[key]

    if info.context_window is None and (info.owned_by or "").startswith("atlas"):
        info.context_window = DEFAULT_ATLAS_CONTEXT_TOKENS
        info.context_window_source = "atlas default (not reported by API)"

    return info


def probe_runtime_info(client: OpenAI, model_id: str, info: ModelInfo) -> None:
    """Lightweight completion to capture fingerprint and server usage metadata."""
    try:
        resp = client.chat.completions.create(
            model=model_id,
            messages=[{"role": "user", "content": "ping"}],
            max_tokens=1,
            temperature=0.0,
        )
        info.system_fingerprint = resp.system_fingerprint
        enrich_from_usage(info, resp.usage)
    except Exception:
        pass


def enrich_from_usage(info: ModelInfo, usage: Any) -> None:
    if usage is None:
        return
    details = getattr(usage, "completion_tokens_details", None)
    if details is not None:
        reasoning = getattr(details, "reasoning_tokens", None)
        if reasoning is not None and int(reasoning) > 0:
            info.supports_reasoning = True


def format_context_window(info: ModelInfo) -> str:
    if info.context_window is None:
        return "not reported by API"
    tokens = info.context_window
    if tokens >= 1024:
        k = tokens / 1024
        label = f"{k:.0f}K" if k == int(k) else f"{k:.1f}K"
        return f"{tokens:,} tokens ({label})"
    return f"{tokens:,} tokens"


def print_model_info(info: ModelInfo) -> None:
    from smoke import section

    section("Model & server")
    print(f"Model:           {info.id}")
    if info.owned_by:
        print(f"Engine:          {info.owned_by}")
    if info.health_status:
        health_model = f" ({info.health_model})" if info.health_model else ""
        print(f"Health:          {info.health_status}{health_model}")
    if info.system_fingerprint:
        print(f"Fingerprint:     {info.system_fingerprint}")
    if info.parameter_hint:
        print(f"Parameters:      {info.parameter_hint}")
    if info.quantization:
        print(f"Quantization:    {info.quantization}")
    ctx = format_context_window(info)
    source = f" — {info.context_window_source}" if info.context_window_source else ""
    print(f"Context window:  {ctx}{source}")
    if info.supports_reasoning is True:
        print("Reasoning:       supported (reasoning tokens observed)")
    if info.supports_tools is True:
        print("Tool calling:    supported")
    if info.extra:
        for key, value in sorted(info.extra.items()):
            print(f"{key.replace('_', ' ').title():16} {value}")


def model_info_to_json(info: ModelInfo) -> dict[str, Any]:
    return {
        "id": info.id,
        "owned_by": info.owned_by,
        "created": info.created,
        "health_status": info.health_status,
        "health_model": info.health_model,
        "system_fingerprint": info.system_fingerprint,
        "quantization": info.quantization,
        "parameter_hint": info.parameter_hint,
        "context_window": info.context_window,
        "context_window_source": info.context_window_source,
        "supports_reasoning": info.supports_reasoning,
        "supports_tools": info.supports_tools,
        "extra": info.extra,
    }


def model_info_to_markdown_section(info: ModelInfo) -> list[str]:
    lines = ["## Model & server", "", "| | |", "|---|---|"]
    rows = [
        ("**Model**", f"`{info.id}`"),
        ("**Engine**", info.owned_by or "—"),
        ("**Health**", info.health_status or "—"),
        ("**Context window**", format_context_window(info)),
        ("**Quantization**", info.quantization or "—"),
        ("**Parameters**", info.parameter_hint or "—"),
        ("**Fingerprint**", info.system_fingerprint or "—"),
    ]
    if info.context_window_source:
        rows.append(("**Context source**", info.context_window_source))
    if info.supports_reasoning is True:
        rows.append(("**Reasoning**", "supported"))
    for key, value in rows:
        lines.append(f"| {key} | {value} |")
    lines.append("")
    return lines
