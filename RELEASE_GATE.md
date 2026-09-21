# RELEASE_GATE — pgcross

**Gate ID:** `GATE_RELEASE_PGCROSS` (supersedes the retired `GATE_A5_PGCROSS_PRODUCT_RELEASE`,
which targeted the abandoned Typhoon-1b/GGUF offline-bundle product direction — see the project's
internal historical record for that superseded evaluation).

**Honesty floor (unchanged from the prior gate, kept exactly):** a checklist box is checked ONLY
when a committed artifact backs it. `gate_passed` stays `false` — no automated step, no CI job, no
AI session may set it `true` or cut a version tag. Only internal authorization can approve a release.

## Checklist (all required before tagging a product release)

- [ ] **Conformance/invariant tests pass** — `pytest tests/conformance -q` green (currently 46
      `test_*` functions in `tests/conformance/test_conformance.py`, covering the fail-closed
      invariants: F1 serving/fail-closed, A1–A8 tiering/grounding/stakes/safety/self-declaration,
      D1 disclosure, R7/R8 RAG grounding, plus card-specific disambiguation tests). As the
      Authorize-stage F1–F15 invariants from the PGCross Next letter land (a planned near-term
      phase per the project's internal engineering roadmap), each gets its own named test here —
      do not claim "F1–F15 covered" until each one has a committed test, per the project's own
      flagged open risk that none of them exist yet.
- [ ] **Leak scan run** — an adversarial pass (per this workspace's `PUB-ADVERSARIAL-REVIEW` /
      `glosa-publish-gate`) for local usernames/paths, internal IDs, ARAYA/salamxp-specific
      content, and anything that reads like an internal working note, before any public-facing
      step. Zero ARAYA-specific content was confirmed for the public-core candidate file set as of
      an earlier internal architecture audit — this box re-confirms that against
      the current file set, it does not inherit the prior finding indefinitely.
- [x] **License/dependency audit reconciled** — `RELEASE_MANIFEST.yaml`, `UPSTREAM_RELEASES.yaml`,
      `licenses/AUDIT.md` all read and reconciled against `pyproject.toml`'s actual dependencies
      and optional extras (per the project's internal engineering decision log); GPL/AGPL
      dependency prohibition holds (core install confirmed clean via isolated-venv `pip-licenses`
      check; `[rag]`/`[llamacpp]` extras' full transitive trees remain an open, explicitly-flagged
      item — see the internal engineering decision log). **License change AUTHORIZED and EXECUTED
      2026-09-21**: the switch to Apache-2.0 was explicitly authorized; `LICENSE`, `pyproject.toml`,
      `THIRD_PARTY_NOTICES.md` updated accordingly (the copyright holder recorded in `LICENSE` is
      a legal attribution only, not organizational branding of the public-facing product itself,
      per a separate internal engineering decision that no org name appears in the public
      artifact's own framing).
- [ ] `CLAIMS.md` / `NON_CLAIMS.md` reflect the current pipeline honestly (diffed against last
      commit before citing as settled — per the project's internal engineering decision log).
- [ ] `PRODUCTION_CHECKLIST.md` all checked.
- [ ] `DEPLOYMENT.md` complete and matches the real `pyproject.toml` install surface.
- [ ] No dead/duplicate route or unwired module on the live server path (e.g. the
      `backends/registry.py` `openai`-kind wiring bug, the `server/app.py` duplicate-route class
      of issue) — confirmed fixed, not merely noted.
- [ ] Release notes recorded in `RELEASE_MANIFEST.yaml`.
- [ ] Sign-off from internal authority (required for `production_deployed` claim tier).

## Current status (2026-09-21, honesty-floor snapshot)

- `RELEASE_MANIFEST.yaml`: `releases: []`; no version tag cut.
- None of the checklist boxes above are checked yet — this file was retargeted from the retired
  GATE_A5/bundle-product checklist during the Phase A→Decision Forge doc migration (per the
  project's internal engineering decision log); it does not carry forward any of GATE_A5's prior
  `[x]`-checked evidence, because that evidence was measured against the retired product surface
  (Typhoon-1b GGUF composer, e5-small embedder, bundled corpus) and does not apply to the current
  pipeline.
- Conformance suite: 46 `test_*` functions currently exist in `tests/conformance/test_conformance.py`
  — this is a count, not a pass/fail claim; run the suite before checking that box.

**gate_passed: false** — not authorised here. Do not tag a release.

## Release command
```bash
git tag v{X.Y.Z} -m "pgcross v{X.Y.Z} — release gate passed, internally authorized"
git push origin v{X.Y.Z}
```
This command is documentation only — it must not be run by any automated step, and only after
every checklist box above is genuinely checked and internal sign-off is given.
