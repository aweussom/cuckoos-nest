"""bridge.py: Anthropic Messages API in front of GitHub Copilot SDK sessions,
so Claude Code can run on Copilot models. Normally started per session by
claude-copilot.ps1; by hand:

    venv/Scripts/python.exe bridge.py --port 8790
    ANTHROPIC_BASE_URL=http://127.0.0.1:8790 ANTHROPIC_AUTH_TOKEN=x \
    ANTHROPIC_MODEL=claude-opus-5.5 claude

How it works, and why it is not a plain proxy:
  Copilot gives no raw completions; the SDK gives an agent session. But a
  session can (a) replace the system prompt, (b) allow ONLY client-declared
  tools, and (c) leave a declared tool without a handler. The runtime then
  emits external_tool.requested and PARKS the turn until someone answers with
  tools.handle_pending_tool_call. That is the bridge:

    POST /v1/messages (new user text)  -> session.send(text)
      model asks for tools              -> return tool_use, stop_reason=tool_use,
                                           turn stays parked in the session
    POST /v1/messages (tool_results)   -> handle_pending_tool_call per id,
                                           stream what the model does next

  Claude Code is stateless (full history every call); the session is not.
  Each call is matched to a live conversation by a signature of the message
  list. A call that matches nothing (first call, compaction, rewind, side
  calls like title generation) gets a fresh session seeded with the earlier
  history flattened to text. That path is lossy and logged as such.

Started life in agentry (github.com/aweussom/agentry), whose backends take one
user message in and give text out. This one is tool calls in both
directions, loopback only and one process per session, so it moved out.
Background and measurements: docs/FEASIBILITY-2026-11-09.md.
"""
import argparse
import asyncio
import base64
import hashlib
import json
import logging
import os
import queue
import sys
import threading
import time
import uuid
from pathlib import Path

from flask import Flask, Response, jsonify, request

logging.basicConfig(format="%(asctime)s %(levelname)s %(filename)s:%(lineno)d %(funcName)s — %(message)s",
                    level=logging.INFO)
log = logging.getLogger("bridge")

from copilot import CopilotClient
from copilot.tools import Tool
from copilot._mode import ToolSet
from copilot.generated.rpc import (
    HandlePendingToolCallRequest, ExternalToolTextResultForLlm,
    ExternalToolTextResultForLlmBinaryResultsForLlm,
    ExternalToolTextResultForLlmBinaryResultsForLlmType, ModelsListRequest,
)
from copilot.generated.session_events import (
    ExternalToolRequestedData, AssistantMessageData, AssistantMessageDeltaData,
    SessionIdleData, SessionErrorData, AssistantUsageData,
)

app = Flask(__name__)

# Set in main().
LOOP = None
CLIENT = None
DEFAULT_MODEL = None
SMALL_MODEL = None
COPILOT_MODELS = set()
PARK_TIMEOUT_S = 1800      # a parked turn nobody resumes is aborted after this
TURN_TIMEOUT_S = 600       # max silence from the runtime while streaming

DUMP_DIR = os.environ.get("BRIDGE_DUMP_DIR")
CONVERSATIONS = {}         # conv_id -> Conversation
CONV_LOCK = threading.Lock()


def run_async(coro, timeout=120):
    """Run a coroutine on the SDK loop thread from a Flask worker."""
    return asyncio.run_coroutine_threadsafe(coro, LOOP).result(timeout=timeout)


# ---------------------------------------------------------------- signatures

def block_text(block):
    if isinstance(block, str):
        return block
    if block.get("type") == "text":
        return block.get("text", "")
    return ""


def message_signature(msg, user_text=True):
    """Stable fingerprint of one message. Ignores cache_control, thinking
    blocks and whitespace: Claude Code moves cache markers between calls and
    may trim text it echoes back. user_text=False leaves out the text of user
    messages: Claude Code rewrites context it already sent (after /model it
    re-wrapped the environment block in <system-reminder> tags, 2026-11-10)."""
    parts = [msg["role"]]
    content = msg["content"]
    if isinstance(content, str):
        content = [{"type": "text", "text": content}]
    for b in content:
        t = b.get("type")
        if t == "text":
            if msg["role"] == "user" and not user_text:
                continue
            txt = b.get("text", "").strip()
            if txt:
                parts.append("t:" + hashlib.sha1(txt.encode()).hexdigest()[:12])
        elif t == "tool_use":
            parts.append("u:" + b["id"])
        elif t == "tool_result":
            parts.append("r:" + b["tool_use_id"])
        elif t == "image":
            parts.append("i")
    return "|".join(parts)


def system_text(system):
    if system is None:
        return ""
    if isinstance(system, str):
        return system
    return "\n\n".join(block_text(b) for b in system)


def tool_names(tools):
    return sorted(t["name"] for t in tools or [])


def declared_tools(tools):
    """Anthropic tool definitions as Copilot tools the SDK never answers."""
    sdk_tools = []
    for t in tools or []:
        sdk_tools.append(Tool(
            name=t["name"],
            description=t.get("description", ""),
            parameters=t.get("input_schema") or {"type": "object", "properties": {}},
            handler=None,           # never answered by the SDK: we answer it
            skip_permission=True,   # Claude Code does its own permission prompts
        ))
    return sdk_tools


# ---------------------------------------------------------------- conversation

class Conversation:
    """One Copilot session standing in for one Claude Code conversation."""

    def __init__(self, model, system, tools):
        self.id = "conv_" + uuid.uuid4().hex[:10]
        self.model = model
        self.system = system
        self.tool_names = tool_names(tools)
        self.sigs = []              # signatures of messages the session has seen
        self.loose_sigs = []        # the same without user text, see message_signature
        self.events = queue.Queue() # SDK loop thread -> Flask worker
        self.pending = {}           # tool_call_id -> request_id (parked calls)
        self.parked_at = None
        self.busy = threading.Lock()
        self.session = None
        self.closed = False

        # Everything but tools and model, so retool() can resume with the same.
        self.session_kwargs = dict(
            available_tools=ToolSet().add_custom("*"),
            system_message={"mode": "replace", "content": system or "You are a helpful assistant."},
            streaming=True,
            skip_custom_instructions=True,
            enable_skills=False,
        )
        sdk_tools = declared_tools(tools)
        log.info("%s: creating session model=%s tools=%d system=%d chars, expecting ~0.5 s",
                 self.id, model, len(sdk_tools), len(system or ""))
        self.session = run_async(CLIENT.create_session(tools=sdk_tools, model=model, **self.session_kwargs))
        self.session.on(self._on_event)
        log.info("%s: session %s up", self.id, self.session.session_id)

    def retool(self, tools):
        """Claude Code adds tools mid-session (ToolSearch loads deferred ones).
        resume_session on the live session id swaps the tool list and keeps
        history, also while a turn is parked (probed 2026-11-10, SDK 1.0.8).
        The client then routes events to the new session object only."""
        new_names = tool_names(tools)
        added = sorted(set(new_names) - set(self.tool_names))
        removed = sorted(set(self.tool_names) - set(new_names))
        log.info("%s: tool list changed (added %s, removed %s); resume_session with %d tools, "
                 "expecting history kept", self.id, added, removed, len(new_names))
        session = run_async(CLIENT.resume_session(self.session.session_id, tools=declared_tools(tools),
                                                  model=self.model, **self.session_kwargs))
        session.on(self._on_event)
        self.session = session
        self.tool_names = new_names
        log.info("%s: session %s resumed with the new tool list", self.id, session.session_id)

    def switch_model(self, model):
        """/model in Claude Code. set_model keeps the session's history
        (probed 2026-11-10, SDK 1.0.8); a new session would flatten it."""
        log.info("%s: switching model %s -> %s on the live session, expecting history kept",
                 self.id, self.model, model)
        run_async(self.session.set_model(model))
        self.model = model

    def _on_event(self, ev):
        # Runs on the SDK loop thread. Hand everything to the worker.
        d = ev.data
        if isinstance(d, AssistantMessageDeltaData):
            if d.delta_content:
                self.events.put(("delta", d.delta_content))
        elif isinstance(d, AssistantMessageData):
            reqs = [(r.tool_call_id, r.name, r.arguments) for r in (d.tool_requests or [])]
            self.events.put(("message", (d.content or "", reqs)))
        elif isinstance(d, ExternalToolRequestedData):
            self.events.put(("tool_requested", (d.tool_call_id, d.request_id)))
        elif isinstance(d, AssistantUsageData):
            self.events.put(("usage", (d.input_tokens or 0, d.output_tokens or 0,
                                       d.cache_read_tokens or 0, d.cache_write_tokens or 0)))
        elif isinstance(d, SessionErrorData):
            self.events.put(("error", d.message or "unknown session error"))
        elif isinstance(d, SessionIdleData):
            self.events.put(("idle", None))

    def close(self, why):
        if self.closed:
            return
        self.closed = True
        log.info("%s: closing session (%s)", self.id, why)
        try:
            run_async(self.session.abort(), timeout=15)
        except Exception as e:
            log.warning("%s: abort failed: %s", self.id, e)
        try:
            run_async(self.session.disconnect(), timeout=15)
        except Exception as e:
            log.warning("%s: disconnect failed: %s", self.id, e)


def find_conversation(model, system, tools, sigs, loose_sigs):
    """A live conversation whose seen messages are exactly this request's
    history minus the new last message. Second choice: the same history
    where only the text of earlier user messages changed (Claude Code
    rewrote context it had already sent). The session keeps the old text;
    losing a re-wrapped reminder beats flattening the whole conversation."""
    # Model and tools are not part of the match: plan_request switches the
    # model and swaps the tool list on the conversation it gets back.
    want_tools = tool_names(tools)
    with CONV_LOCK:
        candidates = [c for c in CONVERSATIONS.values()
                      if not c.closed and c.system == system and len(c.sigs) == len(sigs) - 1]
    for conv in candidates:
        if conv.sigs == sigs[:-1]:
            return conv
    for conv in candidates:
        if conv.loose_sigs != loose_sigs[:-1]:
            continue
        changed = [i for i, (a, b) in enumerate(zip(conv.sigs, sigs[:-1])) if a != b]
        log.warning("%s: resuming although the text of earlier user message(s) %s changed; "
                    "the session keeps the text it saw first", conv.id, changed)
        return conv
    explain_no_match(model, system, want_tools, sigs)
    return None


def explain_no_match(model, system, want_tools, sigs):
    """Log why no live conversation took this request. A request that should
    have resumed but did not ends on the lossy path, so say which check failed
    and, for history, the first message whose signature differs."""
    with CONV_LOCK:
        live = [c for c in CONVERSATIONS.values() if not c.closed]
    if not live:
        return
    if len(sigs) <= 1:
        return  # a new conversation; nothing to match
    for conv in live:
        reasons = []
        if conv.system != system:
            first = next((i for i, (a, b) in enumerate(zip(conv.system, system)) if a != b),
                         min(len(conv.system), len(system)))
            reasons.append(f"system differs at char {first} ({len(conv.system)} vs {len(system)} chars)")
        expected = sigs[:-1]
        if conv.sigs != expected:
            first = next((i for i, (a, b) in enumerate(zip(conv.sigs, expected)) if a != b),
                         min(len(conv.sigs), len(expected)))
            had = conv.sigs[first] if first < len(conv.sigs) else "(none)"
            got = expected[first] if first < len(expected) else "(none)"
            reasons.append(f"history: seen {len(conv.sigs)}, request has {len(expected)} before the new one; "
                           f"first difference at message {first}: seen {had!r}, got {got!r}")
        log.warning("%s: not resuming it: %s", conv.id, "; ".join(reasons) or "pending/busy")


def reap_parked():
    """Abort parked turns nobody came back for (user quit, rewound, ...)."""
    now = time.monotonic()
    with CONV_LOCK:
        stale = [c for c in CONVERSATIONS.values()
                 if c.parked_at and now - c.parked_at > PARK_TIMEOUT_S]
    for c in stale:
        c.close(f"parked > {PARK_TIMEOUT_S}s")
        with CONV_LOCK:
            CONVERSATIONS.pop(c.id, None)


# ---------------------------------------------------------------- flattening

def flatten_history(messages):
    """Lossy fallback: earlier turns as plain text for a fresh session."""
    lines = []
    for m in messages:
        content = m["content"]
        if isinstance(content, str):
            content = [{"type": "text", "text": content}]
        for b in content:
            t = b.get("type")
            if t == "text" and b.get("text", "").strip():
                lines.append(f"[{m['role']}]: {b['text']}")
            elif t == "tool_use":
                lines.append(f"[assistant called tool {b['name']} with {json.dumps(b.get('input'))}]")
            elif t == "tool_result":
                c = b.get("content")
                txt = c if isinstance(c, str) else "\n".join(block_text(x) for x in c or [])
                lines.append(f"[tool result]: {txt[:20000]}")
    return "\n\n".join(lines)


def user_text(msg):
    content = msg["content"]
    if isinstance(content, str):
        return content
    return "\n\n".join(block_text(b) for b in content if b.get("type") == "text")


# ---------------------------------------------------------------- tool results

def tool_result_for_llm(block, extra_text):
    content = block.get("content")
    texts, images = [], []
    if isinstance(content, str):
        texts.append(content)
    for c in content if isinstance(content, list) else []:
        if c.get("type") == "text":
            texts.append(c.get("text", ""))
        elif c.get("type") == "image" and c.get("source", {}).get("type") == "base64":
            images.append(ExternalToolTextResultForLlmBinaryResultsForLlm(
                data=c["source"]["data"], mime_type=c["source"]["media_type"],
                type=ExternalToolTextResultForLlmBinaryResultsForLlmType.IMAGE))
    if extra_text:
        # Text Claude Code put beside the tool results (system reminders,
        # a user interjection). Copilot has nowhere else to put it.
        texts.append(extra_text)
    is_error = bool(block.get("is_error"))
    return ExternalToolTextResultForLlm(
        text_result_for_llm="\n".join(texts) or "(no output)",
        result_type="failure" if is_error else "success",
        error="\n".join(texts) if is_error else None,
        binary_results_for_llm=images or None,
    )


# ---------------------------------------------------------------- the turn

def run_turn(conv, start):
    """Generator of internal events for one Messages API response.
    `start` kicks the session (send text, or answer parked calls)."""
    with conv.busy:
        # Drop leftovers from an earlier response (e.g. trailing usage).
        while not conv.events.empty():
            conv.events.get_nowait()
        conv.parked_at = None
        start()
        tool_batch = None       # tool requests of the latest assistant message
        requested = {}          # tool_call_id -> request_id seen so far
        while True:
            try:
                kind, payload = conv.events.get(timeout=TURN_TIMEOUT_S)
            except queue.Empty:
                yield ("error", f"no event from Copilot runtime for {TURN_TIMEOUT_S}s")
                return
            if kind == "delta":
                yield ("text", payload)
            elif kind == "message":
                content, reqs = payload
                yield ("message_end", content)
                if reqs:
                    tool_batch = reqs
                    log.info("%s: model asked for %d tool(s): %s", conv.id, len(reqs),
                             ", ".join(n for _, n, _ in reqs))
            elif kind == "tool_requested":
                call_id, request_id = payload
                requested[call_id] = request_id
            elif kind == "usage":
                yield ("usage", payload)
            elif kind == "error":
                yield ("error", payload)
                return
            elif kind == "idle":
                yield ("stop", "end_turn")
                return
            # Park once every tool of the batch has its pending request.
            if tool_batch and all(cid in requested for cid, _, _ in tool_batch):
                conv.pending = {cid: requested[cid] for cid, _, _ in tool_batch}
                conv.parked_at = time.monotonic()
                for cid, name, args in tool_batch:
                    yield ("tool_use", (cid, name, args))
                log.info("%s: parked on %d tool call(s), waiting for client results",
                         conv.id, len(tool_batch))
                yield ("stop", "tool_use")
                return


def normalize_messages(messages):
    """Claude Code (2.1.319) puts role=system messages inside the list, also
    as the very last message (environment block). Copilot has one system
    prompt per session, so fold them into the user turn as tagged text and
    merge consecutive same-role messages."""
    out = []
    for m in messages:
        role = m["role"]
        content = m["content"]
        if isinstance(content, str):
            content = [{"type": "text", "text": content}]
        if role == "system":
            text = "\n\n".join(block_text(b) for b in content)
            role = "user"
            content = [{"type": "text", "text": f"<system-message>\n{text}\n</system-message>"}]
        if out and out[-1]["role"] == role:
            out[-1] = {"role": role, "content": out[-1]["content"] + list(content)}
        else:
            out.append({"role": role, "content": list(content)})
    return out


def pick_model(requested):
    """Claude Code asks for Anthropic ids (subagents use claude-sonnet-5-5
    whatever ANTHROPIC_MODEL says). Map families to what Copilot offers."""
    requested = requested or ""
    if requested in COPILOT_MODELS:
        return requested
    if "haiku" in requested:
        return SMALL_MODEL
    if "sonnet" in requested and "claude-sonnet-5" in COPILOT_MODELS:
        return "claude-sonnet-5"
    if "opus" in requested and "claude-opus-5.5" in COPILOT_MODELS:
        return "claude-opus-5.5"
    if not requested:
        log.info("no model in request, using default %s", DEFAULT_MODEL)
        return DEFAULT_MODEL
    # Refuse instead of falling back: a silent fallback had Claude Code's
    # status line say "Fable 5.1" while claude-opus-5.5 answered (2026-11-10).
    usable = sorted(m for m in COPILOT_MODELS if m.startswith(VERIFIED_MODEL_PREFIXES))
    raise ValueError(f"model {requested!r} has no Copilot equivalent on this bridge "
                     f"(usable here: {', '.join(usable)}). Pick another model with /model.")


# Model families whose parallel tool results pair by id in the Copilot
# runtime. GPT models pair by answer order (docs/FEASIBILITY-2026-11-09.md);
# the bridge works around it, but a wrong pairing
# hands the model another file's contents with no error anywhere, so they
# stay out until check_tool_order.py reports them fixed. kimi-k3 is
# untested, so it stays out too. BRIDGE_ALLOW_UNVERIFIED=1 lifts this.
VERIFIED_MODEL_PREFIXES = ("claude-",)


def require_verified(model):
    if model.startswith(VERIFIED_MODEL_PREFIXES):
        return
    if os.environ.get("BRIDGE_ALLOW_UNVERIFIED") == "1":
        log.warning("model %s is not verified for tool-result pairing; allowed by "
                    "BRIDGE_ALLOW_UNVERIFIED=1", model)
        return
    raise ValueError(f"model {model!r} is refused: its tool results are not verified to pair "
                     f"by id in the Copilot runtime (allowed: {', '.join(VERIFIED_MODEL_PREFIXES)}*; "
                     f"see check_tool_order.py, or set BRIDGE_ALLOW_UNVERIFIED=1)")


def plan_request(body):
    """Decide which conversation serves this call and how to kick it.
    Returns (conv, start_fn, path_label)."""
    model = pick_model(body.get("model"))
    require_verified(model)
    system = system_text(body.get("system"))
    tools = body.get("tools") or []
    # Server tools (web_search_20250305 and kin) run on Anthropic's side.
    # Passed on as plain tools they came back as "0 searches" with no error
    # (2026-11-10), so refuse them where Claude Code shows the reason.
    server_tools = [t.get("type") for t in tools if t.get("type") not in (None, "custom")]
    if server_tools:
        raise ValueError(f"server tool(s) {server_tools} run on Anthropic's servers and are not available "
                         f"through the Copilot bridge (WebSearch does not work here)")
    messages = normalize_messages(body["messages"])
    sigs = [message_signature(m) for m in messages]
    loose_sigs = [message_signature(m, user_text=False) for m in messages]
    last = messages[-1]

    conv = find_conversation(model, system, tools, sigs, loose_sigs)
    if conv and conv.model != model:
        conv.switch_model(model)
    if conv and conv.tool_names != tool_names(tools):
        conv.retool(tools)

    if conv and conv.pending:
        content = last["content"] if isinstance(last["content"], list) else []
        results = {b["tool_use_id"]: b for b in content if b.get("type") == "tool_result"}
        extra = "\n\n".join(b.get("text", "") for b in content if b.get("type") == "text").strip()
        if set(results) == set(conv.pending):
            pending = conv.pending

            def start():
                first = True
                # ORDER MATTERS. `pending` is in the model's tool_requests
                # order, and answers go out one at a time in that order. On
                # GPT models the runtime pairs results with calls by answer
                # order, not by request id: answering in reverse swapped the
                # results 3 of 3 times on gpt-6-luna; claude-sonnet-5 was
                # unaffected (probe_tool_order.py, 2026-11-09).
                for call_id, request_id in pending.items():
                    res = tool_result_for_llm(results[call_id], extra if first else "")
                    first = False
                    run_async(conv.session.rpc.tools.handle_pending_tool_call(
                        HandlePendingToolCallRequest(request_id=request_id, result=res)), timeout=30)
                conv.pending = {}
            conv.sigs = sigs
            conv.loose_sigs = loose_sigs
            return conv, start, "resume"
        log.warning("%s: parked on %s but call carries results for %s; abandoning it",
                    conv.id, sorted(conv.pending), sorted(results))
        conv.close("tool results did not match parked calls")
        conv = None

    if conv and not conv.pending:
        text = user_text(last)
        conv.sigs = sigs
        conv.loose_sigs = loose_sigs

        def start():
            run_async(conv.session.send(text), timeout=30)
        return conv, start, "continue"

    # Fresh session. Seed earlier history as text when there is any.
    if last["role"] != "user":
        raise ValueError(f"last message must be from the user, got {last['role']}: "
                         f"{json.dumps(last['content'])[:300]}")
    conv = Conversation(model, system, tools)
    with CONV_LOCK:
        CONVERSATIONS[conv.id] = conv
    history = messages[:-1]
    if any(b.get("type") == "tool_result" for b in (last["content"] if isinstance(last["content"], list) else [])):
        # Results for calls this bridge never parked: everything goes to text.
        history = messages
        prompt = "Continue from the conversation above."
    else:
        prompt = user_text(last)
    if history:
        prompt = ("<earlier_conversation>\n" + flatten_history(history)
                  + "\n</earlier_conversation>\n\n" + prompt)
    conv.sigs = sigs
    conv.loose_sigs = loose_sigs
    path = "fresh-flattened" if history else "fresh"

    def start():
        run_async(conv.session.send(prompt), timeout=30)
    return conv, start, path


# ---------------------------------------------------------------- HTTP

def sse(event, data):
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


@app.post("/v1/messages")
def messages_endpoint():
    reap_parked()
    body = request.get_json(force=True)
    if DUMP_DIR:
        # Feasibility debugging: the exact shape Claude Code sends. Contains
        # prompts and file contents; scratch only.
        name = f"{time.strftime('%H%M%S')}-{uuid.uuid4().hex[:6]}.json"
        with open(os.path.join(DUMP_DIR, name), "w", encoding="utf-8") as f:
            json.dump(body, f, indent=1)
    stream = bool(body.get("stream"))
    t0 = time.monotonic()
    try:
        conv, start, path = plan_request(body)
    except Exception as e:
        log.exception("could not plan request")
        return jsonify({"type": "error", "error": {"type": "invalid_request_error", "message": str(e)}}), 400
    log.info("%s: %s, %d messages, %d tools, model=%s (asked %s), stream=%s",
             conv.id, path, len(body["messages"]), len(body.get("tools") or []),
             conv.model, body.get("model"), stream)
    msg_id = "msg_" + uuid.uuid4().hex[:24]

    def produce():
        """Internal events -> Anthropic content blocks. Also records the
        assistant message's signature so the next call matches."""
        text_parts, tool_uses = [], []
        usage = [0, 0, 0, 0]
        stop = "end_turn"
        for kind, payload in run_turn(conv, start):
            if kind == "text":
                text_parts.append(payload)
                yield ("text", payload)
            elif kind == "message_end":
                # Text between tool rounds inside one Copilot turn would be
                # glued together; keep a paragraph break.
                if text_parts and not text_parts[-1].endswith("\n"):
                    text_parts.append("\n\n")
                    yield ("text", "\n\n")
            elif kind == "tool_use":
                tool_uses.append(payload)
                yield ("tool_use", payload)
            elif kind == "usage":
                for i, v in enumerate(payload):
                    usage[i] += v
                # Copilot's input count includes cached tokens, Anthropic's
                # does not; Claude Code adds them up for its context gauge.
                usage[0] = max(0, usage[0] - payload[2] - payload[3])
            elif kind == "error":
                log.error("%s: %s", conv.id, payload)
                yield ("text", f"\n[bridge error] {payload}")
                stop = "end_turn"
                conv.close("error")
            elif kind == "stop":
                stop = payload
        assistant = {"role": "assistant",
                     "content": [{"type": "text", "text": "".join(text_parts)}]
                     + [{"type": "tool_use", "id": cid} for cid, _, _ in tool_uses]}
        conv.sigs = conv.sigs + [message_signature(assistant)]
        conv.loose_sigs = conv.loose_sigs + [message_signature(assistant, user_text=False)]
        log.info("%s: done %s in %.1fs, in=%d out=%d cache_read=%d",
                 conv.id, stop, time.monotonic() - t0, usage[0], usage[1], usage[2])
        yield ("end", (stop, usage))

    if not stream:
        content, text, stop, usage = [], [], "end_turn", [0, 0, 0, 0]
        for kind, payload in produce():
            if kind == "text":
                text.append(payload)
            elif kind == "tool_use":
                cid, name, args = payload
                content.append({"type": "tool_use", "id": cid, "name": name, "input": args or {}})
            elif kind == "end":
                stop, usage = payload
        body_text = "".join(text).strip()
        if body_text:
            content.insert(0, {"type": "text", "text": body_text})
        return jsonify({"id": msg_id, "type": "message", "role": "assistant", "model": conv.model,
                        "content": content, "stop_reason": stop, "stop_sequence": None,
                        "usage": {"input_tokens": usage[0], "output_tokens": usage[1],
                                  "cache_read_input_tokens": usage[2],
                                  "cache_creation_input_tokens": usage[3]}})

    def generate():
        yield sse("message_start", {"type": "message_start", "message": {
            "id": msg_id, "type": "message", "role": "assistant", "model": conv.model,
            "content": [], "stop_reason": None, "stop_sequence": None,
            "usage": {"input_tokens": 0, "output_tokens": 0}}})
        index = -1
        text_open = False
        try:
            for kind, payload in produce():
                if kind == "text":
                    if not text_open:
                        index += 1
                        text_open = True
                        yield sse("content_block_start", {"type": "content_block_start", "index": index,
                                                          "content_block": {"type": "text", "text": ""}})
                    yield sse("content_block_delta", {"type": "content_block_delta", "index": index,
                                                      "delta": {"type": "text_delta", "text": payload}})
                elif kind == "tool_use":
                    if text_open:
                        yield sse("content_block_stop", {"type": "content_block_stop", "index": index})
                        text_open = False
                    cid, name, args = payload
                    index += 1
                    yield sse("content_block_start", {"type": "content_block_start", "index": index,
                                                      "content_block": {"type": "tool_use", "id": cid,
                                                                        "name": name, "input": {}}})
                    yield sse("content_block_delta", {"type": "content_block_delta", "index": index,
                                                      "delta": {"type": "input_json_delta",
                                                                "partial_json": json.dumps(args or {})}})
                    yield sse("content_block_stop", {"type": "content_block_stop", "index": index})
                elif kind == "end":
                    stop, usage = payload
                    if text_open:
                        yield sse("content_block_stop", {"type": "content_block_stop", "index": index})
                    yield sse("message_delta", {"type": "message_delta",
                                                "delta": {"stop_reason": stop, "stop_sequence": None},
                                                "usage": {"input_tokens": usage[0], "output_tokens": usage[1],
                                                          "cache_read_input_tokens": usage[2],
                                                          "cache_creation_input_tokens": usage[3]}})
                    yield sse("message_stop", {"type": "message_stop"})
        except GeneratorExit:
            # Client went away mid-response (Esc in Claude Code).
            log.warning("%s: client disconnected mid-stream; aborting the turn", conv.id)
            conv.close("client disconnected")
            raise

    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/v1/messages/count_tokens")
def count_tokens():
    # Rough estimate; Claude Code only uses it for display and compaction hints.
    body = request.get_json(force=True)
    n = len(json.dumps(body)) // 4
    return jsonify({"input_tokens": n})


@app.get("/v1/models")
def models():
    return jsonify({"data": [{"id": m, "type": "model", "display_name": m} for m in sorted(COPILOT_MODELS)],
                    "has_more": False})


def relocate_runtime_for_store_python():
    """Keep the SDK's downloaded runtime out of %LOCALAPPDATA% on a Microsoft
    Store Python.

    Why: Store Pythons virtualize writes under AppData. The SDK caches its
    runtime at %LOCALAPPDATA%/github-copilot-sdk/..., the files land in the
    package's LocalCache instead, and the runtime then fails to load its
    native library ("LoadLibraryExW failed"). A directory next to this file
    is not virtualized. Copied from agentry's backends.py.
    In: nothing. Out: sets COPILOT_CLI_EXTRACT_DIR, or does nothing off
    Windows, on a regular Python, or when the caller already set it.
    """
    if sys.platform != "win32" or os.environ.get("COPILOT_CLI_EXTRACT_DIR"):
        return
    if "WindowsApps" not in sys.base_prefix:
        return
    try:
        from copilot._cli_version import CLI_VERSION
    except ImportError:
        return
    target = Path(__file__).parent / ".copilot-runtime" / (CLI_VERSION or "unpinned")
    os.environ["COPILOT_CLI_EXTRACT_DIR"] = str(target)
    log.info("Store Python detected; Copilot runtime dir -> %s", target)


def main():
    global LOOP, CLIENT, DEFAULT_MODEL, SMALL_MODEL, COPILOT_MODELS
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8790)
    ap.add_argument("--host", default="127.0.0.1",
                    help="loopback only: 127.0.0.1, ::1 or localhost")
    ap.add_argument("--model", default="claude-opus-5.5")
    ap.add_argument("--small-model", default="claude-sonnet-5",
                    help="for Claude Code's haiku-class calls (titles, summaries)")
    args = ap.parse_args()
    # This endpoint hands out tool calls that Claude Code executes on its own
    # machine, with no auth in front. Anyone on the LAN could drive that.
    # Loopback only.
    if args.host not in ("127.0.0.1", "::1", "localhost"):
        raise SystemExit(f"--host {args.host!r} refused: the harness bridge binds loopback only "
                         f"(127.0.0.1, ::1 or localhost)")
    DEFAULT_MODEL, SMALL_MODEL = args.model, args.small_model
    for name in (DEFAULT_MODEL, SMALL_MODEL):
        try:
            require_verified(name)
        except ValueError as e:
            raise SystemExit(f"--model/--small-model: {e}")

    LOOP = asyncio.new_event_loop()
    threading.Thread(target=LOOP.run_forever, daemon=True, name="copilot-sdk-loop").start()
    relocate_runtime_for_store_python()
    CLIENT = CopilotClient()
    log.info("starting Copilot runtime, expecting it up within ~30 s")
    run_async(CLIENT.start(), timeout=600)
    ml = run_async(CLIENT.rpc.models.list(ModelsListRequest()), timeout=30)
    COPILOT_MODELS = {m.id for m in ml.models}
    for name in (DEFAULT_MODEL, SMALL_MODEL):
        if name not in COPILOT_MODELS:
            raise SystemExit(f"model {name!r} not offered by Copilot; have {sorted(COPILOT_MODELS)}")
    log.info("bridge on http://%s:%d, default=%s small=%s", args.host, args.port, DEFAULT_MODEL, SMALL_MODEL)
    app.run(host=args.host, port=args.port, threaded=True)


if __name__ == "__main__":
    main()
