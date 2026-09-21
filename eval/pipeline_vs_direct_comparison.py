"""eval/pipeline_vs_direct_comparison.py — does going through `run_pipeline()` change the
model's answer versus calling `DecisionBackend.decide()` directly?

Founder's own framing (2026-09-21): "ลองถอด pipeline กับไม่ถอด ค่าเบสต่างกันไหม" (try with vs
without the pipeline, does the score differ) — asked as empirical proof after
`pipeline/authorize.py`'s `decision_question`/`decision_state` fixes (see that module's own
docstring, and `core/models.py::QueryIR`'s `decision_question`/`decision_state` fields, for the
two real bugs this script's live runs actually found and confirmed fixed).

This is the exact comparison that found both bugs, committed here so the claim is reproducible
by anyone (not just prose in a commit message or README) — same discipline as
`eval/decision_forge_benchmark.py`/`eval/jev_public_benchmark_suite.py`: a real measurement,
committed as a real script, not just asserted.

Real results this session (`google/boolq`, n=20, seed=20260921):
  - BEFORE the `decision_state` fix: 17/20 (85%) agreement between `decide()` direct and
    `run_pipeline()` -- despite it being the SAME question to the SAME model, because
    `pipeline/authorize.py` was silently sending a different (synthetic, largely-irrelevant)
    `state` dict to the model in the pipeline path.
  - AFTER the fix: 20/20 (100%) agreement, run identically. Re-run once more directly from this
    committed script to confirm it reproduces exactly: 20/20 (100%) again, 11/20 direct and
    11/20 via pipeline (identical this time, since agreement is now 100%).
  - Accuracy itself (11/20, 55%) is a separate, smaller-sample signal — this script's actual
    question is the AGREEMENT number, not accuracy; see `eval/jev_public_benchmark_suite.py`'s
    `boolq` entry (n=60) for a less noisy accuracy read on this same dataset.

Run: `python eval/pipeline_vs_direct_comparison.py` (needs `pip install pgcross[openthai,eval]`).
"""
from __future__ import annotations

import random
import time

from datasets import load_dataset

from pgcross.core.provider import Registry
from pgcross.decision.backend import OpenThaiSystemOneLocalBackend
from pgcross.decision.schema import DecisionQuestion
from pgcross.pipeline.run import Config, Ctx, run_pipeline

_SEED = 20260921
_N = 20


def main() -> None:
    print("[compare] constructing OpenThaiSystemOneLocalBackend...")
    backend = OpenThaiSystemOneLocalBackend()
    cfg = Config(decision_backend=backend)
    ctx = Ctx(backend=None, registry=Registry(), cfg=cfg, safety=lambda text: False)

    print("[compare] loading google/boolq (validation)...")
    ds = load_dataset("google/boolq", split="validation")
    rng = random.Random(_SEED)
    examples = [ds[i] for i in rng.sample(range(len(ds)), _N)]

    direct_correct = 0
    pipeline_correct = 0
    agree = 0
    no_proposal = 0
    t0 = time.time()
    for ex in examples:
        text = (f"Passage: {ex['passage']!r}. Question: {ex['question']!r}. "
                "Does the passage support a 'yes' answer to the question?")
        q = DecisionQuestion(id="q", kind="noul", text=text)
        gold = bool(ex["answer"])

        proposal_direct = backend.decide(state={}, questions=[q])
        got_direct = proposal_direct.answers[0].label == "yes"

        resp = run_pipeline(text, ctx, decision_question=q, decision_state={})
        model_proposal = resp.authorization.model_proposal
        if model_proposal is None or not model_proposal.answers:
            no_proposal += 1
            print(f"  [no model_proposal from run_pipeline() -- status={resp.authorization.status}]")
            continue
        got_pipeline = model_proposal.answers[0].label == "yes"

        direct_correct += int(got_direct == gold)
        pipeline_correct += int(got_pipeline == gold)
        agree += int(got_pipeline == got_direct)

    scored = _N - no_proposal
    print(f"\n=== RESULT (n={_N}, {scored} scored, {no_proposal} had no model_proposal) ===")
    print(f"  direct decide():    {direct_correct}/{scored}")
    print(f"  via run_pipeline(): {pipeline_correct}/{scored}")
    print(f"  agreement (same answer both ways): {agree}/{scored} ({100 * agree / scored:.0f}%)")
    print(f"  elapsed: {time.time() - t0:.1f}s")
    print("\n  Agreement is the number this script exists to measure -- if it's below 100%, the"
          " same question is getting a different answer depending on which code path reaches"
          " the model, which is worth investigating (see this file's own docstring for the two"
          " real causes already found and fixed this way).")


if __name__ == "__main__":
    main()
