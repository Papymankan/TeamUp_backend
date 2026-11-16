#!/usr/bin/env bash
set -euo pipefail

if [[ -n "${DJANGO_SECRET_KEY:-}" ]]; then
    python manage.py collectstatic --noinput
else
    DJANGO_SECRET_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(64))')" \
        python manage.py collectstatic --noinput
fi
