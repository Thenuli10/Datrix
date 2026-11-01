"""LLMClient interface (PLAN.md §1). Agents depend only on this, so the provider
can be swapped later. Implementations: app.llm.openai_client.OpenAIClient,
app.llm.fake.FakeLLMClient (tests / offline)."""
from abc import ABC, abstractmethod
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Callable, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)

# A tool the model may call: name -> (JSON schema of params, python callable(**kwargs) -> JSON-able)
Tool = tuple[dict[str, Any], Callable[..., Any]]

# Run the current LLM calls belong to (set by the orchestrator for the duration of a run),
# so clients can attribute spend and enforce the per-run cap without changing agent signatures.
current_run_id: ContextVar[int | None] = ContextVar("current_run_id", default=None)


@contextmanager
def llm_run_scope(run_id: int) -> Iterator[None]:
    token = current_run_id.set(run_id)
    try:
        yield
    finally:
        current_run_id.reset(token)


class LLMError(RuntimeError):
    """The model refused or returned no parsable answer."""


class LLMBudgetExceeded(LLMError):
    """A spend cap (settings.llm_*) was hit; the request was NOT sent. Never retried."""


class LLMClient(ABC):
    @abstractmethod
    def structured(
        self,
        *,
        agent: str,
        system: str,
        user: str,
        schema: type[T],
        project_id: int | None = None,
        model: str | None = None,
        images: list[bytes] | None = None,  # PNG bytes, for vision review
    ) -> T:
        """One call returning a validated instance of `schema` (OpenAI structured outputs)."""

    @abstractmethod
    def text(
        self,
        *,
        agent: str,
        system: str,
        user: str,
        project_id: int | None = None,
        model: str | None = None,
    ) -> str:
        """Free-text completion (code generation, insight markdown)."""

    @abstractmethod
    def tool_loop(
        self,
        *,
        agent: str,
        system: str,
        user: str,
        tools: dict[str, Tool],
        schema: type[T],
        project_id: int | None = None,
        model: str | None = None,
        max_steps: int = 12,
    ) -> T:
        """Tool-calling agent loop; ends with a structured `schema` answer."""
