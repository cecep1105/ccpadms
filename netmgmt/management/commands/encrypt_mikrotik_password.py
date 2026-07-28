"""
Enkripsi password Mikrotik untuk fitur netmgmt, pakai
MIKROTIK_ENCRYPTION_KEY yang sudah di-generate (lihat `generate_mikrotik_key`).
Hasilnya (string base64) disimpan di .env sebagai MIKROTIK_PASSWORD_ENCRYPTED.

Jalankan:
    python manage.py encrypt_mikrotik_password
"""
import getpass

from django.core.management.base import BaseCommand

from netmgmt.crypto_utils import NetmgmtCryptoError, encrypt_mikrotik_password


class Command(BaseCommand):
    help = (
        'Enkripsi password Mikrotik (hasil disimpan sbg MIKROTIK_PASSWORD_ENCRYPTED). '
        'Perlu MIKROTIK_ENCRYPTION_KEY sudah diisi lebih dulu (lihat generate_mikrotik_key).'
    )

    def handle(self, *args, **options):
        password = getpass.getpass('Masukkan password Mikrotik (tidak akan tampil di layar): ')
        if not password:
            self.stdout.write(self.style.ERROR('Password tidak boleh kosong.'))
            return

        try:
            encrypted = encrypt_mikrotik_password(password)
        except NetmgmtCryptoError as exc:
            self.stdout.write(self.style.ERROR(str(exc)))
            return

        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS('Password berhasil dienkripsi. Simpan baris berikut di .env:'))
        self.stdout.write('')
        self.stdout.write(f'MIKROTIK_PASSWORD_ENCRYPTED={encrypted}')
        self.stdout.write('')
