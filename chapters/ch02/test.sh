#!/usr/bin/env bash
# Runs every chapter 2 test suite, each inside its component's own image.
# Tests have their own compose file so they need no Kafka, model, or .env.
# Equivalent by hand: docker compose -f compose.tests.yaml run --build --rm <suite>
set -euo pipefail
cd "$(dirname "$0")"

suites=(
    tests-travel-agency
    tests-itinerary-planner
)

for suite in "${suites[@]}"; do
    echo "== ${suite}"
    docker compose -f compose.tests.yaml run --build --rm "${suite}"
done

echo "All chapter 2 suites passed."
