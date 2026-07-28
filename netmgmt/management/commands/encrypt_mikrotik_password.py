"""
Enkripsi password MSSQL untuk fitur Mobile Attendance, pakai
MCLOCK_ENCRYPTION_KEY yang sudah di-generate (lihat `generate_mclock_key`).
Hasilnya (string base64) disimpan di .env sebagai MCLOCK_MSSQL_PASSWORD_ENCRYPTED.

Jalankan:
    python manage.py encrypt_mikrotik_password
"""
import getpass

from django.core.management.base import BaseCommand

from mclock.crypto_utils import MclockCryptoError, encrypt_password


class Command(BaseCommand):
    help = (
        'MIKROTIK_PASSWORD_ENCRYPTED). Perlu MIKROTIK_ENCRYPTION_KEY sudah diisi lebih dulu.'
    )

    def handle(self, *args, **options):
        password = getpass.getpass('Masukkan password MIKROTIK (tidak akan tampil di layar): ')
        if not password:
            self.stdout.write(self.style.ERROR('Password tidak boleh kosong.'))
            return

        try:
            encrypted = encrypt_password(password)
        except MclockCryptoError as exc:
            self.stdout.write(self.style.ERROR(str(exc)))
            return

        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS('Password berhasil dienkripsi. Simpan baris berikut di .env:'))
        self.stdout.write('')
        self.stdout.write(f'MIKROTIK_PASSWORD_ENCRYPTED={encrypted}')
        self.stdout.write('')
