"""Interactive walkthrough: Governance Execution framework.

Run from anywhere:  python scripts/manual_walkthrough/walk_governance_execution.py
"""
import atexit
import shutil

from walk import (ROOT, C, banner, dashboard_check, finish, manual, prereqs, start_dashboard,
                  state, step)

POLICY = ROOT / "governance-execution-framework" / "config" / "decider_policy.yaml"
BACKUP = ROOT / "_out" / "decider_policy.yaml.bak"
_modified = {"policy": False}


def _restore_policy() -> None:
    """Safety net: put the Decider policy back even if you quit half way through."""
    if _modified["policy"] and BACKUP.exists():
        shutil.copy(BACKUP, POLICY)
        print("\n  (safety) decider_policy.yaml restored from _out/decider_policy.yaml.bak")


atexit.register(_restore_policy)

G = "uv run python -m governance_execution"
V = "calm-app-generation-framework/fixtures/variants/invoice-lite-v{}.json"

banner("GOVERNANCE EXECUTION FRAMEWORK - manual walkthrough",
       """This framework takes a finished CALM architecture and decides whether it may go ahead.

       The assessment pipeline:
         1. VALIDATE    is the CALM document valid? If not, status BLOCKED and no decision.
         2. CLASSIFY    work out facts such as data classification. Unclear facts go to the Decider, an AI
                        service that only classifies. It never sets severity, gates or the decision.
         3. EVALUATE    apply applicability, run the Spectral rules, find control gaps.
         4. SCORE       combine risk and gaps with a scoring profile and a decision matrix.
         5. DECIDE      APPROVED_WITH_CONDITIONS, RESTRICTED, REJECTED (or INDETERMINATE if a tool failed).
         6. RECORD      write every artifact, with versions and hashes, under data/ so the run can be shown,
                        traced and replayed.

       Two statuses to keep apart:
         assessment_status  did the run finish? COMPLETED, BLOCKED, WAITING_FOR_HUMAN, FAILED.
         decision           what the governance verdict is. It is null when there is no decision yet.

       Every result is labelled 'illustrative, not approved policy' and 'design-level evidence only'.
       There is no real approval authority in this MVP.""")

prereqs(calm=True, spectral=True)

step("Prepare the two CALM inputs",
     """The Governance framework consumes CALM files and does not create them. V1 (clean) and V4 (invalid) are
     needed for the first steps. If the CALM walkthrough already created them in _out/, this does nothing
     harmful: it simply overwrites them with identical content.""",
     [C("uv run python -m calm_generation instantiate --form governance-execution-framework/forms/v1.attributes.yaml --out _out/v1.json",
        "Build V1."),
      C("uv run python -m calm_generation instantiate --form governance-execution-framework/forms/v4.attributes.yaml --out _out/v4.json",
        "Build V4 (invalid on purpose)."),
      C("ls -l _out/v1.json _out/v4.json", "Confirm both files exist.")],
     "Both files listed.")

step("Run this framework's automated tests (without the golden suite)",
     """The 'golden' suite checks all four variants together and belongs to the integrated test, so it is left
     out here. Everything else is this framework alone, including the acceptance test that assesses an
     external CALM file with frozen catalogs.""",
     [C("uv run pytest -q governance-execution-framework/tests --ignore=governance-execution-framework/tests/golden",
        "Offline tests, no Bedrock or Decider."),
      C("uv run pytest -q governance-execution-framework/tests/test_cli_standalone.py",
        "The standalone acceptance journey.")],
     "All passed.")

step("1. Assess the clean design (V1) with the real tools",
     """This is the core command. The flags:
       --mode no-llm      remediation text is a deterministic list (no LLM)
       --cli real         run the real calm and spectral
       --decider fixture  recorded Decider answers
       --template RA03-LITE  the requirement template to assess against

     The output is JSON. The trace_id identifies this run everywhere: stored files, dashboard URLs and replay.
     The script keeps it for later steps.""",
     [C(f"{G} assess _out/v1.json --mode no-llm --cli real --decider fixture --template RA03-LITE",
        "Assess V1.", save="v1_real")],
     """assessment_status COMPLETED, validation_status VALID, decision APPROVED_WITH_CONDITIONS and a trace_id.""",
     """The decision is conditional, not a plain approval, because the evidence is design-level only. Nobody has
     inspected a running system.""")

step("2. The four variants, one by one",
     """The four sample designs are assessed from recordings (--mode replay --cli replay), which makes the
     results exactly repeatable. Expect each to behave differently:

       V1  COMPLETED  APPROVED_WITH_CONDITIONS  clean design, design-level evidence only
       V2  COMPLETED  REJECTED                  gate G2 failed: Payment Agent writes to the Payment API
                                                directly, without the approval control
       V3  COMPLETED  RESTRICTED                high risk profile: no audit service, autonomous Payment Agent
       V4  BLOCKED    none                      invalid CALM, so no decision is made

     Only the status, decision and trace_id lines are shown.""",
     [C(f"{G} assess {V.format(i)} --mode replay --cli replay --template RA03-LITE",
        f"Assess V{i}.", show=r'"(assessment_status|decision|trace_id)"', save=f"v{i}") for i in (1, 2, 3, 4)],
     "Statuses and decisions match the table above.",
     """Same engine, different designs, different verdicts. V4 shows a deliberate rule: an invalid document is
     never scored, because a decision on broken input would be meaningless.""")

step("3. Show and replay a stored run",
     """Every run is stored. 'show' prints the stored record and artifact list. 'replay' re-runs the assessment
     using the catalogs, rulesets and config that were frozen with it (config_snapshot), then compares the
     result. Editing a catalog afterwards cannot change an old result.""",
     [C(f"{G} show @@v2@@ | head -60", "Show V2's stored record."),
      C(f"{G} replay @@v1_real@@ --cli real", "Replay the real-tools V1 run.")],
     'The replay output has "identical": true and the same decision.',
     "This is the audit guarantee: any past decision can be reproduced and explained.")

step("4. The blocked case with real tools",
     """Now assess the invalid V4 document that you generated with the real CLI. It stops at validation.""",
     [C(f"{G} assess _out/v4.json --mode no-llm --cli real --template RA03-LITE",
        "Assess V4.", show=r'"(assessment_status|decision|validation_status|trace_id)"', save="v4_real")],
     "assessment_status BLOCKED and decision null.",
     "BLOCKED is different from REJECTED. BLOCKED means we could not judge it. REJECTED means we judged it and said no.")

step("5. Human review: pause, review, resume",
     """A run pauses for a person only when the Decider cannot classify a fact confidently AND the policy says to
     wait. To force it, you temporarily edit the policy:
       min_confidence 0.80 -> 0.99    the recorded answer is no longer confident enough
       on_fail: HUMAN_REVIEW          low confidence creates a review task
       block_on_pending_human: true   the run waits for the task

     Your policy file is backed up to _out/decider_policy.yaml.bak first and restored at the end of this step.
     If you quit early, the script restores it on exit.""",
     [C(f"cp {POLICY.relative_to(ROOT).as_posix()} _out/decider_policy.yaml.bak",
        "Back up the real policy."),
      C("P=governance-execution-framework/config/decider_policy.yaml\n"
        "sed -i 's/min_confidence: 0.80/min_confidence: 0.99/; s/on_fail: ABSTAIN  .*/on_fail: HUMAN_REVIEW/' \"$P\"\n"
        "printf '\\nblock_on_pending_human: true\\n' >> \"$P\"\n"
        "git diff -U0 \"$P\"",
        "Edit the policy, then show the diff so you can see the change took effect.",
        confirm="This edits governance-execution-framework/config/decider_policy.yaml in place. A backup was just made.")],
     "The diff shows min_confidence 0.99, on_fail HUMAN_REVIEW and block_on_pending_human true.")
_modified["policy"] = BACKUP.exists()

step("5b. Run the assessment that will wait",
     "With the stricter policy, V1's Decider answer is below the threshold, so the run should pause.",
     [C(f"{G} assess {V.format(1)} --mode replay --cli replay --decider fixture --template RA03-LITE",
        "Assess V1 again.", save="wait")],
     """assessment_status WAITING_FOR_HUMAN, decision null, and pending_human_tasks listing something like
     decider-review-<trace8>-invoice-db-data_classification.""",
     "The system refuses to guess. A fact it cannot classify safely is handed to a person.")

step("5c. Look at the stored task, then start the dashboard",
     "Tasks are plain files under data/human_tasks/, so the flow survives a restart. Outcomes are append-only.",
     [C("ls data/human_tasks 2>&1 | head -10", "The task file for this run.")])
start_dashboard()

manual("5d. Act on the task in the dashboard",
       """You are now playing the reviewer. Do these in the browser (http://127.0.0.1:8001):""",
       ["Open /review, then open the task. The context shows the raw value and the allowed_values.",
        "Act CLAIM with actor bob, role risk_analyst and any rationale.",
        "Act COMPLETE with the same actor and role and the value confidential (one of the allowed values).",
        "Under 'Resume the assessment' pick mode replay and tools replay, then click Resume.",
        "Check the report: status COMPLETED, decision APPROVED_WITH_CONDITIONS, and 'Inferred facts' lists the "
        "classification with the reviewer as its source.",
        "Optional checks: acting with role architect gives HTTP 403. REJECT instead of COMPLETE leaves the fact "
        "UNMAPPED. It is never given a risk-reducing default."])

step("5e. Restore the policy",
     "Put the real Decider policy back and prove nothing is left changed.",
     [C("cp _out/decider_policy.yaml.bak governance-execution-framework/config/decider_policy.yaml\n"
        "git diff --stat governance-execution-framework/config/decider_policy.yaml; echo '(empty above = restored)'",
        "Restore and verify.")],
     "No diff output.")
_modified["policy"] = False

dashboard_check("Governance Execution",
                "Now see the runs you made from a reviewer's point of view.",
                [("/overview", "Counts by decision and status, blocked runs, waiting tasks, framework health, active versions."),
                 ("/assessments", "One row per run. Find V1 to V4, the blocked V4 and the human-reviewed V1."),
                 ("/assessments/@@v2@@",
                  "The V2 report: decision REJECTED, the failed gate G2, risk matrix, control gaps, remediation, "
                  "and the Decider panel."),
                 ("/assessments/@@v2@@/execution",
                  "Timeline of steps with status, input/output references, versions, CALM hash and Decider outcomes."),
                 ("/assessments/@@v2@@/trace", "Lineage: from the decision back to the source ids (AIGF/CCC)."),
                 ("/lineage/source/AIGF:mi-24", "Lineage from a source forward: which assessments used this mitigation."),
                 ("/review", "The review queue. The task you completed should show as finished."),
                 ("/registry/controls", "Open a control and see the assessments that used it."),
                 ("/workbench/governance", "Governance commands and run history."),
                 ("/api/docs", "Swagger UI for the API: upload, assess, instantiate, replay.")])

step("Not covered here: live endpoints",
     """Section 8 of docs/functional_manual_testing.md tests Bedrock and the live Decider on EC2 (what happens when
     the Decider is down, remediation text from Bedrock). Those need credentials and a running endpoint. Switch
     the .env to the live profile and follow that section when you are ready.""")

finish("Governance Execution walkthrough",
       "For the end-to-end flow across all three frameworks, see section 6 of docs/functional_manual_testing.md "
       "and docs/WALKTHROUGH-integrated.md.")
