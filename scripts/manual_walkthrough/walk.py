"""Shared helper for the interactive manual walkthrough scripts.

Every step explains what is about to happen and why, shows the exact command,
waits for you, runs it in Git Bash from the repo root, and tells you what to
look for in the output.

Keys at every prompt:  Enter = go on   s = skip this command   q = quit
"""
from __future__ import annotations

import atexit
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import textwrap
import time
import webbrowser
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # ai-governance-intelligence-platform/
DASH_HOST, DASH_PORT = "127.0.0.1", 8001
DASH_URL = f"http://{DASH_HOST}:{DASH_PORT}"

os.system("")  # enables ANSI colours in the Windows console
B, DIM, CY, GR, YE, RE, X = "\033[1m", "\033[2m", "\033[36m", "\033[32m", "\033[33m", "\033[31m", "\033[0m"

state: dict[str, str] = {}   # values captured from earlier steps, e.g. trace ids
_n = 0
_dash_proc = None


@dataclass
class C:
    """One shell command inside a step."""
    sh: str                      # bash code; use @@key@@ to insert a captured value
    note: str = ""               # one-line explanation of this command
    show: str | None = None      # regex: print only matching lines (full output still captured)
    save: str | None = None      # state key under which to store the trace_id found in the output
    confirm: str | None = None   # destructive: require typing 'yes' with this warning


def find_bash() -> str:
    """Path of Git Bash; exits with a message if it cannot be found."""
    for p in (r"C:\Program Files\Git\bin\bash.exe", r"C:\Program Files\Git\usr\bin\bash.exe"):
        if Path(p).exists():
            return p
    w = shutil.which("bash")
    if w:
        return w
    sys.exit("Git Bash not found. Install Git for Windows or edit find_bash() in walk.py.")


BASH = find_bash()


# ---------------------------------------------------------------- printing
def say(text: str, colour: str = "", indent: int = 2) -> None:
    """Print prose. Unindented lines that follow each other are joined into one wrapped paragraph; indented lines
    (lists, tables) are kept as they are."""
    raw = text.strip("\n").split("\n")
    lines = [raw[0].strip()] + textwrap.dedent("\n".join(raw[1:])).split("\n") if raw else []
    width = 98 - indent
    para: list[str] = []

    def flush() -> None:
        """Print the buffered paragraph wrapped to width, then clear the buffer."""
        if para:
            for line in textwrap.wrap(" ".join(para), width):
                print(f"{colour}{' ' * indent}{line}{X if colour else ''}")
            para.clear()

    for line in lines:
        if not line.strip():
            flush()
            print()
        elif line[0] != " ":
            para.append(line.strip())
        else:
            flush()
            lead = len(line) - len(line.lstrip())
            for i, part in enumerate(textwrap.wrap(line.strip(), width - lead) or [""]):
                pad = lead if i == 0 else lead + 2
                print(f"{colour}{' ' * (indent + pad)}{part}{X if colour else ''}")
    flush()


def pause(prompt: str = "Press Enter to continue (q = quit)") -> str:
    """Prompt and return the lowercased answer. 'q', Ctrl-C and EOF end the program cleanly."""
    try:
        a = input(f"\n{YE}>> {prompt}: {X}").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print("\nStopped.")
        raise SystemExit(0)
    if a == "q":
        print("Bye. Nothing is left running except a dashboard window, if you started one.")
        raise SystemExit(0)
    return a


def banner(title: str, intro: str) -> None:
    """Print the walkthrough title and intro, then wait for Enter."""
    print(f"\n{B}{CY}{'=' * 100}\n  {title}\n{'=' * 100}{X}")
    say(intro)
    print(f"\n{DIM}  Keys: Enter = go on | s = skip a command | q = quit. Commands run in Git Bash from:\n  {ROOT}{X}")
    pause("Press Enter to begin")


# ---------------------------------------------------------------- running
def _env() -> dict[str, str]:
    """Environment for child processes: keep Git Bash in the repo root and force UTF-8 output."""
    e = dict(os.environ)
    e["CHERE_INVOKING"] = "1"           # keep Git Bash in the repo root
    e["PYTHONIOENCODING"] = "utf-8"
    return e


def run(sh: str, show: str | None = None, save: str | None = None) -> tuple[int, str]:
    """Run a command in Git Bash from the repo root after substituting @@name@@ placeholders from `state`. Returns (exit code, combined output); returns 1 if a placeholder has no value yet."""
    for k, v in state.items():
        sh = sh.replace(f"@@{k}@@", v)
    if "@@" in sh:
        print(f"{RE}  A value from an earlier step is missing ({re.findall('@@(.*?)@@', sh)}). "
              f"Run the earlier step first.{X}")
        return 1, ""
    p = subprocess.run([BASH, "-lc", sh], cwd=ROOT, env=_env(), capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    out = (p.stdout or "") + (p.stderr or "")
    lines = out.rstrip("\n").split("\n") if out.strip() else ["(no output)"]
    if show:
        picked = [l for l in lines if re.search(show, l)]
        lines = picked or lines
    limit = 70
    print(f"{DIM}  ---- output ----{X}")
    for l in lines[:limit]:
        print("  " + l)
    if len(lines) > limit:
        print(f"{DIM}  ... {len(lines) - limit} more lines hidden. Type f at the next prompt to see all.{X}")
        if pause("Enter = continue | f = show everything") == "f":
            for l in lines[limit:]:
                print("  " + l)
    print(f"{DIM}  ---- exit code {p.returncode} ----{X}")
    if save:
        m = re.search(r'"trace_id"\s*:\s*"([^"]+)"', out)
        if m:
            state[save] = m.group(1)
            print(f"{GR}  Captured trace_id for later steps: {m.group(1)}{X}")
        else:
            print(f"{YE}  No trace_id found in the output, so later steps that need it will be skipped.{X}")
    return p.returncode, out


def step(title: str, why: str, cmds: list | tuple = (), look_for: str = "", nuance: str = "") -> None:
    """Present one walkthrough step: explain it, show each command and run it on request."""
    global _n
    _n += 1
    print(f"\n{B}{CY}--- STEP {_n}: {title} ---{X}")
    say(why)
    for c in cmds:
        c = C(c) if isinstance(c, str) else c
        print()
        if c.note:
            say(c.note, DIM)
        shown = c.sh
        for k, v in state.items():
            shown = shown.replace(f"@@{k}@@", v)
        print(f"{GR}  $ " + shown.replace("\n", f"\n{GR}    ") + X)
        a = pause("Enter = run it | s = skip | q = quit")
        if a == "s":
            continue
        if c.confirm:
            say(c.confirm, RE)
            if input(f"{RE}>> Type yes to run it: {X}").strip().lower() != "yes":
                print("  Skipped.")
                continue
        code, _ = run(c.sh, c.show, c.save)
        if code != 0:
            print(f"{YE}  Non-zero exit is not always a problem. Some steps are meant to be refused. "
                  f"Compare with 'What to look for'.{X}")
    if look_for:
        print(f"\n{B}  What to look for:{X}")
        say(look_for, indent=4)
    if nuance:
        print(f"\n{B}  Why it matters:{X}")
        say(nuance, indent=4)
    pause("Enter = next step")


def manual(title: str, why: str, todo: list[str]) -> None:
    """A step where you do something yourself (browser, file) and come back."""
    global _n
    _n += 1
    print(f"\n{B}{CY}--- STEP {_n}: {title} (you do this one) ---{X}")
    say(why)
    for t in todo:
        say("- " + t, indent=4)
    pause("Enter when done")


# ---------------------------------------------------------------- dashboard
def _dash_up() -> bool:
    """True if something is listening on the dashboard host and port."""
    try:
        with socket.create_connection((DASH_HOST, DASH_PORT), timeout=1):
            return True
    except OSError:
        return False


def start_dashboard() -> None:
    """Start the dashboard in a new console window unless it is already running, then wait up to 30 seconds for it to listen."""
    global _dash_proc
    if _dash_up():
        print(f"{GR}  Dashboard already running at {DASH_URL}{X}")
        return
    print("  Starting the dashboard in a new console window ...")
    flags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
    _dash_proc = subprocess.Popen(
        [BASH, "-lc", "uv run python -m governance_execution.dashboard.app"],
        cwd=ROOT, env=_env(), creationflags=flags)
    for _ in range(30):
        if _dash_up():
            print(f"{GR}  Dashboard is up at {DASH_URL}{X}")
            return
        time.sleep(1)
    print(f"{RE}  Dashboard did not answer within 30 s. Look at the new window for the error.{X}")


def dashboard_check(title: str, why: str, pages: list[tuple[str, str]]) -> None:
    """Start the dashboard and walk through pages: (path, what to check)."""
    global _n
    _n += 1
    print(f"\n{B}{CY}--- STEP {_n}: DASHBOARD CHECK - {title} ---{X}")
    say(why)
    say("""The dashboard is a read-only view over the files in DATA_DIR (default data/). It reads them on every
          request, so after any CLI run you only need to refresh the browser. Every page shows the labels
          'illustrative, not approved policy' and 'design-level evidence only'. That is intentional.""", DIM)
    pause("Enter = start the dashboard (or reuse the running one)")
    start_dashboard()
    for path, check in pages:
        for k, v in state.items():
            path = path.replace(f"@@{k}@@", v)
        if "@@" in path:
            print(f"\n{YE}  Skipping {path}: it needs a trace id that was not captured.{X}")
            continue
        url = DASH_URL + path
        print(f"\n{B}  Open: {url}{X}")
        say(check, indent=4)
        a = pause("Enter = open in browser and continue | n = continue without opening")
        if a != "n":
            webbrowser.open(url)
            pause("Enter when you have looked at it")
    print(f"\n{GR}  Dashboard left running in its own window. Close it with Ctrl+C there when finished.{X}")


# ---------------------------------------------------------------- prerequisites
def ensure_offline_env() -> None:
    """Offer to set MODEL_PROVIDER=replay and DECIDER_PROVIDER=fixture in .env (backup kept)."""
    env = ROOT / ".env"
    want = {"MODEL_PROVIDER": "replay", "DECIDER_PROVIDER": "fixture"}
    if not env.exists():
        ex = ROOT / ".env.example"
        if ex.exists():
            shutil.copy(ex, env)
            print(f"{GR}  Created .env from .env.example{X}")
        else:
            env.write_text("", encoding="utf-8")
    text = env.read_text(encoding="utf-8")
    current = {k: (re.search(rf"^{k}=(\S*)", text, re.M) or [None, "<unset>"])[1] for k in want}
    print(f"  Current .env: {current}")
    if all(current[k] == v for k, v in want.items()):
        print(f"{GR}  Already offline. Nothing to change.{X}")
        return
    if input(f"{YE}>> Set them to {want}? A backup .env.bak is kept. [y/N]: {X}").strip().lower() != "y":
        print("  Left unchanged. Live settings may call Bedrock or your Decider endpoint.")
        return
    shutil.copy(env, ROOT / ".env.bak")
    for k, v in want.items():
        if re.search(rf"^{k}=", text, re.M):
            text = re.sub(rf"^{k}=.*$", f"{k}={v}", text, flags=re.M)
        else:
            text += f"\n{k}={v}\n"
    env.write_text(text, encoding="utf-8")
    print(f"{GR}  .env updated.{X}")


def prereqs(*, calm: bool = False, spectral: bool = False, aigf: bool = False, ccc: bool = False) -> None:
    """Walk through the prerequisite checks; flags add the checks for calm, spectral, AIGF and CCC."""
    step("Git Bash and the repo root",
         """Every command in this walkthrough runs in Git Bash from the platform folder
         (ai-governance-intelligence-platform). The folder matters because paths such as
         rule-authoring-framework/ and _out/ are relative to it.""",
         [C("pwd && bash --version | head -1", "Confirms the shell works and that it starts in the platform folder.")],
         "The path should end in ai-governance-intelligence-platform and a GNU bash version should print.")

    step("uv and Python dependencies",
         """uv is the Python package manager used here. 'uv sync' reads pyproject.toml and installs every
         dependency into a local virtual environment, so the later 'uv run ...' commands work. It is safe to
         repeat.""",
         [C("uv --version", "Checks uv is installed (install from https://docs.astral.sh/uv/ if not)."),
          C("uv sync", "Installs or updates the Python dependencies.")],
         "No red errors. The final lines mention the packages being resolved or 'Audited'.")

    if calm:
        step("CALM CLI",
             """CALM (Common Architecture Language Model) is a FINOS standard for describing architectures as JSON.
             The 'calm' command validates those documents against the standard's meta-schemas. The platform
             calls it for real in this walkthrough, so it has to be installed. Version 1.60.1 is the one the docs
             were written against.""",
             [C("calm --version", "Prints the installed version."),
              C("npm i -g @finos/calm-cli@1.60.1", "Only run this if the version check failed.")],
             "A version number such as 1.60.1.")
    if spectral:
        step("Spectral",
             """Spectral is a rule linter. The Rule Authoring framework compiles approved controls into Spectral
             rulesets, and the Governance framework runs Spectral over a CALM document to find control gaps.
             It is installed locally under .tools/, not globally.""",
             [C(".tools/node_modules/.bin/spectral --version", "Checks the local install."),
              C("npm i --prefix .tools @stoplight/spectral-cli@6.17.1", "Only run this if the check failed.")],
             "Version 6.17.1.",
             "Offline recorded runs match the exact bytes of the committed rulesets. Spectral itself is only "
             "needed when you pass --cli real.")
    if aigf or ccc:
        step("Source repositories",
             """Rules are authored from two public FINOS sources: AIGF (the AI Governance Framework: risks and
             mitigations) and CCC (Common Cloud Controls: controls, threats, capabilities). Ingestion reads their
             files from folders that sit next to this repo.""",
             [C("ls -d ../ai-governance-framework ../common-cloud-controls 2>&1",
                "Both folders must exist (only the ones you need are checked at ingest time).")],
             "Both paths listed. If one says 'No such file', clone it next to this repo before continuing.")

    step("Offline configuration (.env)",
         """Settings come from a .env file that is never committed. Two settings decide whether anything talks
         to the network:
           MODEL_PROVIDER=replay    the LLM is replaced by recorded answers
           DECIDER_PROVIDER=fixture the Decider (the service that classifies unclear facts) is replaced by
                                    recorded answers
         With both set, nothing calls Bedrock or EC2, so every run is repeatable and free.""",
         [C("grep -E '^(MODEL_PROVIDER|DECIDER_PROVIDER|DATA_DIR)=' .env || echo '(no .env yet)'",
            "Shows what is set now.")])
    ensure_offline_env()
    pause("Enter = next step")

    step("Scratch folder and optional reset",
         """Everything this walkthrough creates goes into _out/ (git-ignored) so the committed catalogs, rulesets
         and config are never touched. Assessment runs are stored under data/ (DATA_DIR) and the dashboard
         reads that folder. Resetting gives an empty dashboard, which makes each new run easy to spot.""",
         [C("mkdir -p _out && ls -d _out", "Creates the scratch folder."),
          C("rm -rf data _out && mkdir -p _out", "Reset: deletes data/ and _out/ (stored runs and scratch files).",
            confirm="This deletes the data/ folder (all stored assessments) and _out/. Skip it if you want to keep earlier runs.")],
         "_out exists afterwards.")


# ---------------------------------------------------------------- live Bedrock check (Rule Authoring)
_WATCH = ("rule-authoring-framework/fixtures/recordings", "rule-authoring-framework/catalogs")


def _git_status() -> dict[str, str]:
    """Porcelain git status of the watched paths as {path: two-letter status}."""
    p = subprocess.run(["git", "status", "--porcelain", "--untracked-files=all", "--", *_WATCH], cwd=ROOT,
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    return {l[3:].strip().strip('"'): l[:2] for l in p.stdout.splitlines() if l.strip()}


def live_bedrock_extraction(item: str = "ri-24", keep_dir: str = "_out/live-bedrock") -> None:
    """One real Bedrock call through Strands. Keeps the live output, then restores committed files it changed."""
    global _n
    _n += 1
    print(f"\n{B}{CY}--- STEP {_n}: LIVE CHECK - Bedrock via Strands (optional, one billed call) ---{X}")
    say(f"""This proves the Rule Authoring LLM path works for real. ingest --extract --provider bedrock builds a
        ModelGateway with a StrandsRuntime (shared/src/agip_shared/gateway/runtime_strands.py). That creates a
        strands.Agent with a BedrockModel, using AWS_PROFILE, AWS_REGION and BEDROCK_MODEL_ID from .env.

        Side effects handled for you: a live call overwrites the committed recording for the same input, which the
        offline replay depends on. This step copies every file the run changed into {keep_dir}/ and then restores
        the committed versions with git. Sources are written to _out, never to catalogs/sources.

        Possible results:
          drafted=1        Bedrock answered and the answer passed the extraction schema (a DRAFT is written).
          errors=1 schema  Bedrock answered, but the answer broke a schema rule. The framework refuses it.
          errors=1 other   no call reached Bedrock (credentials, missing package, model not enabled).""")
    print(f"\n{DIM}  Needs: aws login --profile <AWS_PROFILE> done recently, and the model enabled in that region.{X}")
    cmd = (f"uv run python -m rule_authoring.ingest --source aigf --ids {item} --out {keep_dir}/aigf-{item}.json "
           f"--extract --provider bedrock --drafts {keep_dir}/drafts")
    print(f"{GR}  $ mkdir -p {keep_dir} && {cmd}{X}")
    if pause("Enter = run it (calls Bedrock) | s = skip | q = quit") == "s":
        return
    before = _git_status()
    code, out = run(f"mkdir -p {keep_dir} && {cmd}", show=r"extraction:|ERROR|DRAFT|drafted|wrote|items")
    after = _git_status()
    changed = {p: s for p, s in after.items() if before.get(p) != s}
    keep = ROOT / keep_dir / "changed-files"
    for rel, st in changed.items():
        src = ROOT / rel
        if src.is_file():
            dst = keep / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(src, dst)
        if st.strip() == "??":
            src.unlink(missing_ok=True)                 # created by this run only
        else:
            subprocess.run(["git", "checkout", "--", rel], cwd=ROOT, capture_output=True)
    if changed:
        print(f"{GR}  Kept {len(changed)} changed file(s) under {keep_dir}/changed-files and restored the committed versions:{X}")
        for rel in changed:
            print(f"    {rel}")
    else:
        print(f"{DIM}  No committed file was changed by the run.{X}")
    rec = next((ROOT / keep_dir / "changed-files" / r for r in changed if "recordings" in r and r.endswith(".json")), None)
    if rec and rec.is_file():
        try:
            d = json.loads(rec.read_text(encoding="utf-8"))
            print(f"\n{B}  Live Extraction_Record:{X} model={d.get('model')} prompt={d.get('prompt_id')}.{d.get('prompt_version')} "
                  f"input_hash={str(d.get('input_hash'))[:12]}...")
            print(textwrap.indent(json.dumps(d.get("output"), indent=2, ensure_ascii=False)[:2500], "    "))
        except (ValueError, OSError):
            pass
    print(f"\n{B}  What to look for:{X}")
    say("""model= shows the Bedrock model id (not 'recorded-seed'), which proves a real call. If the output was
          rejected, the ERROR line names the schema rule it broke.""", indent=4)
    pause("Enter = next step")


def finish(what: str, next_hint: str = "") -> None:
    """Print the closing banner and an optional hint for what to do next."""
    print(f"\n{B}{GR}{'=' * 100}\n  Done: {what}\n{'=' * 100}{X}")
    if next_hint:
        say(next_hint)
