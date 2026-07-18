"""
Generate encryption key (Fernet) untuk fitur Mobile Attendance -- dijalankan
SEKALI di awal setup, hasilnya disimpan di .env sebagai MCLOCK_ENCRYPTION_KEY.

Jalankan:
    python manage.py generate_mclock_key
"""
from cryptography.fernet import Fernet
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Generate encryption key (Fernet) baru untuk enkripsi password MSSQL Mobile Attendance.'

    def handle(self, *args, **options):
        key = Fernet.generate_key().decode()
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS('Key berhasil dibuat. Simpan baris berikut di .env:'))
        self.stdout.write('')
        self.stdout.write(f'MCLOCK_ENCRYPTION_KEY={key}')
        self.stdout.write('')
        self.stdout.write(self.style.WARNING(
            'PENTING: simpan key ini baik-baik & JANGAN sampai hilang/berubah -- password yang sudah '
            'dienkripsi pakai key ini tidak akan bisa didekripsi lagi kalau key-nya beda. Setelah '
            'key ini disimpan di .env, jalankan "python manage.py encrypt_mssql_password" untuk '
            'enkripsi password MSSQL Anda.'
        ))
