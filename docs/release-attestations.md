# Release artifact attestations

Before dispatching a release, repository administrators must configure the
`public-release` environment with required reviewers. An environment name alone
does not enforce review. Keep publication disabled until that protection is verified.

The protected, manually invoked public release workflow qualifies the source,
containers, documentation and vulnerability gate before building wheels. Its
pinned GitHub attestation action then signs build provenance for the exact
`public-wheels.tar.gz` and `release-receipt.json` files, plus a CycloneDX 1.6 SBOM
attestation whose subject is the wheel archive. Publishing verifies all three
attestations before observing or mutating release state, including retries.

Verification fixes the public repository, `.github/workflows/release.yml`, both
the source and signer commit, GitHub hostname and hosted-runner requirement.
The SBOM predicate must equal the deterministic inventory reconstructed from
the local archive. A missing signature, wrong identity/digest, changed inventory,
unsupported verifier or unavailable attestation service stops publication.
No ignore flag or unsigned fallback is provided. A release keeps its two
immutable assets; signatures and SBOM evidence are retained separately and are
also available through GitHub's digest-indexed attestation service. New workflow
runs can sign identical assets without overwriting a version's bytes.

The wheel SBOM inventories every shipped wheel's package identity, version,
filename and exact SHA-256. Wheel metadata must match its filename and receipted
archive membership. Duplicate/unsafe members and oversized metadata fail closed.
`Requires-Dist`, license expressions and license files are preserved as reported
metadata properties. They are not resolved dependencies or permission grants.
Installed/transitive/runtime inventory and advisory scans remain separate;
provider-data permissions still follow [the source policy](source-licenses.md).
A build attestation establishes artifact provenance, not scientific correctness.

Consumers can download the two release assets and verify with GitHub CLI:

```sh
gh attestation verify public-wheels.tar.gz --repo unibio-intelligence/biomedmcp --signer-workflow unibio-intelligence/biomedmcp/.github/workflows/release.yml --source-digest COMMIT --signer-digest COMMIT --deny-self-hosted-runners
gh attestation verify release-receipt.json --repo unibio-intelligence/biomedmcp --signer-workflow unibio-intelligence/biomedmcp/.github/workflows/release.yml --source-digest COMMIT --signer-digest COMMIT --deny-self-hosted-runners
gh attestation verify public-wheels.tar.gz --repo unibio-intelligence/biomedmcp --signer-workflow unibio-intelligence/biomedmcp/.github/workflows/release.yml --source-digest COMMIT --signer-digest COMMIT --deny-self-hosted-runners --predicate-type https://cyclonedx.org/bom --format json
```

Replace `COMMIT` with the independently reviewed public commit. The local
publisher additionally checks that the verified SBOM equals the exact archive
projection. Live OIDC signing, transparency-log and protected-environment
behavior require qualification in the approved repository; local synthetic CLI
tests cannot establish those properties. The integration-code license and
security gates must pass before a release workflow can reach signing.

Primary contracts: [GitHub artifact attestations](https://docs.github.com/en/actions/how-tos/secure-your-work/use-artifact-attestations/use-artifact-attestations),
[the pinned action contract](https://github.com/actions/attest/blob/1e69f48acb82d1966a394da916b4c1698aa569d6/action.yml),
[GitHub CLI verification](https://cli.github.com/manual/gh_attestation_verify),
and [CycloneDX 1.6 schema](https://cyclonedx.org/schema/bom-1.6.schema.json).
