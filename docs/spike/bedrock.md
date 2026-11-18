# Spike 1.5: Bedrock model access via Strands

Requirements: 2.9, 2.10.

## Setup checked

- Region: `us-east-1` (default in the script). `AWS_REGION`, `AWS_DEFAULT_REGION` and `AWS_PROFILE` are unset in the shell.
- Credentials: `AWS_ACCESS_KEY_ID` and `AWS_BEARER_TOKEN_BEDROCK` are unset. `~/.aws/credentials` and `~/.aws/config` exist. The profile uses the `aws login` credential provider. No secret values were read or recorded.
- Model ID: `us.anthropic.claude-3-5-haiku-20241022-v1:0` (override with `BEDROCK_MODEL_ID`).
- Call: one `strands.Agent` with `BedrockModel(max_tokens=16)`, prompt "Reply with the single word: ok".

## Run

`bash scripts/spike/run_bedrock_spike.sh` (wraps `scripts/spike/bedrock_spike.py`; run from the repo root with Git Bash).

## Result: FAIL (credentials expired, not a model-access verdict)

| Attempt | Outcome |
|---|---|
| 1 | `MissingDependencyException`: the login credential provider needs `botocore[crt]`. |
| 2 (with `botocore[crt]`) | `LoginRefreshRequired`: session has expired. Run `aws login`. |

The call never reached Bedrock, so model access in `us-east-1` is still unverified.

## Findings

- Any environment that uses `aws login` credentials needs `botocore[crt]` installed alongside `strands-agents`. Add it to the dependencies.
- Re-run after `aws login`. Also confirm the model is enabled in the Bedrock console for the region.

## Contingency (Requirements 2.9, 2.10)

If Bedrock is unreachable, the ModelGateway must still work without a live model:

- `provider: none`: the LLM path is disabled. Deterministic rules and the pipeline run, and LLM-assisted steps return a clear "no model configured" result.
- `provider: replay`: LLM calls are served from recorded responses (fixtures captured while Bedrock was reachable). Use this for the demo and CI.
- `provider: bedrock` is the default when the spike passes. Selection is by config, with no code change.

Until the spike passes, develop and test against `none` and `replay`.

## Configuration (.env)
- Status: remote Bedrock; not re-probed. Last attempt failed on expired credentials.
- .env keys: `MODEL_PROVIDER` (bedrock|none|replay), `AWS_REGION`, `AWS_PROFILE`, `BEDROCK_MODEL_ID`.
- Contingency: `MODEL_PROVIDER=none` or `replay` with recorded outputs.
