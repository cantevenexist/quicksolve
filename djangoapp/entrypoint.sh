#!/bin/sh

if [ "$DATABASE" = "postgres" ]
then
    echo "Waiting for postgres..."

    while ! nc -z $SQL_HOST $SQL_PORT; do
      sleep 0.1
    done

    echo "PostgreSQL started"
fi

# Применение миграций
python manage.py makemigrations
python manage.py migrate

# Очищение таблиц базы данных Postgre
# python manage.py flush --no-input

# Создание аккаунта суперпользователя
sh init_superadmin.sh

exec "$@"