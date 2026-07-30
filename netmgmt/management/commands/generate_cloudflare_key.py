"""
Generate encryption key (Fernet) KHUSUS token API Cloudflare (lihat
netmgmt/cloudflare_view.py) -- hasilnya disimpan di .env sebagai
CLOUDFLARE_ENCRYPTION_KEY.

Jalankan:
    python manage.py generate_cloudflare_key
"""
from cryptography.fernet import Fernet
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Generate encryption key (Fernet) baru untuk enkripsi token API Cloudflare (netmgmt).'

    def handle(self, *args, **options):
        key = Fernet.generate_key().decode()
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS('Key berhasil dibuat. Simpan baris berikut di .env:'))
        self.stdout.write('')
        self.stdout.write('CLOUDFLARE_ENCRYPTION_KEY=%s' % key)
        self.stdout.write('')
