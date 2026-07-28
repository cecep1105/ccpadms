"""
Generate encryption key (Fernet) KHUSUS kredensial bind Zentyal LDAP
(netmgmt) -- hasilnya disimpan di .env sebagai ZENTYAL_ENCRYPTION_KEY.

Jalankan:
    python manage.py generate_zentyal_key
"""
from cryptography.fernet import Fernet
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Generate encryption key (Fernet) baru untuk enkripsi password bind Zentyal LDAP (netmgmt).'

    def handle(self, *args, **options):
        key = Fernet.generate_key().decode()
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS('Key berhasil dibuat. Simpan baris berikut di .env:'))
        self.stdout.write('')
        self.stdout.write(f'ZENTYAL_ENCRYPTION_KEY={key}')
        self.stdout.write('')
