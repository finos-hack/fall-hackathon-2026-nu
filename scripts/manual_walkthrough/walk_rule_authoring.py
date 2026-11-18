"""Interactive walkthrough: Rule Authoring framework.

Run from anywhere:  python scripts/manual_walkthrough/walk_rule_authoring.py
"""
from walk import C, banner, dashboard_check, finish, live_bedrock_extraction, manual, prereqs, step

banner("RULE AUTHORING FRAMEWORK - manual walkthrough",
       """This framework turns written guidance (AIGF risks and mitigations, CCC controls and threats) into
       machine-checkable rules.

       The pipeline has five stages:
         1. INGEST   read the source documents into a uniform list of items.
         2. EXTRACT  propose a rule for each item (normally by an LLM; here from recordings). The result is
                     always a DRAFT. Nothing is trusted yet.
         3. REVIEW   a human moves each item DRAFT -> IN_REVIEW -> APPROVED. Every move records who, role, why
                     and when.
         4. COMPILE  only APPROVED items become Spectral rules. The output is deterministic, so identical
                     input gives byte-identical files.
         5. CHECK    consistency and coverage reports show what is and is not covered.

       The framework depends only on the shared package. It knows nothing about CALM models or assessments.""")

prereqs(aigf=True, ccc=True, spectral=True)

step("Run this framework's automated tests",
     """Before exploring by hand, confirm the framework is healthy. These tests cover the source adapters, the
     extraction schema, the approval lifecycle, the consistency check, compile and the catalogs.""",
     [C("uv run pytest -q rule-authoring-framework/tests", "Runs only this framework's tests, offline.")],
     "All passed. A failure here means the environment is wrong, so fix that before going on.")

step("1. INGEST: read the sources",
     """Ingestion reads the AIGF and CCC files and normalises them into items with an id, a type and text.
     Native ids are kept (ri-24 for an AIGF risk, CCC.Core.CN02 for a CCC control), which keeps lineage
     traceable back to the original document. The summary also records the source commit.""",
     [C("uv run python -m rule_authoring.ingest --source aigf --out _out/aigf.json", "AIGF: mitigations and risks."),
      C("uv run python -m rule_authoring.ingest --source ccc --out _out/ccc.json", "CCC: controls, threats, capabilities."),
      C("head -c 700 _out/aigf.json; echo", "Peek at the first item to see the uniform shape.")],
     """AIGF: '49 items (mitigation=25, risk=24), 0 errors, commit <hash>'.
     CCC: 148 items (38 controls, 51 threats, 59 capabilities), 0 errors.""",
     "Errors are counted and reported, never silently dropped. 0 errors means every source file parsed.")

step("2. EXTRACT: draft rules from recordings",
     """Extraction asks an LLM to read an item and propose a rule in a strict schema. Here --provider replay
     answers from recorded LLM outputs, so no Bedrock call is made. With a live profile you would use
     --provider bedrock.

     Three outcomes matter:
       DRAFT               a rule proposal that still needs human review.
       INEXPRESSIBLE       the control cannot be tested with the CALM vocabulary (for example, CALM has no
                           attribute for transport encryption).
       MISSING-RECORDING   no recording exists for that item in replay mode.""",
     [C("uv run python -m rule_authoring.ingest --source ccc --extract --provider replay --drafts _out/drafts --out _out/ccc.json",
        "Extract from recordings for the CCC items."),
      C("ls _out/drafts", "The draft files that were produced."),
      C("head -c 1200 _out/drafts/CCC.Core.CN02.json; echo", "Open one draft to see the proposed rule.")],
     """Drafts CCC.Core.CN01.json, CCC.Core.CN02.json and CCC.Core.TH01.json.
     The summary reports CCC.Core.CN01 as INEXPRESSIBLE. Items with no recording are listed as
     MISSING-RECORDING.""",
     """Items that cannot be expressed are reported, not dropped, so a gap is visible instead of hidden. An LLM
     draft is never approved automatically. A person must do that.""")

step("3. REVIEW: the approval lifecycle (on a copy)",
     """You will work on a copy of the catalogs in _out/cat so the real ones stay untouched.

     The story, using control AIGF-MI-024:
       a. Flip it to DRAFT in the copy. Compile skips it: 11 rules instead of 12.
       b. Try to approve it directly. The lifecycle refuses, because DRAFT must go to IN_REVIEW first.
       c. Submit it (alice, role author), then approve it (bob, role rule_reviewer).
       d. Compile again: 12 rules, byte-identical to the committed ruleset.

     Two people are used on purpose. The author and the approver must be different roles, and a person cannot
     approve their own work.""",
     [C("cp -r rule-authoring-framework/catalogs _out/cat\n"
        "sed -i '0,/status: APPROVED/s//status: DRAFT/' _out/cat/controls.catalog.yaml\n"
        "grep -n 'status:' _out/cat/controls.catalog.yaml | head -3",
        "Copy the catalogs and set the first APPROVED item (AIGF-MI-024) to DRAFT."),
      C("uv run python -m rule_authoring.compile --catalogs _out/cat --out _out/rs",
        "Compile the copy. Expect: rules=11 skipped_unapproved=1."),
      C('A="uv run python -m rule_authoring.approval"\n'
        '$A approve AIGF-MI-024 --by bob --role rule_reviewer --rationale "skip" --catalog _out/cat/controls.catalog.yaml',
        "Try to jump DRAFT -> APPROVED. This must be REFUSED."),
      C('A="uv run python -m rule_authoring.approval"\n'
        '$A submit AIGF-MI-024 --by alice --role author --rationale "ready" --catalog _out/cat/controls.catalog.yaml',
        "Legal move: DRAFT -> IN_REVIEW."),
      C('A="uv run python -m rule_authoring.approval"\n'
        '$A approve AIGF-MI-024 --by bob --role rule_reviewer --rationale "checked" --catalog _out/cat/controls.catalog.yaml',
        "Legal move: IN_REVIEW -> APPROVED."),
      C("uv run python -m rule_authoring.compile --catalogs _out/cat --out _out/rs",
        "Compile again. Expect rules=12."),
      C("cmp _out/rs/controls.spectral.yaml rule-authoring-framework/rulesets/controls.spectral.yaml && echo identical",
        "Determinism check against the committed ruleset."),
      C("grep -n -A25 'AIGF-MI-024' _out/cat/controls.catalog.yaml | grep -iE 'history|by:|role|rationale|status|at:' | head -30",
        "Read the audit trail the lifecycle wrote.")],
     """First compile: rules=11 skipped_unapproved=1. The direct approve is refused. After submit and approve:
     rules=12 and 'identical'. The history shows each step with who, role, rationale and time.""",
     """Only APPROVED items ever become executable rules, so an unreviewed LLM draft can never fail or pass a
     real assessment. The history is the audit trail.""")

step("3b. Risks need a human confirmation first",
     """Risks have an extra gate. Before a risk can be approved, a person must record a confirmation of its
     likelihood and impact (the command is 'approval confirm <risk-id> ...'). The seed risks already carry a
     'seed-import' confirmation. The refusal case is covered by an existing test, so you run that.""",
     [C("uv run pytest -q rule-authoring-framework/tests/test_lifecycle.py -k confirm",
        "Runs the tests that prove approval is refused without a confirmation.")],
     "The confirm tests pass.",
     "Severity inputs come from a person, never from an LLM guess.")

step("4. CHECK: consistency, compile and coverage on the real catalogs",
     """Now run the real thing:
       consistency  checks that catalogs, rules and registry agree with each other.
       compile      regenerates rulesets/*.spectral.yaml and rulesets/MANIFEST.yaml (version and SHA-256).
       git diff     proves compile is deterministic: no change is expected.
       coverage     one row per AIGF risk/mitigation and CCC control/threat, with its status.""",
     [C("uv run python -m rule_authoring.consistency", "Prints 'consistent' and exits 0."),
      C("uv run python -m rule_authoring.compile", "Writes the rulesets and the manifest."),
      C("git diff --stat rule-authoring-framework/rulesets; echo '(empty above = no change)'",
        "No difference means the compile is reproducible."),
      C("uv run python -m rule_authoring.coverage | tail -15", "The coverage report.")],
     """'consistent'. No diff on the rulesets. Coverage totals: APPROVED rule: 18, missing extraction: 54,
     non-executable (stored): 66.""",
     """Do not edit the committed rulesets. The offline Spectral recordings are keyed by their bytes, so any
     edit breaks the replay runs in the Governance framework. 'Non-executable (stored)' means the guidance is
     kept for lineage but cannot be tested automatically.""")

live_bedrock_extraction()

dashboard_check("Rule Authoring",
                "Confirm that what you produced is visible to a reviewer.",
                [("/registry/sources", "AIGF and CCC items should be listed, with their native ids."),
                 ("/registry/risks", "Approved risks with their confirmations."),
                 ("/registry/controls", "Approved controls. Open one to see which assessments used it."),
                 ("/registry/rulesets", "Each compiled ruleset with its version and SHA-256 (same as MANIFEST.yaml)."),
                 ("/catalogs/controls", "The catalog view of controls with their lifecycle status."),
                 ("/workbench/rule-authoring", "The Rule Authoring commands and their history.")])

finish("Rule Authoring walkthrough",
       "Next: run walk_calm_generation.py, then walk_governance_execution.py.")
