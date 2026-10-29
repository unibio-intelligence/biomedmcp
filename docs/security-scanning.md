# Dependency and runtime image advisory gate

Both CI workflows and the protected manual public release workflow run
`scripts/scan-security.py` after container qualification. A failed scan stops
publication. Reports, CycloneDX inventories and their receipt are retained as
CI artifacts on success or failure; a missing report fails artifact collection.
The scanner reports findings without automatically changing dependencies or
applying advisory exemptions.

The workflows also run a separate [public documentation HTTP link gate](public-links.md).
It retains failed observations and does not use provider credentials or qualify
provider health. External-link failures are advisory in CI; security scans remain
required. Protected manual releases retain the required external-link gate.
Offline documentation paths and generated drift remain part of container
qualification.

Run with Python 3.11 or later and Docker inside the qualification lifecycle:

```sh
./scripts/test-local.sh -- bash -euo pipefail -c '
  python3 scripts/scan-security.py --image "$UBI_RUNTIME_IMAGE" --output /tmp/ubi-security-new
'
```

Use a fresh output directory. Existing evidence is never overwritten or reused
as proof of a new scan. The runner supplies its unique runtime tag and removes
it after the scan. For a separately built local runtime, pass its exact tag with
`--image`; it must be built from the same lock.
Installed Python versions must belong to that frozen lock. This interface
does not build or pull a target image and does not qualify private hosted
dependencies against the public lock.

The official Grype v0.120.1 multi-platform image is pinned to
`sha256:e4a44ef45d285b829ce6efe2642980329661bd2d18eab5fc539138d4adaebbbe`.
The scanner runs as the invoking host UID/GID so it can read private inputs and
write its owned reports/cache without restoring dropped capabilities or widening
input or report permissions. The tool receives read-only input files and a saved Docker archive; it never
receives a Docker socket, provider credentials or a repository mount. Its
root filesystem is read-only, capabilities are dropped and privilege escalation
is disabled. An interrupted or timed-out invocation removes only its uniquely
named scanner container. These are supported [Grype scan targets](https://oss.anchore.com/docs/reference/grype/cli/).

Every third-party registry name/version node in `uv.lock` is scanned, including
development tools and platform alternatives. Versions are queried as exact
Python package URLs without dependency installation or execution. Local
workspace source packages are listed separately; their current source is not
qualified by registry advisory matching. Unknown registry or nonregistry
dependency sources fail rather than silently dropping coverage.

The dependency scan must check for database updates. The database's hash,
validity, fixed upstream origin, published archive checksum, required feeds and
maximum five-day build age are enforced. The runtime scan then uses that same
hash-validated database with networking disabled and a read-only database mount.
The ignored dedicated cache is `reports/security-db`; it can consume several
GB. Neither cache nor target archive is uploaded as a CI artifact.
[Grype documents database verification and update settings](https://oss.anchore.com/docs/reference/grype/configuration/).

Any dependency advisory blocks, including unknown severity and unfixed findings.
Runtime High, Critical and Unknown findings block; lower-severity runtime
findings remain in the report. Configured advisory ignores, path exclusions and
fix-state filters are forbidden. Upstream matcher rules still determine
candidate matches, so a scanner finding requires assessment and does not by
itself demonstrate application exploitability.

The emitted CycloneDX 1.7 inventories must contain every expected frozen
registry node and every installed runtime Python package. Bounded format,
identity and coverage checks do not replace full standards-schema validation.
Image provenance distinguishes Docker's local image/index identity from the
selected config digest: saved manifest blobs establish their relationship.
References to unpulled platforms may be absent from a saved index; a present,
hash-verified path from the local image identity to the selected config is
still required. Wrong identities, malformed/incomplete reports, stale databases or disagreement
between findings and scanner exit status fail closed. Successfully completed
peer scans are preserved when a later phase fails.

`security-receipt.json` binds the source revision where available, export
manifest identity where supplied, lock/project/scanner hashes, exact local
image and archive/config identities, database provenance and report/SBOM/log
hashes. This is unsigned execution evidence. Signed release attestation and
durable association of SBOMs with published wheel artifacts remain separate
release work. A passing advisory scan is not proof of vulnerability absence,
exhaustive native-library detection, source-code security or provider readiness.


Both public and hosted Dockerfiles use the same digest-pinned official Python
3.13.16 Alpine 3.23 base. Its musl C library differs from the prior slim Trixie
base, so scientific numerical/reference tests, transport, public Redis and
reviewed hosted-auth contracts must qualify the built images. Zlib is pinned to
Alpine's patched `1.3.2-r1` package; test-only Git and procps-ng are pinned
separately. They are not installed in the runtime stage. Non-root UID 10001,
health checks, entry points, frozen Python dependencies and source restrictions
remain explicit in both Dockerfiles.

The [official image definition](https://github.com/docker-library/python/blob/d2a898cb88e46203577eabc62cdcf6e92aaee176/3.13/alpine3.23/Dockerfile)
and [Python maintenance release](https://www.python.org/downloads/release/python-31316/)
identify upstream source. Base refreshes require complete deterministic,
exported-container and reviewed hosted-auth qualification plus fresh exact-image
scans. A newer base does not itself establish a passing scan. Qualification
receipts retain built image identities, package versions and earlier failing
observations; the prior Trixie findings remain historical evidence.

The pinned Grype version emits an empty fix-state string for some Alpine APK
NVD/CPE matches. Only this observed combination—Alpine distro, Alpine APK purl,
NVD/CPE namespace, empty state and no fix versions—is represented as unknown
remediation metadata. `reported_fix_state` retains the original empty string.
No advisory is removed: High, Critical and Unknown severity still block, while
lower-severity findings remain reported under the existing policy. Other unknown
or malformed fix states fail closed. Fix-state normalization does not establish
that a vulnerability is fixed or unexploitable.
