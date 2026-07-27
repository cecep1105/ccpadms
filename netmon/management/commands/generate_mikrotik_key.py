"""
Generate encryption key (Fernet) untuk fitur NETMON -- dijalankan
SEKALI di awal setup, hasilnya disimpan di .env sebagai MIKROTIK_ENCRYPTION_KEY.

Jalankan:
    python manage.py generate_mikrotik_key
"""
from cryptography.fernet import Fernet
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Generate encryption key (Fernet) baru untuk enkripsi password MIKROTIK.'

    def handle(self, *args, **options):
        key = Fernet.generate_key().decode()
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS('Key berhasil dibuat. Simpan baris berikut di .env:'))
        self.stdout.write('')
        self.stdout.write(f'MIKROTIK_ENCRYPTION_KEY={key}')
        self.stdout.write('')
        self.stdout.write(self.style.WARNING(
            'PENTING: simpan key ini baik-baik & JANGAN sampai hilang/berubah -- password yang sudah '
            'dienkripsi pakai key ini tidak akan bisa didekripsi lagi kalau key-nya beda. Setelah '
            'key ini disimpan di .env, jalankan "python manage.py encrypt_mIKROTIK_password" untuk '
            'enkripsi password MSSQL Anda.'
        ))
