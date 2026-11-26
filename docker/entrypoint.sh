#!/bin/sh
set -eu

python manage.py migrate --noinput
python manage.py collectstatic --noinput --clear

if [ "${SEED_DEMO_DATA:-0}" = "1" ]; then
    python manage.py seed_benchmark --demo
fi

exec "$@"
