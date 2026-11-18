"""Bedrock access spike (task 1.5). Sends one tiny prompt via Strands.

Run: uv run --with strands-agents python scripts/spike/bedrock_spike.py
Env: AWS_REGION / AWS_DEFAULT_REGION (default us-east-1), BEDROCK_MODEL_ID.
Prints only region, model id, and PASS/FAIL. Never prints credentials.
"""
import os
import re
import sys

region = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "us-east-1"
model_id = os.environ.get("BEDROCK_MODEL_ID", "us.anthropic.claude-3-5-haiku-20241022-v1:0")
print(f"region={region} model_id={model_id}")


def scrub(text: str) -> str:
    """Redact AWS key ids and long token-like strings and truncate to 300 chars so output is safe to log."""
    text = re.sub(r"(AKIA|ASIA)[A-Z0-9]{12,}", "<redacted>", text)
    return re.sub(r"[A-Za-z0-9/+=]{40,}", "<redacted>", text)[:300]


try:
    from strands import Agent
    from strands.models import BedrockModel

    agent = Agent(model=BedrockModel(model_id=model_id, region_name=region, max_tokens=16), callback_handler=None)
    result = agent("Reply with the single word: ok")
    print(f"RESULT=PASS reply_chars={len(str(result))}")
except Exception as exc:  # noqa: BLE001
    print(f"RESULT=FAIL {type(exc).__name__}: {scrub(str(exc))}")
    sys.exit(1)
