"""Deterministic offline LLM client for tests and `settings.llm_fake`.

Register canned responses per agent name; anything unregistered falls back to a
minimal valid instance of the requested schema (structured) or a per-agent default
string (text)."""
import inspect
import types
from typing import Any, Callable, Literal, Union, get_args, get_origin

from annotated_types import Ge, Gt
from pydantic import BaseModel
from pydantic.fields import FieldInfo

from app.llm.base import LLMClient, T, Tool

# Response: schema instance | dict | JSON/plain str | callable | list of those (consumed in order, last sticks)
Response = Any

FAKE_SCRIPT = '''import json, os
import pandas as pd


def run(input_dir: str, output_dir: str, params: dict) -> None:
    with open(os.path.join(input_dir, "manifest.json")) as f:
        manifest = json.load(f)
    rows = 0
    for f in manifest.get("files", []):
        rows += len(pd.read_parquet(os.path.join(input_dir, f["path"])))
    results = {"summary": {"title": "Summary", "rows_processed": rows},
               "kpis": [{"key": "row_count", "label": "Rows", "value": rows, "format": "integer"}]}
    with open(os.path.join(output_dir, "results.json"), "w") as f:
        json.dump(results, f)
'''

FAKE_SPOT_CHECK = '''def spot_check(input_dir: str) -> list[dict]:
    return []
'''

TEXT_DEFAULTS: dict[str, str] = {
    "coder": FAKE_SCRIPT,
    "coder_spot_check": FAKE_SPOT_CHECK,
    "insights": "## Key insights\n\n- No insights available (offline mode).",
}


def _min_int(info: FieldInfo | None) -> int:
    for m in (info.metadata if info else []):
        if isinstance(m, Ge):
            return int(m.ge)
        if isinstance(m, Gt):
            return int(m.gt) + 1
    return 0


def minimal_value(annotation: Any, info: FieldInfo | None = None) -> Any:
    """Smallest valid value for a type annotation (recursive for nested models)."""
    origin = get_origin(annotation)
    args = get_args(annotation)
    if annotation is Any or annotation is None or annotation is type(None):
        return None
    if origin is Literal:
        return args[0]
    if origin in (Union, types.UnionType):
        if type(None) in args:
            return None
        return minimal_value(args[0], info)
    if origin is not None and getattr(origin, "__name__", "") == "Annotated":
        return minimal_value(args[0], info)
    if origin in (list, set, frozenset) or annotation in (list, set, frozenset):
        return []
    if origin is tuple:
        if len(args) == 2 and args[1] is Ellipsis:
            return ()
        return tuple(minimal_value(a) for a in args)
    if origin is dict or annotation is dict:
        return {}
    if isinstance(annotation, type):
        if issubclass(annotation, BaseModel):
            return minimal_instance(annotation)
        if issubclass(annotation, bool):
            return False
        if issubclass(annotation, int):
            return _min_int(info)
        if issubclass(annotation, float):
            return float(_min_int(info))
        if issubclass(annotation, str):
            return "x"
    return None


def minimal_instance(schema: type[T]) -> T:
    """Build a minimal valid instance of a Pydantic model, filling only required fields."""
    data = {name: minimal_value(f.annotation, f) for name, f in schema.model_fields.items() if f.is_required()}
    return schema.model_validate(data)


class FakeLLMClient(LLMClient):
    """Offline client. `calls` records every request as a dict."""

    def __init__(self) -> None:
        self.responses: dict[str, list[Response]] = {}
        self.calls: list[dict[str, Any]] = []

    def register(self, agent: str, response: Response) -> None:
        """Register a response (or list of responses consumed in order) for an agent."""
        self.responses[agent] = list(response) if isinstance(response, list) else [response]

    def _next(self, agent: str) -> Response | None:
        queue = self.responses.get(agent)
        if not queue:
            return None
        return queue.pop(0) if len(queue) > 1 else queue[0]

    def _record(self, kind: str, agent: str, system: str, user: str, **extra: Any) -> None:
        self.calls.append({"kind": kind, "agent": agent, "system": system, "user": user, **extra})

    @staticmethod
    def _coerce(value: Any, schema: type[T]) -> T:
        if isinstance(value, schema):
            return value
        if isinstance(value, BaseModel):
            return schema.model_validate(value.model_dump())
        if isinstance(value, str):
            return schema.model_validate_json(value)
        return schema.model_validate(value)

    def _resolve(self, agent: str, system: str, user: str, schema: type[T], tools: dict[str, Tool] | None) -> T:
        resp = self._next(agent)
        if resp is None:
            return minimal_instance(schema)
        if callable(resp) and not isinstance(resp, (BaseModel, type)):
            fn: Callable[..., Any] = resp
            n_params = len(inspect.signature(fn).parameters)
            resp = fn(system, user, schema, tools) if tools is not None and n_params >= 4 else fn(system, user, schema)
        return self._coerce(resp, schema)

    def structured(self, *, agent: str, system: str, user: str, schema: type[T], project_id: int | None = None,
                   model: str | None = None, images: list[bytes] | None = None) -> T:
        self._record("structured", agent, system, user, schema=schema, model=model, images=len(images or []))
        return self._resolve(agent, system, user, schema, None)

    def text(self, *, agent: str, system: str, user: str, project_id: int | None = None,
             model: str | None = None) -> str:
        self._record("text", agent, system, user, model=model)
        resp = self._next(agent)
        if resp is None:
            return TEXT_DEFAULTS.get(agent, "")
        return str(resp(system, user, str) if callable(resp) else resp)

    def tool_loop(self, *, agent: str, system: str, user: str, tools: dict[str, Tool], schema: type[T],
                  project_id: int | None = None, model: str | None = None, max_steps: int = 12) -> T:
        """Registered callables get `(system, user, schema, tools)` so tests can exercise the tools."""
        self._record("tool_loop", agent, system, user, schema=schema, model=model, tools=sorted(tools))
        return self._resolve(agent, system, user, schema, tools)
