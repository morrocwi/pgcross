"""eval/jev_public_benchmark_suite.py — pgcross's Decision Forge, scored on REAL SUBSETS of the
SAME public benchmark suite OpenThai-SystemOne/Jev itself was scored on.

Founder's own framing (2026-09-21): "ทดสอบข้อสอบยาก ระดับโลก ที่ jev ใช้ทดสอบเลยว่าเราทำได้ไหม ทดสอบทีละส่วน
แต่เป็นต้องข้อสอบภายนอกนะ" (test the hard, world-class exam Jev itself used, test it piece by piece,
but it must be an external exam). OpenThai-SystemOne's own Hugging Face card states it was scored
on "the same 13 subsets, splits, instructions and sampler as Bespoke Nimble's own
`docs/PUBLIC_BENCHMARKS.md`": aegis2, boolq, civil_comments, helpsteer2, massive-de-DE,
massive-en-US, multinli, paws, pubmedqa, squad2, summeval-consistency, summeval-relevance,
vitaminc-dev.

**This script now covers all 13.** The first 3 (`boolq`, `paws`, `multinli`) were the ones
directly loadable with the smallest amount of task-mapping work. The other 10 needed real
per-dataset research (verified live, each one actually loaded via `datasets.load_dataset` before
being wired in here, not assumed from documentation) to find the correct HF repo id/config/split
and an honest mapping onto pgcross's `noul`/`score`/`choice` DecisionQuestion shapes:
  - `aegis2` (nvidia/Aegis-AI-Content-Safety-Dataset-2.0): prompt-safety, noul.
  - `civil_comments` (google/civil_comments): the dataset has no discrete label, only continuous
    [0,1] toxicity fractions — bucketed into 5 ordered levels (`score`), not forced into noul.
  - `helpsteer2` (nvidia/HelpSteer2): the `helpfulness` dimension (0-4), `score`.
  - `massive-de-DE`/`massive-en-US` (AmazonScience/massive): intent classification over the
    dataset's own real 60-intent vocabulary (`choice`). The repo ships a deprecated loading
    script that current `datasets` refuses to run — loaded via the Hub's auto-converted Parquet
    mirror instead (`refs/convert/parquet`), and the intent-name vocabulary is read from that
    parquet file's own embedded HF feature metadata, not hand-typed.
  - `pubmedqa` (qiaojin/PubMedQA, `pqa_labeled`): yes/no/maybe, `choice` (not noul — "maybe" is a
    real third answer, not the same thing as "unresolved").
  - `squad2` (rajpurkar/squad_v2): full SQuAD2 is extractive span QA, not a classification task.
    Narrowed to SQuAD2's own answerable-vs-unanswerable distinction (`answers.text == []`), which
    is the dataset's own designed sub-task (the official leaderboard's HasAns/NoAns split), not
    an invented simplification — `noul`.
  - `summeval-consistency`/`summeval-relevance` (mteb/summeval): each row holds a LIST of ~16
    machine summaries with parallel per-summary human ratings; this harness uses index 0 of that
    list per row as one real, unambiguous example (not fabricated), `score` (1-5, rounded from
    the human-annotator mean).
  - `vitaminc-dev` (tals/vitaminc, `validation` split): SUPPORTS/REFUTES/NOT ENOUGH INFO,
    `choice`.

**Still not apples-to-apples with OpenThai-SystemOne's own published numbers, even where the same
dataset name is used**: this project's own harness (instructions text, sampler, split, prompt
framing) is NOT reconstructed to be byte-identical to Bespoke Nimble's `docs/PUBLIC_BENCHMARKS.md`
methodology — only the underlying public dataset is the same. Same honesty discipline as
`eval/xnli_th_external_benchmark.py`: report the real number this harness gets, and say plainly
what would need to change for it to be a true apples-to-apples comparison.

Sample sizes: the original 3 (`boolq`/`paws`/`multinli`) use `_N=60`, run and verified first.
The 10 added afterward use `_N_NEW=30` — smaller, to keep total run time and GPU/CPU load
bounded across 13 sequential dataset loads in one sitting (this machine has a single 4GB GPU;
these calls run strictly one dataset at a time, never in parallel, checked via `nvidia-smi`/
`free -h` between each during development).

Run: `python eval/jev_public_benchmark_suite.py [<name>|all]` (default: all; `<name>` is any key
in `_BENCHMARKS`, e.g. `aegis2`, `civil_comments`, `massive-en-US`).
Needs `pip install pgcross[openthai,eval]`.

**Real run, all 13, 2026-09-21** (piece by piece, one dataset per invocation, `nvidia-smi`/
`free -h` checked between each — never run in parallel on this machine's single 4GB GPU):
boolq 43/60 (71.7%), paws 37/60 (61.7%), multinli 55/60 (91.7%), aegis2 12/30 (40.0%),
civil_comments 2/30 (6.7%), helpsteer2 12/30 (40.0%), massive-en-US 19/30 (63.3%),
massive-de-DE 11/30 (36.7%), pubmedqa 18/30 (60.0%), squad2 28/30 (93.3%),
summeval-consistency 9/30 (30.0%), summeval-relevance 4/30 (13.3%), vitaminc-dev 17/30 (56.7%).
**Combined: 267/480 (55.6%).** `civil_comments` and `summeval-relevance` are genuinely low —
reported with the same prominence as the high scores, not buried. Both use STRICT exact-match
scoring against an ordinal bucket (5-level Likert/severity scale collapsed from a continuous or
mean-of-raters ground truth); an off-by-one-level tolerant scoring mode (documented as a
recommended alternative in this file's own per-dataset research, not yet implemented here) would
likely read as a fairer measure of ordinal closeness for these two specifically, and is real,
named follow-up work, not a silent gap.
"""
from __future__ import annotations

import json
import random
import sys
import time

import huggingface_hub
import pyarrow.parquet as pq
from datasets import load_dataset

from pgcross.decision.backend import OpenThaiSystemOneLocalBackend
from pgcross.decision.schema import DecisionQuestion

_SEED = 20260921
_N = 60
_N_NEW = 30


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


def _score_index(label: str, n_levels: int) -> int:
    """A `kind="score"` DecisionAnswer's `label` is a FLOAT STRING -- a continuous weighted-
    average index into `levels` (e.g. `"2.5700..."` ), NOT the level text verbatim, and
    `probabilities` is keyed by index strings ("0".."4"), not level text. Confirmed live
    2026-09-21 by a real `decide()` call before writing this function -- the shape assumed by
    this file's own dataset-research pass (label == chosen level string) was wrong; this is the
    corrected, actually-verified parsing. Rounds to the nearest valid index, clamped to range."""
    idx = round(float(label))
    return max(0, min(n_levels - 1, idx))


def _bench_aegis2(backend) -> dict:
    ds = load_dataset("nvidia/Aegis-AI-Content-Safety-Dataset-2.0", split="train")
    rng = random.Random(_SEED)
    examples = [ds[i] for i in rng.sample(range(len(ds)), _N_NEW)]
    correct = 0
    for ex in examples:
        q = DecisionQuestion(
            id="q", kind="noul",
            text=f"Prompt: {ex['prompt']!r}. Is this prompt UNSAFE (violates content-safety "
                 "policy, e.g. criminal planning, hate, sexual content, violence, self-harm)?",
        )
        proposal = backend.decide(state={}, questions=[q])
        got_yes = proposal.answers[0].label == "yes"
        correct += int(got_yes == (ex["prompt_label"] == "unsafe"))
    return {"name": "aegis2", "source": "nvidia/Aegis-AI-Content-Safety-Dataset-2.0 (train, 30007 total)",
            "n": _N_NEW, "correct": correct}


_TOXICITY_LEVELS = ["not toxic", "slightly toxic", "moderately toxic", "very toxic", "severely toxic"]


def _toxicity_bucket(score: float) -> int:
    return min(4, int(score * 5))  # [0,.2)->0 .. [.8,1]->4


def _bench_civil_comments(backend) -> dict:
    ds = load_dataset("google/civil_comments", split="validation")
    rng = random.Random(_SEED)
    examples = [ds[i] for i in rng.sample(range(len(ds)), _N_NEW)]
    correct = 0
    for ex in examples:
        q = DecisionQuestion(
            id="q", kind="score", levels=_TOXICITY_LEVELS,
            text=f"Comment: {ex['text']!r}. Rate how toxic this comment is.",
        )
        proposal = backend.decide(state={}, questions=[q])
        got_idx = _score_index(proposal.answers[0].label, len(_TOXICITY_LEVELS))
        correct += int(got_idx == _toxicity_bucket(ex["toxicity"]))
    return {"name": "civil_comments", "source": "google/civil_comments (validation, 97320 total)",
            "n": _N_NEW, "correct": correct}


_HELPFULNESS_LEVELS = ["not helpful at all", "slightly helpful", "moderately helpful", "helpful", "extremely helpful"]


def _bench_helpsteer2(backend) -> dict:
    ds = load_dataset("nvidia/HelpSteer2", split="train")
    rng = random.Random(_SEED)
    examples = [ds[i] for i in rng.sample(range(len(ds)), _N_NEW)]
    correct = 0
    for ex in examples:
        q = DecisionQuestion(
            id="q", kind="score", levels=_HELPFULNESS_LEVELS,
            text=f"Prompt: {ex['prompt']!r}. Response: {ex['response']!r}. "
                 "Rate how helpful the response is to the prompt.",
        )
        proposal = backend.decide(state={}, questions=[q])
        got_idx = _score_index(proposal.answers[0].label, len(_HELPFULNESS_LEVELS))
        correct += int(got_idx == round(ex["helpfulness"]))
    return {"name": "helpsteer2", "source": "nvidia/HelpSteer2 (train, 20324 total)", "n": _N_NEW, "correct": correct}


def _load_massive(locale: str):
    """AmazonScience/massive ships a deprecated loading script current `datasets` refuses to
    run -- loads the Hub's auto-converted Parquet mirror instead (same canonical repo/data, not
    a substitute dataset), and reads the real intent-name vocabulary from that parquet file's
    own embedded HF feature metadata rather than a hand-typed list."""
    url = f"hf://datasets/AmazonScience/massive@refs%2Fconvert%2Fparquet/{locale}/test/0000.parquet"
    ds = load_dataset("parquet", data_files={"test": url})["test"]
    path = huggingface_hub.hf_hub_download(
        repo_id="AmazonScience/massive", repo_type="dataset",
        revision="refs/convert/parquet", filename=f"{locale}/test/0000.parquet",
    )
    meta = json.loads(pq.read_schema(path).metadata[b"huggingface"])
    intent_names = meta["info"]["features"]["intent"]["names"]
    return ds, intent_names


def _bench_massive(backend, locale: str) -> dict:
    ds, intent_names = _load_massive(locale)
    rng = random.Random(_SEED)
    examples = [ds[i] for i in rng.sample(range(len(ds)), _N_NEW)]
    criteria = {name: name.replace("_", " ") for name in intent_names}
    correct = 0
    for ex in examples:
        expected = intent_names[ex["intent"]]
        q = DecisionQuestion(
            id="q", kind="choice", option_descriptions=criteria,
            text=f"Utterance: {ex['utt']!r}. Which intent category best describes what the "
                 "speaker wants the voice assistant to do?",
        )
        proposal = backend.decide(state={}, questions=[q])
        correct += int(proposal.answers[0].label == expected)
    return {"name": f"massive-{locale}", "source": f"AmazonScience/massive {locale} (test, {len(ds)} total)",
            "n": _N_NEW, "correct": correct}


_bench_massive_de_de = lambda backend: _bench_massive(backend, "de-DE")  # noqa: E731
_bench_massive_en_us = lambda backend: _bench_massive(backend, "en-US")  # noqa: E731


_PUBMEDQA_CRITERIA = {
    "yes": "the evidence in the context supports a 'yes' answer to the research question",
    "no": "the evidence in the context supports a 'no' answer to the research question",
    "maybe": "the evidence in the context is inconclusive/mixed",
}


def _bench_pubmedqa(backend) -> dict:
    ds = load_dataset("qiaojin/PubMedQA", "pqa_labeled", split="train")
    rng = random.Random(_SEED)
    examples = [ds[i] for i in rng.sample(range(len(ds)), _N_NEW)]
    correct = 0
    for ex in examples:
        context = " ".join(ex["context"]["contexts"])
        q = DecisionQuestion(
            id="q", kind="choice", option_descriptions=_PUBMEDQA_CRITERIA,
            text=f"Context: {context!r}. Research question: {ex['question']!r}. "
                 "Based solely on the context, answer the research question.",
        )
        proposal = backend.decide(state={}, questions=[q])
        correct += int(proposal.answers[0].label == ex["final_decision"])
    return {"name": "pubmedqa", "source": "qiaojin/PubMedQA pqa_labeled (train, 1000 total)",
            "n": _N_NEW, "correct": correct}


def _bench_squad2(backend) -> dict:
    ds = load_dataset("rajpurkar/squad_v2", split="validation")
    rng = random.Random(_SEED)
    examples = [ds[i] for i in rng.sample(range(len(ds)), _N_NEW)]
    correct = 0
    for ex in examples:
        q = DecisionQuestion(
            id="q", kind="noul",
            text=f"Passage: {ex['context']!r}. Question: {ex['question']!r}. "
                 "Can this question be answered from the passage (yes = the passage contains "
                 "the answer, no = the passage does not contain enough information)?",
        )
        proposal = backend.decide(state={}, questions=[q])
        got_yes = proposal.answers[0].label == "yes"
        answerable = len(ex["answers"]["text"]) > 0
        correct += int(got_yes == answerable)
    return {"name": "squad2", "source": "rajpurkar/squad_v2 (validation, 11873 total)", "n": _N_NEW, "correct": correct}


_SUMMEVAL_LEVELS_CONSISTENCY = [
    "1 - completely inconsistent with the article", "2 - mostly inconsistent",
    "3 - somewhat consistent", "4 - mostly consistent", "5 - fully consistent with the article",
]
_SUMMEVAL_LEVELS_RELEVANCE = [
    "1 - misses most important content", "2 - captures some key points, omits a lot",
    "3 - captures most key points with some gaps", "4 - captures nearly all key points",
    "5 - captures all the important content",
]


def _bench_summeval(backend, dimension: str, levels: list) -> dict:
    ds = load_dataset("mteb/summeval", split="test")
    rng = random.Random(_SEED)
    row_indices = rng.sample(range(len(ds)), _N_NEW)
    correct = 0
    for i in row_indices:
        ex = ds[i]
        summary = ex["machine_summaries"][0]
        gold = ex[dimension][0]
        q = DecisionQuestion(
            id="q", kind="score", levels=levels,
            text=f"Source article: {ex['text']!r}. Candidate summary: {summary!r}. "
                 f"Rate this summary's {dimension}.",
        )
        proposal = backend.decide(state={}, questions=[q])
        got_idx = _score_index(proposal.answers[0].label, len(levels))
        correct += int(got_idx == round(gold) - 1)  # gold is 1-5, levels are 0-indexed
    return {"name": f"summeval-{dimension}", "source": "mteb/summeval (test, 100 rows x 16 summaries each, idx 0 used)",
            "n": _N_NEW, "correct": correct}


_bench_summeval_consistency = lambda backend: _bench_summeval(backend, "consistency", _SUMMEVAL_LEVELS_CONSISTENCY)  # noqa: E731
_bench_summeval_relevance = lambda backend: _bench_summeval(backend, "relevance", _SUMMEVAL_LEVELS_RELEVANCE)  # noqa: E731


_VITAMINC_CRITERIA = {
    "SUPPORTS": "the evidence confirms the claim is true",
    "REFUTES": "the evidence contradicts or disproves the claim",
    "NOT ENOUGH INFO": "the evidence does not contain enough information to confirm or deny the claim",
}


def _bench_vitaminc(backend) -> dict:
    ds = load_dataset("tals/vitaminc", split="validation")
    rng = random.Random(_SEED)
    examples = [ds[i] for i in rng.sample(range(len(ds)), _N_NEW)]
    correct = 0
    for ex in examples:
        q = DecisionQuestion(
            id="q", kind="choice", option_descriptions=_VITAMINC_CRITERIA,
            text=f"Evidence: {ex['evidence']!r}. Claim: {ex['claim']!r}. "
                 "Based only on the evidence, is the claim SUPPORTS, REFUTES, or NOT ENOUGH INFO?",
        )
        proposal = backend.decide(state={}, questions=[q])
        correct += int(proposal.answers[0].label == ex["label"])
    return {"name": "vitaminc-dev", "source": "tals/vitaminc validation (63054 total)", "n": _N_NEW, "correct": correct}


_BENCHMARKS = {
    "boolq": _bench_boolq, "paws": _bench_paws, "multinli": _bench_multinli,
    "aegis2": _bench_aegis2, "civil_comments": _bench_civil_comments, "helpsteer2": _bench_helpsteer2,
    "massive-de-DE": _bench_massive_de_de, "massive-en-US": _bench_massive_en_us,
    "pubmedqa": _bench_pubmedqa, "squad2": _bench_squad2,
    "summeval-consistency": _bench_summeval_consistency, "summeval-relevance": _bench_summeval_relevance,
    "vitaminc-dev": _bench_vitaminc,
}


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
    print(f"\n  Covers all 13 of the datasets OpenThai-SystemOne's own published benchmark uses "
          f"({len(names)} run this invocation). Sample sizes differ by design (boolq/paws/multinli "
          f"use n={_N}, the 10 added afterward use n={_N_NEW} to keep total run time bounded across "
          f"13 sequential real model calls on a single 4GB GPU) -- do NOT average across rows as if "
          f"every dataset carried equal weight without accounting for that. This is NOT a "
          f"byte-identical reconstruction of Bespoke Nimble's own instructions/sampler methodology, "
          f"and several subsets here use a real, documented, but narrowed sub-task of the original "
          f"dataset (squad2 -> answerable/unanswerable only; summeval-* -> row index 0 of each "
          f"summary list only) -- see this file's module docstring for exactly what was narrowed and "
          f"why. Real dataset, real sample, real score -- not a reproduction of their exact "
          f"published number.")


if __name__ == "__main__":
    main()
