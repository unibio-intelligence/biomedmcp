#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/docker-test-lifecycle.sh
ubi_test_init biomedmcp "$@"
docker_resources_started=true
docker build --label "$UBI_TEST_RUN_LABEL" --target test -t "$UBI_TEST_IMAGE" .
docker run --label "$UBI_TEST_RUN_LABEL" --rm --network none "$UBI_TEST_IMAGE" uv run --frozen --no-sync ruff check src/biomedmcp scripts
docker run --label "$UBI_TEST_RUN_LABEL" --rm --network none "$UBI_TEST_IMAGE" uv run --frozen --no-sync python scripts/check-governance.py
docker network create --label "$UBI_TEST_RUN_LABEL" --internal "$run_id" >/dev/null
docker run --label "$UBI_TEST_RUN_LABEL" -d --name "$run_id-redis" --network "$run_id" --network-alias redis \
  redis@sha256:3811787313eba226a2ef38658c6ccb91cd5e110edc89c37767de373120a0e5a0 >/dev/null
redis_ready=0
for attempt in {1..30}; do
  if docker exec "$run_id-redis" redis-cli ping | grep -q PONG; then redis_ready=1; break; fi
  sleep 1
done
[[ "$redis_ready" == 1 ]] || { echo "Required Redis qualification dependency did not become ready" >&2; exit 1; }
docker run --label "$UBI_TEST_RUN_LABEL" --rm --name "$run_id-tests" --network "$run_id" -e UBI_PROFILE=local \
  -e UBI_TEST_REDIS_URL=redis://redis:6379/15 \
  "$UBI_TEST_IMAGE" uv run --frozen --no-sync pytest tests -q -m 'not redis'
docker run --label "$UBI_TEST_RUN_LABEL" --rm --name "$run_id-tests" --network "$run_id" -e UBI_PROFILE=local \
  -e UBI_TEST_REDIS_URL=redis://redis:6379/15 \
  "$UBI_TEST_IMAGE" uv run --frozen --no-sync pytest tests/redis -q -m redis
docker build --label "$UBI_TEST_RUN_LABEL" --target runtime -t "$UBI_RUNTIME_IMAGE" .
ubi_test_after
