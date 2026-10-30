#!/bin/sh
set -eu
# Use only a disposable development installation; pytest creates/drops a test DB.
docker compose run --rm --no-deps -e DJANGO_SETTINGS_MODULE=config.settings.test -e DB_HOST=postgres -e DB_USER=avia app sh -c 'export DB_PASSWORD="$POSTGRES_PASSWORD"; pytest apps/avia_brand apps/members apps/composer apps/calendar apps/approvals apps/api apps/publisher tests/test_media_routing.py'
