"""
Generate encryption key (Fernet) KHUSUS token API Zentyal Mail (Flask,
lihat test/zentyalmail_v2.py) -- hasilnya disimpan di .env sebagai
ZENTYAL_MAIL_ENCRYPTION_KEY.

Jalankan:
    python manage.py generate_zentyal_mail_key
"""
from cryptography.fernet import Fernet
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Generate encryption key (Fernet) baru untuk enkripsi token API Zentyal Mail (netmgmt).'

    def handle(self, *args, **options):
        key = Fernet.generate_key().decode()
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS('Key berhasil dibuat. Simpan baris berikut di .env:'))
        self.stdout.write('')
        self.stdout.write('ZENTYAL_MAIL_ENCRYPTION_KEY=%s' % key)
        self.stdout.write('')
