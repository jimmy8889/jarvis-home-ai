#!/usr/bin/env bash
set -euo pipefail

fixture_suffix="$$"
fixture_network="pilot-teslamate-fixture-${fixture_suffix}"
fixture_database="pilot-teslamate-postgres-${fixture_suffix}"
fixture_app="pilot-teslamate-app-${fixture_suffix}"
fixture_python="${PILOT_TESLAMATE_TEST_PYTHON:-python3}"

cleanup() {
  docker rm -f "$fixture_app" "$fixture_database" >/dev/null 2>&1 || true
  docker network rm "$fixture_network" >/dev/null 2>&1 || true
}
trap cleanup EXIT

docker network create "$fixture_network" >/dev/null
docker run -d --rm \
  --name "$fixture_database" \
  --network "$fixture_network" \
  --network-alias database \
  -e POSTGRES_DB=teslamate \
  -e POSTGRES_USER=postgres \
  -e POSTGRES_PASSWORD=fixture-postgres \
  -p 127.0.0.1::5432 \
  postgres:17-alpine >/dev/null

for attempt in {1..60}; do
  if docker exec "$fixture_database" pg_isready -U postgres -d teslamate >/dev/null 2>&1; then
    break
  fi
  if [[ "$attempt" == 60 ]]; then
    docker logs "$fixture_database"
    exit 1
  fi
  sleep 1
done

docker run -d --rm \
  --name "$fixture_app" \
  --network "$fixture_network" \
  -e DATABASE_HOST=database \
  -e DATABASE_NAME=teslamate \
  -e DATABASE_USER=postgres \
  -e DATABASE_PASS=fixture-postgres \
  -e MQTT_HOST=127.0.0.1 \
  teslamate/teslamate:4.0.1 >/dev/null

for attempt in {1..120}; do
  if [[ "$(docker exec "$fixture_database" psql -U postgres -d teslamate -Atqc \
    "SELECT to_regclass('public.charging_processes') IS NOT NULL" 2>/dev/null)" == "t" ]]; then
    break
  fi
  if [[ "$attempt" == 120 ]]; then
    docker logs "$fixture_app"
    exit 1
  fi
  sleep 1
done

fixture_port="$(docker port "$fixture_database" 5432/tcp | sed 's/.*://')"
export TESLAMATE_FIXTURE_ADMIN_URL="postgresql://postgres:fixture-postgres@127.0.0.1:${fixture_port}/teslamate"
"$fixture_python" -m unittest discover -s apps/teslamate-adapter/tests/integration -p 'test_*.py' -v
