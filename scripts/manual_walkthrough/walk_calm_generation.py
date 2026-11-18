"""Interactive walkthrough: CALM App Generation framework.

Run from anywhere:  python scripts/manual_walkthrough/walk_calm_generation.py
"""
from walk import C, banner, dashboard_check, finish, prereqs, step

banner("CALM APP GENERATION FRAMEWORK - manual walkthrough",
       """CALM is a FINOS standard for describing a system architecture as JSON: nodes (services, databases,
       agents), relationships between them, and metadata.

       This framework builds and checks those documents. It does not know about rules or governance
       decisions.

       Key terms:
         PATTERN   a reusable, versioned piece of architecture (for example an approval gate).
         RA        an Assessment Requirement template. Here RA03-LITE says what an application must describe.
         FORM      a YAML file of attribute answers (application name, data classification, payment limit...).
         INSTANTIATE  compose patterns and a form into a concrete CALM document.
         VALIDATE  check the result against the CALM schema and the template.

       Patterns and RAs have a lifecycle (DRAFT, IN_REVIEW, APPROVED, PUBLISHED, DEPRECATED). Only approved or
       published ones may be composed.""")

prereqs(calm=True)

step("Run this framework's automated tests",
     "A baseline check before exploring by hand. The tests cover the pattern library, lifecycle, composition and validation.",
     [C("uv run pytest -q calm-app-generation-framework/tests", "Only this framework's tests, offline.")],
     "All passed.")

step("1. Patterns, versions and the attributes form",
     """Start with what the library contains. 'versions' prints a version and SHA-256 hash for every pattern and
     for RA03-LITE. Those hashes are what later assessments record, so a result can always be tied to the exact
     pattern content it used. 'form' writes the questionnaire for an RA, which a person fills in.""",
     [C("uv run python -m calm_generation patterns", "List the patterns and their lifecycle state."),
      C("uv run python -m calm_generation versions", "Version and SHA-256 per pattern and RA."),
      C("uv run python -m calm_generation form RA03-LITE --out _out/form.yaml", "Generate the attributes form."),
      C("head -40 _out/form.yaml", "Read the questions the form asks.")],
     "8 patterns, all PUBLISHED. A hash next to every item. A YAML form with attribute fields.",
     "Content-addressed versions give reproducibility. If a pattern changes by one byte, its hash changes.")

step("2. Lifecycle: a deprecated pattern cannot be used (on a copy)",
     """The registry file lifecycle.yaml stores each pattern's state. You will work on a copy, using --registry,
     so the real registry is unchanged.

     You deprecate pattern P13, then ask the framework to compose. Composition must be refused because P13 is
     no longer APPROVED or PUBLISHED. The other lifecycle commands (submit, approve, publish, reject) take the
     same --by --role --rationale options.""",
     [C("cp calm-app-generation-framework/registry/lifecycle.yaml _out/lifecycle.yaml", "Make a safe copy."),
      C('uv run python -m calm_generation --registry _out/lifecycle.yaml deprecate P13 --by ann --role architect --rationale "test"',
        "Deprecate P13. The role must be allowed to do this (architect or governance_admin)."),
      C("uv run python -m calm_generation --registry _out/lifecycle.yaml compose",
        "Try to compose. This must be REFUSED."),
      C("grep -n -A8 'P13' _out/lifecycle.yaml | head -25", "See the recorded state change.")],
     "compose is refused and names P13 as not APPROVED/PUBLISHED. The copy records who deprecated it and why.",
     "Governance depends on this: an unapproved or retired pattern can never end up in an assessed architecture.")

step("3. Instantiate and validate: the good case (V1)",
     """V1 is the 'clean' variant of the sample Invoice Lite application. Instantiating combines the patterns
     with the attributes form to produce a CALM JSON file. Validation then runs the real calm CLI.

     The output includes a SHA-256 of the document. Doing it twice must give the same hash. That proves
     generation is deterministic.""",
     [C("uv run python -m calm_generation instantiate --form governance-execution-framework/forms/v1.attributes.yaml --out _out/v1.json",
        "Build V1 from its form."),
      C("uv run python -m calm_generation validate _out/v1.json", "Validate with the real calm CLI."),
      C("uv run python -m calm_generation instantiate --form governance-execution-framework/forms/v1.attributes.yaml --out _out/v1_again.json && "
        "uv run python -m calm_generation validate _out/v1_again.json",
        "Do it again and compare the hash printed by the two validations."),
      C("head -c 900 _out/v1.json; echo", "Peek at the generated CALM document (nodes, relationships, metadata).")],
     "'VALID app=invoice-lite-v1 sha256=2796d275...' both times, with the same hash.")

step("4. Instantiate and validate: the bad case (V4)",
     """V4 deliberately breaks a rule: the Payment Agent's payment_limit is above the allowed maximum of 100000.
     The schema catches it, so the document is INVALID.

     This matters later. The Governance framework refuses to make a decision on an invalid document. It reports
     BLOCKED instead.""",
     [C("uv run python -m calm_generation instantiate --form governance-execution-framework/forms/v4.attributes.yaml --out _out/v4.json",
        "Build V4. The instantiate step already reports the problem."),
      C("uv run python -m calm_generation validate _out/v4.json", "Validate it explicitly."),
      C("uv run python -m calm_generation validate _out/v4.json --template RA03-LITE",
        "Validate against the template too (the troubleshooting variant).")],
     "'INVALID' with '/nodes/payment-agent/metadata/payment_limit: must be <= 100000'.")

step("5. Build V2 and V3 and compare with the committed fixtures",
     """V2 and V3 are the other two sample variants. They are valid documents but have design problems that the
     Governance framework judges later: V2 lets the Payment Agent call the Payment API directly, skipping the
     approval control. V3 has no audit service and an autonomous Payment Agent. CALM validation does not care
     about those, because they are governance concerns, not schema errors.""",
     [C("uv run python -m calm_generation instantiate --form governance-execution-framework/forms/v2.attributes.yaml --out _out/v2.json",
        "Build V2."),
      C("uv run python -m calm_generation instantiate --form governance-execution-framework/forms/v3.attributes.yaml --out _out/v3.json",
        "Build V3."),
      C("ls calm-app-generation-framework/fixtures/variants", "The same four variants are committed as fixtures."),
      C("uv run python -m calm_generation validate calm-app-generation-framework/fixtures/variants/invoice-lite-v2.json",
        "Validate a committed fixture. Compare with your generated V2.")],
     "V2 and V3 report VALID. The fixtures folder lists invoice-lite-v1.json to invoice-lite-v4.json.",
     "These four files are the test inputs for the Governance walkthrough.")

dashboard_check("CALM App Generation",
                "Check that the pattern library and RA templates are visible, with the same versions you printed.",
                [("/registry/patterns", "The patterns with state PUBLISHED and their version and SHA-256."),
                 ("/registry/ras", "RA03-LITE with its version and state."),
                 ("/versions", "All active versions in one table. Compare with 'calm_generation versions'."),
                 ("/variants", "Summary of the four sample variants (their decisions appear after the Governance run)."),
                 ("/workbench/calm-generation", "The CALM generation commands and history.")])

finish("CALM App Generation walkthrough",
       "Next: run walk_governance_execution.py. It reuses _out/v1.json and _out/v4.json if they exist, and builds them if not.")
