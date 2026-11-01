"""OpenAI implementation of LLMClient: structured outputs (Pydantic), tool calling,
vision (base64 PNG), retries on transient errors, and per-call logging to `llm_calls`."""
import base64
import json
import logging
import time
from typing import Any, Callable

import openai
from openai import OpenAI
from pydantic import BaseModel

from app.core.config import settings
from app.llm.base import LLMClient, T, Tool

log = logging.getLogger(__name__)

# USD per 1M tokens (input, output); matched by longest model-name prefix. Rough estimates only.
PRICES: dict[str, tuple[float, float]] = {
    "gpt-4.1": (2.00, 8.00),
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4.1-nano": (0.10, 0.40),
    "gpt-4o": (2.50, 10.00),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-5": (1.25, 10.00),
    "gpt-5-mini": (0.25, 2.00),
    "gpt-5-nano": (0.05, 0.40),
    "o3": (2.00, 8.00),
    "o4-mini": (1.10, 4.40),
}

TRANSIENT = (openai.RateLimitError, openai.APITimeoutError, openai.APIConnectionError, openai.InternalServerError)
MAX_TRIES = 3
MAX_TOOL_OUTPUT = 20_000  # chars per tool result sent back to the model


class LLMError(RuntimeError):
    """The model refused or returned no parsable answer."""


def estimate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    match = max((k for k in PRICES if model.startswith(k)), key=len, default=None)
    if match is None:
        return 0.0
    p_in, p_out = PRICES[match]
    return (prompt_tokens * p_in + completion_tokens * p_out) / 1_000_000


def _strip_defaults(node: Any) -> Any:
    """Strict mode rejects `default`; the SDK only strips `None` defaults."""
    if isinstance(node, dict):
        return {k: _strip_defaults(v) for k, v in node.items() if k != "default"}
    if isinstance(node, list):
        return [_strip_defaults(v) for v in node]
    return node


def strict_response_format(schema: type[BaseModel]) -> dict[str, Any]:
    """json_schema response_format for a Pydantic model, safe for OpenAI strict mode."""
    from openai.lib._pydantic import to_strict_json_schema

    return {"type": "json_schema", "json_schema": {
        "name": schema.__name__, "strict": True, "schema": _strip_defaults(to_strict_json_schema(schema))}}


def _user_content(user: str, images: list[bytes] | None) -> str | list[dict[str, Any]]:
    if not images:
        return user
    parts: list[dict[str, Any]] = [{"type": "text", "text": user}]
    for png in images:
        url = "data:image/png;base64," + base64.b64encode(png).decode("ascii")
        parts.append({"type": "image_url", "image_url": {"url": url, "detail": "high"}})
    return parts


def _tool_output(fn: Callable[..., Any], raw_args: str) -> str:
    """Run a tool; errors are returned to the model as text instead of raising."""
    try:
        args = json.loads(raw_args or "{}")
        out = fn(**args)
        text = out if isinstance(out, str) else json.dumps(out, default=str)
    except Exception as e:  # noqa: BLE001 - tool errors go back to the model
        text = f"ERROR: {type(e).__name__}: {e}"
    return text[:MAX_TOOL_OUTPUT]


class OpenAIClient(LLMClient):
    def __init__(self, client: Any | None = None, sleep: Callable[[float], None] = time.sleep) -> None:
        self.client = client or OpenAI(api_key=settings.openai_api_key, max_retries=0, timeout=180)
        self._sleep = sleep

    # -- plumbing ---------------------------------------------------------------
    def _parse_fn(self) -> Callable[..., Any]:
        chat = self.client.chat.completions
        return chat.parse if hasattr(chat, "parse") else self.client.beta.chat.completions.parse

    def _call(self, fn: Callable[..., Any], *, agent: str, project_id: int | None, **kwargs: Any) -> Any:
        """Call the API with retries on transient errors, then log usage."""
        for attempt in range(MAX_TRIES):
            start = time.perf_counter()
            try:
                resp = fn(**kwargs)
            except TRANSIENT as e:
                if attempt == MAX_TRIES - 1:
                    raise
                log.warning("LLM transient error (%s), retry %d: %s", agent, attempt + 1, e)
                self._sleep(2 ** attempt)
                continue
            self._log(agent, kwargs.get("model", ""), resp, time.perf_counter() - start, project_id)
            return resp
        raise AssertionError("unreachable")

    @staticmethod
    def _log(agent: str, model: str, resp: Any, latency: float, project_id: int | None) -> None:
        """Persist an LLMCall row; never raises."""
        try:
            from sqlmodel import Session

            from app.core.db import engine
            from app.models.tables import LLMCall

            usage = getattr(resp, "usage", None)
            pt = int(getattr(usage, "prompt_tokens", 0) or 0)
            ct = int(getattr(usage, "completion_tokens", 0) or 0)
            with Session(engine) as s:
                s.add(LLMCall(project_id=project_id, agent=agent, model=model, prompt_tokens=pt,
                              completion_tokens=ct, cost=estimate_cost(model, pt, ct), latency=latency))
                s.commit()
        except Exception as e:  # noqa: BLE001
            log.debug("LLM call logging failed: %s", e)

    def _parse(self, *, agent: str, messages: list[dict[str, Any]], schema: type[T], model: str,
               project_id: int | None) -> T:
        resp = self._call(self._parse_fn(), agent=agent, project_id=project_id,
                          model=model, messages=messages, response_format=strict_response_format(schema))
        msg = resp.choices[0].message
        if getattr(msg, "parsed", None) is not None:
            return msg.parsed if isinstance(msg.parsed, schema) else schema.model_validate(msg.parsed)
        if getattr(msg, "content", None):
            return schema.model_validate_json(msg.content)
        raise LLMError(f"{agent}: no structured answer ({getattr(msg, 'refusal', None) or 'empty'})")

    # -- LLMClient ----------------------------------------------------------------
    def structured(self, *, agent: str, system: str, user: str, schema: type[T], project_id: int | None = None,
                   model: str | None = None, images: list[bytes] | None = None) -> T:
        messages = [{"role": "system", "content": system}, {"role": "user", "content": _user_content(user, images)}]
        return self._parse(agent=agent, messages=messages, schema=schema, model=model or settings.openai_model,
                           project_id=project_id)

    def text(self, *, agent: str, system: str, user: str, project_id: int | None = None,
             model: str | None = None) -> str:
        resp = self._call(self.client.chat.completions.create, agent=agent, project_id=project_id,
                          model=model or settings.openai_model,
                          messages=[{"role": "system", "content": system}, {"role": "user", "content": user}])
        return resp.choices[0].message.content or ""

    def tool_loop(self, *, agent: str, system: str, user: str, tools: dict[str, Tool], schema: type[T],
                  project_id: int | None = None, model: str | None = None, max_steps: int = 12) -> T:
        model = model or settings.openai_model
        specs = [{"type": "function", "function": {
            "name": name, "description": params.get("description") or (fn.__doc__ or "").strip(),
            "parameters": {k: v for k, v in params.items() if k != "description"}}}
            for name, (params, fn) in tools.items()]
        messages: list[dict[str, Any]] = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        for _ in range(max_steps):
            resp = self._call(self.client.chat.completions.create, agent=agent, project_id=project_id,
                              model=model, messages=messages, tools=specs, tool_choice="auto")
            msg = resp.choices[0].message
            calls = getattr(msg, "tool_calls", None) or []
            if not calls:
                if msg.content:
                    messages.append({"role": "assistant", "content": msg.content})
                break
            messages.append({"role": "assistant", "content": msg.content, "tool_calls": [
                {"id": c.id, "type": "function", "function": {"name": c.function.name,
                                                              "arguments": c.function.arguments}} for c in calls]})
            for c in calls:
                tool = tools.get(c.function.name)
                out = _tool_output(tool[1], c.function.arguments) if tool else f"ERROR: unknown tool {c.function.name}"
                messages.append({"role": "tool", "tool_call_id": c.id, "content": out})
        messages.append({"role": "user", "content": "Now give your final answer in the required structured format."})
        return self._parse(agent=agent, messages=messages, schema=schema, model=model, project_id=project_id)
