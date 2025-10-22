#!/bin/sh

if [ -z "$DJANGO_SUPERADMIN_USERNAME" ] || [ -z "$DJANGO_SUPERADMIN_EMAIL" ] || [ -z "$DJANGO_SUPERADMIN_PASSWORD" ]; then
  echo "Environment variables DJANGO_SUPERADMIN_USERNAME, DJANGO_SUPERADMIN_EMAIL and DJANGO_SUPERADMIN_PASSWORD must be set."
  exit 1
fi
python manage.py shell -c "
from django.contrib.auth import get_user_model;
User = get_user_model();
if not User.objects.filter(username='$DJANGO_SUPERADMIN_USERNAME').exists():
    User.objects.create_superuser('$DJANGO_SUPERADMIN_USERNAME', '$DJANGO_SUPERADMIN_EMAIL', '$DJANGO_SUPERADMIN_PASSWORD');
    print('Superadmin was created.');
else:
    print('Superadmin already exists.');
"