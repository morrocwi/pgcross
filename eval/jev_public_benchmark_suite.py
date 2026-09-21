"""eval/jev_public_benchmark_suite.py — pgcross's Decision Forge, scored on REAL SUBSETS of the
SAME public benchmark suite OpenThai-SystemOne/Jev itself was scored on.

Founder's own framing (2026-09-21): "ทดสอบข้อสอบยาก ระดับโลก ที่ jev ใช้ทดสอบเลยว่าเราทำได้ไหม ทดสอบทีละส่วน
แต่เป็นต้องข้อสอบภายนอกนะ" (test the hard, world-class exam Jev itself used, test it piece by piece,
but it must be an external exam). OpenThai-SystemOne's own Hugging Face card states it was scored
on "the same 13 subsets, splits, instructions and sampler as Bespoke Nimble's own
`docs/PUBLIC_BENCHMARKS.md`": aegis2, boolq, civil_comments, helpsteer2, massive-de-DE,
massive-en-US, multinli, paws, pubmedqa, squad2, summeval-consistency, summeval-relevance,
vitaminc-dev.

**This script covers 3 of those 13** (piece by piece, per the founder's own instruction — not
all 13 in one attempt): `boolq`, `paws`, `multinli`. These three were chosen because they are
directly, publicly loadable via the Hugging Face `datasets` library with clear, unambiguous
ground truth (verified live before writing this file, not assumed) and map cleanly onto
pgcross's own `noul`/`choice` DecisionQuestion shapes. The other 10 (`aegis2`, `civil_comments`,
`helpsteer2`, `massive-*`, `pubmedqa`, `squad2`, `summeval-*`, `vitaminc-dev`) are NOT covered
here — some need a different task shape (`squad2` is extractive QA, `summeval-*` are `score`-type
summarization-quality judgments, `helpsteer2` is a different score rubric), and adding them is
real, separate follow-up work, not silently skipped without saying so.

**Still not apples-to-apples with OpenThai-SystemOne's own published numbers, even where the same
dataset name is used**: this project's own harness (instructions text, sampler, split, prompt
framing) is NOT reconstructed to be byte-identical to Bespoke Nimble's `docs/PUBLIC_BENCHMARKS.md`
methodology — only the underlying public dataset is the same. Same honesty discipline as
`eval/xnli_th_external_benchmark.py`: report the real number this harness gets, and say plainly
what would need to change for it to be a true apples-to-apples comparison.

Run: `python eval/jev_public_benchmark_suite.py [boolq|paws|multinli|all]` (default: all).
Needs `pip install pgcross[openthai,eval]`.
"""
from __future__ import annotations

import random
import sys
import time

from datasets import load_dataset

from pgcross.decision.backend import OpenThaiSystemOneLocalBackend
from pgcross.decision.schema import DecisionQuestion

_SEED = 20260921
_N = 60


def _bench_boolq(backend) -> dict:
    ds = load_dataset("google/boolq", split="validation")
    rng = random.Random(_SEED)
    examples = [ds[i] for i in rng.sample(range(len(ds)), _N)]
    correct = 0
    for ex in examples:
        q = DecisionQuestion(
            id="q", kind="noul",
            text=f"Passage: {ex['passage']!r}. Question: {ex['question']!r}. "
                 "Does the passage support a 'yes' answer to the question?",
        )
        proposal = backend.decide(state={}, questions=[q])
        got_yes = proposal.answers[0].label == "yes"
        correct += int(got_yes == bool(ex["answer"]))
    return {"name": "boolq", "source": "google/boolq (validation, 3270 total)", "n": _N, "correct": correct}


def _bench_paws(backend) -> dict:
    ds = load_dataset("google-research-datasets/paws", "labeled_final", split="test")
    rng = random.Random(_SEED)
    examples = [ds[i] for i in rng.sample(range(len(ds)), _N)]
    correct = 0
    for ex in examples:
        q = DecisionQuestion(
            id="q", kind="noul",
            text=f"Sentence 1: {ex['sentence1']!r}. Sentence 2: {ex['sentence2']!r}. "
                 "Do these two sentences mean the same thing (are they paraphrases)?",
        )
        proposal = backend.decide(state={}, questions=[q])
        got_yes = proposal.answers[0].label == "yes"
        correct += int(got_yes == bool(ex["label"] == 1))
    return {"name": "paws", "source": "google-research-datasets/paws labeled_final (test, 8000 total)",
            "n": _N, "correct": correct}


_MNLI_LABELS = {0: "entailment", 1: "neutral", 2: "contradiction"}
_MNLI_CRITERIA = {
    "entailment": "the hypothesis logically follows from / is true given the premise",
    "neutral": "the hypothesis is possibly true but not established by the premise",
    "contradiction": "the hypothesis contradicts / cannot be true given the premise",
}


def _bench_multinli(backend) -> dict:
    ds = load_dataset("nyu-mll/multi_nli", split="validation_matched")
    rng = random.Random(_SEED)
    examples = [ds[i] for i in rng.sample(range(len(ds)), _N)]
    correct = 0
    for ex in examples:
        expected = _MNLI_LABELS.get(ex["label"])
        if expected is None:
            continue  # label -1: no gold label agreement in the source dataset; skip, don't guess
        q = DecisionQuestion(
            id="q", kind="choice", option_descriptions=_MNLI_CRITERIA,
            text=f"Premise: {ex['premise']!r}. Hypothesis: {ex['hypothesis']!r}. "
                 "Does the hypothesis follow from the premise (entailment), is it "
                 "unrelated/uncertain (neutral), or does it contradict the premise (contradiction)?",
        )
        proposal = backend.decide(state={}, questions=[q])
        correct += int(proposal.answers[0].label == expected)
    return {"name": "multinli", "source": "nyu-mll/multi_nli (validation_matched, 9815 total)",
            "n": _N, "correct": correct}


_BENCHMARKS = {"boolq": _bench_boolq, "paws": _bench_paws, "multinli": _bench_multinli}


def main() -> None:
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    names = list(_BENCHMARKS) if which == "all" else [which]
    for n in names:
        if n not in _BENCHMARKS:
            print(f"unknown benchmark {n!r}; choices: {list(_BENCHMARKS)} or 'all'", file=sys.stderr)
            raise SystemExit(2)

    print("[bench] constructing OpenThaiSystemOneLocalBackend...")
    backend = OpenThaiSystemOneLocalBackend()

    results = []
    for name in names:
        print(f"\n[bench] loading {name} from the Hugging Face Hub...")
        t0 = time.time()
        r = _BENCHMARKS[name](backend)
        r["elapsed_s"] = time.time() - t0
        results.append(r)
        print(f"  {r['name']}: {r['correct']}/{r['n']} ({100 * r['correct'] / r['n']:.1f}%) "
              f"in {r['elapsed_s']:.1f}s -- source: {r['source']}")

    total_correct = sum(r["correct"] for r in results)
    total_n = sum(r["n"] for r in results)
    print(f"\n=== SUMMARY (piece-by-piece subset of OpenThai-SystemOne's own 13-dataset suite) ===")
    for r in results:
        print(f"  {r['name']:>10}: {r['correct']}/{r['n']} ({100 * r['correct'] / r['n']:.1f}%)")
    print(f"  {'combined':>10}: {total_correct}/{total_n} ({100 * total_correct / total_n:.1f}%)")
    print(f"\n  Covers 3 of the 13 datasets OpenThai-SystemOne's own published benchmark uses "
          f"(boolq, paws, multinli) -- NOT the other 10 (aegis2, civil_comments, helpsteer2, "
          f"massive-de-DE, massive-en-US, pubmedqa, squad2, summeval-consistency, "
          f"summeval-relevance, vitaminc-dev), and NOT a byte-identical reconstruction of Bespoke "
          f"Nimble's own instructions/sampler methodology even for the 3 covered here. Real dataset,"
          f" real sample, real score -- not a reproduction of their exact published number.")


if __name__ == "__main__":
    main()
