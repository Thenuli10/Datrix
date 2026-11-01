"""OpenAI implementation of LLMClient: structured outputs (Pydantic), tool calling,
vision (base64 PNG), retries on transient errors, and per-call logging to `llm_calls`.

Every request goes through `_call`, which enforces the spend caps (app.llm.budget), the
prompt-size cap and the output-token cap, so no agent can bypass them."""
import base64
import json
import logging
import time
from typing import Any, Callable

import openai
from openai import OpenAI
from pydantic import BaseModel

from app.core.config import settings
from app.llm.base import LLMBudgetExceeded, LLMClient, LLMError, T, Tool, current_run_id
from app.llm.budget import check_budget

__all__ = ["LLMBudgetExceeded", "LLMError", "OpenAIClient", "estimate_cost"]

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

UNKNOWN_MODEL_PRICE = (5.00, 20.00)

TRANSIENT =(openai.RateLimitError, openai.APITimeoutError, openai.APIConnectionError, openai.InternalServerError)
MAX_TRIES = 3  # 1 request + 2 retries on transient errors (SDK retries are off)
REQUEST_TIMEOUT_S = 180


def estimate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    match = max((k for k in PRICES if model.startswith(k)), key=len, default=None)
    # Unknown model: assume a high price so the spend caps still bite (fail safe, never $0).
    p_in, p_out = PRICES[match] if match else UNKNOWN_MODEL_PRICE
    return (prompt_tokens * p_in + completion_tokens * p_out) / 1_000_000


def max_output_tokens(agent: str) -> int:
    """max_completion_tokens per request: code generation gets the larger cap."""
    return settings.llm_max_output_tokens if agent == "coder" else settings.llm_max_output_tokens_other


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
    for png in images[:settings.llm_max_images]:
        url = "data:image/png;base64," + base64.b64encode(png).decode("ascii")
        parts.append({"type": "image_url", "image_url": {"url": url, "detail": settings.llm_vision_detail}})
    return parts


def _text_chars(messages: list[dict[str, Any]]) -> int:
    """Characters of text in a request (images excluded)."""
    n = 0
    for m in messages:
        c = m.get("content")
        if isinstance(c, str):
            n += len(c)
        elif isinstance(c, list):
            n += sum(len(p.get("text", "")) for p in c if isinstance(p, dict))
        n += sum(len(tc["function"]["arguments"] or "") for tc in m.get("tool_calls") or [])
    return n


def _tool_output(fn: Callable[..., Any], raw_args: str) -> str:
    """Run a tool; errors are returned to the model as text instead of raising."""
    try:
        args = json.loads(raw_args or "{}")
        out = fn(**args)
        text = out if isinstance(out, str) else json.dumps(out, default=str)
    except Exception as e:  # noqa: BLE001 - tool errors go back to the model
        text = f"ERROR: {type(e).__name__}: {e}"
    cap = settings.llm_tool_output_chars
    return text if len(text) <= cap else text[:cap] + f"\n...[truncated, {len(text) - cap} more chars]"


class OpenAIClient(LLMClient):
    def __init__(self, client: Any | None = None, sleep: Callable[[float], None] = time.sleep) -> None:
        self.client = client or OpenAI(api_key=settings.openai_api_key, max_retries=0, timeout=REQUEST_TIMEOUT_S)
        self._sleep = sleep

    # -- plumbing ---------------------------------------------------------------
    def _parse_fn(self) -> Callable[..., Any]:
        chat = self.client.chat.completions
        return chat.parse if hasattr(chat, "parse") else self.client.beta.chat.completions.parse

    @staticmethod
    def _check_budget(project_id: int | None, run_id: int | None) -> None:
        check_budget(project_id, run_id)

    def _call(self, fn: Callable[..., Any], *, agent: str, project_id: int | None, **kwargs: Any) -> Any:
        """The single gateway to the API: size + spend caps, output cap, transient retries, usage logging."""
        run_id = current_run_id.get()
        chars = _text_chars(kwargs["messages"])
        if chars > settings.llm_max_input_chars:
            raise LLMBudgetExceeded(f"{agent}: prompt is {chars} chars, over LLM_MAX_INPUT_CHARS="
                                    f"{settings.llm_max_input_chars}; no request was sent.")
        kwargs["max_completion_tokens"] = max_output_tokens(agent)
        model = kwargs.get("model", "")
        for attempt in range(MAX_TRIES):
            self._check_budget(project_id, run_id)
            start = time.perf_counter()
            try:
                resp = fn(**kwargs)
            except TRANSIENT as e:
                if attempt == MAX_TRIES - 1:
                    raise
                log.warning("LLM transient error (%s), retry %d: %s", agent, attempt + 1, e)
                self._sleep(2 ** attempt)
                continue
            except openai.LengthFinishReasonError as e:  # structured answer cut off; tokens were still billed
                self._log(agent, model, e.completion, time.perf_counter() - start, project_id, run_id)
                raise LLMError(f"{agent}: answer exceeded max_completion_tokens={kwargs['max_completion_tokens']} "
                               "(see LLM_MAX_OUTPUT_TOKENS_OTHER / LLM_MAX_OUTPUT_TOKENS)") from e
            self._log(agent, model, resp, time.perf_counter() - start, project_id, run_id)
            return resp
        raise AssertionError("unreachable")

    @staticmethod
    def _log(agent: str, model: str, resp: Any, latency: float, project_id: int | None,
             run_id: int | None = None) -> None:
        """Persist an LLMCall row; never raises."""
        try:
            from sqlmodel import Session

            from app.core.db import engine
            from app.models.tables import LLMCall

            usage = getattr(resp, "usage", None)
            pt = int(getattr(usage, "prompt_tokens", 0) or 0)
            ct = int(getattr(usage, "completion_tokens", 0) or 0)
            with Session(engine) as s:
                s.add(LLMCall(project_id=project_id, run_id=run_id, agent=agent, model=model, prompt_tokens=pt,
                              completion_tokens=ct, cost=estimate_cost(model, pt, ct), latency=latency))
                s.commit()
        except Exception as e:  # noqa: BLE001
            log.warning("LLM call logging failed (spend not recorded): %s", e)

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
        choice = resp.choices[0]
        if getattr(choice, "finish_reason", None) == "length":
            log.warning("%s: output cut off at max_completion_tokens=%d", agent, max_output_tokens(agent))
        return choice.message.content or ""

    def tool_loop(self, *, agent: str, system: str, user: str, tools: dict[str, Tool], schema: type[T],
                  project_id: int | None = None, model: str | None = None, max_steps: int = 12) -> T:
        """At most min(max_steps, settings.llm_tool_max_steps) tool rounds, then exactly 1 structured answer."""
        model = model or settings.openai_model
        specs = [{"type": "function", "function": {
            "name": name, "description": params.get("description") or (fn.__doc__ or "").strip(),
            "parameters": {k: v for k, v in params.items() if k != "description"}}}
            for name, (params, fn) in tools.items()]
        messages: list[dict[str, Any]] = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        tool_chars = 0
        for _ in range(min(max_steps, settings.llm_tool_max_steps)):
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
            for i, c in enumerate(calls):
                tool = tools.get(c.function.name)
                if i >= settings.llm_tool_max_calls_per_step:
                    out = "ERROR: too many tool calls in one step; this one was skipped"
                elif tool is None:
                    out = f"ERROR: unknown tool {c.function.name}"
                else:
                    out = _tool_output(tool[1], c.function.arguments)
                tool_chars += len(out)
                messages.append({"role": "tool", "tool_call_id": c.id, "content": out})
            if tool_chars >= settings.llm_tool_total_output_chars:
                log.info("%s: tool output budget used up; forcing the final answer", agent)
                break
        messages.append({"role": "user", "content": "Now give your final answer in the required structured format."})
        return self._parse(agent=agent, messages=messages, schema=schema, model=model, project_id=project_id)
