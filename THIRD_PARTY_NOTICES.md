# PGCross — Third-Party Notices

PGCross is licensed under Apache License 2.0 (see `LICENSE`). It is assembled from
open-source components listed below. Each component retains its original license;
PGCross's own Apache-2.0 license applies only to the original PGCross code and
architecture.

Obligation: for MIT/BSD/Apache-2.0 components, copyright notices and license texts are
preserved here as required by each respective license.

---

## Runtime Dependencies

### fastapi
- **License:** MIT
- **Copyright:** Sebastián Ramírez and contributors
- **SPDX:** MIT
- **Compliance note:** Permissive. No conditions beyond copyright notice retention. Compliant.

### uvicorn
- **License:** BSD-3-Clause
- **Copyright:** Encode OSS Ltd. and contributors
- **SPDX:** BSD-3-Clause
- **Compliance note:** Permissive. Requires preservation of copyright notice, list of conditions,
  and disclaimer. Compliant.

### pydantic
- **License:** MIT
- **Copyright:** Samuel Colvin and contributors
- **SPDX:** MIT
- **Compliance note:** Permissive. No conditions beyond copyright notice retention. Compliant.

### typer
- **License:** MIT
- **Copyright:** Sebastián Ramírez and contributors
- **SPDX:** MIT
- **Compliance note:** Permissive. No conditions beyond copyright notice retention. Compliant.

### numpy
- **License:** BSD-3-Clause
- **Copyright:** NumPy Developers
- **SPDX:** BSD-3-Clause
- **Compliance note:** Permissive. Requires preservation of copyright notice, list of conditions,
  and disclaimer. Compliant.

### pyyaml
- **License:** MIT
- **Copyright:** Kirill Simonov and contributors
- **SPDX:** MIT
- **Compliance note:** Permissive. No conditions beyond copyright notice retention. Compliant.

### httpx
- **License:** BSD-3-Clause
- **Copyright:** Encode OSS Ltd. and contributors
- **SPDX:** BSD-3-Clause
- **Compliance note:** Permissive. Requires preservation of copyright notice, list of conditions,
  and disclaimer. Compliant.

---

## Optional / Extra Dependencies

### sentence-transformers
- **License:** Apache-2.0
- **Copyright:** UKPLab and contributors
- **SPDX:** Apache-2.0
- **Compliance note:** Permissive. Requires preservation of NOTICE file and license text where
  applicable. No patent retaliation clause triggered by internal use. Compliant.

### pypdf
- **License:** BSD-3-Clause
- **Copyright:** Mathieu Fenniak and contributors
- **SPDX:** BSD-3-Clause
- **Compliance note:** Permissive. Requires preservation of copyright notice, list of conditions,
  and disclaimer. Compliant.

### llama-cpp-python
- **License:** MIT
- **Copyright:** Andrei Betlen and contributors (Python bindings); llama.cpp: Georgi Gerganov and contributors (MIT)
- **SPDX:** MIT
- **Compliance note:** Both the Python bindings and the underlying llama.cpp C++ library are MIT.
  Permissive. No conditions beyond copyright notice retention. Compliant.

### openthai_systemone
- **License:** Apache-2.0
- **Copyright:** iapp-technology and the OpenThai team
- **SPDX:** Apache-2.0
- **Compliance note:** Permissive, same terms as this project's own license. `[openthai]` extra,
  lazy-imported only inside `decision/backend.py`'s `OpenThaiSystemOneLocalBackend`, so a caller
  who never instantiates that class never needs it installed. Permissive, compliant.

### transformers
- **License:** Apache-2.0
- **Copyright:** The HuggingFace team
- **SPDX:** Apache-2.0
- **Compliance note:** Permissive. `[safety]` extra, lazy-imported only inside `safety.py`'s
  `ClassifierSafety`. Compliant.

### torch
- **License:** BSD-3-Clause (PyTorch's own license, BSD-style)
- **Copyright:** PyTorch Contributors
- **SPDX:** BSD-3-Clause
- **Compliance note:** Permissive. `[safety]` extra, `transformers`' inference backend for
  `ClassifierSafety`. Compliant.

### unitary/toxic-bert (model weights)
- **License:** Apache-2.0
- **Copyright:** unitary and contributors
- **SPDX:** Apache-2.0
- **Compliance note:** Model weights, not code — downloaded at runtime via the Hugging Face Hub
  when `--safety classifier` is used; not redistributed in this repository. Permissive, compliant.

---

## Development Dependencies (not shipped in production builds)

### pytest
- **License:** MIT
- **Copyright:** Holger Krekel and contributors
- **SPDX:** MIT
- **Compliance note:** Development-only. Permissive. Compliant.

### pip-licenses
- **License:** MIT
- **Copyright:** raimon49 and contributors
- **SPDX:** MIT
- **Compliance note:** Development-only (CI audit gate). Permissive. Compliant.

---

## Prohibited Dependencies

GPL and AGPL licensed packages are PROHIBITED in this product. Any dependency audit
that surfaces a GPL/AGPL package must be resolved (replace, isolate, or remove) before
any internal or external distribution. See `licenses/AUDIT.md` for the current audit
result. CI is configured to fail on GPL/AGPL detection.
