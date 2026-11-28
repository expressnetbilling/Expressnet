#!/bin/sh
# Run the web/API service. The dedicated Railway RADIUS service runs the
# Django AAA listener independently.
set -eu

python manage.py collectstatic --noinput --settings=billing_saas_django.Settings.production
python manage.py migrate --settings=billing_saas_django.Settings.production
python manage.py ensure_superuser --settings=billing_saas_django.Settings.production

exec daphne --bind 0.0.0.0 --port "${PORT:-8000}" billing_saas_django.asgi:application
