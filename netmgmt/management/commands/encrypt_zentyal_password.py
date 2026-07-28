"""
Enkripsi password bind Zentyal LDAP untuk fitur netmgmt, pakai
ZENTYAL_ENCRYPTION_KEY yang sudah di-generate (lihat `generate_zentyal_key`).
Hasilnya (string base64) disimpan di .env sebagai ZENTYAL_BIND_PASSWORD_ENCRYPTED.

Jalankan:
    python manage.py encrypt_zentyal_password
"""
import getpass

from django.core.management.base import BaseCommand

from netmgmt.crypto_utils import NetmgmtCryptoError, encrypt_zentyal_password


class Command(BaseCommand):
    help = 'Enkripsi password bind Zentyal LDAP (hasil disimpan sbg ZENTYAL_BIND_PASSWORD_ENCRYPTED).'

    def handle(self, *args, **options):
        password = getpass.getpass('Masukkan password bind Zentyal (tidak akan tampil di layar): ')
        if not password:
            self.stdout.write(self.style.ERROR('Password tidak boleh kosong.'))
            return
        try:
            encrypted = encrypt_zentyal_password(password)
        except NetmgmtCryptoError as exc:
            self.stdout.write(self.style.ERROR(str(exc)))
            return
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS('Password berhasil dienkripsi. Simpan baris berikut di .env:'))
        self.stdout.write('')
        self.stdout.write(f'ZENTYAL_BIND_PASSWORD_ENCRYPTED={encrypted}')
        self.stdout.write('')
