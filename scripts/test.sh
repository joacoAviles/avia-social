#!/bin/sh
set -eu
# Disposable development installation only: pytest creates/drops a test DB.
# Root is limited to this one-shot test container so media fixtures can be created;
# app and worker continue running as UID 10001.
if docker compose version >/dev/null 2>&1; then
    compose() { docker compose "$@"; }
elif command -v docker-compose >/dev/null 2>&1; then
    compose() { docker-compose "$@"; }
else
    echo 'Docker Compose v2 is required.' >&2
    exit 1
fi
compose run --rm --no-deps --user 0 -e DJANGO_SETTINGS_MODULE=config.settings.test -e DB_HOST=postgres -e DB_USER=avia app sh -c 'export DB_PASSWORD="$POSTGRES_PASSWORD"; pytest apps/avia_brand apps/accounts apps/common/tests/test_review_banner.py tests/test_oauth_pkce.py apps/members apps/composer apps/calendar apps/approvals apps/api apps/publisher tests/test_media_routing.py'
