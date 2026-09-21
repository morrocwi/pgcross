"""server/responses_api.py — OpenAI Responses API compatibility layer.

WHY THIS EXISTS: pgcross's server originally implemented only the older Chat Completions
shape (/v1/chat/completions, server/chat.py). OpenAI-ecosystem clients (Codex CLI >= the
2026-02 deprecation cycle, https://github.com/openai/codex/discussions/7782) now require the
newer Responses API (/v1/responses) — `wire_api = "chat"` is a hard error in current Codex CLI.
This module translates Responses API request/response shapes onto the SAME underlying
run_pipeline() call server/chat.py already uses — no pipeline logic is duplicated, only the
wire-protocol adapter is new.

SCOPE: single-turn (matches chat.py's existing declared v0.1 scope — this endpoint does not
add multi-turn conversation state), text-only input, minimal streaming (one delta + a
completed event — real reasoning-model incremental streaming is out of scope; the pipeline
itself is not incremental). No tool-calling support (pgcross's engine is the tool; there is
nothing to call back into from a Responses-API client — see NON_CLAIMS.md for the SWE-bench-
class scope boundary this deliberately stays inside of).
"""
from __future__ import annotations
import json
import time
import uuid
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from .render import render_candidates_for_human
from ..pipeline.run import run_pipeline, HarmfulRequest

router = APIRouter()


def _extract_input_text(req: dict) -> str:
    """Responses API `input` is either a plain string, or a list of message-like items
    (each `{"role": "...", "content": [{"type": "input_text", "text": "..."}]}` or, in some
    client shapes, `content` as a plain string). Single-turn: use the LAST user item's text,
    same declared scope as server/chat.py's `messages[-1]`."""
    raw = req.get("input", "")
    if isinstance(raw, str):
        return raw
    if isinstance(raw, list):
        for item in reversed(raw):
            if not isinstance(item, dict):
                continue
            if item.get("role") not in (None, "user"):
                continue
            content = item.get("content")
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                for part in content:
                    if isinstance(part, dict) and part.get("type") in ("input_text", "text"):
                        return part.get("text", "")
    return ""


def _response_object(resp_id: str, model: str, status: str, text: str, refusal: bool = False) -> dict:
    """Build a Responses API `response` object (the non-streaming shape, and also the
    payload carried inside the streaming `response.completed` event)."""
    return {
        "id": resp_id,
        "object": "response",
        "created_at": int(time.time()),
        "status": status,
        "model": model,
        "output": [
            {
                "type": "message",
                "id": "msg_" + uuid.uuid4().hex[:12],
                "status": "completed",
                "role": "assistant",
                "content": [
                    {"type": "output_text", "text": text, "annotations": []}
                ],
            }
        ],
        "output_text": text,
        "pgcross": {"refusal": True} if refusal else None,
    }


@router.post("/v1/responses")
async def responses(req: dict, request: Request):
    ctx = request.app.state.ctx
    model = req.get("model", "pgcross-1")
    resp_id = "resp_" + uuid.uuid4().hex[:24]
    user_text = _extract_input_text(req)

    try:
        pipeline_resp = run_pipeline(user_text, ctx)
        text = render_candidates_for_human(pipeline_resp)
        refusal = False
    except HarmfulRequest:
        text = "I'm unable to help with that request."
        refusal = True

    body = _response_object(resp_id, model, "completed", text, refusal=refusal)

    if not req.get("stream", False):
        return JSONResponse(body)

    async def gen():
        # Minimal but structurally valid SSE stream. pgcross's pipeline produces a complete
        # answer in one shot (nothing to incrementally stream), but the client still requires
        # the full output-item/content-part LIFECYCLE around the delta — a delta referencing
        # an item_id the client never saw an `output_item.added` for is a protocol violation
        # (confirmed directly: Codex CLI raised "OutputTextDelta without active item" when this
        # was missing). So: created -> output_item.added -> content_part.added ->
        # output_text.delta (single, whole-text) -> output_text.done -> content_part.done ->
        # output_item.done -> completed. Every event after created reuses the SAME item_id.
        item_id = "msg_" + uuid.uuid4().hex[:12]

        def sse(evt_type: str, payload: dict) -> str:
            return f"event: {evt_type}\ndata: {json.dumps({'type': evt_type, **payload})}\n\n"

        yield sse("response.created",
                  {"response": _response_object(resp_id, model, "in_progress", "", refusal=refusal)})

        item = {"id": item_id, "type": "message", "status": "in_progress", "role": "assistant", "content": []}
        yield sse("response.output_item.added", {"output_index": 0, "item": item})

        part = {"type": "output_text", "text": "", "annotations": []}
        yield sse("response.content_part.added",
                  {"item_id": item_id, "output_index": 0, "content_index": 0, "part": part})

        yield sse("response.output_text.delta",
                  {"item_id": item_id, "output_index": 0, "content_index": 0, "delta": text})

        yield sse("response.output_text.done",
                  {"item_id": item_id, "output_index": 0, "content_index": 0, "text": text})

        done_part = {"type": "output_text", "text": text, "annotations": []}
        yield sse("response.content_part.done",
                  {"item_id": item_id, "output_index": 0, "content_index": 0, "part": done_part})

        done_item = {"id": item_id, "type": "message", "status": "completed", "role": "assistant",
                     "content": [{"type": "output_text", "text": text, "annotations": []}]}
        yield sse("response.output_item.done", {"output_index": 0, "item": done_item})

        yield sse("response.completed", {"response": body})

    return StreamingResponse(gen(), media_type="text/event-stream")
