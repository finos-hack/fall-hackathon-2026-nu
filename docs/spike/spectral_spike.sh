#!/usr/bin/env bash
# Spectral spike: run from the platform root. Uses a temp dir for the install.
set -u
ROOT="$(pwd)"
T="$(mktemp -d)"
cd "$T"
npm init -y >/dev/null 2>&1
npm i @stoplight/spectral-cli >/dev/null 2>&1
S="npx spectral"
echo "node: $(node -v)"
echo "spectral: $($S --version)"
cat > ruleset.yaml <<'EOF'
rules:
  agent-needs-description:
    description: Every node must have a description
    severity: error
    given: "$.nodes[*]"
    then:
      field: description
      function: truthy
  node-type-actor-warn:
    description: Actor nodes are flagged
    severity: warn
    given: "$.nodes[?(@['node-type']=='actor')]"
    then:
      field: name
      function: pattern
      functionOptions:
        match: "^zzz"
EOF
cp "$ROOT/calm-app-generation-framework/fixtures/variants/customer-support-gap.json" calm.json
echo "--- lint with findings"
$S lint calm.json -r ruleset.yaml -f json > out.json 2> err.txt; echo "exit=$?"
cat out.json | head -c 2500; echo; echo "stderr:"; head -c 500 err.txt
echo "--- clean ruleset (no findings)"
cat > clean.yaml <<'EOF'
rules:
  has-nodes:
    severity: error
    given: "$"
    then:
      field: nodes
      function: truthy
EOF
$S lint calm.json -r clean.yaml -f json > out2.json 2>/dev/null; echo "exit=$?"; cat out2.json
echo "--- warn only"
cat > warn.yaml <<'EOF'
rules:
  w:
    severity: warn
    given: "$"
    then:
      field: nonexistent
      function: truthy
EOF
$S lint calm.json -r warn.yaml -f json >/dev/null 2>&1; echo "warn exit=$?"
$S lint calm.json -r warn.yaml -f json --fail-severity=warn >/dev/null 2>&1; echo "warn+fail-severity=warn exit=$?"
echo "--- bad ruleset path"
$S lint calm.json -r nope.yaml -f json >/dev/null 2>err3.txt; echo "exit=$?"; head -c 300 err3.txt
echo "--- missing file"
$S lint nofile.json -r clean.yaml -f json >/dev/null 2>err4.txt; echo "exit=$?"; head -c 300 err4.txt
