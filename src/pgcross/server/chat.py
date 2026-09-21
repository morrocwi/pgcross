from __future__ import annotations
import uuid
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
import json
from .schema import ChatRequest, ChatResponse, ChatResponseMessage, ChatChoice, PGCrossMeta
from .render import render_candidates_for_human
from ..pipeline.run import run_pipeline, HarmfulRequest

router = APIRouter()

def _refusal(model: str):
    msg = ChatResponseMessage(
        content="I cannot help with that request.",
        pgcross=None,
    )
    return ChatResponse(
        id="chatcmpl-" + uuid.uuid4().hex[:12],
        model=model,
        choices=[ChatChoice(message=msg, finish_reason="content_filter")],
    )

@router.post("/v1/chat/completions")
async def chat(req: ChatRequest, request: Request):
    ctx = request.app.state.ctx
    user_text = req.messages[-1].content  # single-turn v0.1 (declared, not a bug)
    try:
        resp = run_pipeline(user_text, ctx)
    except HarmfulRequest:
        return JSONResponse(_refusal(req.model).model_dump())
    content = render_candidates_for_human(resp)
    meta = PGCrossMeta(
        candidates=[c.model_dump() for c in resp.candidates],
        stakes=resp.stakes.value,
    )
    msg = ChatResponseMessage(content=content, pgcross=meta)
    chat_resp = ChatResponse(
        id="chatcmpl-" + uuid.uuid4().hex[:12],
        model=req.model,
        choices=[ChatChoice(message=msg)],
    )
    if req.stream:
        # fake streaming: byte-identical to non-streamed (declared behavior)
        body = json.dumps(chat_resp.model_dump())
        async def gen():
            yield f"data: {body}\n\ndata: [DONE]\n\n"
        return StreamingResponse(gen(), media_type="text/event-stream")
    return chat_resp
