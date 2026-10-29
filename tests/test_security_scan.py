"""Scanner evidence must be complete and fail closed without live advisory calls."""

import copy
import hashlib
import importlib.util
import io
import json
import subprocess
import tarfile
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 9, 16, tzinfo=UTC)
PURLS = ["pkg:pypi/multidict@6.9.1", "pkg:pypi/pyjwt@2.15.0"]


@pytest.fixture
def scanner():
    spec = importlib.util.spec_from_file_location("security_scan", ROOT / "scripts/scan-security.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def evidence(scanner):
    # Selected v0.120.1 report fields observed in the real discovery scan.
    # This bounded fixture is not a live advisory or runtime qualification receipt.
    report = {
        "matches": [],
        "source": {"type": "sbom-file", "target": "/inputs/locked.purls"},
        "descriptor": {
            "name": "grype",
            "version": scanner.VERSION,
            "configuration": {
                "ignore": [],
                "exclude": [],
                "only-fixed": False,
                "only-notfixed": False,
                "externalSources": {"enable": False},
                "db": {
                    "validate-by-hash-on-start": True,
                    "validate-age": True,
                    "auto-update": True,
                    "require-update-check": True,
                },
            },
            "db": {
                "status": {
                    "valid": True,
                    "built": "2026-10-09T06:32:32Z",
                    "from": "https://grype.anchore.io/databases/v6/example.tar.zst?checksum=sha256%3A"
                    + "a" * 64,
                },
                "providers": {"github": {}, "debian": {}},
            },
        },
    }
    bom = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.7",
        "components": [
            {
                "bom-ref": purl,
                "purl": purl,
                "name": purl.split("/")[-1].split("@")[0],
                "version": purl.split("@")[1],
            }
            for purl in PURLS
        ],
    }
    return report, bom


def finding(severity):
    return {
        "artifact": {"name": "pyjwt", "version": "2.15.0", "type": "python"},
        "vulnerability": {
            "id": "SYNTHETIC-ADVISORY",
            "namespace": "github:language:python",
            "severity": severity,
            "fix": {"state": "not-fixed", "versions": []},
        },
    }


def test_complete_clean_lock_inventory_is_accepted(scanner, evidence):
    report, bom = evidence
    assert scanner.validate(report, bom, target="dependencies", expected=PURLS, now=NOW)["result"] == "passed"


@pytest.mark.parametrize("severity", ["Negligible", "Low", "Medium", "High", "Critical", "Unknown"])
def test_any_dependency_advisory_blocks_including_unfixed(scanner, evidence, severity):
    report, bom = evidence
    report["matches"] = [finding(severity)]
    assert scanner.validate(report, bom, target="dependencies", expected=PURLS, now=NOW)["result"] == "failed"


@pytest.mark.parametrize(
    "mutation",
    [
        "version",
        "valid",
        "age",
        "origin",
        "hash",
        "feed",
        "ignore",
        "filter",
        "exclude",
        "external",
        "inventory",
        "duplicate",
        "target",
        "severity",
    ],
)
def test_incomplete_or_untrusted_lock_evidence_is_rejected(scanner, evidence, mutation):
    report, bom = evidence
    descriptor = report["descriptor"]
    configuration = descriptor["configuration"]
    status = descriptor["db"]["status"]
    if mutation == "version":
        descriptor["version"] = "unknown"
    elif mutation == "valid":
        status["valid"] = False
    elif mutation == "age":
        status["built"] = "2026-01-01T00:00:00Z"
    elif mutation == "origin":
        status["from"] = status["from"].replace("grype.anchore.io", "untrusted.invalid")
    elif mutation == "hash":
        configuration["db"]["validate-by-hash-on-start"] = False
    elif mutation == "feed":
        descriptor["db"]["providers"].pop("github")
    elif mutation == "ignore":
        configuration["ignore"] = [{"vulnerability": "SYNTHETIC-ADVISORY"}]
    elif mutation == "filter":
        configuration["only-fixed"] = True
    elif mutation == "exclude":
        configuration["exclude"] = ["**"]
    elif mutation == "external":
        configuration["externalSources"]["enable"] = True
    elif mutation == "inventory":
        bom["components"].pop()
    elif mutation == "duplicate":
        bom["components"].append(copy.deepcopy(bom["components"][0]))
    elif mutation == "target":
        report["source"]["target"] = "/inputs/not-the-lock.purls"
    else:
        report["matches"] = [finding("unrecognized")]
    with pytest.raises(ValueError):
        scanner.validate(report, bom, target="dependencies", expected=PURLS, now=NOW)


@pytest.mark.parametrize(
    "severity,expected_result",
    [("Medium", "passed"), ("High", "failed"), ("Critical", "failed"), ("Unknown", "failed")],
)
def test_runtime_severity_gate_and_image_identity(scanner, evidence, severity, expected_result):
    report, bom = evidence
    report["matches"] = [finding(severity)]
    report["source"] = {"type": "image", "target": {"imageID": "sha256:" + "b" * 64}}
    report["descriptor"]["configuration"]["db"].update({"auto-update": False, "require-update-check": False})
    expected = {"image_config_digest": "sha256:" + "b" * 64, "installed": [("pyjwt", "2.15.0")]}
    assert (
        scanner.validate(report, bom, target="runtime", expected=expected, now=NOW)["result"]
        == expected_result
    )
    expected["image_config_digest"] = "sha256:" + "c" * 64
    with pytest.raises(ValueError, match="image identity"):
        scanner.validate(report, bom, target="runtime", expected=expected, now=NOW)


def test_timeout_cleans_only_the_scanner_container_without_daemon_mount(scanner, tmp_path, monkeypatch):
    calls = []

    def run(arguments, **kwargs):
        calls.append(arguments)
        if arguments[:2] == ["docker", "run"]:
            raise subprocess.TimeoutExpired(arguments, 600)
        return subprocess.CompletedProcess(arguments, 0)

    monkeypatch.setattr(scanner, "run", run)
    monkeypatch.setattr(scanner, "os", SimpleNamespace(getuid=lambda: 1337, getgid=lambda: 2448))
    with pytest.raises(subprocess.TimeoutExpired):
        scanner.docker_scan(
            tmp_path, tmp_path, tmp_path, target="docker-archive:/inputs/runtime.tar", online=False
        )
    command = calls[0]
    assert "/var/run/docker.sock" not in " ".join(command)
    assert command[command.index("--user") + 1] == "1337:2448"
    assert "--read-only" in command and "none" in command and "no-new-privileges" in command
    assert calls[-1] == ["docker", "rm", "-f", command[command.index("--name") + 1]]


def test_existing_output_cannot_be_reused_or_overwritten(scanner, tmp_path):
    output = tmp_path / "existing"
    output.mkdir()
    marker = output / "security-receipt.json"
    marker.write_text("previous receipt")
    with pytest.raises(ValueError, match="fresh output"):
        scanner.scan(ROOT, output, "biomedmcp:candidate")
    assert marker.read_text() == "previous receipt"


def test_lock_registry_nodes_are_complete_and_unknown_sources_fail(scanner, tmp_path):
    purls, local = scanner.lock_nodes(ROOT / "uv.lock")
    assert len(purls) == 107 and [row["name"] for row in local] == ["biomedmcp"]
    assert {"pkg:pypi/beartype@0.22.9", "pkg:pypi/beartype@0.23.1"} <= set(purls)
    assert "pkg:pypi/mmcif-pdbx@2.1.0" in purls
    assert "pkg:pypi/pyjwt@2.15.0" in purls and "pkg:pypi/multidict@6.9.1" in purls
    target = tmp_path / "uv.lock"
    target.write_text(
        (ROOT / "uv.lock").read_text().replace("https://pypi.org/simple", "https://private.invalid/simple")
    )
    with pytest.raises(ValueError, match="registry"):
        scanner.lock_nodes(target)


def test_public_ci_and_release_fail_on_security_gate_and_keep_evidence():
    for name in ["ci.yml", "release.yml"]:
        workflow = yaml.safe_load((ROOT / ".github/workflows" / name).read_text())
        job = next(iter(workflow["jobs"].values()))
        steps = job["steps"]
        scan = next(step for step in steps if "scan-security.py" in step.get("run", ""))
        assert not scan.get("continue-on-error") and "|| true" not in scan["run"]
        upload = next(
            step for step in steps if step.get("with", {}).get("name") == "public-security-evidence"
        )
        assert "upload-artifact@" in upload["uses"]
        assert upload["if"] == "always()" and upload["with"]["if-no-files-found"] == "error"
        assert len(upload["uses"].split("@")[1]) == 40
        if name == "release.yml":
            publish = next(step for step in steps if " publish " in step.get("run", ""))
            assert steps.index(scan) < steps.index(publish)
            assert "environment" in job and "github.repository ==" in job["if"]


@pytest.mark.parametrize("index_identity", [False, True])
def test_archive_binds_legacy_config_and_oci_index_to_the_config_digest(scanner, tmp_path, index_identity):
    config = json.dumps({"architecture": "amd64", "os": "linux"}).encode()
    config_digest = hashlib.sha256(config).hexdigest()
    leaf = json.dumps({"config": {"digest": "sha256:" + config_digest}}).encode()
    leaf_digest = hashlib.sha256(leaf).hexdigest()
    index = json.dumps({"manifests": [{"digest": "sha256:" + leaf_digest}]}).encode()
    index_digest = hashlib.sha256(index).hexdigest()
    entries = {
        "manifest.json": json.dumps([{"Config": "blobs/sha256/" + config_digest}]).encode(),
        "blobs/sha256/" + config_digest: config,
        "blobs/sha256/" + leaf_digest: leaf,
        "blobs/sha256/" + index_digest: index,
    }
    archive = tmp_path / "image.tar"
    with tarfile.open(archive, "w") as output:
        for path, data in entries.items():
            member = tarfile.TarInfo(path)
            member.size = len(data)
            output.addfile(member, io.BytesIO(data))
    image_id = "sha256:" + (index_digest if index_identity else config_digest)
    result = scanner.archive_identity(archive, image_id)
    assert result["image_config_digest"] == "sha256:" + config_digest
    with pytest.raises((KeyError, ValueError)):
        scanner.archive_identity(archive, "sha256:" + "f" * 64)


@pytest.mark.parametrize("selected_present", [True, False])
def test_archive_index_can_reference_unpulled_platforms_but_must_bind_the_saved_config(
    scanner, tmp_path, selected_present
):
    config = json.dumps({"architecture": "arm64", "os": "linux"}).encode()
    config_digest = hashlib.sha256(config).hexdigest()
    selected = json.dumps({"config": {"digest": "sha256:" + config_digest}}).encode()
    selected_digest = hashlib.sha256(selected).hexdigest()
    index = json.dumps(
        {"manifests": [{"digest": "sha256:" + "1" * 64}, {"digest": "sha256:" + selected_digest}]}
    ).encode()
    entries = {
        "manifest.json": json.dumps([{"Config": "blobs/sha256/" + config_digest}]).encode(),
        "blobs/sha256/" + config_digest: config,
        "blobs/sha256/" + hashlib.sha256(index).hexdigest(): index,
    }
    if selected_present:
        entries["blobs/sha256/" + selected_digest] = selected
    archive = tmp_path / "selected-platform.tar"
    with tarfile.open(archive, "w") as output:
        for path, data in entries.items():
            member = tarfile.TarInfo(path)
            member.size = len(data)
            output.addfile(member, io.BytesIO(data))
    identity = "sha256:" + hashlib.sha256(index).hexdigest()
    if selected_present:
        assert scanner.archive_identity(archive, identity)["image_config_digest"] == "sha256:" + config_digest
    else:
        with pytest.raises(ValueError, match="does not match"):
            scanner.archive_identity(archive, identity)


@pytest.mark.parametrize('severity,blocked', [('Negligible',False),('Low',False),('Medium',False),('High',True),('Critical',True),('Unknown',True)])
def test_observed_alpine_cpe_empty_fix_preserves_advisory_and_severity_gate(scanner,evidence,severity,blocked):
    report,bom=evidence;match=finding(severity)
    match['artifact'].update(name='busybox',version='1.37.0-r30',type='apk',purl='pkg:apk/alpine/busybox@1.37.0-r30')
    match['vulnerability'].update(namespace='nvd:cpe',fix={'state':'','versions':[]})
    report.update(matches=[match],distro={'name':'alpine','version':'3.23.6'},source={'type':'image','target':{'imageID':'sha256:'+'b'*64}})
    report['descriptor']['configuration']['db'].update({'auto-update':False,'require-update-check':False})
    value=scanner.validate(report,bom,target='runtime',expected={'image_config_digest':'sha256:'+'b'*64,'installed':[('pyjwt','2.15.0')]},now=NOW)
    assert value['result']==('failed' if blocked else 'passed')
    row=value['findings'][0];assert row['blocking']==blocked and row['fix_state']=='unknown' and row['reported_fix_state']==''
    assert row['id']=='SYNTHETIC-ADVISORY' and row['package']=='busybox'


@pytest.mark.parametrize('change',['namespace','artifact','purl','distro','versions','state'])
def test_empty_fix_outside_observed_alpine_cpe_contract_is_refused(scanner,evidence,change):
    report,bom=evidence;match=finding('High')
    match['artifact'].update(type='apk',purl='pkg:apk/alpine/busybox@1.37.0-r30')
    match['vulnerability'].update(namespace='nvd:cpe',fix={'state':'','versions':[]})
    report.update(matches=[match],distro={'name':'alpine'})
    if change=='namespace':match['vulnerability']['namespace']='github:language:python'
    elif change=='artifact':match['artifact']['type']='python'
    elif change=='purl':match['artifact']['purl']='pkg:apk/other/package@1'
    elif change=='distro':report['distro']['name']='debian'
    elif change=='versions':match['vulnerability']['fix']['versions']=['patched']
    elif change=='state':match['vulnerability']['fix']['state']='safe'
    with pytest.raises(ValueError,match='Invalid fix information'):
        scanner.validate(report,bom,target='dependencies',expected=PURLS,now=NOW)
