"""Generic associative fold primitive — the `A2` root instance for Verify/Authorize.

Toledo's `A2` ("FOLD (the engine)", untagged/root, `status: current`), statement as registered
in Toledo's canonical equation registry (read verbatim, not paraphrased from memory;
also quoted in the project's architecture design notes §1/§2.1):

    I_⊕[f](N) = ⨁_{k<N} f[k]      (and, for the differenced form: I(Df) = f[N] ⊟ f[0])

"one generic accumulation over a carrier+operation; changing `(⊕,⊗)` changes the branch, the
telescoping/FTCC identity is exact" (per `R/M.09.v1` `FTCC_exact` and `R/M.10.v1`
`FTCC_eps_exact`, both `Th_coqc`).

The project's architecture design notes §2.1 names five Verify-stage instances of this one root,
each a different choice of `⊕`, never a separate mechanism:

    evidence-sum      ⊕ = Σ    (sum of supporting evidence weight)          -> fold_sum
    weakest-gate       ⊕ = min  (weakest-link tiering; already live as
                                  `core/tiering.py`'s `final_tier`)          -> fold_min
    max-risk           ⊕ = max  (worst-case risk aggregation)               -> fold_max
    all-required        ⊕ = AND (all required documents/fields present)      -> fold_all
    any-red-flag       ⊕ = OR   (any disqualifying condition found)          -> fold_any

`core/tiering.py::final_tier` is documented (§4 item 3 of the same doc) as the live
`A2`-with-`min` instance; it is NOT modified here — `fold_min` below is a drop-in equivalent to
Python's builtin `min()` over the same carrier, proven by `tests/test_core_fold.py`, not a
replacement for `final_tier`'s own weakest-link computation.

Because `A2` is associative (and, for the named instances here, commutative) by construction,
these folds can run in any order or be chunked/reordered without changing the result — this is
the concrete mechanism behind the Fast Path concurrency design noted in the same doc's §2.1.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable
from functools import reduce
from typing import TypeVar

T = TypeVar("T")


def fold(op: Callable[[T, T], T], items: Iterable[T], identity: T) -> T:
    """The generic `A2` fold: `I_⊕[f](N) = ⨁_{k<N} f[k]`.

    `op` is the `⊕` of Toledo's statement; `identity` is `⊕`'s identity element so that an
    empty `items` returns `identity` rather than raising. `op` must be associative for the
    result to be independent of evaluation order/chunking, per `A2`'s own registered statement.
    """
    return reduce(op, items, identity)


def fold_sum(items: Iterable[float]) -> float:
    """`⊕ = Σ` — evidence-sum instance (§2.1)."""
    return fold(lambda a, b: a + b, items, 0)


def fold_min(items: Iterable[T]) -> T | None:
    """`⊕ = min` — weakest-gate instance (§2.1); the live pattern in `core/tiering.py::final_tier`.

    Returns `None` on an empty `items` (there is no universal top element to use as identity for
    an arbitrary ordered `T`) instead of silently picking one — callers with a known top element
    should pass it as a sentinel in `items` or handle `None` explicitly.
    """
    items = list(items)
    if not items:
        return None
    return reduce(lambda a, b: a if a <= b else b, items)


def fold_max(items: Iterable[T]) -> T | None:
    """`⊕ = max` — max-risk instance (§2.1). `None` on empty `items`, symmetric with `fold_min`."""
    items = list(items)
    if not items:
        return None
    return reduce(lambda a, b: a if a >= b else b, items)


def fold_all(items: Iterable[bool]) -> bool:
    """`⊕ = AND` — all-required instance (§2.1). Identity `True` (vacuously all-satisfied)."""
    return fold(lambda a, b: a and b, items, True)


def fold_any(items: Iterable[bool]) -> bool:
    """`⊕ = OR` — any-red-flag instance (§2.1). Identity `False` (vacuously no red flag)."""
    return fold(lambda a, b: a or b, items, False)
