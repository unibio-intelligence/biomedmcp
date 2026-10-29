"""Execute the runner against a Docker lifecycle model, without service access."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

DOCKER = r"""
import fcntl, json, os, pathlib, sys
p = pathlib.Path(os.environ['FAKE_DOCKER_STATE'])
lock = open(str(p) + '.lock', 'w')
fcntl.flock(lock, fcntl.LOCK_EX)
s = json.loads(p.read_text())
a = sys.argv[1:]
s['calls'].append(a)
def done(code=0):
    p.write_text(json.dumps(s))
    sys.exit(code)
def option(flag, default=None):
    return a[a.index(flag)+1] if flag in a else default
kind = a[0]
action = a[1] if len(a) > 1 else ''
fail = os.environ.get('FAKE_DOCKER_FAIL', '')
if fail == kind + '-' + action:
    print('synthetic cleanup failure', file=sys.stderr)
    done(19)
if kind == 'build':
    s['image'][option('-t')] = {}
    if fail == 'build-' + option('--target'):
        print('synthetic build failure', file=sys.stderr)
        done(23)
elif kind == 'run':
    name = option('--name', 'auto-' + str(len(s['calls'])))
    label = option('--label')
    volume = name + '-anonymous'
    s['container'][name] = {'label': label, 'volume': volume}
    s['volume'][volume] = {}
    if '--rm' in a:
        del s['container'][name]
        del s['volume'][volume]
    if '-d' not in a and fail == 'tests':
        done(23)
    print(name)
elif kind == 'exec':
    print('PONG')
elif action == 'create':
    s[kind][a[-1]] = {'label': option('--label')}
elif action == 'ls':
    if kind == 'image':
        if a[-1] in s['image']: print(a[-1])
    else:
        label = option('--filter').removeprefix('label=')
        for name, data in s[kind].items():
            if data.get('label') == label: print(name)
elif action == 'rm' or kind == 'rm':
    if kind == 'rm': kind, args = 'container', a[1:]
    else: args = a[2:]
    for name in args:
        if name.startswith('-'): continue
        old = s[kind].pop(name, None)
        if kind == 'container' and old and ('--volumes' in args or '-v' in args):
            s['volume'].pop(old.get('volume'), None)
else:
    print('Unsupported fake Docker command: ' + repr(a), file=sys.stderr)
    done(99)
done()
"""


def fixture_runner(tmp_path, runner=None):
    source = runner or ROOT / "scripts/test-local.sh"
    root = tmp_path / "project"
    scripts = root / "scripts"
    scripts.mkdir(parents=True)
    shutil.copyfile(source, scripts / "test-local.sh")
    helper = ROOT / "scripts/docker-test-lifecycle.sh"
    if helper.exists():
        shutil.copyfile(helper, scripts / helper.name)
    # A private caller can supply another runner; its local layout is prepared there.
    binary = tmp_path / "bin"
    binary.mkdir()
    docker = binary / "docker"
    docker.write_text("#!" + sys.executable + "\n" + DOCKER)
    docker.chmod(0o755)
    state = tmp_path / "docker.json"
    state.write_text(
        json.dumps(
            {
                "container": {"active-other": {"label": "other", "volume": "data-other"}},
                "network": {"network-other": {"label": "other"}},
                "volume": {"data-other": {}, "persistent-data": {}},
                "image": {"production:current": {}, "biomedmcp:test": {}, "biomedmcp:candidate": {}},
                "calls": [],
            }
        )
    )
    env = {
        **os.environ,
        "PATH": str(binary) + os.pathsep + os.environ["PATH"],
        "FAKE_DOCKER_STATE": str(state),
    }
    return root, state, env


def execute(root, report, env, extra=()):
    return subprocess.run(
        ["bash", "scripts/test-local.sh", "--report-dir", str(report), *extra],
        cwd=root,
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )


def assert_preserved(state):
    assert set(state["container"]) == {"active-other"}
    assert set(state["network"]) == {"network-other"}
    assert set(state["volume"]) == {"data-other", "persistent-data"}
    assert set(state["image"]) == {"production:current", "biomedmcp:test", "biomedmcp:candidate"}
    assert all("prune" not in call for call in state["calls"])
    assert all("--force" not in call for call in state["calls"] if call[:2] == ["image", "rm"])


@pytest.mark.parametrize("failure", ["", "build-test", "build-runtime", "tests"])
def test_runner_cleans_success_partial_builds_and_test_failures(tmp_path, failure):
    root, state, env = fixture_runner(tmp_path)
    report = tmp_path / "report"
    result = execute(root, report, {**env, "FAKE_DOCKER_FAIL": failure})
    assert result.returncode == (23 if failure else 0), result.stderr
    assert_preserved(json.loads(state.read_text()))
    receipt = json.loads((report / "run.json").read_text())
    assert receipt["cleanup_complete"]
    assert receipt["qualification_exit_code"] == result.returncode


@pytest.mark.parametrize("failure", ["container-rm", "network-rm", "container-ls", "image-rm", "image-ls"])
def test_cleanup_errors_fail_success_and_do_not_stop_other_removals(tmp_path, failure):
    root, state, env = fixture_runner(tmp_path)
    report = tmp_path / "report"
    result = execute(root, report, {**env, "FAKE_DOCKER_FAIL": failure})
    assert result.returncode == 1
    assert "Cleanup" in result.stderr
    assert "synthetic cleanup failure" in (report / "cleanup.log").read_text()
    receipt = json.loads((report / "run.json").read_text())
    assert receipt["cleanup_failures"] > 0 and not receipt["cleanup_complete"]
    assert receipt["qualification_exit_code"] == 0
    current = json.loads(state.read_text())
    assert "active-other" in current["container"] and "persistent-data" in current["volume"]
    assert any(call[:2] == ["image", "ls"] for call in current["calls"])


@pytest.mark.parametrize("hook", ["exit 31", 'kill -TERM "$PPID"; exit 0', 'kill -INT "$PPID"; exit 0'])
def test_post_checks_and_interrupts_stay_inside_cleanup_scope(tmp_path, hook):
    root, state, env = fixture_runner(tmp_path)
    result = execute(root, tmp_path / "report", env, ("--", "bash", "-c", hook))
    assert result.returncode == (143 if "TERM" in hook else 130 if "INT" in hook else 31)
    assert_preserved(json.loads(state.read_text()))


def test_post_check_can_use_unique_images_before_they_are_removed(tmp_path):
    root, state, env = fixture_runner(tmp_path)
    report = tmp_path / "report"
    hook = 'docker image ls --quiet "$UBI_TEST_IMAGE"; docker image ls --quiet "$UBI_RUNTIME_IMAGE"'
    result = execute(root, report, env, ("--", "bash", "-c", hook))
    assert result.returncode == 0, result.stderr
    receipt = json.loads((report / "run.json").read_text())
    assert receipt["test_image"] in result.stdout and receipt["runtime_image"] in result.stdout
    assert_preserved(json.loads(state.read_text()))


def test_concurrent_runs_never_remove_each_others_resources(tmp_path):
    root, state, env = fixture_runner(tmp_path)
    processes = [
        subprocess.Popen(
            ["bash", "scripts/test-local.sh", "--report-dir", str(tmp_path / f"report-{i}")],
            cwd=root,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for i in range(2)
    ]
    for process in processes:
        output, error = process.communicate(timeout=30)
        assert process.returncode == 0, output + error
    receipts = [json.loads((tmp_path / f"report-{i}" / "run.json").read_text()) for i in range(2)]
    assert receipts[0]["test_image"] != receipts[1]["test_image"]
    assert_preserved(json.loads(state.read_text()))


def test_existing_report_directory_is_rejected_before_docker(tmp_path):
    root, state, env = fixture_runner(tmp_path)
    report = tmp_path / "report"
    report.mkdir()
    (report / "sentinel").write_text("keep")
    result = execute(root, report, env)
    assert result.returncode != 0
    assert not json.loads(state.read_text())["calls"]
    assert (report / "sentinel").read_text() == "keep"


def test_receipt_failure_is_visible_after_resources_are_cleaned(tmp_path):
    root, state, env = fixture_runner(tmp_path)
    report = tmp_path / "report"
    env["FAKE_RECEIPT_DIR"] = str(report)
    result = execute(root, report, env, (
        "--", "bash", "-c", 'mkdir "$FAKE_RECEIPT_DIR/run.json"',
    ))
    assert result.returncode == 1
    assert "Cleanup receipt failed" in result.stderr
    assert_preserved(json.loads(state.read_text()))


def test_callback_output_directory_is_not_replaced_by_cleanup_receipts(tmp_path):
    root, state, env = fixture_runner(tmp_path)
    output = tmp_path / "user-output"
    result = execute(root, tmp_path / "report", {**env, "report_dir": str(output)}, (
        "--", "bash", "-c", 'mkdir "$report_dir"; printf preserved > "$report_dir/sentinel"',
    ))
    assert result.returncode == 0, result.stderr
    assert (output / "sentinel").read_text() == "preserved"
    assert_preserved(json.loads(state.read_text()))
