#!/usr/bin/env bash
# Runs every chapter 3 test suite, each inside its component's own image.
# Tests have their own compose file so they need no Kafka, model, or .env.
# Equivalent by hand: docker compose -f compose.tests.yaml run --build --rm <suite>
set -euo pipefail
cd "$(dirname "$0")"

suites=(
    tests-agentic-eda
    tests-agentic-eda-postgres
    tests-travel-agency
    tests-supplier-world
    tests-booking-agent
    tests-itinerary-planner
    tests-airline-reservation-system
    tests-hotel-reservation-system
    tests-audit-consumer
    tests-chapter
)

# One suite starts a database; stop it however the run ends.
trap 'docker compose -f compose.tests.yaml down --remove-orphans' EXIT

for suite in "${suites[@]}"; do
    echo "== ${suite}"
    docker compose -f compose.tests.yaml run --build --rm "${suite}"
done

echo "All chapter 3 suites passed."
