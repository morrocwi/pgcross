from __future__ import annotations
from typing import Protocol, runtime_checkable
from pydantic import BaseModel

class TransportPrompt(BaseModel):
    task: str
    text: str
    schema_hint: dict = {}

class TransportOut(BaseModel):
    json: dict  # STRUCTURE ONLY — never a fact or number (I7)

class BackendInfo(BaseModel):
    model_id: str
    quantization: str | None = None
    context_length: int
    license_tag: str

@runtime_checkable
class LLMBackend(Protocol):
    def transport(self, p: TransportPrompt) -> TransportOut:
        """Structure/extract only. NEVER assert a fact, NEVER produce a numeric answer,
        NEVER add info not in the input. I7 compliance is required.
        PROVE-IT: verify your chosen weights only return structure, never a fact.
        """
        ...
    def info(self) -> BackendInfo: ...
    def propose_bridge(self, p: TransportPrompt) -> TransportOut:
        """OPTIONAL — the imagine/cross-domain-bridge hook (pipeline/imagine.py). Unlike
        `transport()`, this method IS allowed to propose a value not literally present in the
        input — it is explicitly a speculative hypothesis, never a verified fact. This is the
        SAME single wrapped model/weights as `transport()`, just a different invocation mode
        for a different, honestly-labeled purpose (same pattern as the K6 benchmark needing a
        different call style than the I7 transport-only one for code generation) — it does NOT
        introduce a second model.

        A backend that does not implement this method is simply skipped by pipeline/imagine.py
        (checked via `hasattr`) — the imagine layer is optional and off by default (Config.
        enable_imagine_bridge=False), never a required part of a working backend.

        SAFETY NOTE: the pipeline NEVER trusts this method's own framing/confidence — every
        candidate it produces is hard-tagged CType.GUESS, which tiering.py caps at Tier.Open
        unconditionally, regardless of what this method returns. Return
        {"guess": <value-or-short-string> | None, "rationale": <str>} in TransportOut.json;
        `guess=None` means "no hypothesis", which pipeline/imagine.py skips silently.
        """
        ...
    def general_chat(self, text: str) -> str:
        """OPTIONAL — the general-conversation router fallback (pipeline/run.py). When NO
        engine card, RAG corpus, or lens has ANY structured signal for a query (the pipeline's
        own answer would otherwise be a bare CONSULTATION refusal) AND the query is LOW
        stakes, this lets the SAME wrapped model answer as a plain assistant instead of
        refusing — this is what makes pgcross usable as a general model backend for a client
        like Codex CLI (which also sends casual chat, `/review`, and general coding requests
        pgcross's structured engine has no card for at all).

        Same single-model architecture constraint as propose_bridge(): no second model, just a
        third invocation MODE on the same weights (open-ended assistant chat, no I7 structure-
        only constraint, no single-value-hypothesis framing).

        SAFETY: the pipeline ONLY calls this when q.stakes != HIGH and zero COMPUTED/RETRIEVED
        candidates exist — it can NEVER override a genuine high-stakes safety refusal (I5), and
        every candidate this produces is hard-tagged CType.GUESS (Tier.Open), same discipline as
        propose_bridge. A backend without this method is simply skipped (hasattr check) — the
        fallback is optional and off by default (Config.enable_general_chat_fallback=False).
        """
        ...
