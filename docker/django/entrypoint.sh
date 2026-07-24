#!/bin/sh
set -e

# --- Tunggu MySQL & Redis siap ---
# netcat cek port TERBUKA -- BUKAN jaminan MySQL SIAP terima query (bisa
# saja port sudah listen tapi proses inisialisasi internal MySQL belum
# selesai), tapi cukup utk kasus docker-compose biasa (healthcheck
# `depends_on: condition: service_healthy` di docker-compose.yml JUGA
# jaga ini dari sisi lain, dua lapis).
echo "Menunggu MySQL di ${DB_HOST:-mysql}:${DB_PORT:-3306}..."
until nc -z "${DB_HOST:-mysql}" "${DB_PORT:-3306}"; do
  sleep 1
done
echo "MySQL siap."

echo "Menunggu Redis di ${REDIS_HOST:-redis}:${REDIS_PORT:-6379}..."
until nc -z "${REDIS_HOST:-redis}" "${REDIS_PORT:-6379}"; do
  sleep 1
done
echo "Redis siap."

# Migrasi & collectstatic CUMA dijalankan service yang di-set
# RUN_MIGRATIONS=true di docker-compose.yml (django-web) -- HINDARI 2
# proses (web & celery) migrate BERSAMAAN saat container start bareng,
# MySQL tidak sekuat PostgreSQL soal locking DDL concurrent.
if [ "$RUN_MIGRATIONS" = "true" ]; then
  echo "Menjalankan migrasi..."
  python manage.py migrate --noinput
  echo "Mengumpulkan static files..."
  python manage.py collectstatic --noinput --clear
fi

exec "$@"
