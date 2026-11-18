#!/usr/bin/env bash
# Decider spike (task 1.3). Run in Git Bash: bash docs/spike/decider_spike.sh
BASE=http://localhost:8000
REQ='{"state":"The agent can send emails to external recipients.","questions":[{"type":"choice","id":"q1","question":"Does the agent have external connectivity?","choices":["yes","no"]}],"model":"decider-2b","images":[]}'
echo "REQUEST GET $BASE/health"
curl -sS -m 10 -w "\nHTTP %{http_code} time_total=%{time_total}s\n" "$BASE/health"
echo "exit=$?"
echo "REQUEST POST $BASE/v1/systemone"
echo "$REQ"
curl -sS -m 60 -w "\nHTTP %{http_code} time_total=%{time_total}s\n" -X POST "$BASE/v1/systemone" -H "Content-Type: application/json" -d "$REQ"
echo "exit=$?"
