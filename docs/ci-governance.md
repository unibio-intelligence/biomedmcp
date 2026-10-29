# Public CI governance checks

`./scripts/test-local.sh` builds the test image, then runs scoped Ruff and
`scripts/check-governance.py` with Docker networking disabled. These read-only
checks precede deterministic contracts and the separate required Redis suite.
They use uv's `--no-sync` against the frozen, preinstalled test-image environment,
so checking evidence does not trigger dependency resolution or workspace builds.
The public CI workflow uses this qualifier. No provider credentials or live canaries are required.

The check compares the actual 13-tool in-process MCP catalog, ownership map,
adapter schemas, generated examples and onboarding documents against their
committed bytes. Adapter discovery uses synthetic settings and an empty study
directory; it does not establish operator access, live health or study readiness.
Optional tokenizer measurements must be well formed but can differ by tokenizer
installation. All other catalog fields must match.

Markdown inline, reference, image and HTML links must resolve inside the public
tree. Markdown heading fragments are checked, including duplicate headings;
directory links are allowed. Fenced examples are ignored. Symlink documents
and private traversal fail before reading their targets. External URLs are
neither requested nor qualified by this offline gate.

The manual [readiness matrix](capability-readiness.json) must identify the current
scientific implementation, preserve all 42 capabilities and their ownership,
and resolve its public evidence files. Its bounded qualification labels are not
automatically promoted. The bundled offline receipt must match installed source
and dependency fingerprints, every test input and the qualification runner.
The full adapter import/operation contract tests remain mandatory.

[Locked dependencies](locked-dependencies.json) records every frozen lock node,
platform alternative and source artifact hash, including development tools.
The [installed metadata inventory](python-dependency-inventory.json) records a
point-in-time installed subset with versions and available license metadata;
it must be bound to the current lock and contain no unknown or duplicate
distributions. Neither inventory is a vulnerability scan, SBOM attestation or
an integration-license decision.

After a reviewed source or dependency change, refresh generated documents:

```sh
uv sync --frozen
uv run --frozen python scripts/regenerate-governance.py
uv run --frozen python scripts/check-governance.py --generated-only
```

Review the manual readiness matrix and update its implementation revision when
appropriate, while preserving its evidence limits. Refresh the offline receipt
only by running the complete passing suite with a fresh JUnit path:

```sh
uv run --frozen python scripts/qualify-readiness.py --junit /tmp/ubi-readiness-new.xml
uv run --frozen python scripts/check-governance.py
./scripts/test-local.sh
```

`--generated-only` supports local preparation before the receipt is refreshed.
The shared CI qualifier always runs the full check. Checks never rewrite stale
documents or fabricate receipt evidence. License absence continues to block
publication. The separate [dependency/image advisory gate](security-scanning.md)
retains findings and CycloneDX inventories. [Release attestation](release-attestations.md) is implemented with exact artifact
verification; live signing and protected publication remain separately qualified.
External-link checks remain separate release work.
