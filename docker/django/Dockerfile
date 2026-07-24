# syntax=docker/dockerfile:1
#
# 1 image dipakai utk 2 service beda (lihat docker-compose.yml):
#   - django-web    : daphne (ASGI -- HTTP biasa + WebSocket /ws/iclock sekaligus)
#   - django-celery : celery worker (proses face recognition, dst)
# Beda cuma `command:` override di docker-compose.yml, image-nya SAMA
# PERSIS -- tidak perlu 2 Dockerfile terpisah utk 2 hal yang toh butuh
# environment Python yang identik.
#
# PENTING -- kode app SENGAJA TIDAK di-COPY ke image ini (lihat baris
# COPY di bawah, cuma requirements.txt). Kode Django dipasang lewat BIND
# MOUNT di docker-compose.yml (volume `..:/app`), supaya:
#   1. Rebuild image TIDAK PERNAH perlu tiap kali ubah kode Python biasa
#      (cuma perlu kalau requirements.txt berubah -- itu pun cuma re-run
#      dari layer `pip install`, layer apt di atasnya tetap kepakai cache).
#   2. Tetap bisa dev seperti biasa (edit file di host, langsung kepakai
#      di container -- daphne TIDAK auto-reload spt `runserver`, restart
#      container-nya kalau perlu lihat perubahan: `docker compose restart django-web`).
FROM python:3.11-slim AS base

# --- Dependency SISTEM ---
# build-essential + cmake + libopenblas-dev: WAJIB utk compile dlib dari
# source (TIDAK ADA wheel prebuilt di PyPI utk banyak platform -- lihat
# catatan panjang di requirements.txt). Compile ini BISA 10-30+ MENIT,
# WAJAR, bukan hang -- ini SEKALI SAJA per build image (di-cache Docker
# selama requirements.txt tidak berubah).
# freetds-dev: dibutuhkan pymssql (koneksi MSSQL eksternal, app mclock).
# default-libmysqlclient-dev + pkg-config: jaga-jaga kalau nanti pindah
# dari PyMySQL ke mysqlclient (lihat komentar requirements.txt) -- aman
# ditinggal terpasang, tidak dipakai kalau tetap pakai PyMySQL.
# libjpeg62-turbo-dev zlib1g-dev: Pillow, dukungan format gambar lengkap.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    cmake \
    libopenblas-dev \
    liblapack-dev \
    freetds-dev \
    freetds-bin \
    default-libmysqlclient-dev \
    pkg-config \
    libjpeg-dev \
    zlib1g-dev \
    netcat-traditional \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Cuma requirements.txt dulu -- layer pip install ini di-cache SELAMA
# requirements.txt tidak berubah, jadi ganti kode app (yg toh bind-mount,
# bukan lewat COPY) TIDAK PERNAH bikin proses lambat (compile dlib dkk)
# ini terulang percuma.
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir mysqlclient  # driver alternatif performa lebih baik, opsional dipakai

COPY docker/django/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
# Default kalau docker-compose TIDAK override `command:` -- daphne, ASGI,
# port 8000 (HTTP PUSH SDK/API/dashboard + WebSocket /ws/iclock, SEMUA
# lewat 1 port yang sama, ASGI menangani routing protokolnya otomatis).
CMD ["daphne", "-b", "0.0.0.0", "-p", "8000", "config.asgi:application"]
