# Spike 1.6: Fluxnova (finos/fluxnova-bpm-platform)

Date: 2026-11-15 (UTC)
Result: **FAIL (not executed, Docker unavailable)**

## Evidence
`docker version` failed:
`failed to connect to the docker API at npipe:////./pipe/dockerDesktopLinuxEngine ... The system cannot find the file specified.`
The Docker Desktop daemon is not running or not installed, so the container could not be started.

## Endpoints not verified (all untested)
| Capability | Expected path | Status |
|---|---|---|
| Deploy BPMN | POST /engine-rest/deployment/create (multipart) | untested |
| Start instance | POST /engine-rest/process-definition/key/{key}/start | untested |
| Fetch and lock | POST /engine-rest/external-task/fetchAndLock | untested |
| Complete | POST /engine-rest/external-task/{id}/complete | untested |
| Failure | POST /engine-rest/external-task/{id}/failure | untested |
| User tasks | GET /engine-rest/task | untested |

The paths above are the Camunda 7 REST API conventions that Fluxnova is expected to follow. They are not confirmed.

## Recommendation
Use **Direct_Adapter** for the MVP. Fluxnova compatibility is unconfirmed. Re-run this spike when Docker is available, and adopt Fluxnova only if all six calls pass.

## Configuration (.env)
- Status: local, DEFERRED, not probed since the Docker failure above.
- Expected interface: `/engine-rest` `deployment/create`, `external-task/fetchAndLock`, `external-task/{id}/complete`, `external-task/{id}/failure`, `task`.
- .env keys: `EXECUTOR` (direct|fluxnova), `FLUXNOVA_URL`.
- Contingency: Direct_Adapter (`EXECUTOR=direct`).
