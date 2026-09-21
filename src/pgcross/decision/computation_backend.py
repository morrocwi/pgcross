"""ComputationBackend — sibling protocol to DecisionBackend, NOT the same thing.

Per the project's architecture design notes §6a: a calculator is not a proposer.
`DecisionBackend` (System-One-style: OpenThai-SystemOne / Jev / mock) produces a
*probabilistic proposal* that must still pass Verify/Authorize. `ComputationBackend`
routes to an existing, separately-owned, separately-verified calculator
(`information-discrete-math` for finite/exact math, and a private sibling repo not
included here for cross-domain structural/spine dynamics) and returns an
already-certified-or-estimated result — no probabilistic model call involved at all.

Grounding (registry-verified primitives cited by code, per this project's own lookup-before-derive discipline):
- `A3` (`P(X) <=> exists w finite: check(X,w)=True`) is the witness-before-model
  discipline this protocol continues: §6a's end-to-end order places
  `ComputationBackend` routing *after* the deterministic engine card and the `A3`
  witness check, and *before* any `DecisionBackend` call — still no probabilistic
  model call at step 3.
- `D/M.65.v1` (`Sz <> Sbot`, Th_coqc): `ComputationResult.status` must never collapse
  an unresolved/HOLD result into a false "value" — `IDMBackend` passes through the
  underlying `idm.solve()` `status` (e.g. "HOLD") rather than coercing it.

This module defines the protocol + two backends per §6a's explicit scope:
- `IDMBackend` — a REAL implementation, direct Python call to `idm.solve()` (no REST,
  per §6a's deployment note: same-machine calls should be direct Python).
- `UniversalSolverBackend` — a CLEARLY-LABELED STUB. It routes to a separate, private
  sibling repo not included here; §6a explicitly says to "flag as a
  dependency-availability risk, not a blocker to defining the protocol itself."
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, Field


class IDMNotInstalledError(ImportError):
    """Raised by `IDMBackend` when the `idm` package cannot be imported.

    `idm` (`information-discrete-math`, https://github.com/morrocwi/information-discrete-math)
    is a separate public repo/package — it may not be pip-installed into pgcross's own
    virtualenv. This is a documented
    dependency-availability condition, not a silent no-op: `IDMBackend.solve()` must
    raise this (never fabricate a result) when `idm` is not importable.
    """

    def __init__(self, original: Exception | None = None) -> None:
        message = (
            "The 'idm' package (information-discrete-math) is not importable in "
            "this environment. IDMBackend calls idm.solve() directly (same-machine "
            "Python call, per the project's architecture design notes §6a's deployment "
            "note), not over REST, so the package must be installed into pgcross's "
            "own environment. Install it with:\n"
            "    pip install -e <path-to-information-discrete-math>\n"
            "(clone from https://github.com/morrocwi/information-discrete-math; brings in "
            "mpmath, sympy). See that repo's API.md for the library and "
            "idm.solve(problem) surface this backend calls."
        )
        super().__init__(message)
        self.__cause__ = original


class ComputationResult(BaseModel):
    """Normalized result of a `ComputationBackend.solve()` call.

    Field shapes follow the project's architecture design notes §6a, which
    observed that `idm.solve()`'s own result shape ("status", "tier", "value",
    "bound") is "already shaped like a PGCross VerificationResult" — this model
    keeps that shape rather than inventing a new one.
    """

    value: Any = None
    tier: str = "Open"  # matches core.enums.Tier vocabulary where applicable (name, not int)
    bound: dict[str, Any] | None = None
    status: str = "ESTIMATED"  # e.g. "CERTIFIED" / "ESTIMATED" / "HOLD"
    method: str = ""


@runtime_checkable
class ComputationBackend(Protocol):
    """Sibling protocol to `DecisionBackend` — a calculator is not a proposer.

    `DecisionBackend.decide(state, questions) -> DecisionProposal` is a
    probabilistic proposal that must pass Verify/Authorize before it can act.
    `ComputationBackend.solve(request) -> ComputationResult` routes to an already
    finite/exact (or rigorously bounded) calculator and carries its own
    status/tier — it is reached in the kernel's routing order *before* any
    `DecisionBackend` call (§6a step 3, after the deterministic engine card
    and the `A3` witness check at steps 1-2).
    """

    def solve(self, request: dict[str, Any]) -> ComputationResult:
        """Solve a structured problem request and return a normalized result."""
        ...


class IDMBackend:
    """`ComputationBackend` routing to `information-discrete-math`'s `idm.solve()`.

    Direct same-machine Python call (no REST/serialization overhead), per §6a's
    deployment note. `request` is passed straight through as the structured
    problem body `idm.solve()` expects (a `kind` key plus that kind's own
    parameters — see the `information-discrete-math` repo's `API.md`, e.g.
    `{"kind": "integral", "f": "exp(-x**2)", "a": "-6", "b": "6", "eps": "1e-8"}`).

    Raises `IDMNotInstalledError` (never silently no-ops, never fakes a result) if
    the `idm` package is not importable in this environment.
    """

    def solve(self, request: dict[str, Any]) -> ComputationResult:
        try:
            import idm  # local import: only required when IDMBackend is actually used
        except ImportError as exc:
            raise IDMNotInstalledError(exc) from exc

        raw: dict[str, Any] = idm.solve(request)

        return ComputationResult(
            value=raw.get("value"),
            tier=str(raw.get("tier", "Open")),
            bound=raw.get("bound"),
            status=str(raw.get("status", "ESTIMATED")),
            method=str(raw.get("method", "")),
        )


class UniversalSolverBackend:
    """`ComputationBackend` STUB routing to a private sibling repo, not included here.

    Deliberately NOT wired up in this pass. Per §6a: "UniversalSolverBackend
    depends on a private sibling repo being available as a dependency --
    flag as a dependency-availability risk, not a blocker to defining the
    protocol itself." This class exists only to satisfy the `ComputationBackend`
    protocol shape and document that scope decision; `solve()` always raises
    `NotImplementedError`.
    """

    def solve(self, request: dict[str, Any]) -> ComputationResult:
        raise NotImplementedError(
            "UniversalSolverBackend is a stub. It depends on a private sibling "
            "repo (not included in this package) being available as a "
            "dependency, per the project's architecture design notes §6a. Wiring this "
            "up for real is out of scope for this pass -- flagged as a "
            "dependency-availability risk, not a blocker to defining the "
            "ComputationBackend protocol itself."
        )
