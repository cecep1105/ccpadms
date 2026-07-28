"""
Generate encryption key (Fernet) KHUSUS kredensial service account
Active Directory (netmgmt) -- dijalankan SEKALI di awal setup, hasilnya
disimpan di .env sebagai AD_ENCRYPTION_KEY.

Jalankan:
    python manage.py generate_ad_key
"""
from cryptography.fernet import Fernet
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Generate encryption key (Fernet) baru untuk enkripsi password service account Active Directory (netmgmt).'

    def handle(self, *args, **options):
        key = Fernet.generate_key().decode()
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS('Key berhasil dibuat. Simpan baris berikut di .env:'))
        self.stdout.write('')
        self.stdout.write(f'AD_ENCRYPTION_KEY={key}')
        self.stdout.write('')
        self.stdout.write(self.style.WARNING(
            'PENTING: simpan key ini baik-baik & JANGAN sampai hilang/berubah. Setelah key ini '
            'disimpan di .env, jalankan "python manage.py encrypt_ad_password" untuk enkripsi '
            'password service account AD Anda.'
        ))
