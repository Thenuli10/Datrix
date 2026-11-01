"""LLMClient interface (PLAN.md §1). Agents depend only on this, so the provider
can be swapped later. Implementations: app.llm.openai_client.OpenAIClient,
app.llm.fake.FakeLLMClient (tests / offline)."""
from abc import ABC, abstractmethod
from typing import Any, Callable, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)

# A tool the model may call: name -> (JSON schema of params, python callable(**kwargs) -> JSON-able)
Tool = tuple[dict[str, Any], Callable[..., Any]]


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
