"""Offline test of the model allowlist in bridge.py: verdicts from
check_tool_order.py first, the prefixes as fallback. No Copilot runtime.

    uv run python tests/test_allowlist.py

Exits 0 when every check holds, 1 with the failing check named otherwise.
"""
import json
import logging
import sys
import tempfile
from pathlib import Path

logging.basicConfig(format="%(asctime)s %(levelname)s %(filename)s:%(lineno)d %(funcName)s — %(message)s",
                    level=logging.INFO)
log = logging.getLogger("test-allowlist")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import bridge  # noqa: E402
from copilot._cli_version import CLI_VERSION  # noqa: E402

FAILED = []


def check(name, ok, detail):
    if ok:
        log.info("PASS %s", name)
        return
    log.error("FAIL %s: %s", name, detail)
    FAILED.append(name)


def main():
    scratch = Path(tempfile.mkdtemp(prefix="allowlist-test-"))
    state_file = scratch / "state.json"

    log.info("no state file: the prefixes decide")
    bridge.TOOL_ORDER_STATE = state_file
    bridge.PAIRING_VERDICTS = {}
    bridge.load_pairing_verdicts()
    check("1 claude- allowed by prefix", bridge.pairing_refusal("claude-opus-5.5") is None,
          bridge.pairing_refusal("claude-opus-5.5"))
    check("1 gpt- allowed by prefix", bridge.pairing_refusal("gpt-6-luna") is None,
          bridge.pairing_refusal("gpt-6-luna"))
    check("1 kimi-k3 refused without a verdict", bridge.pairing_refusal("kimi-k3") is not None, "allowed")

    log.info("state file with verdicts for this CLI (%s), another CLI, and the old format", CLI_VERSION)
    state = {
        "kimi-k3": {"verdict": "ok", "cli": CLI_VERSION},
        "gpt-6-sol": {"verdict": "broken", "cli": CLI_VERSION},
        "gpt-6-luna": {"verdict": "inconclusive", "cli": CLI_VERSION},
        "other-model": {"verdict": "ok", "cli": "0.0.1"},
        "old-format-model": "ok",
        "gpt-6-astra": {"verdict": "broken", "cli": "0.0.1"},
    }
    state_file.write_text(json.dumps(state), encoding="utf-8")
    bridge.load_pairing_verdicts()
    check("2 ok on this CLI allows a model outside the prefixes",
          bridge.pairing_refusal("kimi-k3") is None, bridge.pairing_refusal("kimi-k3"))
    check("2 broken on this CLI refuses a model inside the prefixes",
          bridge.pairing_refusal("gpt-6-sol") is not None, "allowed")
    check("2 inconclusive falls back to the prefix",
          bridge.pairing_refusal("gpt-6-luna") is None, bridge.pairing_refusal("gpt-6-luna"))
    check("2 ok from another CLI does not count",
          bridge.pairing_refusal("other-model") is not None, "allowed")
    check("2 a bare verdict without a CLI version does not count",
          bridge.pairing_refusal("old-format-model") is not None, "allowed")
    check("2 broken from another CLI does not count either",
          bridge.pairing_refusal("gpt-6-astra") is None, bridge.pairing_refusal("gpt-6-astra"))

    log.info("require_verified raises with the reason")
    raised = ""
    try:
        bridge.require_verified("gpt-6-sol")
    except ValueError as e:
        raised = str(e)
    check("3 require_verified names the measurement", "measured it broken" in raised, raised or "no error")

    if FAILED:
        log.error("%d check(s) failed: %s", len(FAILED), FAILED)
        sys.exit(1)
    log.info("all checks passed")


main()
