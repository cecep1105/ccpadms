"""
Generate encryption key (Fernet) KHUSUS data IT-Infra (lihat
netmgmt/models.py::ITInfraEntry) -- hasilnya disimpan di .env sebagai
ITINFRA_ENCRYPTION_KEY.

Jalankan:
    python manage.py generate_itinfra_key
"""
from cryptography.fernet import Fernet
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Generate encryption key (Fernet) baru untuk enkripsi data Data IT-Infra (netmgmt).'

    def handle(self, *args, **options):
        key = Fernet.generate_key().decode()
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS('Key berhasil dibuat. Simpan baris berikut di .env:'))
        self.stdout.write('')
        self.stdout.write('ITINFRA_ENCRYPTION_KEY=%s' % key)
        self.stdout.write('')
