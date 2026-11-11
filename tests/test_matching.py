"""Offline test of conversation matching in bridge.py. No Copilot runtime, no
credits: Conversation is replaced by a fake that records what would be sent.

Replays what a bridge log showed on 2026-11-10: three minutes after a turn,
Claude Code sent a request of its own on the main history. The bridge took
it as `continue`, and the owner's next message no longer matched and was
flattened into a new session.

    uv run python tests/test_matching.py

Exits 0 when every check holds, 1 with the failing check named otherwise.
"""
import logging
import sys
import threading
from pathlib import Path

logging.basicConfig(format="%(asctime)s %(levelname)s %(filename)s:%(lineno)d %(funcName)s — %(message)s",
                    level=logging.INFO)
log = logging.getLogger("test-matching")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import bridge  # noqa: E402

SENT = []       # (conv_id, text) for every message a start() would send
FAILED = []


class FakeSession:
    def __init__(self, conv_id):
        self.conv_id = conv_id

    def send(self, text):
        SENT.append((self.conv_id, text))
        return None


class FakeConversation:
    """The fields plan_request and find_conversation touch, nothing more."""
    count = 0

    def __init__(self, model, system, tools):
        FakeConversation.count += 1
        self.id = f"conv_fake{FakeConversation.count}"
        self.model = model
        self.system = system
        self.tool_names = bridge.tool_names(tools)
        self.sigs = []
        self.loose_sigs = []
        self.before_continue_sigs = None
        self.before_continue_loose = None
        self.pending = {}
        self.busy = threading.Lock()
        self.closed = False
        self.session = FakeSession(self.id)

    def switch_model(self, model):
        self.model = model

    def retool(self, tools):
        self.tool_names = bridge.tool_names(tools)

    def close(self, why):
        self.closed = True


def check(name, ok, detail):
    if ok:
        log.info("PASS %s", name)
        return
    log.error("FAIL %s: %s", name, detail)
    FAILED.append(name)


def user(text):
    return {"role": "user", "content": [{"type": "text", "text": text}]}


def assistant(text):
    return {"role": "assistant", "content": [{"type": "text", "text": text}]}


def request(messages, model="claude-opus-5.5"):
    """One /v1/messages call, as far as planning goes. Runs start() so SENT
    shows the text that would reach the Copilot session."""
    body = {"model": model, "system": "You are a test.", "tools": [], "messages": messages}
    conv, start, path = bridge.plan_request(body)
    start()
    return conv, path


def reply(conv, text):
    """What messages_endpoint does when a turn ends: the reply joins the history."""
    msg = assistant(text)
    conv.sigs = conv.sigs + [bridge.message_signature(msg)]
    conv.loose_sigs = conv.loose_sigs + [bridge.message_signature(msg, user_text=False)]
    return msg


def main():
    bridge.Conversation = FakeConversation
    bridge.run_async = lambda coro, timeout=120: coro
    bridge.COPILOT_MODELS = {"claude-opus-5.5", "claude-sonnet-5"}
    bridge.DEFAULT_MODEL = "claude-opus-5.5"
    bridge.SMALL_MODEL = "claude-sonnet-5"

    u1 = user("first question")
    main_conv, path = request([u1])
    check("1 first message is fresh", path == "fresh", path)
    a1 = reply(main_conv, "first answer")

    log.info("side request on the main history, as Claude Code sends after 3 idle minutes")
    conv, path = request([u1, a1, user("summarise the session so far")])
    check("2 side request rides on the main conversation", conv is main_conv and path == "continue",
          f"{conv.id} {path}")
    reply(conv, "a summary")

    log.info("the owner's next message: its history does not have the side exchange")
    u2 = user("second question")
    conv, path = request([u1, a1, u2])
    check("3 next real message resumes the main conversation",
          conv is main_conv and path == "continue-dropped-last", f"{conv.id} {path}")
    sent_text = SENT[-1][1]
    check("3 the model is told to disregard the side exchange",
          sent_text.startswith(bridge.DROPPED_EXCHANGE_NOTE) and sent_text.endswith("second question"),
          sent_text[:120])
    a2 = reply(conv, "second answer")

    log.info("second side request, then a real message where message 0 was re-wrapped (/model)")
    conv, path = request([u1, a1, u2, a2, user("summarise the session so far")])
    check("4 second side request rides along too", conv is main_conv and path == "continue",
          f"{conv.id} {path}")
    reply(conv, "another summary")
    u1_rewrapped = user("<system-reminder>first question</system-reminder>")
    u3 = user("third question")
    conv, path = request([u1_rewrapped, a1, u2, a2, u3], model="claude-sonnet-5")
    check("5 resumes although earlier user text changed and the model switched",
          conv is main_conv and path == "continue-dropped-last" and conv.model == "claude-sonnet-5",
          f"{conv.id} {path} {conv.model}")
    a3 = reply(conv, "third answer")

    log.info("an ordinary follow-up must not carry the note")
    u4 = user("fourth question")
    conv, path = request([u1_rewrapped, a1, u2, a2, u3, a3, u4], model="claude-sonnet-5")
    check("6 ordinary follow-up is a plain continue", conv is main_conv and path == "continue",
          f"{conv.id} {path}")
    check("6 ordinary follow-up is sent as typed", SENT[-1][1] == "fourth question", SENT[-1][1][:120])
    reply(conv, "fourth answer")

    log.info("a turn that used tools is kept by Claude Code: no going back past it")
    tool_conv, path = request([user("tool question")])
    a_t1 = reply(tool_conv, "tool answer")
    u_t2 = user("run the tool")
    conv, path = request([user("tool question"), a_t1, u_t2])
    check("7 follow-up before the tool turn is a plain continue", conv is tool_conv and path == "continue",
          f"{conv.id} {path}")
    tool_use = {"role": "assistant", "content": [{"type": "tool_use", "id": "call_1", "name": "Read",
                                                  "input": {"file_path": "a.txt"}}]}
    tool_conv.sigs = tool_conv.sigs + [bridge.message_signature(tool_use)]
    tool_conv.loose_sigs = tool_conv.loose_sigs + [bridge.message_signature(tool_use, user_text=False)]
    tool_conv.pending = {"call_1": "request_1"}
    conv, path = request([user("tool question"), a_t1, user("something else")])
    check("7 a parked conversation is not resumed from before its continue",
          conv is not tool_conv and path == "fresh-flattened", f"{conv.id} {path}")

    log.info("a history no conversation has seen")
    conv, path = request([user("unknown"), assistant("unknown answer"), user("more")])
    check("8 unknown history is flattened into a new conversation",
          conv is not main_conv and conv is not tool_conv and path == "fresh-flattened", f"{conv.id} {path}")

    if FAILED:
        log.error("%d check(s) failed: %s", len(FAILED), FAILED)
        sys.exit(1)
    log.info("all checks passed")


main()
