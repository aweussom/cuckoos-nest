"""Feasibility probe: can a Copilot SDK session act as a raw-ish model for a
client-side tool loop (Claude Code / opencode)?

Checks, against the live Copilot runtime (uses AI credits, keep it short):
  1. mode="empty" + system_message replace + only client-declared tools
  2. a declaration-only tool (no handler) surfaces as external_tool.requested
     and the turn PARKS until we answer with handle_pending_tool_call
  3. parallel tool calls: how many requests arrive before the turn parks
  4. how long a pending call may wait (DELAY_S) before the runtime gives up

Usage: uv run probe_tool_order.py [model] [delay_s] [events|msg|reverse]
"""
import asyncio
import json
import logging
import sys
import time

logging.basicConfig(format="%(asctime)s %(levelname)s %(filename)s:%(lineno)d %(funcName)s — %(message)s",
                    level=logging.INFO)
log = logging.getLogger("probe")

from copilot import CopilotClient
from copilot.tools import Tool
from copilot._mode import ToolSet
from copilot.generated.rpc import HandlePendingToolCallRequest, ExternalToolTextResultForLlm
from copilot.generated.session_events import (
    ExternalToolRequestedData, AssistantMessageData, AssistantMessageDeltaData,
    SessionIdleData, SessionErrorData, AssistantUsageData,
)

MODEL = sys.argv[1] if len(sys.argv) > 1 else None
DELAY_S = float(sys.argv[2]) if len(sys.argv) > 2 else 2.0
# msg = answer in the order of assistant.message tool_requests, reverse = opposite
ORDER = sys.argv[3] if len(sys.argv) > 3 else "events"

FILES = {"a.txt": "alpha-7731", "b.txt": "bravo-4410"}

READ_TOOL = Tool(
    name="Read",
    description="Read a file from the local filesystem and return its contents.",
    parameters={"type": "object",
                "properties": {"file_path": {"type": "string", "description": "Path of the file"}},
                "required": ["file_path"]},
    handler=None,           # declaration only: we answer the pending call ourselves
    skip_permission=True,
)

SYSTEM = ("You are a coding assistant. You can only act through the provided tools. "
          "When asked about file contents, call Read. Call independent tools in parallel.")


async def main():
    # mode="empty" needs its own base_directory (would move auth away from
    # ~/.copilot); default mode with a custom-only allowlist and a replaced
    # system prompt gets the same isolation for this probe.
    client = CopilotClient()
    log.info("starting Copilot client, expecting a runtime within ~30 s")
    await client.start()

    models = (await client.rpc.models.list(__import__("copilot.generated.rpc", fromlist=["x"]).ModelsListRequest())).models
    for m in models:
        d = m.to_dict()
        log.info("model %-28s billing=%s", d.get("id"), json.dumps(d.get("billing"))[:160])

    pending = []
    msg_order = []
    done = asyncio.Event()
    text = []
    t0 = time.monotonic()

    def on_event(ev):
        d = ev.data
        if isinstance(d, ExternalToolRequestedData):
            log.info("+%.1fs external_tool.requested tool=%s call=%s req=%s args=%s",
                     time.monotonic() - t0, d.tool_name, d.tool_call_id, d.request_id, d.arguments)
            pending.append(d)
        elif isinstance(d, AssistantMessageData):
            msg_order.extend(r.tool_call_id for r in (d.tool_requests or []))
            log.info("+%.1fs assistant.message tool_requests=%s content=%r", time.monotonic() - t0,
                     [(r.name, r.tool_call_id) for r in (d.tool_requests or [])], (d.content or "")[:200])
        elif isinstance(d, AssistantMessageDeltaData):
            text.append(d.delta_content or "")
        elif isinstance(d, AssistantUsageData):
            log.info("+%.1fs usage in=%s out=%s cache_read=%s", time.monotonic() - t0,
                     getattr(d, "input_tokens", None), getattr(d, "output_tokens", None),
                     getattr(d, "cache_read_tokens", None))
        elif isinstance(d, SessionErrorData):
            log.error("+%.1fs session.error %s", time.monotonic() - t0, d.message)
            done.set()
        elif isinstance(d, SessionIdleData):
            log.info("+%.1fs session.idle", time.monotonic() - t0)
            done.set()
        else:
            log.debug("event %s", ev.type)

    kwargs = dict(
        tools=[READ_TOOL],
        available_tools=ToolSet().add_custom("*"),
        system_message={"mode": "replace", "content": SYSTEM},
        streaming=True,
        working_directory=".",
        skip_custom_instructions=True,
        enable_skills=False,
    )
    if MODEL:
        kwargs["model"] = MODEL
    session = await client.create_session(**kwargs)
    session.on(on_event)
    cur = await session.rpc.model.get_current()
    log.info("session %s runs model %s", session.session_id, cur.model_id)

    log.info("sending prompt, expecting two parallel Read calls that park the turn")
    t0 = time.monotonic()
    await session.send("What do a.txt and b.txt contain? Answer exactly in the form \"a.txt: <value>\" and \"b.txt: <value>\" on two lines.")

    # Let the turn reach the park point, then hold it for DELAY_S.
    await asyncio.sleep(DELAY_S)
    log.info("after %.0fs: %d pending call(s), idle=%s", DELAY_S, len(pending), done.is_set())
    if done.is_set():
        log.error("turn ended before we answered: runtime did NOT park on declaration-only tools")

    answer = list(pending)
    if ORDER in ("msg", "reverse"):
        answer.sort(key=lambda p: msg_order.index(p.tool_call_id))
        if ORDER == "reverse":
            answer.reverse()
    log.info("message order %s, answering %s order: %s", msg_order, ORDER,
             [(p.tool_call_id, p.arguments) for p in answer])
    for p in answer:
        name = (p.arguments or {}).get("file_path", "")
        content = FILES.get(name.split("/")[-1].split("\\")[-1], f"ERROR: no such file {name}")
        log.info("answering %s(%s) -> %r", p.tool_name, name, content)
        await session.rpc.tools.handle_pending_tool_call(HandlePendingToolCallRequest(
            request_id=p.request_id,
            result=ExternalToolTextResultForLlm(text_result_for_llm=content, result_type="success")))

    try:
        await asyncio.wait_for(done.wait(), timeout=180)
    except asyncio.TimeoutError:
        log.error("no idle within 180 s after answering")
    final = "".join(text)
    log.info("final text: %r", final[-400:])
    ok = "alpha-7731" in final and "bravo-4410" in final
    swapped = ("a.txt: bravo" in final.replace("*", "")) or ("b.txt: alpha" in final.replace("*", ""))
    log.info("MAPPING: %s", "SWAPPED" if swapped else "ok")
    log.info("RESULT: %s", "PASS, both tool results reached the model" if ok else "FAIL")
    await session.disconnect()
    await client.stop()


asyncio.run(main())
