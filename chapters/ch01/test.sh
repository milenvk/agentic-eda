#!/usr/bin/env bash
# Runs every chapter 1 test suite, each inside its component's own image.
# Tests have their own compose file so they need no Kafka, model, or .env.
# Equivalent by hand: docker compose -f compose.tests.yaml run --build --rm <suite>
set -euo pipefail
cd "$(dirname "$0")"

suites=(
    tests-travel-agency
    tests-itinerary-planner
    tests-audit-consumer
    tests-front-desk
    tests-chapter
)

for suite in "${suites[@]}"; do
    echo "== ${suite}"
    docker compose -f compose.tests.yaml run --build --rm "${suite}"
done

echo "All chapter 1 suites passed."
