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
    'netmgmt',
    'idcard',
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

# ---------------------------------------------------------------------------
# MEDIA -- file yang DIUNGGAH lewat aplikasi ini (BEDA dari STATIC yang
# dikumpulkan dari kode, mis. CSS/JS) -- konsumen PERTAMA: aplikasi ID
# Card (idcard/), background template & foto kartu (idcard/models.py::
# IDCardTemplate/IDCard/IDCardHolder). Belum pernah ada fitur upload
# file lokal sebelum ini di proyek ini.
#
# Development: Django sendiri yang serve file ini (lihat config/urls.py,
# `+ static(...)`, CUMA aktif saat DEBUG=True). Produksi: WAJIB di-serve
# oleh web server (nginx/dst) langsung dari MEDIA_ROOT, Django TIDAK
# efisien utk serve file besar/banyak trafik -- konfigurasi nginx utk
# alias /media/ -> MEDIA_ROOT ada di LUAR cakupan kode ini.
# ---------------------------------------------------------------------------
MEDIA_URL = 'media/'
MEDIA_ROOT = BASE_DIR / 'media'
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

# Celery Beat -- PENJADWAL task periodik (BEDA dari worker biasa, WAJIB
# dijalankan sbg proses TERPISAH: `celery -A config beat --loglevel=info`
# -- worker biasa TETAP perlu jalan jg utk benar2 EKSEKUSI task-nya, Beat
# cuma "nyalain alarm", tidak eksekusi sendiri).
#
# check_mailq (netmgmt/tasks.py): cek isi mailq Zentyal tiap 1 menit,
# broadcast lewat WebSocket (group 'netmgmt', section='mailq') ke halaman
# Mail Queue yang lagi dibuka, biar update TANPA refresh manual.
CELERY_BEAT_SCHEDULE = {
    'netmgmt-check-mailq': {
        'task': 'netmgmt.tasks.check_mailq',
        'schedule': env.int('NETMGMT_MAILQ_CHECK_INTERVAL_SECONDS', default=10),
    },
    'netmgmt-check-ad-locked-users': {
        'task': 'netmgmt.tasks.check_ad_locked_users',
        # Default 10 detik -- filter di get_recently_locked_users() cuma
        # tangkap user terkunci 2 menit TERAKHIR, jadi interval cek ini
        # PERLU lebih pendek dari itu supaya user yg baru saja terkunci
        # tertangkap tepat waktu (bukan cuma kebetulan lolos sebelum
        # jendela 2 menitnya berakhir).
        'schedule': env.int('NETMGMT_AD_LOCKED_CHECK_INTERVAL_SECONDS', default=10),
    },
}

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
        "httpx": { "level": "WARNING", "propagate": False},
    },
}

# --- Kredensial Mikrotik (netmgmt) -- lihat netmgmt/crypto_utils.py ---
MIKROTIK_ENCRYPTION_KEY = env('MIKROTIK_ENCRYPTION_KEY', default='')
MIKROTIK_PASSWORD_ENCRYPTED = env('MIKROTIK_PASSWORD_ENCRYPTED', default='')

# --- Webhook Netwatch (dipanggil LANGSUNG oleh script RouterOS saat status
# up/down berubah, lihat test/netwatchscript.txt & netmgmt/routeros_netwatch_webhook_view.py)
# -- BEDA dari endpoint netmgmt lain (yang dipanggil user login lewat
# Next.js), endpoint ini dipanggil MIKROTIK SENDIRI (`/tool fetch`), TIDAK
# via session/JWT biasa.
#
# MIKROTIK_NETWATCH_ROUTER_IP: router yang di-QUERY BALIK utk ambil daftar
# LENGKAP netwatch tiap kali webhook masuk (payload dari Mikrotik cuma
# berisi 1 host yg berubah statusnya, TAPI broadcast WebSocket ke frontend
# butuh DAFTAR LENGKAP -- lihat docstring view). SAMA persis dgn env var
# yang dipakai Next.js (nextadms .env: MIKROTIK_NETWATCH_ROUTER_IP) --
# WAJIB nilainya SAMA (router yang sama), krn keduanya rujuk router fisik
# yang sama, cuma beda proses (Django vs Next.js) yang membacanya.
MIKROTIK_NETWATCH_ROUTER_IP = env('MIKROTIK_NETWATCH_ROUTER_IP', default='10.100.202.1')
# Router DEFAULT utk DHCP Lease/Firewall Filter PORTAL (netmgmt/portal_views.py)
# -- fallback KALAU admin belum set default lewat NetmgmtRouterDefault
# (Django Admin) -- SAMA nama/nilai default dgn env var yang dipakai
# Next.js (nextadms .env: MIKROTIK_DHCP_ROUTER_IP/MIKROTIK_FWFILTER_ROUTER_IP)
# utk halaman STAFF, TAPI ini VARIABEL TERPISAH (Django vs Next.js baca
# .env masing2 proses sendiri) -- WAJIB nilainya SAMA kalau mau router
# defaultnya konsisten antara portal & staff.
MIKROTIK_DHCP_ROUTER_IP = env('MIKROTIK_DHCP_ROUTER_IP', default='10.100.202.254')
MIKROTIK_FWFILTER_ROUTER_IP = env('MIKROTIK_FWFILTER_ROUTER_IP', default='10.100.202.254')

# ---------------------------------------------------------------------------
# ID CARD -- sumber foto EKSTERNAL (idcard/photo_utils.py, diadaptasi dari
# test/photoutils.py) -- foto karyawan/driver SUDAH ada di beberapa server
# terpisah (BUKAN diunggah baru lewat aplikasi ini). FTP1/FTP2/FTP3: format
# URL FTPStorage location, CONTOH: 'ftp://user:password@host.contoh.com/'
# (SLASH di akhir WAJIB). Isi SEBENARNYA WAJIB diisi lewat .env server
# produksi, JANGAN di-commit ke git dgn nilai asli.
# ---------------------------------------------------------------------------
IDCARD_FTP1 = env('IDCARD_FTP1', default='')
IDCARD_FTP2 = env('IDCARD_FTP2', default='')
IDCARD_FTP3 = env('IDCARD_FTP3', default='')

# (left, top, right, bottom) -- kotak foto untuk idcard
IDCARD_PHOTO_BOX = env.tuple("IDCARD_PHOTO_BOX", cast=int, default=(289, 400, 589, 700))

# Connection string ODBC (pyodbc) ke SQL Server pihak ketiga -- KHUSUS
# sumber foto driver KBA, lihat idcard/photo_utils.py::_get_kba_driver_photo().
IDCARD_KBA_CONNECTION_STRING = env('IDCARD_KBA_CONNECTION_STRING', default='')
# Token OPSIONAL (query string ?token=...) -- endpoint /nwupdate TIDAK
# PAKAI autentikasi Django biasa (session/JWT) krn dipanggil Mikrotik
# langsung, bukan browser. Kalau env var ini KOSONG, endpoint TERBUKA
# TANPA proteksi (cukup utk testing/LAN tertutup, TAPI sebaiknya diisi
# utk produksi) -- isi token acak & tambahkan ke URL script Mikrotik:
# url="http://$ADMSHOST:8000/api/v1/netmgmt/nwupdate?token=xxx"
NETWATCH_WEBHOOK_TOKEN = env('NETWATCH_WEBHOOK_TOKEN', default='')

# --- Koneksi Active Directory (netmgmt) -- TERPISAH dari AUTH_LDAP_* di
# atas (itu KHUSUS login staff, service account-nya BISA SAJA beda hak
# akses -- AD di sini perlu hak BACA users/groups DAN TULIS (ubah member
# group), biasanya butuh account service dgn privilege lebih tinggi). ---
AD_ENCRYPTION_KEY = env('AD_ENCRYPTION_KEY', default='')
AD_SERVER_URI = env('AD_SERVER_URI', default='')
AD_BIND_DN = env('AD_BIND_DN', default='')  # mis. 'CN=svc-netmgmt,CN=Users,DC=contoso,DC=com'
AD_BIND_PASSWORD_ENCRYPTED = env('AD_BIND_PASSWORD_ENCRYPTED', default='')
AD_BASE_DN = env('AD_BASE_DN', default='')  # mis. 'DC=contoso,DC=com'
# DN root FOREST -- BEDA dari AD_BASE_DN kalau domain Anda CHILD domain di
# forest multi-domain -- dipakai cari zone DNS "ForestDnsZones". Default
# SAMA DENGAN AD_BASE_DN (asumsi single-domain-forest, paling umum).
AD_FOREST_BASE_DN = env('AD_FOREST_BASE_DN', default='') or AD_BASE_DN
# Override opsional kalau users/groups ada di sub-OU BEDA dari AD_BASE_DN --
# kalau kosong, AD_BASE_DN dipakai utk keduanya.
AD_USER_BASE_DN = env('AD_USER_BASE_DN', default='') or AD_BASE_DN
AD_GROUP_BASE_DN = env('AD_GROUP_BASE_DN', default='') or AD_BASE_DN
AD_USE_SSL = env.bool('AD_USE_SSL', default=False)
AD_CONNECT_TIMEOUT = env.int('AD_CONNECT_TIMEOUT', default=5)
# Batas jumlah baris diambil per fetch dari AD -- proteksi supaya query
# "list semua user" di direktori BESAR (ribuan+) tidak bikin request lambat
# tak terbatas. Pagination TETAP jalan normal di bawah batas ini (lihat
# netmgmt/list_utils.py) -- kalau direktori Anda LEBIH BESAR dari ini &
# perlu akses baris di luar batas, naikkan nilainya.
AD_MAX_FETCH_ROWS = env.int('AD_MAX_FETCH_ROWS', default=5000)

# --- Koneksi Zentyal LDAP (netmgmt) -- mail server Zentyal 3.4, backend
# Courier. User: posixAccount+inetOrgPerson+usereboxmail (1 entry). Group:
# posixGroup (memberUid) -- TIDAK ADA objectClass custom "zentyalGroup" di
# schema yang di-cek, jadi kemungkinan besar grup biasa HANYA posixGroup.
# Kode di netmgmt/zentyal_view.py ADAPTIF (cek atribut member/memberUid
# mana yang ADA di tiap grup) -- TETAP VERIFIKASI ke data live Anda.
#
# CATATAN dari user: SSL ke server LDAP Zentyal ini SAAT INI tidak bisa
# konek (penyebab belum diketahui) -- default AD_USE_SSL=False DULU.
ZENTYAL_ENCRYPTION_KEY = env('ZENTYAL_ENCRYPTION_KEY', default='')
ZENTYAL_SERVER_URI = env('ZENTYAL_SERVER_URI', default='')
ZENTYAL_BIND_DN = env('ZENTYAL_BIND_DN', default='')
ZENTYAL_BIND_PASSWORD_ENCRYPTED = env('ZENTYAL_BIND_PASSWORD_ENCRYPTED', default='')
ZENTYAL_BASE_DN = env('ZENTYAL_BASE_DN', default='')
ZENTYAL_USER_BASE_DN = env('ZENTYAL_USER_BASE_DN', default='') or ZENTYAL_BASE_DN
ZENTYAL_GROUP_BASE_DN = env('ZENTYAL_GROUP_BASE_DN', default='') or ZENTYAL_BASE_DN
ZENTYAL_USE_SSL = env.bool('ZENTYAL_USE_SSL', default=False)
ZENTYAL_CONNECT_TIMEOUT = env.int('ZENTYAL_CONNECT_TIMEOUT', default=5)
ZENTYAL_MAX_FETCH_ROWS = env.int('ZENTYAL_MAX_FETCH_ROWS', default=5000)
# gidNumber DEFAULT utk user BARU (lihat netmgmt/zentyal_view.py::ZentyalUserCreateView)
# -- GID grup Unix biasa dipakai BERSAMA banyak user (BUKAN dihitung
# otomatis per-user spt uidNumber), jadi WAJIB dikonfigurasi eksplisit
# sesuai grup default di server Zentyal Anda (cek `getent group users`
# di server itu kalau tidak yakin). Default 100 = GID grup "users" baku
# di Debian (dasar OS Zentyal 3.4), TAPI VERIFIKASI DULU sebelum pakai.
ZENTYAL_DEFAULT_GID_NUMBER = env.int('ZENTYAL_DEFAULT_GID_NUMBER', default=100)

# --- Zentyal Mail API (Flask, Python 2.7, jalan TERPISAH di server mail
# -- lihat test/zentyalmail_v2.py & test/README.md) -- BEDA dari koneksi
# LDAP Zentyal di atas (itu utk users/groups, ini utk mail queue/log/dst,
# protokolnya HTTP+JSON biasa, bukan LDAP). ---
ZENTYAL_MAIL_ENCRYPTION_KEY = env('ZENTYAL_MAIL_ENCRYPTION_KEY', default='')
ZENTYAL_MAIL_API_URL = env('ZENTYAL_MAIL_API_URL', default='')  # mis. 'http://mail.internal:5100'
ZENTYAL_MAIL_API_TOKEN_ENCRYPTED = env('ZENTYAL_MAIL_API_TOKEN_ENCRYPTED', default='')
ZENTYAL_MAIL_API_TIMEOUT = env.int('ZENTYAL_MAIL_API_TIMEOUT', default=10)

# --- VMware vCenter (SOAP API via pyVmomi, BUKAN REST -- lihat
# netmgmt/vmware_view.py) -- dipakai KHUSUS utk halaman detail per-VM
# (guest OS/IP/tools status, disk & datastore) yang butuh BANYAK
# property sekaligus -- REST API vCenter (dipakai Next.js utk list Host/
# VM Guest, src/lib/vsphere-client.ts di nextadms) perlu request TERPISAH
# per jenis detail (N+1), sedangkan SOAP PropertyCollector bisa ambil
# semuanya dlm 1 round-trip. List Host/VM Guest TETAP di Next.js (sudah
# jalan baik, tidak perlu diganti) -- CUMA detail per-VM yang lewat sini.
VMWARE_ENCRYPTION_KEY = env('VMWARE_ENCRYPTION_KEY', default='')
VMWARE_HOST = env('VMWARE_HOST', default='')
VMWARE_USER = env('VMWARE_USER', default='')
VMWARE_PASSWORD_ENCRYPTED = env('VMWARE_PASSWORD_ENCRYPTED', default='')
# vCenter on-prem BIASANYA sertifikat self-signed -- SAMA pertimbangan
# spt VSPHERE_ALLOW_SELF_SIGNED_CERT di sisi Next.js (src/lib/vsphere-client.ts),
# TAPI ini pengaturan TERPISAH krn koneksi SOAP (pyVmomi, dari Django) &
# REST (dari Next.js) adalah 2 KONEKSI BERBEDA meski ke server yang sama.
VMWARE_ALLOW_SELF_SIGNED_CERT = env.bool('VMWARE_ALLOW_SELF_SIGNED_CERT', default=True)

# --- Cloudflare DNS (manajemen domain/record) -- lihat netmgmt/cloudflare_view.py
# -- API v4 Cloudflare, autentikasi via API Token (Bearer), BUKAN Global
# API Key lama (Token lebih aman -- bisa dibatasi scope-nya per-zone di
# dashboard Cloudflare, Global Key akses semua akun tanpa batas). ---
CLOUDFLARE_ENCRYPTION_KEY = env('CLOUDFLARE_ENCRYPTION_KEY', default='')
CLOUDFLARE_API_TOKEN_ENCRYPTED = env('CLOUDFLARE_API_TOKEN_ENCRYPTED', default='')
CLOUDFLARE_API_TIMEOUT = env.int('CLOUDFLARE_API_TIMEOUT', default=15)

# --- Data IT-Infra (registry data infrastruktur bebas -- internet/VPS/
# domain/dll, lihat netmgmt/itinfra_view.py & netmgmt/models.py::ITInfraEntry)
# -- data (JSON bebas, SERING berisi password) dienkripsi UTUH sebelum
# disimpan ke database. ---
ITINFRA_ENCRYPTION_KEY = env('ITINFRA_ENCRYPTION_KEY', default='')

#--- Mirror push-sdk ke server lain (mis. server cadangan di lokasi berbeda) -- lihat iclock/pushsdk_writer.py
MIRROR_REQUEST = env.bool('MIRROR_REQUEST', default=False)  # kalau True, semua request pushsdk akan dikirim ke host mirror
MIRROR_REQUEST_URL = env('MIRROR_REQUEST_URL', default='')  # mis. 'http://mirror.example.com:8000', kalau kosong, mirror request TIDAK dikirim sama sekali (meski MIRROR_REQUEST=True)
SEND_ORIGINIP=env('ORIGINIP', default=False) # kalau True, IP asli pengirim request akan dikirim ke mirror via header X-Forwarded-For (untuk keperluan logging/traceability di server mirror)
