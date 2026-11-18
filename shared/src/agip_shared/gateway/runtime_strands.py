"""Strands + Bedrock runtime. The only module allowed to import Strands (Req 21.2)."""
from __future__ import annotations

from typing import Any, Callable, Optional

# A steering check takes the model's text answer and returns guidance when it must be retried, else None.
SteeringCheck = Callable[[str], Optional[str]]


def _model_kwargs(max_tokens: int, temperature: Optional[float]) -> dict[str, Any]:
    """Bedrock model options; temperature is only passed when set."""
    kw: dict[str, Any] = {"max_tokens": max_tokens}
    if temperature is not None:
        kw["temperature"] = temperature
    return kw


def _steering_plugin(check: SteeringCheck, max_retries: int) -> Any:
    """Strands steering handler: after each model answer, run ``check``; on guidance, discard and retry.

    Retries are capped; after ``max_retries`` the last answer is accepted and the caller's own validation decides.
    """
    from strands.vended_plugins.steering import Guide, Proceed, SteeringHandler

    class _CheckSteering(SteeringHandler):
        """Steering handler that retries a model answer while check() reports a problem."""
        name = "extraction-steering"

        def __init__(self) -> None:
            """Start with zero retries used."""
            super().__init__()
            self.retries = 0

        async def steer_after_model(self, *, agent: Any, message: Any, stop_reason: Any, **kwargs: Any) -> Any:
            """Check the answer text; guide the model to retry until max_retries is reached, then proceed."""
            text = "".join(b.get("text", "") for b in (message or {}).get("content") or [] if isinstance(b, dict))
            problem = check(text)
            if problem is None or self.retries >= max_retries:
                return Proceed(reason="output accepted" if problem is None else f"retry limit reached: {problem}")
            self.retries += 1
            return Guide(reason=f"Your previous answer was rejected: {problem}. Return the corrected JSON object only.")

    return _CheckSteering()


class StrandsRuntime:
    """Calls Bedrock through Strands. ``profile`` selects a named AWS profile (AWS_PROFILE in .env); empty uses the default chain.

    ``temperature`` (None = model default) and ``steering`` (a :data:`SteeringCheck`) are opt-in; ``steering_retries``
    caps how often a rejected answer is retried with guidance.
    """

    def __init__(self, max_tokens: int = 4096, profile: Optional[str] = None, temperature: Optional[float] = None,
                 steering: Optional[SteeringCheck] = None, steering_retries: int = 2):
        """Settings for live Bedrock calls: token limit, AWS profile, optional temperature, and optional output check with its retry cap."""
        self.max_tokens = max_tokens
        self.profile = profile or None
        self.temperature = temperature
        self.steering = steering
        self.steering_retries = steering_retries

    @property
    def fingerprint(self) -> str:
        """Runtime parameters that change the answer; part of the gateway's reuse check."""
        return (f"strands;max_tokens={self.max_tokens};temperature={self.temperature};"
                f"steering={getattr(self.steering, 'fingerprint', bool(self.steering))};retries={self.steering_retries}")

    def complete(self, prompt: str, model: str, region: str) -> str:
        """Run the prompt through a Strands agent on Bedrock and return the answer text. boto3 and strands are imported lazily."""
        import boto3  # lazy: only needed for live Bedrock calls
        from strands import Agent
        from strands.models import BedrockModel

        session = boto3.Session(profile_name=self.profile, region_name=region)
        plugins = [_steering_plugin(self.steering, self.steering_retries)] if self.steering else None
        agent = Agent(model=BedrockModel(model_id=model, boto_session=session,
                                         **_model_kwargs(self.max_tokens, self.temperature)),
                      callback_handler=None, plugins=plugins)
        return str(agent(prompt))

    def run_agent(self, prompt: str, model: str, region: str, *, system_prompt: str, tools: list) -> str:
        """Strands Agent with a system prompt and plain-function tools (each needs a docstring and type hints)."""
        import boto3
        from strands import Agent, tool
        from strands.models import BedrockModel

        session = boto3.Session(profile_name=self.profile, region_name=region)
        agent = Agent(model=BedrockModel(model_id=model, boto_session=session,
                                         **_model_kwargs(self.max_tokens, self.temperature)),
                      system_prompt=system_prompt, tools=[tool(f) for f in tools], callback_handler=None)
        return str(agent(prompt))
