# NON_CLAIMS — pgcross-1

> What this repo explicitly does NOT do, and will not silently grow into. Follows a
> NON_CLAIMS convention already used in a private sibling repo.

## Execution-oracle scope boundary (K6 track 3)

`providers/oracle/execution_oracle.py` runs generated code against a real test suite and
reads pass/fail as ground truth. This is a deliberate, declared exception to I7 ("LLM
transports only — structures/extracts, never asserts a fact"): execution, not the LLM,
is what asserts the fact here. The exception is bounded to exactly this grain, matching
HumanEval/MBPP's own scope:

- **IN scope:** one function, one prompt, one test file, no build system, no multi-file edit.
- **OUT of scope, permanently:** repo-level patching, multi-file context, issue-to-PR agentic
  coding — the SWE-bench class of benchmark. pgcross-1 is not an agentic coding tool.

**This boundary is a gate, not a suggestion.** Any invocation of `execution_oracle` requiring
more than one file or one test target is out of bounds and must be rejected before it runs,
not audited after the fact. If a future task seems to need repo-level execution, that is a
signal to build a separate, explicitly-scoped tool — not to quietly widen this module.

## Everything else out of scope

pgcross is a general-purpose, model-agnostic evidence-gated decision runtime (per the project's
internal architecture design records for the current target architecture) — it does not carry any
organization-specific business logic, policy, or deployment concern, and is not the place to add
one. Model training/fine-tuning, an org-specific policy overlay, and platform-level deployment are
all explicitly separate concerns and belong in other, separately-scoped repositories, never folded
into this one. (The older `PRODUCT_SPEC.md` this section previously pointed to has been superseded
and archived — see the project's internal engineering decision log for why.)
