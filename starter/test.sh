#!/usr/bin/env bash
# Runs the starter's tests inside its own image, with no Kafka, no model, and no .env.
# Equivalent by hand: docker compose -f compose.tests.yaml run --build --rm tests
set -euo pipefail
cd "$(dirname "$0")"

docker compose -f compose.tests.yaml run --build --rm tests

echo "The starter's suite passed."
