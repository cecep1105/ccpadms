# Docker Compose — Test Production (CCPADMS)

Setup ini utk **testing mirip-production** di mesin lokal/staging, BUKAN
production sungguhan yang menghadap internet langsung (belum ada SSL,
belum ada backup otomatis, dst -- itu topik terpisah kalau sudah siap ke
sana).

## Prasyarat lokasi folder

Compose ini **mengasumsikan** kedua repo di-clone SEJAJAR:

```
some-folder/
  ccpadms/          <- repo Django (compose file ada di ccpadms/docker/)
    docker/
      docker-compose.yml
      django/
      nginx/
      env.docker.example
  nextadms/         <- repo Next.js
```

Kalau lokasi Anda beda, sesuaikan `context:` di service `nextjs` pada
`docker-compose.yml`.

## Arsitektur

```
                    ┌─────────────┐
   Browser  ──────► │    nginx    │  (port 80 -- SATU-SATUNYA pintu masuk)
                    └──────┬──────┘
                           │
              ┌────────────┼────────────────┐
              │            │                │
         /api /admin   /ws (WebSocket)      / (sisanya)
              │            │                │
              ▼            ▼                ▼
        ┌──────────────────────┐      ┌──────────┐
        │   django-web         │      │  nextjs  │
        │   (daphne, ASGI)     │      └──────────┘
        └──────────┬───────────┘
                    │
        ┌───────────┼───────────┐
        ▼           ▼           ▼
     mysql       redis     django-celery
                              (worker face
                               recognition)
```

**PENTING -- keputusan desain**: dengan nginx di depan begini, saya
satukan Next.js & Django jadi **1 origin** (`http://localhost`), BUKAN 2
origin terpisah seperti setup dev biasa (`localhost:3000` vs
`localhost:8000`). Ini artinya CORS antar keduanya JADI TIDAK RELEVAN LAGI
utk trafik via nginx (sudah same-origin) -- tapi app tetap PUNYA CORS
lengkap kalau nanti Anda mau balik ke 2-origin (mis. Next.js di-deploy
terpisah/CDN).

Kalau mau setup 2-origin lagi nanti, cukup ubah 4 variabel di `.env`:
`NEXT_PUBLIC_API_BASE_URL`, `NEXT_PUBLIC_WS_BASE_URL`, `NEXTAUTH_URL`,
`CORS_ALLOWED_ORIGINS` -- SEMUA harus konsisten sekaligus.

## 1 image Django, 2 service (`django-web` & `django-celery`)

Sesuai permintaan -- SATU Dockerfile/image dipakai keduanya, cuma beda
`command:`. **Kode app di-BIND MOUNT** (`volumes: - ..:/app`), BUKAN
di-`COPY` ke image -- jadi:
- Edit file Python di host **langsung kepakai** di container (mode
  development tetap jalan).
- **TIDAK PERLU rebuild image** tiap ganti kode -- image cuma perlu
  di-rebuild kalau `requirements.txt` berubah (dependency baru/versi
  beda).
- daphne **TIDAK auto-reload** spt `manage.py runserver` -- restart
  manual kalau perlu lihat perubahan langsung:
  ```bash
  docker compose restart django-web django-celery
  ```

## Cara pakai

```bash
cd ccpadms/docker
cp env.docker.example .env
# edit .env -- ISI MINIMAL: SECRET_KEY, NEXTAUTH_SECRET, DB_PASSWORD

docker compose build   # ⚠️ PERTAMA KALI bisa 15-30+ MENIT -- dlib (face
                        # recognition) HARUS di-compile dari source, TIDAK
                        # ADA wheel prebuilt. WAJAR, bukan hang. Build
                        # berikutnya jauh lebih cepat (di-cache) SELAMA
                        # requirements.txt tidak berubah.

docker compose up -d

# Buat superuser admin pertama:
docker compose exec django-web python manage.py createsuperuser
```

Buka `http://localhost` -- itu Next.js (dashboard/portal/mobile). API di
`http://localhost/api/v1/...`, admin Django di `http://localhost/admin/`.

## Perintah berguna

```bash
docker compose logs -f django-web      # log daphne (HTTP + WebSocket)
docker compose logs -f django-celery   # log worker (proses face recognition dst)
docker compose logs -f nginx

docker compose exec django-web python manage.py shell
docker compose exec django-web python manage.py migrate   # manual kalau perlu
docker compose exec mysql mysql -uroot -p                 # masuk MySQL langsung

docker compose down                    # stop semua (data MySQL/Redis TETAP ada, named volume)
docker compose down -v                 # stop + HAPUS SEMUA DATA (mysql_data, redis_data) -- hati-hati
```

## Device fingerprint fisik & mobile app

Device fisik (protokol PUSH SDK) & app mobile karyawan perlu diarahkan ke
`http://<ip-mesin-ini>/iclock/...` (BUKAN `localhost` -- device/HP fisik
beda mesin dari yang menjalankan Docker). Sesuaikan juga
`NEXT_PUBLIC_API_BASE_URL`/`NEXT_PUBLIC_WS_BASE_URL`/`NEXTAUTH_URL`/
`ALLOWED_HOSTS`/`CSRF_TRUSTED_ORIGINS`/`CORS_ALLOWED_ORIGINS` di `.env`
kalau mau diakses dari device/HP lain di jaringan yang sama (ganti
`localhost` jadi IP mesin Docker-nya, SEMUA variabel itu harus konsisten).

## ✅ Sudah divalidasi

- **Syntax YAML** `docker-compose.yml` — valid (`python3 -c "import yaml..."`)
- **Anchor/alias** environment bersama `django-web`↔`django-celery` — ter-resolve benar, `RUN_MIGRATIONS` override per-service jalan sesuai desain
- **Syntax `nginx.conf`** — valid (`nginx -t`, diuji dgn hostname pengganti krn hostname docker-internal tidak bisa di-resolve di luar compose network)
- **Syntax `entrypoint.sh`** — valid (`sh -n`)
- **Nama paket apt** di Dockerfile Django — dicek satu-satu ada di repo (1 nama paket sempat salah, `libjpeg62-turbo-dev` → `libjpeg-dev`, sudah diperbaiki)

## ⚠️ BELUM bisa saya uji (tidak ada Docker di sandbox saya)

- **`docker compose build` & `up` sungguhan** — TIDAK BISA saya jalankan
  (sandbox saya tidak punya Docker terinstall). Konfigurasinya sudah saya
  validasi semaksimal mungkin tanpa itu (lihat di atas), tapi **build
  pertama kali** (terutama compile `dlib`) **mohon dicoba & diawasi
  langsung** -- kemungkinan ada 1-2 hal kecil (versi paket, dsb) yang
  cuma ketahuan saat build sungguhan berjalan.
- Migrasi database MySQL sungguhan dari kosong.
- Koneksi WebSocket lewat proxy nginx end-to-end.
- Upload foto wajah/QR scan lewat `client_max_body_size` yang saya set (20M) -- sesuaikan kalau ternyata kurang/kebesaran.

Kalau ada error saat `docker compose build`/`up`, tolong kirim pesan
errornya lengkap -- saya bisa diagnosis dari situ meski tidak bisa
menjalankan Docker langsung.
