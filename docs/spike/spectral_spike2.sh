#!/usr/bin/env bash
# Follow-up: error-severity exit code, stdout/stderr split, -o and -q.
set -u
ROOT="$(pwd)"
T="$(mktemp -d)"; cd "$T"
npm init -y >/dev/null 2>&1; npm i @stoplight/spectral-cli >/dev/null 2>&1
SP=./node_modules/.bin/spectral
cp "$ROOT/calm-app-generation-framework/fixtures/variants/customer-support-gap.json" c.json
cat > e.yaml <<'EOF'
rules:
  e:
    severity: error
    given: "$"
    then:
      field: nonexistent
      function: truthy
EOF
$SP lint c.json -r e.yaml -f json >o.txt 2>s.txt; echo "exit=$?"
echo "--stdout"; cat o.txt; echo "--stderr"; cat s.txt
$SP lint c.json -r e.yaml -f json -o r.json >o2.txt 2>s2.txt; echo "exit_o=$?"
echo "--r.json"; cat r.json; echo "--stdout"; cat o2.txt; echo "--stderr"; cat s2.txt
