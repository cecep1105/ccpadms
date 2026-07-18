"""
Konfigurasi Celery app -- dipakai supaya proses berat/CPU-intensive (mis.
face recognition, lihat mattendance/tasks.py) bisa dilempar ke WORKER
TERPISAH, tidak menghabiskan CPU/thread proses Django/Daphne utama yang
juga menangani request HTTP lain + koneksi WebSocket (iclock console
real-time).

Jalankan worker-nya TERPISAH dari `manage.py runserver`:
    celery -A config worker --loglevel=info --pool=solo

⚠️ WINDOWS: WAJIB pakai `--pool=solo` (atau `--pool=threads --concurrency=N`)
-- pool default Celery ("prefork") butuh `os.fork()` yang TIDAK ada di
Windows, worker akan gagal/berperilaku aneh tanpa flag ini.
"""
import os

from celery import Celery

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

app = Celery('config')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()
