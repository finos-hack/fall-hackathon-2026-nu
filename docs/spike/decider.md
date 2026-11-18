# Decider spike (task 1.3, Requirements 2.6, 2.10)

Script: `docs/spike/decider_spike.sh` (Git Bash, curl).

## Result: Decider DOWN (not reachable at localhost:8000)

### GET /health
- Request: `GET http://localhost:8000/health`
- Response: none. `curl: (7) Failed to connect to localhost port 8000 ... Could not connect to server` (HTTP 000)
- Client latency until failure: 2.216 s

### POST /v1/systemone
- Request (body, as per design contract `{state, questions, model, images}`):
```json
{"state":"The agent can send emails to external recipients.","questions":[{"type":"choice","id":"q1","question":"Does the agent have external connectivity?","choices":["yes","no"]}],"model":"decider-2b","images":[]}
```
- Response: none. Connection refused (curl exit 7, HTTP 000)
- Client latency until failure: 2.249 s

## Unconfirmed (carry forward as [spike] items)
Because the service was not running, none of these were observed: the real `/health` payload, the exact question field names (`id`, `question`, `choices` are assumed), the model name (`decider-2b` is assumed), the response shape `{model, answers, usage}`, and real inference latency. The design contract is used unchanged until the service is run and the script is re-run.

## Fallback (chosen contingency)
- Adapter `adapters/decider.py` treats a connection error or timeout as Decider unavailable and returns answers marked `unavailable` (no value) for each question. No default answer is substituted, so nothing can lower risk. UNMAPPED Facts go to `ABSTAIN`/`HUMAN_REVIEW`. The Decider is advisory (D8), so severity and decisions are unaffected.
- `provider: fixture` serves recorded Decider outputs for tests and demos (Replay_Mode); favourable-Decider tests need no live service.
- Re-check on 2026-run: `GET /health` still refused (HTTP 000, ~2.2 s), so noul/choice/score question types were not tried.
- Re-run: start the Strands Decider 2B service on port 8000, then `bash docs/spike/decider_spike.sh`, and replace this fallback section with the observed shapes and latency.

## Configuration and contingency (remote Decider)
- Status: remote. The earlier local probe found nothing at localhost:8000; the Decider is now expected on another host. Not re-probed.
- Expected interface (design): `POST /v1/systemone`, `GET /health`.
- .env keys: `DECIDER_PROVIDER` (http|fixture), `DECIDER_URL`, `DECIDER_MODEL`, `DECIDER_TIMEOUT_S`.
- Contingency: `DECIDER_PROVIDER=fixture`; unreachable or timeout gives `unavailable` answers with no risk-reducing default.
