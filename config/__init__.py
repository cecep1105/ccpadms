"""
PyMySQL dipakai sebagai driver MySQL murni-Python (tidak perlu compile
native, gampang di-deploy). Kalau nanti mau performa lebih baik di
produksi, install `mysqlclient` lalu hapus 2 baris di bawah ini serta
hapus PyMySQL dari requirements.txt.
"""
import pymysql

pymysql.install_as_MySQLdb()

# Pastikan Celery app ke-load begitu Django start, supaya @shared_task di
# app lain (mis. mattendance/tasks.py) otomatis terhubung ke app ini --
# pola standar integrasi Django+Celery.
from .celery import app as celery_app  # noqa: E402

__all__ = ('celery_app',)
