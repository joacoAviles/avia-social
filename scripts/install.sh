#!/bin/sh
# First installation only. Updating existing data requires docs/UPGRADES.md.
set -eu
cd "$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
if [ -e .env ]; then
    echo 'Existing .env preserved. For updates see docs/UPGRADES.md; for an interrupted first install see docs/ONBOARDING.md.' >&2
    exit 1
fi
if docker compose version >/dev/null 2>&1; then
    compose() { docker compose "$@"; }
elif command -v docker-compose >/dev/null 2>&1; then
    compose() { docker-compose "$@"; }
else
    echo 'Docker Compose v2 is required.' >&2
    exit 1
fi
docker info >/dev/null
# Run setup with the invoking user's ownership. No host Python dependency.
docker run --rm --user "$(id -u):$(id -g)" -v "$PWD:/setup" -w /setup \
    python:3.12.12-slim-bookworm python scripts/setup.py
compose up -d --build --wait app worker
compose exec -T app python manage.py avia_setup_code
echo 'Open http://localhost:8088/ and finish the guided setup. Keep this code private.'
