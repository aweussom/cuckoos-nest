"""Weekly check: does the Copilot runtime pair parallel tool results by
request id, or by answer order, on each model this account has?

On CLI 1.0.73 GPT models paired by answer order (2026-11-09: gpt-6-luna
swapped results 3 of 3 times when answered in reverse order; 2026-11-10,
CLI 1.0.108: no swap seen). This asks the SDK which models the account has,
runs probe_tool_order.py in reverse-answer mode RUNS times on each, and
records a verdict per model:

  ok           every run correct            -> bridge.py allows the model
  broken       at least one swapped run     -> bridge.py refuses the model
  inconclusive no swap seen, but at least one run gave no usable answer:
               the model did not make both Read calls in one message (so
               there was no order to reverse), the final text lacked a
               value, or the probe timed out

"ok" is a state, not a change. A repair shows in the mail as broken -> ok.

claude-sonnet-5.5 is the control and runs first. If it is not "ok", the probe
itself is broken: nothing else is run, state.json is left alone, exit 1.

Results: logs/tool-order/history.jsonl (one line per model per run) and
logs/tool-order/state.json (last verdict per model, with the SDK and CLI
version it was measured on). bridge.py reads state.json at startup and only
trusts verdicts measured on the CLI it runs. A mail goes out through
--mail-script only when a verdict differs from state.json, so a quiet week
sends nothing. The first run sends one, because there is no state yet.

Costs RUNS short probe turns per model in Copilot AI credits.

    uv run check_tool_order.py                       # every model the SDK lists
    uv run check_tool_order.py --models gpt-6-luna   # only these
    uv run check_tool_order.py --mail-script C:/path/to/send-mail.ps1

--mail-script is any PowerShell script taking -Subject and -Body (HTML) and
exiting 0 on success. Without it, nothing is mailed and the log says so.
"""
import argparse
import asyncio
import datetime as dt
import json
import logging
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT_DIR = ROOT / "logs" / "tool-order"
STATE = OUT_DIR / "state.json"
HISTORY = OUT_DIR / "history.jsonl"
PROBE = ROOT / "probe_tool_order.py"

CONTROL = "claude-sonnet-5.5"
# "auto" lets Copilot pick the model per request, so a verdict for it would
# describe whatever it picked that minute.
NOT_A_MODEL = ("auto",)
RUNS = 5
PARK_S = 8          # the probe holds the parked calls this long before answering

OUT_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    format="%(asctime)s %(levelname)s %(filename)s:%(lineno)d %(funcName)s — %(message)s",
    level=logging.INFO,
    handlers=[logging.FileHandler(OUT_DIR / "check.log", encoding="utf-8"),
              logging.StreamHandler(sys.stderr)])
log = logging.getLogger("tool-order")


def run_probe(model):
    """One reverse-order probe run. Returns 'ok', 'swapped' or 'inconclusive'."""
    cmd = [sys.executable.replace("pythonw.exe", "python.exe"), str(PROBE), model, str(PARK_S), "reverse"]
    log.info("running probe on %s, expecting MAPPING and RESULT lines within ~60 s", model)
    try:
        proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=300)
    except subprocess.TimeoutExpired:
        log.error("probe on %s timed out after 300 s", model)
        return "inconclusive"
    out = proc.stdout + proc.stderr
    mapping = re.search(r"MAPPING: (ok|SWAPPED)", out)
    result = re.search(r"RESULT: (PASS|FAIL)", out)
    if mapping and mapping.group(1) == "SWAPPED":
        log.info("probe on %s: SWAPPED", model)
        return "swapped"
    if mapping and result and result.group(1) == "PASS":
        log.info("probe on %s: ok", model)
        return "ok"
    # The pending count says whether the model made both calls in one message.
    pending = re.search(r"\d+ pending call\(s\), idle=\w+", out)
    final = re.search(r"final text: .*", out)
    log.warning("probe on %s gave no usable answer (exit %s): %s; %s", model, proc.returncode,
                pending.group(0) if pending else "no pending-call line",
                final.group(0)[:200] if final else "no final text")
    return "inconclusive"


def verdict(runs):
    if "swapped" in runs:
        return "broken"
    if all(r == "ok" for r in runs):
        return "ok"
    return "inconclusive"


async def list_models_from_sdk():
    from copilot import CopilotClient
    from copilot.generated.rpc import ModelsListRequest
    client = CopilotClient()
    await client.start()
    listed = await client.rpc.models.list(ModelsListRequest())
    await client.stop()
    return [m.id for m in listed.models]


def models_to_check():
    """Every model the account has, control first. A model that appears in
    Copilot next month gets measured without anyone editing a list."""
    log.info("asking the Copilot SDK which models this account has, expecting a list within ~60 s")
    listed = asyncio.run(list_models_from_sdk())
    log.info("SDK lists %d model(s): %s", len(listed), listed)
    if CONTROL not in listed:
        log.error("control model %s is not in the SDK's list; cannot tell a broken probe from a "
                  "broken runtime. Pick another CONTROL in %s", CONTROL, Path(__file__).name)
        sys.exit(1)
    models = [CONTROL]
    for model in listed:
        if model == CONTROL:
            continue
        if model in NOT_A_MODEL:
            log.info("skipping %s: not one model", model)
            continue
        models.append(model)
    return models


def previous_verdict(entry):
    """state.json before 2026-11-11 held a bare verdict per model; now it is
    a dict with the versions it was measured on."""
    if entry is None:
        return None
    if isinstance(entry, str):
        return entry
    return entry["verdict"]


def copilot_versions():
    try:
        from importlib import metadata
        sdk = metadata.version("github-copilot-sdk")
    except Exception:
        sdk = "unknown"
    try:
        from copilot._cli_version import CLI_VERSION
    except Exception:
        CLI_VERSION = "unknown"
    return {"sdk": sdk, "cli": CLI_VERSION}


def send_mail(script, subject, html):
    cmd = ["pwsh.exe", "-NoProfile", "-File", script, "-Subject", subject, "-Body", html]
    log.info("mailing %r through %s, expecting exit 0", subject, script)
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if proc.returncode != 0:
        log.error("mail script failed (exit %d): %s", proc.returncode, (proc.stdout + proc.stderr).strip()[-300:])
        return False
    log.info("mail script accepted the mail")
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mail-script", default=None,
                    help="PowerShell script taking -Subject and -Body; omit to send no mail")
    ap.add_argument("--models", nargs="+", default=None,
                    help="models to check; default is every model the Copilot SDK lists")
    args = ap.parse_args()

    models = args.models
    if models is None:
        models = models_to_check()

    previous = {}
    if STATE.exists():
        previous = json.loads(STATE.read_text(encoding="utf-8"))
    versions = copilot_versions()
    now = dt.datetime.now().isoformat(timespec="seconds")
    log.info("checking %d model(s) %s, %d reverse-order runs each, copilot %s; next: %s",
             len(models), models, RUNS, versions, models[0])

    current = {}
    runs_by_model = {}
    done = 0
    for model in models:
        runs = []
        for i in range(RUNS):
            runs.append(run_probe(model))
        v = verdict(runs)
        current[model] = v
        runs_by_model[model] = runs
        done += 1
        log.info("%s: %s (%s); %d of %d models done", model, v, runs, done, len(models))
        with HISTORY.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"time": now, "model": model, "verdict": v, "runs": runs,
                                "versions": versions}) + "\n")
        if model == CONTROL and v != "ok":
            log.error("control model %s is %s (%s): the probe is broken, so no other verdict would "
                      "mean anything. Stopping; %s is left as it was", CONTROL, v, runs, STATE)
            sys.exit(1)

    changed = {}
    for model, v in current.items():
        old = previous_verdict(previous.get(model))
        if old != v:
            changed[model] = (old, v)
    # Merge: a --models subset must not wipe the other models' verdicts.
    state = dict(previous)
    for model, v in current.items():
        state[model] = {"verdict": v, "runs": runs_by_model[model], "time": now,
                        "sdk": versions["sdk"], "cli": versions["cli"]}
    STATE.write_text(json.dumps(state, indent=1), encoding="utf-8")

    if changed and not args.mail_script:
        log.warning("verdict changed (%s) but no --mail-script given; not mailed", changed)
    if changed and args.mail_script:
        rows = ""
        for m, (old, new) in changed.items():
            runs_text = ", ".join(runs_by_model[m])
            rows += f"<tr><td>{m}</td><td>{old or '(none)'}</td><td>{new}</td><td>{runs_text}</td></tr>"
        html = (f"<p>Copilot tool-result pairing check, {now}, SDK {versions['sdk']}, "
                f"CLI {versions['cli']}. Only models whose verdict changed are listed.</p>"
                f"<table border='1' cellpadding='4'><tr><th>Model</th><th>Was</th><th>Now</th>"
                f"<th>Runs ({RUNS}, answered in reverse order)</th></tr>{rows}</table>"
                f"<p>ok = {RUNS} of {RUNS} runs paired correctly. broken = at least one run swapped "
                f"the results. inconclusive = no swap seen, but at least one run gave no usable "
                f"answer (the model did not make both calls in one message, the answer lacked a "
                f"value, or the probe timed out); logs/tool-order/check.log says which.</p>"
                f"<p>bridge.py reads these verdicts at startup: it allows a model that is ok on its "
                f"CLI and refuses one that is broken.</p>")
        send_mail(args.mail_script, "[cuckoos-nest] Copilot tool-order check: verdict changed", html)
    elif not changed:
        log.info("no verdict changed since last run; no mail")

    # A failed control has already exited 1 above.
    sys.exit(0)


if __name__ == "__main__":
    main()
