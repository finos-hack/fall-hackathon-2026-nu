"""Interactive end-to-end showcase:

  User requirements -> CALM reference architecture -> CALM model -> Governance framework
  -> Assessment -> Decision -> Remediation -> Dashboard

Every stage prints its INPUT, the COMMAND it runs, and its OUTPUT. Wherever an LLM (Bedrock via Strands) or the
Decider model is involved, the script prints the exact prompt or request and says when it is, and is not, called.

Run from the platform folder:  uv run python scripts/manual_walkthrough/walk_e2e_demo.py
"""
import re

from walk import (B, CY, DIM, GR, ROOT, X, YE, C, dashboard_check, finish, live_bedrock_extraction, pause, say,
                  state, step)

SHOW = "uv run python scripts/manual_walkthrough/show.py"
VARIANTS = {"1": ("APPROVED_WITH_CONDITIONS", "clean design"),
            "2": ("REJECTED", "Payment Agent calls the Payment API directly, skipping human approval"),
            "3": ("RESTRICTED", "autonomous Payment Agent and no audit service"),
            "4": ("BLOCKED", "invalid CALM: payment_limit above 100000")}


def env_values() -> dict[str, str]:
    """Selected model and decider settings from .env, or '(unset)'; read directly so the demo shows what the file says."""
    f = ROOT / ".env"
    text = f.read_text(encoding="utf-8") if f.is_file() else ""
    keys = ("MODEL_PROVIDER", "BEDROCK_MODEL_ID", "AWS_REGION", "AWS_PROFILE", "DECIDER_PROVIDER", "DECIDER_URL", "DECIDER_MODEL")
    return {k: ((re.search(rf"^{k}=([^\s#]*)", text, re.M) or [None, ""])[1] or "(unset)") for k in keys}


def stage(n: int, name: str, inp: str, out: str) -> None:
    """Print a stage heading with its input and output."""
    print(f"\n\n{B}{CY}{'#' * 100}\n  STAGE {n}: {name}\n{'#' * 100}{X}")
    print(f"{B}  INPUT : {X}{inp}")
    print(f"{B}  OUTPUT: {X}{out}")


def model_note(title: str, lines: list[str]) -> None:
    """Print a highlighted note on how the model is used at this stage."""
    print(f"\n{B}{YE}  [MODEL USAGE] {title}{X}")
    for l in lines:
        say(l, indent=4)


# ================================================================ intro and choices
print(f"\n{B}{CY}{'=' * 100}\n  AIGP END-TO-END DEMO\n{'=' * 100}{X}")
say("""This demo follows one application, Invoice Lite (an AI invoice and payment system), through the whole platform:

    1  User requirements      the attribute answers a team gives about their application
    2  CALM reference arch.   the approved patterns and the RA03-LITE template the answers plug into
    3  CALM model             the concrete CALM JSON generated from 1 + 2, validated by the calm CLI
    4  Governance framework   the approved controls, risks and compiled Spectral rules
    5  Assessment             facts, Decider classification, control gaps and risk profile
    6  Decision               gates plus decision matrix (deterministic, no model involved)
    7  Remediation            the fix list, and the LLM-written Fix Prompt
    8  Dashboard              the same run as a reviewer sees it

Keys: Enter = go on | s = skip a command | q = quit.""")

ev = env_values()
model_note("Where models are used in the platform", [
    f"LLM (Amazon Bedrock via a Strands agent). Configured model: {ev['BEDROCK_MODEL_ID']} in {ev['AWS_REGION']}, profile {ev['AWS_PROFILE']}.",
    "  - Rule Authoring, extraction (prompts extraction.v1 for AIGF, extraction.v2 for CCC): drafts rules. Authoring time only.",
    "  - CALM Generation, pattern drafting (prompt pattern-draft.v1): available for architects. The demo pipeline does not call it.",
    "  - Governance Execution, remediation (prompt remediation.v1): writes the Fix Prompt after the decision.",
    f"Decider (remote Strands classification service). Configured: {ev['DECIDER_URL']} model {ev['DECIDER_MODEL']}.",
    "  - Governance Execution, fact extraction: classifies attribute values the taxonomy cannot map.",
    "Never model-driven: CALM validation, Spectral rules, control status, severity, gates, the decision itself.",
])

print(f"\n{B}  Choose the run profile:{X}")
print("    1  Offline (default): recorded LLM and Decider answers, recorded calm/spectral outputs. No network.")
print("    2  Live: real calm and spectral, Bedrock for remediation, your HTTP Decider endpoint. Billed calls.")
live = (input(f"{YE}>> 1 or 2 [1]: {X}").strip() == "2")
v = input(f"{YE}>> Variant 1-4 [3]: {X}").strip() or "3"
v = v if v in VARIANTS else "3"
print(f"{GR}  Profile: {'LIVE' if live else 'OFFLINE'} | Variant V{v}: expected {VARIANTS[v][0]} ({VARIANTS[v][1]}){X}")

FORM = f"governance-execution-framework/forms/v{v}.attributes.yaml"
CALM = f"_out/e2e/invoice-lite-v{v}.json"
if live:
    ASSESS = (f"MODEL_PROVIDER=bedrock DECIDER_PROVIDER=http uv run python -m governance_execution assess {CALM} "
              f"--mode normal --cli real --decider http --template RA03-LITE")
else:
    ASSESS = f"uv run python -m governance_execution assess {CALM} --mode replay --cli replay --decider fixture --template RA03-LITE"
pause("Enter = start with the prerequisites")

# ================================================================ prerequisites
step("Prerequisites",
     """The demo runs every command in Git Bash from the platform folder. uv installs the Python dependencies. calm
     validates CALM documents; Spectral runs the governance rules. In the offline profile the command flags force
     recorded answers, so .env is not changed.""",
     [C("pwd && uv --version && uv sync -q && echo 'python deps OK'", "Shell, uv and dependencies."),
      C("calm --version; .tools/node_modules/.bin/spectral --version", "CALM CLI and Spectral (only needed for real-tool runs)."),
      C("mkdir -p _out/e2e && echo 'scratch folder _out/e2e ready'", "Scratch folder for this demo.")]
     + ([C("aws sts get-caller-identity --profile \"$(grep -E '^AWS_PROFILE=' .env | cut -d= -f2 | cut -d' ' -f1)\" --query Arn --output text",
           "Live: confirm the AWS profile is logged in (run 'aws login --profile <name>' if this fails)."),
         C("curl -s -m 10 \"$(grep -E '^DECIDER_URL=' .env | cut -d= -f2 | cut -d' ' -f1)/health\"; echo",
           "Live: confirm the Decider endpoint answers.")] if live else []),
     "No errors. Versions print for calm and spectral." + (" The AWS ARN prints and the Decider health check answers." if live else ""))

# ================================================================ 1 user requirements
stage(1, "USER REQUIREMENTS", "the RA03-LITE template (what an application must describe)",
      f"an attributes form with the team's answers ({FORM})")
step("1a. The questionnaire generated from the template",
     """A team does not write CALM by hand. They answer a questionnaire generated from the reference-architecture
     template: application name, data classification, whether an agent can execute payments, the approval path,
     autonomy, and so on.""",
     [C("uv run python -m calm_generation form RA03-LITE --out _out/e2e/form.yaml && head -45 _out/e2e/form.yaml",
        "Generate the blank form.")],
     "A YAML form with one field per attribute and the allowed values.")
step(f"1b. The team's answers for V{v}",
     f"""This is the user requirement for this run. Variant V{v} is expected to end {VARIANTS[v][0]}: {VARIANTS[v][1]}.
     Look for the values that drive that result.""",
     [C(f"cat {FORM}", "The filled-in form, the only human input to generation.")],
     "Agent attributes such as autonomy, can_execute_payment and payment_approval_path, and database data_classification.")

# ================================================================ 2 CALM reference architecture
stage(2, "CALM REFERENCE ARCHITECTURE", "the Pattern_Library and the RA03-LITE compose spec",
      "a versioned template (patterns plus their SHA-256) the form is instantiated into")
step("2a. Patterns and the template",
     """Patterns are reusable CALM fragments (API gateway, human approval, audit service...). RA03-LITE composes 8 of
     them. Only APPROVED or PUBLISHED patterns can be composed, and every version is pinned by hash.""",
     [C("uv run python -m calm_generation patterns", "The pattern library."),
      C("uv run python -m calm_generation versions", "Version and SHA-256 of each pattern and of RA03-LITE."),
      C("head -40 calm-app-generation-framework/templates/RA03-LITE.compose.yaml", "How RA03-LITE is composed.")],
     "8 PUBLISHED patterns and RA03-LITE, each with a hash.")
model_note("LLM at this stage: pattern drafting (not called in this run)", [
    "Prompt calm-app-generation-framework/prompts/pattern-draft.v1.md lets an LLM draft a NEW pattern for an architect.",
    "The draft is CANDIDATE only: a human reviews it and 'calm validate -p' checks it before it can be published.",
    "Generating a CALM model from a form (stage 3) is deterministic and uses no LLM."])
step("2b. The pattern-drafting prompt (for reference)", "Printed so you can see what the LLM would be asked.",
     [C("cat calm-app-generation-framework/prompts/pattern-draft.v1.md", "LLM prompt: pattern-draft.v1.")])

# ================================================================ 3 CALM model
stage(3, "CALM MODEL", f"the form ({FORM}) + RA03-LITE", f"a CALM 1.2 architecture JSON ({CALM}) and its validation result")
step("3a. Instantiate the CALM model",
     """The composer fills the template with the answers and writes a concrete CALM document. The same input always
     gives the same bytes, so the printed SHA-256 identifies this exact model.""",
     [C(f"uv run python -m calm_generation instantiate --form {FORM} --out {CALM}", "Generate the CALM model."),
      C(f"{SHOW} --calm {CALM}", "Readable view: nodes, their governance metadata, and relationships.")],
     "VALID (or INVALID for V4) with a sha256, then the node list. Note the metadata on payment-agent and invoice-db.")
step("3b. Validate with the real calm CLI",
     "Schema validation is separate from governance. An invalid model never reaches a decision.",
     [C(f"uv run python -m calm_generation validate {CALM}", "Validate.")],
     "VALID for V1-V3. V4: INVALID with /nodes/payment-agent/metadata/payment_limit: must be <= 100000.")

# ================================================================ 4 governance framework
stage(4, "GOVERNANCE FRAMEWORK", "AIGF and CCC guidance, reviewed by humans",
      "approved controls and risks, and compiled Spectral rulesets with hashes")
step("4a. What the assessment will apply",
     """Controls and risks were drafted from AIGF and CCC, reviewed, and APPROVED. Only approved items are compiled
     into Spectral rules. The manifest pins each ruleset by SHA-256, and the assessment records those hashes.""",
     [C("uv run python -m rule_authoring.consistency", "Catalogs, rules and registry agree."),
      C("cat rule-authoring-framework/rulesets/MANIFEST.yaml", "Ruleset versions and hashes."),
      C("grep -E '^  - (control_id|risk_id):' rule-authoring-framework/catalogs/controls.catalog.yaml rule-authoring-framework/catalogs/risks.catalog.yaml | sed 's#.*catalogs/##'",
        "The approved control and risk IDs.")],
     "'consistent', two rulesets with hashes, 12 controls and 6 risks.")
model_note("LLM at this stage: rule extraction (authoring time, before any assessment)", [
    "Rule Authoring sends each source item with prompt extraction.v1 (AIGF) or extraction.v2 (CCC) to Bedrock via Strands.",
    "The answer must pass a strict schema, and it is only ever a DRAFT. A person approves it before it compiles.",
    "Offline runs use recorded answers (model 'recorded-seed'). The next step can make one real call."])
step("4b. The extraction prompts and a recorded extraction",
     "This is exactly what the LLM is asked, and what a stored answer looks like.",
     [C("cat rule-authoring-framework/prompts/extraction.v1.md", "LLM prompt: extraction.v1 (AIGF)."),
      C("cat rule-authoring-framework/prompts/extraction.v2.md", "LLM prompt: extraction.v2 (CCC)."),
      C("f=$(ls rule-authoring-framework/fixtures/recordings/llm/extraction/v1/*.json | head -1); echo \"$f\"; "
        "uv run python -c \"import json,sys; d=json.load(open(sys.argv[1],encoding='utf-8')); "
        "print('item', d.get('item_id'), '| model', d.get('model'), '| prompt', d.get('prompt_id'), d.get('prompt_version')); "
        "print(json.dumps(d.get('output'), indent=2)[:1800])\" \"$f\"",
        "One recorded Extraction_Record: item, model, prompt version and the structured answer.")])
live_bedrock_extraction(keep_dir="_out/e2e/live-bedrock")

# ================================================================ 5 assessment
stage(5, "ASSESSMENT", f"the CALM model ({CALM}) + approved catalogs and rulesets",
      "stored artifacts: calm_validation, facts, decider_calls, control_gap, risk_profile (under data/artifacts/<trace>)")
step("5a. Run the assessment",
     f"""One command runs the whole pipeline: validate CALM, extract facts, ask the Decider about unclear facts, run
     Spectral, compute control gaps and the risk profile, decide, and remediate. The trace_id identifies the run.
     Profile: {'LIVE (real tools, Bedrock, HTTP Decider)' if live else 'OFFLINE (recorded tools, LLM and Decider)'}.""",
     [C(ASSESS, "Assess.", save="trace")],
     "JSON with assessment_status, validation_status, decision and trace_id.")
step("5b. CALM validation result",
     "Reported separately from governance findings.",
     [C(f"{SHOW} @@trace@@ calm_validation --fields status,errors,guidance", "calm_validation artifact.")])
step("5c. Facts extracted from the model",
     """Every governance-relevant attribute becomes a fact and is mapped through the taxonomy:
       MAPPED    the raw value maps to a known normalised value
       UNMAPPED  the value is outside the taxonomy (kept, never guessed)
       UNKNOWN   the attribute is absent
       INFERRED  an UNMAPPED value that the Decider classified with enough confidence (raw value kept)""",
     [C(f"{SHOW} @@trace@@ facts --rows facts --cols element_id,attribute,raw,mapping_status,normalized", "facts artifact.")],
     "Mostly MAPPED. invoice-db.data_classification 'supplier-financial' is INFERRED as confidential.")
model_note("Decider model at this stage: classification of UNMAPPED facts", [
    f"Provider: {'http -> ' + ev['DECIDER_URL'] + '/v1/systemone' if live else 'fixture (recorded answers keyed by input hash)'}.",
    "Request: {state, questions:[{type, id, question, choices}], model}. 'state' is built only from element_id, element_type,",
    "attribute_name, raw_value and description, scrubbed of secrets and paths, max 4000 chars. The CALM JSON is never sent.",
    "Policy (config/decider_policy.yaml): accept a choice only if confidence >= 0.80 and the top-2 margin >= 0.20.",
    "Otherwise ABSTAIN (fact stays UNMAPPED) or HUMAN_REVIEW. The Decider never sets severity, gates or the decision."])
step("5d. Decider calls for this run",
     "The audit record of every Decider call, including cache hits and failures.",
     [C(f"{SHOW} @@trace@@ decider_calls --rows . --cols task,question,outcome,confidence,latency_ms,cache_hit", "All calls."),
      C(f"{SHOW} @@trace@@ decider_calls --item 0 && echo && sed -n '1,20p' governance-execution-framework/config/decider_policy.yaml",
        "The first call in full (state, question, answer), then the policy that judged it.")],
     "outcome ACCEPTED with a confidence above 0.80, or ABSTAIN/ERROR, which leave the fact UNMAPPED.")
step("5e. Control gaps",
     """Spectral runs the compiled control rules over the model. Each applicable control is PASS or FAIL; FAIL adds to
     the gap level. PASS means design-level evidence only.""",
     [C(f"{SHOW} @@trace@@ control_gap --fields gap_level,gap_rule_version", "Overall gap level."),
      C(f"{SHOW} @@trace@@ control_gap --rows controls --cols control_id,title,status,gap_contribution", "Per control.")],
     "V2: the human-approval control fails (critical). V3: the audit-service control fails (minor).")
step("5f. Risk profile",
     "Spectral runs the risk rules. Each triggered risk gets likelihood x impact from the approved catalog, giving a severity.",
     [C(f"{SHOW} @@trace@@ risk_profile --fields profile_level,tier,label", "Overall risk level."),
      C(f"{SHOW} @@trace@@ risk_profile --rows risks --cols risk_id,title,likelihood,impact,severity", "Triggered risks.")],
     "V3: autonomous execution and no audit trail risks, profile High.")

# ================================================================ 6 decision
stage(6, "DECISION", "gap level + risk profile + gate results", "APPROVED_WITH_CONDITIONS, RESTRICTED, REJECTED, or none if blocked")
model_note("No model at this stage", ["The decision is pure code over config/gates.yaml and config/decision_matrix.yaml.",
                                      "No LLM or Decider output is an input. A test (test_no_decider_in_decision.py) enforces this."])
step("6a. The decision and how it was reached",
     """Gates are hard rules that fire first (for example G2: payment without the approval control means REJECTED).
     If no gate decides, the matrix cell gap x risk gives the result. Design-only evidence caps the best outcome at
     APPROVED_WITH_CONDITIONS.""",
     [C(f"{SHOW} @@trace@@ decision --fields decision,conditions,matrix_cell", "decision artifact."),
      C(f"{SHOW} @@trace@@ decision --rows gates_evaluated --cols id,fired,outcome,overridden", "Gate by gate.")],
     ("No decision: the run is BLOCKED (invalid CALM), so there is no decision artifact." if v == "4"
      else f"Decision {VARIANTS[v][0]}."))

# ================================================================ 7 remediation
stage(7, "REMEDIATION", "the decision + remediation texts of failed controls and triggered risks",
      "a deterministic fix list, plus an LLM-written summary and Fix Prompt (cannot change the decision)")
model_note("LLM at this stage: remediation.v1 (Bedrock via Strands)", [
    "Called only when a decision exists and there is something to fix. Skipped in --mode no-llm.",
    ("This run: --mode normal, so Bedrock is called." if live else
     "This run: --mode replay, so the recorded answer for the same input is used. Profile 2 (--mode normal) calls Bedrock."),
    "INPUT sent: {decision: {decision, conditions}, items: [{id, text}]}. Only catalog remediation texts, no CALM, no paths.",
    "If Bedrock fails, the deterministic list is used and the decision is unchanged."])
step("7a. The remediation prompt",
     "Exactly what the LLM is told.",
     [C("cat governance-execution-framework/prompts/remediation.v1.md", "LLM prompt: remediation.v1.")])
step("7b. Input sent to the LLM, and its output",
     """'items' is the INPUT (with the decision). 'source' says who wrote the text: llm or deterministic. 'model' names
     the model (recorded-seed for offline recordings, the Bedrock model id for live calls).""",
     [C(f"{SHOW} @@trace@@ remediation --fields decision,conditions,items", "INPUT to remediation."),
      C(f"{SHOW} @@trace@@ remediation --fields source,model,reason,summary,fix_prompt,deterministic_list", "OUTPUT.")]
     + ([C("ls -t data/llm-records 2>/dev/null | head -5 || echo '(no live LLM records yet)'", "Live: stored LLM records.")] if live else []),
     "A numbered fix list, each item ending with its control or risk ID. The decision is never restated or changed.")

# ================================================================ 8 dashboard
stage(8, "DASHBOARD", "the stored artifacts of this run", "the same run as reviewers see it")
dashboard_check("E2E run", "Open the run and follow its links into the catalogs.",
                [("/", "Overview: catalog counts and the control-gap and risk assessment counts, now including this run."),
                 ("/assessments/@@trace@@", "The full report: decision, gates, control gaps, risk profile, remediation, Decider panel."),
                 ("/assessments?q=@@trace@@", "The same run in the list. Expand the row; click a control or risk ID to jump to its catalog entry."),
                 ("/assessments/@@trace@@/trace", "Lineage from the decision back to the AIGF/CCC source IDs."),
                 ("/source-registry/dimensions", "Risk dimensions used by the risk profile."),
                 ("/source-registry/adrs", "Design decisions behind these rules (for example, invalid CALM gets no decision).")])

print(f"\n{B}{CY}  RECAP{X}")
for line in [
        f"1 Requirements  {FORM}",
        "2 CALM ref arch RA03-LITE + 8 pinned patterns                     (LLM pattern-draft.v1: authoring only)",
        f"3 CALM model    {CALM}                                (deterministic)",
        "4 Governance    12 controls, 6 risks, 2 rulesets                   (LLM extraction.v1/v2: authoring only)",
        f"5 Assessment    trace {state.get('trace', '?')}  (Decider: UNMAPPED facts only)",
        "6 Decision      gates + matrix                                     (no model)",
        f"7 Remediation   fix list + Fix Prompt                              (LLM remediation.v1, {'Bedrock' if live else 'recorded'})"]:
    print(f"  {line}")
finish("End-to-end demo", "Re-run with another variant to compare outcomes, or with profile 2 for live Bedrock and Decider calls.")
