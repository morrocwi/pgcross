# pgcross — License Audit

> Generated from pyproject.toml dependencies. Must show NO GPL/AGPL before any distribution.

## Status: CLEAN (no GPL/AGPL detected)

| Package | SPDX | Permissive? | Notes |
|---------|------|-------------|-------|
| fastapi | MIT | YES | Runtime core |
| uvicorn | BSD-3-Clause | YES | Runtime ASGI server |
| pydantic | MIT | YES | Runtime core |
| typer | MIT | YES | Runtime CLI |
| numpy | BSD-3-Clause | YES | Runtime numerics |
| pyyaml | MIT | YES | Runtime config |
| httpx | BSD-3-Clause | YES | Runtime HTTP client |
| sentence-transformers | Apache-2.0 | YES | Optional extra [rag] |
| pypdf | BSD-3-Clause | YES | Optional extra [rag] |
| llama-cpp-python | MIT | YES | Optional extra [llamacpp]; underlying llama.cpp also MIT |
| pytest | MIT | YES | Dev only; not shipped |
| pip-licenses | MIT | YES | Dev only; CI audit gate |

## GPL/AGPL scan result

No GPL or AGPL packages detected in the dependency tree as declared in pyproject.toml.

## Notes

- This table covers direct dependencies declared in `[project.dependencies]` and
  `[project.optional-dependencies]`. Transitive dependencies should also be audited
  before any external distribution.
- Optional extras (`[llamacpp]`, `[rag]`, `[vllm]`) are only subject to audit when
  actually installed. The `[vllm]` extra (Apache-2.0) is not listed above as it is
  not part of the default or recommended install path.
- Run `pip-licenses --format=markdown` to regenerate this table from the active
  virtual environment and compare against the values here.
- CI (`ci.yml`) runs `pip-licenses` and fails the build on any GPL/AGPL detection.
  No distribution or merge may proceed while the CI gate is red.

### Transitive-dependency verification status (2026-09-21)

- **Core deps + full transitive tree, verified clean in an isolated venv** (not the
  workstation's shared conda base env, which carries hundreds of unrelated packages —
  including GPL/AGPL-licensed ones from other projects — that would give false
  positives if used directly): `fastapi`, `uvicorn`, `pydantic`, `typer`, `numpy`,
  `pyyaml`, `httpx`, `pip-licenses` and everything they pull in (`starlette`, `anyio`,
  `click`, `rich`, `h11`, `httpcore`, `idna`, `pydantic_core`, `typing_extensions`,
  `certifi`, `shellingham`, `markdown-it-py`, `mdurl`, `prettytable`, `wcwidth`,
  `Pygments`, `typing-inspection`, `annotated-types`, `annotated-doc`). Result: all
  MIT / BSD-3-Clause / BSD-2-Clause / PSF-2.0 / ISC / 0BSD / Zlib / CC0-1.0, with one
  exception noted below. **No GPL/AGPL anywhere in this tree.**
- **One nuance, not a blocker:** `certifi`'s current release is MPL-2.0 (Mozilla
  Public License 2.0), not the plain permissive license this file's table implies by
  omission (it isn't a direct dependency so it wasn't in the table above). MPL-2.0 is
  weak (file-level) copyleft, not GPL/AGPL-family, and is standard/accepted for
  distributed Python software (used unmodified, as a CA-bundle-only dependency here);
  flagged for completeness, not treated as a compliance problem.
- **NOT independently re-verified this pass:** the `[rag]` extra's full transitive
  tree (`sentence-transformers` pulls in `torch`, `transformers`, `huggingface-hub`,
  `scikit-learn`, `scipy`, `Pillow`, `tqdm`, and more) and the `[llamacpp]` extra's
  build-time tree. An isolated-venv install of `sentence-transformers`/`pypdf` was
  attempted for this audit but failed on this workstation with `OSError: [Errno 122]
  Disk quota exceeded` before completing — this is an honest gap, not a clean result
  being claimed. The direct-dependency claims for `sentence-transformers` (Apache-2.0),
  `pypdf` (BSD-3-Clause), and `llama-cpp-python` (MIT, matching upstream llama.cpp's
  MIT license) are well-established/high-confidence for those packages themselves;
  what remains unverified by this pass is their full transitive trees. This should be
  completed with a real `pip-licenses` run in a disk-adequate isolated venv before
  those extras are part of any external distribution.

## Audit history

| Date | Result | Auditor |
|------|--------|---------|
| 2026-07-01 | CLEAN | spec-driven static audit from pyproject.toml |
| 2026-09-21 | CLEAN for core deps (isolated-venv `pip-licenses` run, full transitive tree); direct-dependency claims for `[rag]`/`[llamacpp]` extras re-confirmed by static/well-known-fact reasoning; full transitive tree for those two extras NOT independently re-verified this pass (disk-quota failure mid-install) — open item, not a finding | Phase 7 item 39 reconciliation pass (`RELEASE_MANIFEST.yaml`, `UPSTREAM_RELEASES.yaml` found stale/describing an abandoned N14 architecture and rewritten; this file's direct-dependency table found already accurate and left as-is) |
