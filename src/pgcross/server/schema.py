from __future__ import annotations
from pydantic import BaseModel
from typing import Any

class ChatMessage(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    model: str = "pgcross-1"
    messages: list[ChatMessage]
    stream: bool = False
    max_tokens: int | None = None

class PGCrossMeta(BaseModel):
    candidates: list[dict]
    stakes: str

class ChatResponseMessage(BaseModel):
    role: str = "assistant"
    content: str
    pgcross: PGCrossMeta | None = None

class ChatChoice(BaseModel):
    index: int = 0
    message: ChatResponseMessage
    finish_reason: str = "stop"

class ChatResponse(BaseModel):
    id: str
    object: str = "chat.completion"
    model: str
    choices: list[ChatChoice]

class RefusalResponse(BaseModel):
    id: str
    object: str = "chat.completion"
    model: str
    choices: list[ChatChoice]
    error: str = "content_policy"
