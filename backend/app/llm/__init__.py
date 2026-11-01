"""LLM access point. Agents receive an LLMClient; the app obtains one via get_llm()."""
from app.core.config import settings
from app.llm.base import LLMClient, Tool  # noqa: F401

_client: LLMClient | None = None


def get_llm() -> LLMClient:
    """Process-wide client: FakeLLMClient when `settings.llm_fake` or no API key, else OpenAIClient."""
    global _client
    if _client is None:
        if settings.llm_fake or not settings.openai_api_key:
            from app.llm.fake import FakeLLMClient

            _client = FakeLLMClient()
        else:
            from app.llm.openai_client import OpenAIClient

            _client = OpenAIClient()
    return _client


def set_llm(client: LLMClient | None) -> None:
    """Override (or reset with None) the process-wide client, e.g. in tests."""
    global _client
    _client = client
