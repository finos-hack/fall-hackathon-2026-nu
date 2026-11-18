#!/usr/bin/env bash
# Spike 1.1: CALM CLI. Run from platform root in Git Bash. Raw outputs go to $OUT (default /tmp/calm_spike).
# Spike inputs are written from quoted heredocs; all CLI args are literal (no interpolation of untrusted values).
set -u
FIX="calm-app-generation-framework/fixtures/variants"
OUT="${OUT:-${TMPDIR:-/tmp}/calm_spike}"
mkdir -p "$OUT"

cat >"$OUT/pattern.json" <<'EOF'
{
  "$schema": "https://calm.finos.org/release/1.2/meta/calm.json",
  "$id": "https://example.test/spike-pattern.json",
  "title": "Spike pattern",
  "type": "object",
  "properties": {
    "nodes": {
      "type": "array",
      "minItems": 2,
      "prefixItems": [
        {
          "$ref": "https://calm.finos.org/release/1.2/meta/core.json#/defs/node",
          "properties": {
            "unique-id": {"const": "svc"},
            "node-type": {"const": "service"},
            "name": {"type": "string"},
            "description": {"type": "string"},
            "metadata": {"type": "object", "properties": {"flag": {"type": "boolean"}, "count": {"type": "integer"}}}
          }
        },
        {
          "$ref": "https://calm.finos.org/release/1.2/meta/core.json#/defs/node",
          "properties": {
            "unique-id": {"const": "db"},
            "node-type": {"const": "database"},
            "name": {"const": "DB"},
            "description": {"const": "Data store"}
          }
        }
      ]
    },
    "relationships": {
      "type": "array",
      "minItems": 1,
      "prefixItems": [
        {
          "$ref": "https://calm.finos.org/release/1.2/meta/core.json#/defs/relationship",
          "properties": {
            "unique-id": {"const": "r1"},
            "relationship-type": {"const": {"connects": {"source": {"node": "svc"}, "destination": {"node": "db"}}}}
          }
        },
        {
          "$ref": "https://calm.finos.org/release/1.2/meta/core.json#/defs/relationship",
          "properties": {
            "unique-id": {"const": "r2"},
            "relationship-type": {"type": "object", "properties": {"connects": {"type": "object", "properties": {
              "source": {"type": "object", "properties": {"node": {"type": "string"}}},
              "destination": {"type": "object", "properties": {"node": {"const": "db"}}}}}}}
          }
        }
      ]
    }
  },
  "required": ["nodes", "relationships"]
}
EOF
cat >"$OUT/arch_valid.json" <<'EOF'
{
  "$schema": "https://calm.finos.org/release/1.2/meta/calm.json",
  "nodes": [
    {"unique-id": "svc", "node-type": "service", "name": "Svc", "description": "A service"},
    {"unique-id": "db", "node-type": "database", "name": "DB", "description": "Data store"}
  ],
  "relationships": [
    {"unique-id": "r1", "relationship-type": {"connects": {"source": {"node": "svc"}, "destination": {"node": "db"}}}}
  ]
}
EOF
cat >"$OUT/arch_invalid.json" <<'EOF'
{
  "$schema": "https://calm.finos.org/release/1.2/meta/calm.json",
  "nodes": [
    {"unique-id": "svc", "node-type": "service", "name": "Svc"}
  ],
  "relationships": [
    {"unique-id": "r1", "relationship-type": {"connects": {"source": {"node": "svc"}, "destination": {"node": "ghost"}}}}
  ]
}
EOF
cat >"$OUT/arch_warn.json" <<'EOF'
{
  "$schema": "https://calm.finos.org/release/1.2/meta/calm.json",
  "nodes": [
    {"unique-id": "svc", "node-type": "service", "name": "Svc", "description": "A service"},
    {"unique-id": "orphan", "node-type": "service", "name": "Orphan", "description": "Not referenced"}
  ],
  "relationships": []
}
EOF
cat >"$OUT/arch_ai.json" <<'EOF'
{
  "$schema": "https://calm.finos.org/release/1.2/meta/calm.json",
  "nodes": [
    {"unique-id": "agent", "node-type": "ai:agent", "name": "A", "description": "agent"},
    {"unique-id": "llm", "node-type": "ai:llm", "name": "L", "description": "llm"},
    {"unique-id": "tool", "node-type": "ai:tool", "name": "T", "description": "tool"}
  ],
  "relationships": [
    {"unique-id": "r1", "relationship-type": {"invokes": {"source": {"node": "agent"}, "destination": {"node": "tool"}}}}
  ]
}
EOF
cat >"$OUT/arch_ai_connects.json" <<'EOF'
{
  "$schema": "https://calm.finos.org/release/1.2/meta/calm.json",
  "nodes": [
    {"unique-id": "agent", "node-type": "service", "name": "A", "description": "agent", "metadata": {"ai-kind": "agent"}},
    {"unique-id": "tool", "node-type": "service", "name": "T", "description": "tool", "metadata": {"ai-kind": "tool"}}
  ],
  "relationships": [
    {"unique-id": "r1", "metadata": {"verb": "invokes"}, "relationship-type": {"connects": {"source": {"node": "agent"}, "destination": {"node": "tool"}}}}
  ]
}
EOF
printf '{}' >"$OUT/choices.json"

run() { # run <name> <args...>; captures stdout, stderr, exit code
  local n="$1"; shift
  calm "$@" >"$OUT/$n.out" 2>"$OUT/$n.err"
  echo "$?" >"$OUT/$n.rc"
  echo "== $n: rc=$(cat "$OUT/$n.rc") stdout=$(wc -c <"$OUT/$n.out")B stderr=$(wc -c <"$OUT/$n.err")B"
}

echo "calm version: $(calm --version 2>&1)"; echo "node: $(node --version)"

run val_valid     validate -a "$OUT/arch_valid.json" -f json
run val_invalid   validate -a "$OUT/arch_invalid.json" -f json
run pat_valid     validate -p "$OUT/pattern.json" -a "$OUT/arch_valid.json" -f json
run pat_invalid   validate -p "$OUT/pattern.json" -a "$OUT/arch_invalid.json" -f json
run val_compliant validate -a "$FIX/customer-support-compliant.json" -f json
run val_gap       validate -a "$FIX/customer-support-gap.json" -f json

run val_warn        validate -a "$OUT/arch_warn.json" -f json
run val_ai          validate -a "$OUT/arch_ai.json" -f json
run val_ai_connects validate -a "$OUT/arch_ai_connects.json" -f json
run val_warn_strict validate -a "$OUT/arch_warn.json" --strict -f json
run gen1 generate -p "$OUT/pattern.json" --option-choices "$OUT/choices.json" -o "$OUT/gen1.json"
run gen2 generate -p "$OUT/pattern.json" --option-choices "$OUT/choices.json" -o "$OUT/gen2.json"
if cmp -s "$OUT/gen1.json" "$OUT/gen2.json"; then echo "generate byte-identical: YES"; else echo "generate byte-identical: NO"; fi
echo "outputs in $OUT"
