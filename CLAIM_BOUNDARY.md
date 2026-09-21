# CLAIM_BOUNDARY — pgcross

**Claim tier:** `benchmark_candidate` → `production_deployed` after the release gate
(`RELEASE_GATE.md`) is genuinely met and internally authorized.

**Decision-layer vocabulary:** pgcross's Verify/Authorize stage speaks in
`AuthorizationStatus` (`ADMIT` / `HOLD` / `REJECT` / `ESCALATE` — `src/pgcross/decision/schema.py`),
not a bare pass/fail. A claim about what pgcross "decided" on a given input must cite one of these
four states, never a paraphrase. `HOLD` (and the underlying `S4.BOT` resolution) means genuinely
unresolved — it is never silently collapsed into `REJECT`/false/empty, per `D/M.65.v1`
(`Sz <> Sbot`, cited in `decision/schema.py`).

## What this product may claim
- "pgcross v{X.Y.Z}: benchmark accuracy Y% on domain Z (claim tier: benchmark_candidate)."
- "After the release gate + internal sign-off: production_deployed claim tier."
- "For input X, the Authorize stage returned ADMIT/HOLD/REJECT/ESCALATE" — only when that state
  was actually produced by the pipeline, not inferred or assumed.
- Schemas and configs in this repo are authoritative product specs, not research drafts.

## What this product may NOT claim
- "Answers are true" — all outputs are grounded readouts, not truth.
- "Works on any domain without evidence providers configured for that domain" — accuracy is
  provider/domain-specific.
- "Ready for end-users" until the release gate has passed and internal sign-off has been given.
- That a `DecisionBackend`/`ComputationBackend` integration (e.g. OpenThai-SystemOne,
  `information-discrete-math`, `research_universal_solver`) is working before it actually is —
  see `CHANGELOG.md` for the honest current state of each.
- That `HOLD`/unresolved (`S4.BOT`) is the same as a negative/false/empty answer — it is not.

## Authority
The project's internal engineering authority holds authority over all product claims and over any
change to this claim boundary. AI generates readouts, draft specs, and proposed claims — never the
final claim.
