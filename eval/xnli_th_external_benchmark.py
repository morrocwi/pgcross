"""eval/xnli_th_external_benchmark.py — pgcross's Decision Forge scored against a REAL, EXTERNAL,
PUBLIC dataset, not a self-authored one.

Founder's own framing (2026-09-21): "เราทำโจทย์จากภายนอกได้ไหม public หนะ" (can we do problems from an
external, public source?) — a direct follow-up to `decision_forge_benchmark.py`'s honest disclaimer
that its 12 hand-labeled cases are NOT held-out/external. This script closes exactly that gap:

  Dataset: `facebook/xnli`, Thai config (`"th"`), `validation` split — a genuine, third-party,
  publicly released NLI benchmark (2490 examples total), loaded live via the Hugging Face
  `datasets` library, not authored by this project. Same Thai-language claim class the founder's
  pasted OpenThai-SystemOne announcement cites its own XNLI-th number for (76.5%) — this is an
  INDEPENDENT run of a DIFFERENT system (pgcross's whole Forge, not the bare model) against a
  RANDOM SAMPLE of the same public dataset, not a comparison against their number (different
  sample, different n, different scoring harness — not apples-to-apples, stated plainly below).

  Task: standard XNLI 3-way natural language inference (does the hypothesis follow from the
  premise? entailment / neutral / contradiction), mapped to a `choice` DecisionQuestion and
  answered via `OpenThaiSystemOneLocalBackend.decide()` directly (no engine card exists for NLI,
  so pgcross's Forge always reaches the real model here — this specifically tests real
  model-assisted judgment at a larger, externally-sourced n).

  Sample: 100 examples, `random.Random(20260921).sample(...)` — a FIXED SEED so this is
  reproducible (rerun this script, get the same 100 examples), not cherry-picked. 100/2490 is
  still a SUBSET of the full validation set, not the whole thing — reported honestly as such,
  same "do not cite this as if it were the real accuracy" discipline as this project's own README
  LOOCV note. A "world-class" version of this would run the full 2490, or several seeded samples
  with a reported confidence interval; this is a real, external, but still bounded first step.

Run: `python eval/xnli_th_external_benchmark.py` (needs `pip install pgcross[openthai,eval]`).
"""
from __future__ import annotations

import random
import time

from datasets import load_dataset

from pgcross.decision.backend import OpenThaiSystemOneLocalBackend
from pgcross.decision.schema import DecisionQuestion

_SEED = 20260921
_N = 100

_LABEL_NAMES = {0: "entailment", 1: "neutral", 2: "contradiction"}

_CRITERIA = {
    "entailment": "the hypothesis logically follows from / is true given the premise",
    "neutral": "the hypothesis is possibly true but not established by the premise",
    "contradiction": "the hypothesis contradicts / cannot be true given the premise",
}


def _sample(ds) -> list[dict]:
    rng = random.Random(_SEED)
    indices = rng.sample(range(len(ds)), _N)
    return [ds[i] for i in indices]


def main() -> None:
    print(f"[bench] loading facebook/xnli (th, validation) from the Hugging Face Hub...")
    ds = load_dataset("facebook/xnli", "th", split="validation")
    print(f"[bench] {len(ds)} total validation examples; sampling {_N} with seed={_SEED}")
    examples = _sample(ds)

    print("[bench] constructing OpenThaiSystemOneLocalBackend...")
    backend = OpenThaiSystemOneLocalBackend()

    t0 = time.time()
    correct = 0
    confusion: dict[tuple[str, str], int] = {}
    for i, ex in enumerate(examples):
        expected = _LABEL_NAMES[ex["label"]]
        instructions = (
            f"Premise: {ex['premise']!r}. Hypothesis: {ex['hypothesis']!r}. "
            "Does the hypothesis follow from the premise (entailment), is it unrelated/uncertain "
            "given the premise (neutral), or does it contradict the premise (contradiction)?"
        )
        q = DecisionQuestion(id="nli", text=instructions, kind="choice", option_descriptions=_CRITERIA)
        proposal = backend.decide(state={}, questions=[q])
        got = proposal.answers[0].label
        is_correct = got == expected
        correct += int(is_correct)
        confusion[(expected, got)] = confusion.get((expected, got), 0) + 1
        if (i + 1) % 20 == 0:
            print(f"  ...{i + 1}/{_N} ({correct}/{i + 1} correct so far)")

    elapsed = time.time() - t0
    print(f"\n=== SCORE (facebook/xnli, th, validation, n={_N}, seed={_SEED}) ===")
    print(f"  accuracy: {correct}/{_N} ({100 * correct / _N:.1f}%) in {elapsed:.1f}s "
          f"({elapsed / _N:.2f}s/example)")
    print(f"  confusion (expected, got) -> count:")
    for (exp, got), count in sorted(confusion.items(), key=lambda kv: -kv[1]):
        marker = "OK" if exp == got else "  "
        print(f"    [{marker}] {exp:>13} -> {got or 'None':>13}: {count}")
    print(f"\n  NOT comparable to OpenThai-SystemOne's own published XNLI-th number (76.5%) -- "
          f"different system (pgcross's whole Forge, not the bare model), different sample "
          f"(n={_N} of 2490, not the full set), different scoring harness. See this file's own "
          f"module docstring before citing this number anywhere.")


if __name__ == "__main__":
    main()
