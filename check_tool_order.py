"""Weekly check: does the Copilot runtime still pair parallel tool results by
answer order instead of request id on GPT models?

bridge.py refuses every model family not listed in its
VERIFIED_MODEL_PREFIXES because of this defect (2026-11-09: gpt-6-luna swapped
results 3 of 3 times when answered in reverse order). This runs
probe_tool_order.py in reverse-answer mode, RUNS times per model, and
records a verdict per model:

  fixed        every run correct            -> candidate for the allowlist
  broken       at least one swapped run
  inconclusive no swap seen, but not every run produced a usable answer

claude-sonnet-5 is the control. If it is not "fixed", the probe itself is
broken and the run exits 1.

Results: logs/tool-order/history.jsonl (one line per model per run) and
logs/tool-order/state.json (last verdict per model). A mail goes out through
--mail-script only when a verdict differs from state.json, so a quiet week sends
nothing. The first run sends one, because there is no state yet.

Costs RUNS short probe turns per model in Copilot AI credits; a few credits
per week at 2026-11 prices.

    uv run check_tool_order.py
    uv run check_tool_order.py --mail-script C:/path/to/send-mail.ps1

--mail-script is any PowerShell script taking -Subject and -Body (HTML) and
exiting 0 on success. Without it, nothing is mailed and the log says so.
"""
import argparse
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

CONTROL = "claude-sonnet-5"
MODELS = ["gpt-6-luna", "gpt-6-sol", "kimi-k3", CONTROL]
RUNS = 5
PARK_S = 8          # the probe waits this long for both tool calls to arrive

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
    tail = out.strip().splitlines()[-3:]
    log.warning("probe on %s gave no usable answer (exit %s): %s", model, proc.returncode, tail)
    return "inconclusive"


def verdict(runs):
    if "swapped" in runs:
        return "broken"
    if all(r == "ok" for r in runs):
        return "fixed"
    return "inconclusive"


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
    ap.add_argument("--models", nargs="+", default=MODELS)
    args = ap.parse_args()

    previous = {}
    if STATE.exists():
        previous = json.loads(STATE.read_text(encoding="utf-8"))
    versions = copilot_versions()
    now = dt.datetime.now().isoformat(timespec="seconds")
    log.info("checking %s, %d reverse-order runs each, copilot %s", args.models, RUNS, versions)

    current = {}
    for model in args.models:
        runs = []
        for i in range(RUNS):
            runs.append(run_probe(model))
        v = verdict(runs)
        current[model] = v
        log.info("%s: %s (%s)", model, v, runs)
        with HISTORY.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"time": now, "model": model, "verdict": v, "runs": runs,
                                "versions": versions}) + "\n")

    changed = {m: (previous.get(m), v) for m, v in current.items() if previous.get(m) != v}
    # Merge: a --models subset must not wipe the other models' verdicts.
    STATE.write_text(json.dumps({**previous, **current}, indent=1), encoding="utf-8")

    control_ok = current.get(CONTROL, "fixed") == "fixed"
    if not control_ok:
        log.error("control model %s is %s: the probe is broken, not only GPT", CONTROL, current[CONTROL])

    if changed and not args.mail_script:
        log.warning("verdict changed (%s) but no --mail-script given; not mailed", changed)
    if changed and args.mail_script:
        rows = "".join(f"<tr><td>{m}</td><td>{old or '(none)'}</td><td>{new}</td></tr>"
                       for m, (old, new) in changed.items())
        html = (f"<p>Copilot tool-result pairing check, {now}, SDK {versions['sdk']}, "
                f"CLI {versions['cli']}.</p>"
                f"<table border='1' cellpadding='4'><tr><th>Model</th><th>Was</th><th>Now</th></tr>{rows}</table>"
                f"<p>fixed = {RUNS} of {RUNS} reverse-order runs paired correctly. A model that is "
                f"fixed can go into VERIFIED_MODEL_PREFIXES in bridge.py.</p>"
                + ("" if control_ok else f"<p>Control {CONTROL} failed: the probe itself is broken.</p>"))
        send_mail(args.mail_script, "[cuckoos-nest] Copilot tool-order check: verdict changed", html)
    elif not changed:
        log.info("no verdict changed since last run; no mail")

    sys.exit(0 if control_ok else 1)


if __name__ == "__main__":
    main()
