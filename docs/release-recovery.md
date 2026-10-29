# Public artifact release recovery

Publication remains a protected, manually dispatched operation in the exact
public `unibio-intelligence/biomedmcp` repository.
An approved, nonempty integration LICENSE and a publishable source manifest
are required.

The public workflow qualifies the exported distribution in Docker, builds its
wheel set with `SOURCE_DATE_EPOCH` from the reviewed commit, then invokes
`scripts/release-artifacts.py`. The archive sorts wheel filenames and fixes
member ownership, permissions, timestamps and gzip metadata. It accepts and
excludes only uv's exact one-byte `.gitignore` output marker; unexpected files
or marker contents fail before packaging. The deterministic
`release-receipt.json` binds the version, full public commit, export digest,
lockfile digest, source timestamp, wheel hashes and archive hash. The publisher
checks selected source bytes against the manifest and requires a clean checkout
at the reviewed commit. Build artifacts stay outside the source checkout.

The publisher observes all releases, including authorized draft listings,
and peels annotated tags to their commit. It verifies the fixed public
repository and authenticated push permission before treating a missing tag as
absent. API reads, writes and asset uploads explicitly bind `github.com`, so
`GH_HOST` cannot redirect an upload to another host. Observation failures stop
publication. Collection inventories are
bounded; exceeding the bound requires manual review rather than assuming that
no prior release exists.

A new release creates its exact tag and a draft. Its notes bind the source
commit and receipt hash. Existing assets are downloaded and hashed, including
when GitHub supplies no digest. A matching partial draft uploads only missing
assets. It verifies the tag, metadata and both complete assets again before
publishing. A completed matching release is a verified no-op on rerun.
Version-specific workflow concurrency queues runs instead of cancelling a run
that could have partially changed remote state.

After an interrupted call, rerun the same reviewed version and commit. A lost
response may already have created the tag, draft or asset; the next run observes
that state before deciding what remains. This follows GitHub's documented
[draft-first release model](https://cli.github.com/manual/gh_release_create).
There are no automatic destructive repairs, force pushes or clobber uploads.

A conflicting tag, changed notes/source/receipt, unexpected or duplicate asset,
wrong asset bytes, incomplete published release or `starter` upload stops with
recovery instructions. Inspect the remote draft and the retained qualified
artifacts. Use a new reviewed version for changed source or artifact bytes.
If a failed draft needs repair, an authorized maintainer must explicitly review
and perform that repair before retrying. Existing versions are never silently
reassigned to different bytes. GitHub documents that an upload failure can leave
[a starter asset](https://docs.github.com/en/rest/releases/assets#upload-a-release-asset).

Archive determinism assumes identical wheel bytes; this is not a claim that
all build backends or future dependency resolutions reproduce identical wheels.
A different rebuild fails comparison rather than overwriting a prior version.
Repository tag protections and GitHub immutable releases should protect released
versions against other writers; configuring those external controls remains an
owner operation. Offline CLI/server-state tests qualify recovery behavior,
not actual GitHub publication, artifact attestation or a live production release.
The [dependency/image advisory gate](security-scanning.md) precedes artifact
building and publication and retains its reports and CycloneDX inventories in
CI, including failed runs. Unresolved blocking findings stop publication.
The public integration code uses the owner-selected Apache-2.0 license.
[Artifact attestation](release-attestations.md) now binds the published archive
and receipt to the reviewed source and workflow; the signed wheel SBOM contains
exact member hashes. The publisher verifies this evidence before every remote
mutation. Live signing/protected-environment qualification, actual publication
and unresolved advisory remediation require separate qualification.
