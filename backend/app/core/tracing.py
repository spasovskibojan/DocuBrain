from contextlib import contextmanager
from typing import Any, Iterator

from app.core.config import settings

# Tracing is optional: without Langfuse keys nothing is imported or sent
langfuse = None
if settings.LANGFUSE_PUBLIC_KEY and settings.LANGFUSE_SECRET_KEY:
    from langfuse import Langfuse, is_default_export_span, propagate_attributes
    from langfuse.langchain import CallbackHandler

    # LangGraph state writes and prompt formatting add no insight to the trace tree
    _NOISE_PREFIXES = ("ChannelWrite<", "ChatPromptTemplate", "__start__")

    def _should_export(span) -> bool:
        return is_default_export_span(span) and not span.name.startswith(_NOISE_PREFIXES)

    langfuse = Langfuse(
        public_key=settings.LANGFUSE_PUBLIC_KEY,
        secret_key=settings.LANGFUSE_SECRET_KEY,
        base_url=settings.LANGFUSE_BASE_URL,
        environment=settings.LANGFUSE_ENVIRONMENT,
        should_export_span=_should_export,
    )


def model_metadata(model: str) -> dict:
    """langchain-groq does not report the model to callbacks; Langfuse needs it for cost tracking."""
    return {"metadata": {"ls_model_name": model, "ls_provider": "groq"}}


class Trace:
    """LangChain config for the calls inside a trace, plus a way to record the final output."""

    def __init__(self, observation=None):
        self.observation = observation
        self.config: dict = {}
        if observation is not None:
            self.config = {"callbacks": [CallbackHandler(public_key=settings.LANGFUSE_PUBLIC_KEY)]}

    def set_output(self, output: Any) -> None:
        if self.observation is not None:
            self.observation.update(output=output)


@contextmanager
def trace_request(name: str, user_id: str, input: Any, session_id: str | None = None, metadata: dict | None = None) -> Iterator[Trace]:
    """Groups all LLM calls of one request into a single Langfuse trace."""
    if langfuse is None:
        yield Trace()
        return

    with langfuse.start_as_current_observation(name=name, as_type="chain", input=input, metadata=metadata) as root, \
            propagate_attributes(user_id=user_id, session_id=session_id, trace_name=name, tags=[name]):
        yield Trace(root)


def flush_traces() -> None:
    if langfuse is not None:
        langfuse.flush()
