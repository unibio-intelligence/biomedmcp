#!/usr/bin/env bash
# Shared by qualification runners; resources belong to one invocation only.
ubi_test_init() {
  local repository="$1"
  shift
  cleanup_report_dir=""
  while (($#)); do
    case "$1" in
      --report-dir) cleanup_report_dir="${2:?--report-dir requires a new directory}"; shift 2 ;;
      --) shift; break ;;
      *) echo "Usage: $0 [--report-dir NEW_DIRECTORY] [-- COMMAND [ARG...]]" >&2; exit 2 ;;
    esac
  done
  post_test_count=$#
  post_test_command=("$@")
  run_id="$(python3 -c 'import uuid; print(uuid.uuid4().hex)')"
  if test -n "$cleanup_report_dir"; then
    mkdir "$cleanup_report_dir" || return 1
  else
    cleanup_report_dir=$(mktemp -d "${TMPDIR:-/tmp}/ubi-docker-test.XXXXXXXX")
  fi
  cleanup_report_dir=$(cd "$cleanup_report_dir" && pwd)
  export UBI_TEST_RUN_LABEL="com.unibio.docker-test.run=$run_id"
  export UBI_TEST_IMAGE="$repository:test-$run_id"
  export UBI_RUNTIME_IMAGE="$repository:runtime-$run_id"
  cleanup_failures=0
  docker_resources_started=false
  trap ubi_test_cleanup EXIT
  trap 'exit 130' INT
  trap 'exit 143' TERM
  echo "Docker qualification receipts: $cleanup_report_dir"
}

ubi_cleanup_command() {
  local output
  if output=$("$@" 2>&1); then
    printf '%s\n' "$output" >> "$cleanup_report_dir/cleanup.log" || cleanup_failures=$((cleanup_failures + 1))
  else
    cleanup_failures=$((cleanup_failures + 1))
    printf 'Cleanup failed: %s\n%s\n' "$*" "$output" >&2
    printf 'Cleanup failed: %s\n%s\n' "$*" "$output" >> "$cleanup_report_dir/cleanup.log"
  fi
  return 0
}

ubi_cleanup_owned() {
  local kind="$1" resources resource
  shift
  if resources=$(docker "$kind" ls --quiet --filter "label=$UBI_TEST_RUN_LABEL" "$@" 2>> "$cleanup_report_dir/cleanup.log"); then
    for resource in $resources; do
      if test "$kind" = container; then
        ubi_cleanup_command docker container rm --force --volumes "$resource"
      else
        ubi_cleanup_command docker "$kind" rm "$resource"
      fi
    done
  else
    cleanup_failures=$((cleanup_failures + 1))
    echo "Cleanup failed: cannot list owned $kind resources; see $cleanup_report_dir/cleanup.log" >&2
  fi
}

ubi_test_cleanup() {
  local qualification_result=$? result image_tag image_id
  trap - EXIT
  trap '' INT TERM
  set +e
  if $docker_resources_started; then
    ubi_cleanup_owned container --all
    ubi_cleanup_owned network
    for image_tag in "$UBI_TEST_IMAGE" "$UBI_RUNTIME_IMAGE"; do
      if image_id=$(docker image ls --quiet "$image_tag" 2>> "$cleanup_report_dir/cleanup.log"); then
        if test -n "$image_id"; then
          # No force: preserve an image still needed by another container.
          ubi_cleanup_command docker image rm "$image_tag"
        fi
      else
        cleanup_failures=$((cleanup_failures + 1))
        echo "Cleanup failed: cannot inspect $image_tag; see $cleanup_report_dir/cleanup.log" >&2
      fi
    done
  fi
  result=$qualification_result
  if test "$cleanup_failures" -ne 0; then
    echo "Cleanup incomplete ($cleanup_failures errors); see $cleanup_report_dir/cleanup.log" >&2
    if test "$result" -eq 0; then result=1; fi
  fi
  if ! python3 - "$cleanup_report_dir/run.json" "$run_id" "$UBI_TEST_IMAGE" "$UBI_RUNTIME_IMAGE" "$qualification_result" "$cleanup_failures" "$result" <<'PY'
import json, pathlib, sys
path, run_id, test, runtime, qualification, failures, result = sys.argv[1:]
pathlib.Path(path).write_text(json.dumps({
    "run_id": run_id, "test_image": test, "runtime_image": runtime,
    "qualification_exit_code": int(qualification), "exit_code": int(result),
    "cleanup_failures": int(failures), "cleanup_complete": int(failures) == 0,
}, indent=2) + "\n")
PY
  then
    echo "Cleanup receipt failed: cannot write $cleanup_report_dir/run.json" >&2
    if test "$result" -eq 0; then result=1; fi
  fi
  exit "$result"
}

ubi_test_after() {
  if test "$post_test_count" -gt 0; then
    "${post_test_command[@]}"
  fi
}
