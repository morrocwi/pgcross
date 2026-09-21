from __future__ import annotations
from .base import TransportPrompt, TransportOut, BackendInfo

_SYSTEM_PROMPT = (
    "Output ONLY the requested JSON. You are a transporter: extract and structure "
    "information from the input. Never assert a fact. Never produce a numeric answer. "
    "Never add information not present in the input. Return structure only."
)

# Deliberately DIFFERENT from _SYSTEM_PROMPT: this call is explicitly allowed — expected — to
# propose something not present in the input (that's the whole point of a hypothesis). The
# honesty guarantee for this path is NOT "the model won't invent anything" (unlike transport());
# it's structural, enforced downstream by pipeline/imagine.py hard-tagging every resulting
# candidate CType.GUESS, which tiering.py caps at Tier.Open no matter what this prompt returns.
_BRIDGE_SYSTEM_PROMPT = (
    "Output ONLY JSON: {\"guess\": <value or null>, \"rationale\": <short string>}. "
    "You are proposing a SPECULATIVE, UNVERIFIED hypothesis for a missing value, not a "
    "verified fact — the system will label your answer as an unverified guess regardless of "
    "how confident you are. If you genuinely have no reasonable guess, return "
    "{\"guess\": null, \"rationale\": \"\"}."
)

# Even in open-ended chat mode, this stays under the SAME epistemic floor the rest of pgcross
# is built on: a correct-sounding output is not the same thing as a verified truth ("output =
# retained readout, not truth"). Every candidate this produces is ALSO structurally hard-capped
# at CType.GUESS/Tier.Open downstream (pipeline/run.py's _general_chat_fallback) regardless of
# what this prompt says — the prompt asking for honesty and the pipeline enforcing honesty are
# two independent layers, matching the same defense-in-depth pattern as _BRIDGE_SYSTEM_PROMPT.
_GENERAL_CHAT_SYSTEM_PROMPT = (
    "You are a helpful, concise assistant. Answer naturally in whatever language the user "
    "writes in — this is plain open-ended conversation, not structure-only extraction. "
    "Hold the same epistemic floor as the rest of this system: a correct-sounding answer is "
    "not the same as a verified fact. State plainly when you are uncertain, estimating, or "
    "speaking from general pattern rather than a checked source — do not present a guess with "
    "unearned confidence just because the tone is conversational."
)

class LlamaCppBackend:
    def __init__(self, weights: str, context_length: int = 8192, **kwargs):
        self._weights = weights
        self._context_length = context_length
        self._llm = None

    def _load(self):
        if self._llm is not None: return
        try:
            from llama_cpp import Llama
            self._llm = Llama(model_path=self._weights, n_ctx=self._context_length, verbose=False)
        except ImportError:
            raise ImportError("llama-cpp-python required: pip install pgcross[llamacpp]")

    def transport(self, p: TransportPrompt) -> TransportOut:
        """I7: system prompt enforces structure-only output. PROVE-IT on your weights."""
        self._load()
        messages = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": f"Task: {p.task}\nInput: {p.text}\nReturn JSON only."},
        ]
        resp = self._llm.create_chat_completion(
            messages=messages,
            response_format={"type": "json_object"},
            max_tokens=512,
        )
        import json
        raw = resp["choices"][0]["message"]["content"]
        try:
            return TransportOut(json=json.loads(raw))
        except Exception:
            return TransportOut(json={"raw": raw})

    def propose_bridge(self, p: TransportPrompt) -> TransportOut:
        """See backends/base.py's LLMBackend.propose_bridge docstring for the safety contract.
        Same weights as transport(), a different (non-I7) system prompt and framing."""
        self._load()
        missing_slot = p.schema_hint.get("missing_slot", "the missing value")
        messages = [
            {"role": "system", "content": _BRIDGE_SYSTEM_PROMPT},
            {"role": "user", "content": (
                f"Query: {p.text}\nMissing value needed: {missing_slot}\n"
                f"Propose ONE speculative guess for '{missing_slot}', or null if none is reasonable."
            )},
        ]
        resp = self._llm.create_chat_completion(
            messages=messages,
            response_format={"type": "json_object"},
            max_tokens=200,
        )
        import json
        raw = resp["choices"][0]["message"]["content"]
        try:
            return TransportOut(json=json.loads(raw))
        except Exception:
            return TransportOut(json={"guess": None, "rationale": ""})

    def general_chat(self, text: str) -> str:
        """See backends/base.py's LLMBackend.general_chat docstring for the safety contract
        (router fallback: only reached on LOW-stakes, zero-structured-signal queries)."""
        self._load()
        messages = [
            {"role": "system", "content": _GENERAL_CHAT_SYSTEM_PROMPT},
            {"role": "user", "content": text},
        ]
        resp = self._llm.create_chat_completion(messages=messages, max_tokens=400)
        return resp["choices"][0]["message"]["content"].strip()

    def info(self) -> BackendInfo:
        return BackendInfo(
            model_id=self._weights,
            quantization="gguf",
            context_length=self._context_length,
            license_tag="model-specific",
        )
