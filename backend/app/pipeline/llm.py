"""Pluggable LLM providers with a common tool-calling loop.

Anthropic is the default. OpenAI and Azure OpenAI use function calling with the same tool specs, so the
agent code does not change when a carrier switches providers."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from ..config import get_settings

# USD per million tokens (input, output), from the providers' public pricing pages (Nov 2026).
# Unknown models report cost as None rather than guessing.
PRICING: dict[str, tuple[float, float]] = {
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-sonnet-5-5": (2.0, 10.0),
    "claude-sonnet-5": (2.0, 10.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-sonnet-4-5-20250929": (3.0, 15.0),
    "claude-haiku-4-5-20251001": (1.0, 5.0),
    "claude-opus-5-5": (4.0, 20.0),
    "gpt-5.4-mini": (0.75, 4.50),
    "gpt-5.4-nano": (0.20, 1.25),
    "gpt-5.4": (2.50, 15.0),
}


@dataclass
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]
    handler: Callable[[dict[str, Any]], dict[str, Any]] | None = None  # None => terminal tool


@dataclass
class Usage:
    model: str = ""
    provider: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    calls: int = 0
    latency_ms: int = 0

    @property
    def cost_usd(self) -> float | None:
        price = PRICING.get(self.model)
        if not price:
            return None
        return round(self.input_tokens / 1e6 * price[0] + self.output_tokens / 1e6 * price[1], 6)

    def add(self, other: Usage) -> None:
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens
        self.calls += other.calls
        self.latency_ms += other.latency_ms
        self.model = self.model or other.model
        self.provider = self.provider or other.provider

    def as_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "calls": self.calls,
            "latency_ms": self.latency_ms,
            "cost_usd": self.cost_usd,
        }


@dataclass
class LoopResult:
    final_input: dict[str, Any]
    usage: Usage
    trace: list[dict[str, Any]] = field(default_factory=list)


class LLMError(RuntimeError):
    pass


def _run_handler(spec: ToolSpec, args: dict[str, Any]) -> dict[str, Any]:
    assert spec.handler is not None
    try:
        return spec.handler(args)
    except Exception as e:  # tool errors go back to the model, not up the stack
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, model: str) -> None:
        import anthropic

        key = get_settings().anthropic_api_key
        if not key:
            raise LLMError("ANTHROPIC_API_KEY is not set")
        self.client = anthropic.Anthropic(api_key=key, max_retries=3, timeout=120)
        self.model = model

    def run_tools(self, system: str, user: str, tools: list[ToolSpec], final_tool: str, max_steps: int) -> LoopResult:
        by_name = {t.name: t for t in tools}
        api_tools = [{"name": t.name, "description": t.description, "input_schema": t.input_schema} for t in tools]
        messages: list[dict[str, Any]] = [{"role": "user", "content": user}]
        usage = Usage(model=self.model, provider=self.name)
        trace: list[dict[str, Any]] = []
        for step in range(max_steps):
            force = step == max_steps - 1 or len(tools) == 1
            t0 = time.perf_counter()
            resp = self.client.messages.create(  # type: ignore[call-overload]
                model=self.model,
                max_tokens=4096,
                system=system,
                tools=api_tools,
                tool_choice={"type": "tool", "name": final_tool} if force else {"type": "any"},
                messages=messages,
            )
            ms = int((time.perf_counter() - t0) * 1000)
            usage.add(
                Usage(
                    input_tokens=resp.usage.input_tokens, output_tokens=resp.usage.output_tokens, calls=1, latency_ms=ms
                )
            )
            messages.append({"role": "assistant", "content": resp.content})
            results = []
            for b in resp.content:
                if b.type != "tool_use":
                    continue
                if b.name == final_tool:
                    trace.append({"step": step, "tool": final_tool, "latency_ms": ms})
                    return LoopResult(final_input=dict(b.input), usage=usage, trace=trace)
                spec = by_name.get(b.name)
                out = _run_handler(spec, dict(b.input)) if spec and spec.handler else {"error": "unknown tool"}
                trace.append({"step": step, "tool": b.name, "input": b.input, "output": out, "latency_ms": ms})
                results.append({"type": "tool_result", "tool_use_id": b.id, "content": json.dumps(out)})
            if not results:
                messages.append({"role": "user", "content": f"Call {final_tool} now."})
            else:
                messages.append({"role": "user", "content": results})
        raise LLMError(f"Model did not call {final_tool} within {max_steps} steps")


class OpenAICompatProvider:
    """OpenAI and Azure OpenAI (function calling)."""

    def __init__(self, model: str, azure: bool = False) -> None:
        import openai

        s = get_settings()
        if azure:
            if not (s.azure_openai_endpoint and s.azure_openai_api_key):
                raise LLMError("AZURE_OPENAI_ENDPOINT / AZURE_OPENAI_API_KEY are not set")
            self.client: Any = openai.AzureOpenAI(
                azure_endpoint=s.azure_openai_endpoint,
                api_key=s.azure_openai_api_key,
                api_version=s.azure_openai_api_version,
            )
            self.model = s.azure_openai_deployment or model
            self.name = "azure_openai"
        else:
            if not s.openai_api_key:
                raise LLMError("OPENAI_API_KEY is not set")
            self.client = openai.OpenAI(api_key=s.openai_api_key)
            self.model = model
            self.name = "openai"

    def run_tools(self, system: str, user: str, tools: list[ToolSpec], final_tool: str, max_steps: int) -> LoopResult:
        by_name = {t.name: t for t in tools}
        api_tools = [
            {
                "type": "function",
                "function": {"name": t.name, "description": t.description, "parameters": t.input_schema},
            }
            for t in tools
        ]
        messages: list[dict[str, Any]] = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        usage = Usage(model=self.model, provider=self.name)
        trace: list[dict[str, Any]] = []
        for step in range(max_steps):
            force = step == max_steps - 1 or len(tools) == 1
            t0 = time.perf_counter()
            # Reasoning-family models (gpt-5*, o*) reject a temperature setting.
            extra: dict[str, Any] = {} if self.model.startswith(("gpt-5", "o")) else {"temperature": 0}
            resp = self.client.chat.completions.create(
                model=self.model,
                **extra,
                messages=messages,
                tools=api_tools,
                tool_choice={"type": "function", "function": {"name": final_tool}} if force else "required",
            )
            ms = int((time.perf_counter() - t0) * 1000)
            if resp.usage:
                usage.add(
                    Usage(
                        input_tokens=resp.usage.prompt_tokens,
                        output_tokens=resp.usage.completion_tokens,
                        calls=1,
                        latency_ms=ms,
                    )
                )
            msg = resp.choices[0].message
            messages.append(msg.model_dump(exclude_none=True))
            for tc in msg.tool_calls or []:
                args = json.loads(tc.function.arguments or "{}")
                if tc.function.name == final_tool:
                    trace.append({"step": step, "tool": final_tool, "latency_ms": ms})
                    return LoopResult(final_input=args, usage=usage, trace=trace)
                spec = by_name.get(tc.function.name)
                out = _run_handler(spec, args) if spec and spec.handler else {"error": "unknown tool"}
                trace.append({"step": step, "tool": tc.function.name, "input": args, "output": out, "latency_ms": ms})
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": json.dumps(out)})
        raise LLMError(f"Model did not call {final_tool} within {max_steps} steps")


def get_provider(provider: str, model: str) -> AnthropicProvider | OpenAICompatProvider:
    if provider == "anthropic":
        return AnthropicProvider(model)
    if provider == "openai":
        return OpenAICompatProvider(model)
    if provider == "azure_openai":
        return OpenAICompatProvider(model, azure=True)
    raise LLMError(f"Unknown LLM provider '{provider}'")
