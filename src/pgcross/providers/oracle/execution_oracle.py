"""providers/oracle/execution_oracle.py — K6 track 3: the execution-oracle exception.

WHAT THIS IS: running generated code against a real test suite and reading pass/fail is
asserting a fact from EXECUTION, not from the LLM. That is legitimate, but I7 ("LLM
transports only — structures/extracts, never asserts a fact") does not cover it by default,
so it must be an explicit, declared exception — not a card quietly treating "the test
passed" as an ordinary self-consistent or coq_checked claim.

SCOPE BOUNDARY (see ../../../../NON_CLAIMS.md): this module executes exactly ONE function
against ONE test file, no repo context, no multi-file edits, no build system. It must never
be extended toward repo-level/multi-file/agentic coding (the SWE-bench class of benchmark).
Any caller needing more than one file or one test target is out of bounds for this module.

SAFETY NOTE (read before using): `run_candidate` executes arbitrary Python via subprocess
with a wall-clock timeout and CPU/memory rlimits — the same safety model the reference
HumanEval execution harness uses. This is NOT a security sandbox against an adversarial
model (it does not block filesystem or network access). Do not point it at an untrusted or
adversarial code-generation source without a real sandbox (container/gVisor/firejail) in
front of it.
"""
from __future__ import annotations
import os
import resource
import subprocess
import sys
import tempfile
from dataclasses import dataclass


@dataclass
class OracleVerdict:
    passed: bool
    stdout: str
    stderr: str
    timed_out: bool
    returncode: int | None


def _limit_resources(cpu_seconds: int, mem_bytes: int):
    """Preexec function: apply rlimits inside the child before exec."""
    def _set():
        resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds))
        resource.setrlimit(resource.RLIMIT_AS, (mem_bytes, mem_bytes))
        resource.setrlimit(resource.RLIMIT_NPROC, (32, 32))
    return _set


def run_candidate(
    candidate_code: str,
    test_code: str,
    *,
    entry_point: str | None = None,
    timeout_seconds: float = 5.0,
    cpu_seconds: int = 5,
    mem_bytes: int = 512 * 1024 * 1024,
) -> OracleVerdict:
    """Execute `candidate_code` then `test_code` in a single fresh subprocess.

    `test_code` is expected to raise (AssertionError or otherwise) on failure and exit 0
    on success — the same convention HumanEval/MBPP reference harnesses use. `entry_point`
    is informational only (recorded for logging); the module does not special-case it.
    """
    script = candidate_code + "\n\n" + test_code + "\n"
    with tempfile.TemporaryDirectory() as tmpdir:
        script_path = os.path.join(tmpdir, "candidate_check.py")
        with open(script_path, "w") as f:
            f.write(script)
        try:
            proc = subprocess.run(
                [sys.executable, script_path],
                cwd=tmpdir,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                preexec_fn=_limit_resources(cpu_seconds, mem_bytes) if os.name == "posix" else None,
            )
        except subprocess.TimeoutExpired as e:
            return OracleVerdict(passed=False, stdout=e.stdout or "", stderr=e.stderr or "",
                                  timed_out=True, returncode=None)
        return OracleVerdict(
            passed=(proc.returncode == 0),
            stdout=proc.stdout, stderr=proc.stderr,
            timed_out=False, returncode=proc.returncode,
        )


def _short_error(verdict: OracleVerdict, max_len: int = 160) -> str:
    """One clean line describing the failure — no tracebacks, no newlines (must stay a
    valid single-line Python comment when spliced into completion-style repair prompts)."""
    if verdict.timed_out:
        return "timed out (possible infinite loop)"
    text = (verdict.stderr or verdict.stdout or "unknown failure").strip()
    line = text.splitlines()[-1] if text else "unknown failure"
    line = line.replace("\n", " ").replace('"""', "'''")
    return line[:max_len]


def repair_prompt_completion_style(problem_prompt: str, verdict: OracleVerdict) -> str:
    """Repair prompt for a BASE / plain-completion model (no instruction-following).

    K6 finding (round 1 with typhoon2-1b-base): an instruction-style repair prompt
    ("Task: ... Write a corrected solution...") makes a base model continue as PROSE, not
    code — it has no chat/instruct training to follow that framing. Every repair attempt
    failed the SAME way (IndentationError) because the model's prose response, naively
    spliced after `problem_prompt`, was not valid code at all.

    Fix: stay in the model's native mode — code completion. Return `problem_prompt` with a
    ONE-LINE code comment appended (still valid Python, same indentation the model already
    expects to continue from), so the model's natural next move is to keep writing code,
    now informed by what execution showed. Callers must treat AS THE PROMPT: the returned
    string (not `problem_prompt` alone) is the prefix the model's completion continues —
    the final candidate must be `returned_string + completion`, not `problem_prompt +
    completion`, or the hint comment is silently dropped and the indentation this repair
    exists to fix breaks again.

    For an instruction-tuned model, a chat-formatted instruction prompt (system/user turns)
    is the correct approach instead — this function is deliberately NOT that.
    """
    err = _short_error(verdict)
    return problem_prompt.rstrip("\n") + f"\n    # NOTE: a previous attempt failed ({err}). Careful, corrected implementation:\n"


def repair_prompt(problem_prompt: str, candidate_code: str, verdict: OracleVerdict) -> str:
    """Repair prompt for an INSTRUCT-TUNED model (chat/instruction-following).

    Natural-language framing is fine here — unlike a base model, an instruct-tuned model can
    actually follow "here is what failed, write a corrected version". Meant to be sent as a
    chat user turn (see eval/k6_humaneval_bench.py's ChatCompletionModel), not concatenated
    directly onto code like `repair_prompt_completion_style`.
    """
    err = (verdict.stderr or verdict.stdout or "(no output)").strip()[-2000:]
    return (
        f"The following candidate solution failed its test:\n\n{candidate_code}\n\n"
        f"Execution error/output:\n{err}\n\n"
        f"Task:\n{problem_prompt}\n\n"
        f"Write a corrected, complete solution to the same task."
    )
