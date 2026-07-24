"""
Django settings for the project.

Struktur:
- accounts : model User custom + logic autentikasi LDAP/local (services.py, backends.py)
- dashboard: UI custom (bukan Django admin bawaan) untuk admin & user biasa
- api      : REST API (JWT) yang dikonsumsi frontend Nuxt, memanggil accounts.services
"""
import os
from datetime import timedelta
from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(DEBUG=(bool, False))
environ.Env.read_env(BASE_DIR / '.env')

# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------
SECRET_KEY = env('SECRET_KEY', default='django-insecure-CHANGE-ME-IN-PRODUCTION')
DEBUG = env.bool('DEBUG', default=True)
ALLOWED_HOSTS = env.list('ALLOWED_HOSTS', default=['localhost', '127.0.0.1'])

# ---------------------------------------------------------------------------
# CSRF & reverse proxy (WAJIB diisi kalau deploy di belakang nginx/reverse
# proxy lain, terutama kalau SSL/HTTPS-nya DITERMINASI DI NGINX -- bukan di
# Django/Daphne langsung). Tanpa ini, login & semua form POST akan gagal
# dengan error "CSRF verification failed... Origin checking failed - https://
# domain-anda does not match any trusted origins."
# ---------------------------------------------------------------------------
# Django 4.0+ WAJIB validasi header Origin request POST terhadap daftar ini
# secara eksplisit -- isi dgn domain PUBLIK (yang diketik user di browser),
# LENGKAP dengan skema https://, dipisah koma di .env. Contoh:
#   CSRF_TRUSTED_ORIGINS=https://absensi.perusahaan.com,https://www.perusahaan.com
CSRF_TRUSTED_ORIGINS = env.list('CSRF_TRUSTED_ORIGINS', default=[])

# Kalau SSL DITERMINASI DI NGINX (nginx yang pegang sertifikat, lalu proxy ke
# Django via HTTP biasa di belakangnya) -- Django TIDAK tahu request aslinya
# HTTPS kecuali diberi tahu lewat header ini. WAJIB dipasangkan dengan baris
# `proxy_set_header X-Forwarded-Proto $scheme;` di config nginx (lihat
# README bagian Deployment) -- kalau nginx TIDAK di-setting utk override
# header ini dari client, JANGAN aktifkan (risiko keamanan: client bisa
# palsukan header X-Forwarded-Proto sendiri kalau nginx cuma meneruskan apa
# adanya tanpa menimpanya).
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

# Cookie session & CSRF cuma dikirim lewat HTTPS -- aktifkan di produksi
# (biarkan False saat development lokal via HTTP biasa, makanya dikaitkan
# ke `not DEBUG` sebagai default, tapi tetap bisa di-override manual lewat
# .env kalau perlu).
SESSION_COOKIE_SECURE = env.bool('SESSION_COOKIE_SECURE', default=not DEBUG)
CSRF_COOKIE_SECURE = env.bool('CSRF_COOKIE_SECURE', default=not DEBUG)

INSTALLED_APPS = [
    # 'daphne' HARUS di baris paling atas (sebelum app Django bawaan lain) --
    # ini konvensi resmi Django Channels: daphne menyediakan override command
    # 'runserver' yang ASGI-aware (bisa serve HTTP + WebSocket sekaligus).
    # Tanpa ini, 'python manage.py runserver' cuma pakai runserver bawaan
    # Django (WSGI-only) dan endpoint /ws/iclock TIDAK akan berfungsi saat
    # development, meskipun 'channels' sendiri sudah terpasang -- 'channels'
    # cuma menyediakan command 'runworker', BUKAN 'runserver'.
    'daphne',

    # Sengaja TIDAK memasukkan 'django.contrib.admin' karena dashboard
    # custom dipakai, bukan Django admin bawaan.
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    'channels',

    'rest_framework',
    'rest_framework_simplejwt',
    'rest_framework_simplejwt.token_blacklist',
    'corsheaders',

    'accounts',
    'dashboard',
    'api',
    'iclock',
    'mclock',
    'mattendance',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    # WAJIB setelah AuthenticationMiddleware (butuh request.user) & setelah
    # MessageMiddleware (dia pakai messages.error()) -- lihat docstring
    # middleware-nya, ini murni no-op utk user REGULER (staff/LDAP/local),
    # cuma aktif utk user "mobile-only" (login via PIN Employee).
    'accounts.middleware.MobileAccessMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'
ASGI_APPLICATION = 'config.asgi.application'

# ---------------------------------------------------------------------------
# Database (MySQL). Bisa dioverride ke sqlite untuk dev lokal cepat lewat .env
# ---------------------------------------------------------------------------
DB_ENGINE = env('DB_ENGINE', default='django.db.backends.mysql')

DATABASES = {
    'default': {
        'ENGINE': DB_ENGINE,
        'NAME': env('DB_NAME', default='nuxt_backend'),
        'USER': env('DB_USER', default='root'),
        'PASSWORD': env('DB_PASSWORD', default=''),
        'HOST': env('DB_HOST', default='127.0.0.1'),
        'PORT': env('DB_PORT', default='3306'),
    }
}
if 'mysql' in DB_ENGINE:
    DATABASES['default']['OPTIONS'] = {'charset': 'utf8mb4'}

# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
AUTH_USER_MODEL = 'accounts.User'

AUTHENTICATION_BACKENDS = [
    'accounts.backends.LDAPOrLocalBackend',
    # PENTING: 'LDAPOrLocalBackend' cuma nge-handle AUTENTIKASI (cek username
    # /password), dia extend 'BaseBackend' yang TIDAK punya logic permission
    # sungguhan (has_perm()/get_all_permissions() bawaan BaseBackend cuma
    # placeholder kosong). Tanpa 'ModelBackend' di sini, SELURUH sistem
    # permission Django (user.has_perm(), user_permissions M2M, dipakai fitur
    # "Kelola Izin User" utk Transfer Data Finger/Attendance Recap) diam-diam
    # TIDAK PERNAH mengembalikan True untuk siapapun, walau permission-nya
    # sudah benar ke-assign di database -- 'ModelBackend' inilah yang
    # menyediakan logic pengecekan permission standar Django tersebut.
    'django.contrib.auth.backends.ModelBackend',
    # Login Mobile Attendance via PIN Employee (BUKAN username/password akun
    # accounts.User) -- dipanggil dgn kwargs BEDA (`pin`/`mobile_password`),
    # aman berdampingan dgn backend lain (lihat docstring backend-nya).
    'accounts.mobile_backend.EmployeeMobileBackend',
]

# Password default login Mobile Attendance (via PIN) -- WAJIB diganti user
# begitu login pertama kali (atau kalau ke-reset balik ke ini), lihat
# accounts/mobile_backend.py & accounts/middleware.py.
MOBILE_DEFAULT_PASSWORD = env('MOBILE_DEFAULT_PASSWORD', default='123456')

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator', 'OPTIONS': {'min_length': 8}},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LOGIN_URL = 'accounts:login'
LOGIN_REDIRECT_URL = 'dashboard:index'
LOGOUT_REDIRECT_URL = 'accounts:login'

# ---------------------------------------------------------------------------
# LDAP
# ---------------------------------------------------------------------------
AUTH_LDAP_SERVER_URI = env('AUTH_LDAP_SERVER_URI', default='ldap://localhost:389')
AUTH_LDAP_BIND_DN = env('AUTH_LDAP_BIND_DN', default='')          # service account utk search
AUTH_LDAP_BIND_PASSWORD = env('AUTH_LDAP_BIND_PASSWORD', default='')
AUTH_LDAP_BASE_DN = env('AUTH_LDAP_BASE_DN', default='')
AUTH_LDAP_USER_SEARCH_FILTER = env('AUTH_LDAP_USER_SEARCH_FILTER', default='(uid={username})')
AUTH_LDAP_USE_SSL = env.bool('AUTH_LDAP_USE_SSL', default=False)
AUTH_LDAP_CONNECT_TIMEOUT = env.int('AUTH_LDAP_CONNECT_TIMEOUT', default=5)
AUTH_LDAP_USER_ATTR_MAP = {
    'email': env('AUTH_LDAP_ATTR_EMAIL', default='mail'),
    'first_name': env('AUTH_LDAP_ATTR_FIRST_NAME', default='givenName'),
    'last_name': env('AUTH_LDAP_ATTR_LAST_NAME', default='sn'),
}

# ---------------------------------------------------------------------------
# iclock -- mapping kode Function (device & transaksi) ke label yang bisa
# dibaca. Dipakai di combo filter "Device Function" pada Attendance Recap,
# dan method transaction.FncName(). Sesuaikan sesuai kebutuhan perusahaan.
# ---------------------------------------------------------------------------
DEVICEFUNCTION = {
    '89': 'KARYAWAN',
    '1': 'DRIVER-HIBA',
    '56': 'DRIVER-HRC',
    'X': 'KANTIN',
    '2': 'DRIVER-AKAP',
    '3': 'YAYASAN',
    '7': 'BHL',
    '4': 'DRIVER-KBA',
    '0': 'TESTING',
}

# ---------------------------------------------------------------------------
# Mobile Attendance -- Check/Meal (absen makan siang, verifikasi GPS + QR
# Code sekaligus). Mapping ISI QR code -> PoolCode: format {'<poolcode>':
# '<isi qr code>'}. QR dipakai DISAMBIGUASI kalau ada geofence yang overlap
# (mis. kantin berdekatan dgn kantor utama) -- poolcode dari QR HARUS
# sesuai dgn salah satu poolcode geofence yang cocok dgn GPS user, kalau
# tidak, check/meal ditolak. Lihat mattendance/qr_utils.py.
# ---------------------------------------------------------------------------
QRDEVICE = {
    '114': 'KANTINQR-KANTOR1',
    '272': 'KANTINQR-KANTOR2',
    '250': 'KANTINQR-KANTOR3',
}

# Kalau True, enrollment wajah DITOLAK kalau wajah yang didaftarkan sudah
# "mirip" (di bawah tolerance face_recognition) dengan wajah user LAIN yang
# sudah lebih dulu terdaftar (FaceProfile) -- mencegah 2 user berbeda
# mendaftarkan wajah orang yang sama. Kalau False, tidak ada pengecekan ini
# sama sekali (enrollment ulang wajah SENDIRI tetap selalu diizinkan,
# terlepas dari setting ini). Default True (lebih aman/ketat).
PREVENT_DUPLICATE_FACE = env.bool('PREVENT_DUPLICATE_FACE', default=True)

# Kode `State`/`checktype` yang dianggap "IN" (check-in) di Attendance Recap.
# Selain kode-kode ini dianggap "OUT" (sesuai instruksi: tidak ada kategori
# ketiga). Default mencakup dua konvensi yang pernah ditemukan: '0' (sesuai
# ATTSTATES di model) dan 'I' (yang ternyata dipakai di data produksi nyata
# Anda -- device firmware tertentu memang menulis huruf I/O, bukan digit).
# Sesuaikan list ini kalau device Anda pakai kode lain.
ATTENDANCE_IN_STATE_CODES = ['0', 'I']

# ---------------------------------------------------------------------------
# CORS - dipakai frontend Nuxt yang beda origin
# ---------------------------------------------------------------------------
CORS_ALLOWED_ORIGINS = env.list('CORS_ALLOWED_ORIGINS', default=['http://localhost:3000'])
CORS_ALLOW_CREDENTIALS = True

# ---------------------------------------------------------------------------
# DRF + JWT
# ---------------------------------------------------------------------------
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework_simplejwt.authentication.JWTAuthentication',
        'rest_framework.authentication.SessionAuthentication',
    ),
    'DEFAULT_PERMISSION_CLASSES': (
        'rest_framework.permissions.IsAuthenticated',
    ),
    'DEFAULT_PAGINATION_CLASS': 'api.pagination.DefaultPagination',
    'PAGE_SIZE': 20,
}

SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(minutes=env.int('JWT_ACCESS_TOKEN_LIFETIME_MINUTES', default=30)),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=env.int('JWT_REFRESH_TOKEN_LIFETIME_DAYS', default=7)),
    'ROTATE_REFRESH_TOKENS': True,
    'BLACKLIST_AFTER_ROTATION': True,
    'AUTH_HEADER_TYPES': ('Bearer',),
}

# ---------------------------------------------------------------------------
# I18N / static
# ---------------------------------------------------------------------------
LANGUAGE_CODE = 'id'
TIME_ZONE = env('TIME_ZONE', default='Asia/Jakarta')
USE_I18N = True
# Default False: dari investigasi Attendance Recap, timestamp mentah yang
# ditulis device fingerprint fisik ke MySQL (`checkinout.checktime`) adalah
# waktu LOKAL apa adanya (bukan UTC). Kalau USE_TZ=True, Django keliru
# mengira nilai itu UTC dan menggeser jamnya saat ditampilkan (mis. 07:30
# jadi 14:30). Ubah ke True lewat .env HANYA kalau proses yang menulis data
# ke database sudah benar-benar menyimpan dalam UTC.
USE_TZ = env.bool('USE_TZ', default=False)

STATIC_URL = 'static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# ---------------------------------------------------------------------------
# Channels / WebSocket (real-time console iclock, lihat iclock/consumers.py)
# ---------------------------------------------------------------------------
ASGI_APPLICATION = 'config.asgi.application'

REDIS_HOST = env('REDIS_HOST', default='127.0.0.1')
REDIS_PORT = env.int('REDIS_PORT', default=6379)

CHANNEL_LAYERS = {
    'default': {
        'BACKEND': 'channels_redis.core.RedisChannelLayer',
        'CONFIG': {
            "hosts": [
                {
                    # SEBELUMNYA hardcode "127.0.0.1" -- cuma kebetulan
                    # kepakai selama Django & Redis SELALU di mesin yang
                    # SAMA (dev lokal biasa). Begitu dijalankan di Docker
                    # (Redis di container TERPISAH, dijangkau lewat nama
                    # service `redis`, BUKAN 127.0.0.1 dari dalam
                    # container django-web/django-celery), koneksi gagal
                    # total (Connection refused) -- CELERY_BROKER_URL di
                    # bawah SUDAH benar pakai REDIS_HOST/REDIS_PORT,
                    # cuma yang ini kelupaan disamakan.
                    "address": f"redis://{REDIS_HOST}:{REDIS_PORT}/0",
                    "socket_timeout": None,
                }
            ],
        },
    },
}

# ---------------------------------------------------------------------------
# Cache framework (Django cache, BEDA dari Channels & Celery meski sama-sama
# pakai Redis -- makanya DB index beda: Channels=0 (default), Celery=1, cache
# ini=2). Dipakai utk pola "cache-aware save" push protocol iclock (device
# polling ~30 detik, hindari beban baca/tulis DB berlebihan tiap request --
# lihat iclock/models.py::iclock.get_cached/save_heartbeat, test/myrule.md
# poin 1).
# ---------------------------------------------------------------------------
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.redis.RedisCache',
        'LOCATION': f'redis://{REDIS_HOST}:{REDIS_PORT}/2',
    },
}

# ---------------------------------------------------------------------------
# PUSH SDK -- 'DB Write Policy' (test/myrule.md Rule 4): data device
# (attendance/operation log/fingerprint template) ditulis ke TEXT FILE dulu
# (durability/source-of-truth) SEBELUM diproses Celery task tulis ke
# database. Struktur: {PUSHSDK_BASE_DIR}/masterattlog/{MMYYYY}/{DD}.txt
# (dst utk masteroplog/masterfplog, +variant '_other' utk PIN tidak valid).
# Default 'data/' di root project, folder DIPISAH dari static/media Django
# supaya gampang di-backup/rotate terpisah. Lihat iclock/pushsdk_writer.py.
# ---------------------------------------------------------------------------
PUSHSDK_BASE_DIR = env('PUSHSDK_BASE_DIR', default=str(BASE_DIR / 'data'))

# ---------------------------------------------------------------------------
# Google Maps JavaScript API -- dipakai halaman "Gambar Polygon di Peta"
# (mclock, Mobile Pool Location) supaya admin bisa klik titik-titik geofence
# LANGSUNG di peta, bukan ketik koordinat manual satu-satu. WAJIB diisi di
# .env (GOOGLE_MAPS_API_KEY=...) -- kosong = halaman peta akan tampilkan
# pesan jelas ke admin (bukan diam-diam gagal/blank).
# ---------------------------------------------------------------------------
GOOGLE_MAPS_API_KEY = env('GOOGLE_MAPS_API_KEY', default='')


# ---------------------------------------------------------------------------
# Celery -- dipakai utk lempar proses berat/CPU-intensive (face recognition,
# lihat mattendance/tasks.py) ke WORKER TERPISAH, supaya tidak membebani
# proses Django/Daphne utama yang juga menangani request lain + WebSocket.
#
# Reuse Redis yang SAMA dengan Channels di atas (bukan instance terpisah),
# tapi pakai DB index BEDA (`/1` vs default Channels `/0`) supaya key-nya
# tidak tercampur dalam 1 instance Redis yang sama.
#
# Jalankan worker (TERPISAH dari `manage.py runserver`):
#   celery -A config worker --loglevel=info --pool=solo
# ⚠️ WINDOWS: WAJIB --pool=solo (atau --pool=threads) -- pool default
# ("prefork") butuh os.fork() yang tidak ada di Windows.
# ---------------------------------------------------------------------------
CELERY_BROKER_URL = env('CELERY_BROKER_URL', default=f'redis://{REDIS_HOST}:{REDIS_PORT}/1')
CELERY_RESULT_BACKEND = env('CELERY_RESULT_BACKEND', default=f'redis://{REDIS_HOST}:{REDIS_PORT}/1')
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = TIME_ZONE
# Kalau True, task dijalankan LANGSUNG di proses pemanggil (bukan dilempar
# ke worker) -- TIDAK memberi manfaat isolasi CPU apa pun, cuma berguna utk
# testing/development tanpa perlu jalankan worker Celery sungguhan. WAJIB
# False di produksi supaya tujuan fitur ini (isolasi proses face
# recognition) benar-benar tercapai.
CELERY_TASK_ALWAYS_EAGER = env.bool('CELERY_TASK_ALWAYS_EAGER', default=False)
CELERY_TASK_EAGER_PROPAGATES = True

# ---------------------------------------------------------------------------
# mclock -- Mobile Attendance (monitoring data absensi mobile dari MSSQL
# eksternal, di luar database Django ini). Koneksi pakai pymssql, password
# disimpan TERENKRIPSI (lihat mclock/crypto_utils.py) -- setup awal:
#   1. python manage.py generate_mclock_key   -> isi MCLOCK_ENCRYPTION_KEY
#   2. python manage.py encrypt_mssql_password -> isi MCLOCK_MSSQL_PASSWORD_ENCRYPTED
# ---------------------------------------------------------------------------
MCLOCK_ENCRYPTION_KEY = env('MCLOCK_ENCRYPTION_KEY', default='')
MCLOCK_MSSQL_HOST = env('MCLOCK_MSSQL_HOST', default='')
MCLOCK_MSSQL_PORT = env.int('MCLOCK_MSSQL_PORT', default=1433)
# Versi protokol TDS (Tabular Data Stream) -- SQL Server versi lama (mis.
# 2008) butuh '7.0' secara eksplisit, kalau tidak koneksi gagal dgn error
# "Adaptive Server connection failed". Bisa di-override PER SOURCE di
# mclock/sources.py (key 'tds_version') kalau ada server lain yg butuh
# versi berbeda -- ini cuma DEFAULT global.
MCLOCK_MSSQL_TDS_VERSION = env('MCLOCK_MSSQL_TDS_VERSION', default='7.0')
MCLOCK_MSSQL_DATABASE = env('MCLOCK_MSSQL_DATABASE', default='')
MCLOCK_MSSQL_USERNAME = env('MCLOCK_MSSQL_USERNAME', default='')
MCLOCK_MSSQL_PASSWORD_ENCRYPTED = env('MCLOCK_MSSQL_PASSWORD_ENCRYPTED', default='')

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'filters': {
        # Perlu didefinisikan ulang di sini (persis sama dgn default Django) --
        # dictConfig() tidak bisa "mewarisi" handler/filter dari pemanggilan
        # dictConfig() sebelumnya cukup dgn menyebut namanya saja; harus
        # didefinisikan lengkap lagi kalau mau dipakai di config kita sendiri.
        'require_debug_false': {'()': 'django.utils.log.RequireDebugFalse'},
    },
    'handlers': {
        'console': {'class': 'logging.StreamHandler'},
        'mail_admins': {
            'level': 'ERROR',
            'filters': ['require_debug_false'],
            'class': 'django.utils.log.AdminEmailHandler',
        },
    },
    'root': {'handlers': ['console'], 'level': 'INFO'},
    'loggers': {
        # PENTING: Django secara default sudah memasang handler sendiri di
        # logger 'django' (lewat django.utils.log.DEFAULT_LOGGING), dan
        # karena disable_existing_loggers=False, handler bawaan itu TETAP
        # aktif berdampingan dengan handler 'console' yang kita pasang di
        # 'root' -- akibatnya pesan dari sublogger 'django.*' (termasuk
        # 'django.channels.server' yang dipakai daphne utk access log HTTP
        # "HTTP GET ... 200 [...]") diproses & tercetak DUA KALI (sekali
        # lewat handler bawaan Django di 'django', sekali lagi lewat 'root'
        # setelah ikut propagate). Daftarkan 'django' secara eksplisit di
        # sini (propagate=False) supaya cuma ada SATU jalur/handler yang
        # menanganinya -- 'mail_admins' didefinisikan ulang di atas supaya
        # notifikasi email ke ADMINS saat error 500 di production (DEBUG=False)
        # tetap jalan seperti perilaku default Django, tidak ikut hilang.
        'django': {'handlers': ['console', 'mail_admins'], 'level': 'INFO', 'propagate': False},
        'accounts': {'handlers': ['console'], 'level': 'DEBUG' if DEBUG else 'INFO', 'propagate': False},
        'iclock': {'handlers': ['console'], 'level': 'DEBUG' if DEBUG else 'INFO', 'propagate': False},
        'mclock': {'handlers': ['console'], 'level': 'DEBUG' if DEBUG else 'INFO', 'propagate': False},
    },
}