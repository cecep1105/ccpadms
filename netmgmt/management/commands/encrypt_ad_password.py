"""
Enkripsi password service account Active Directory untuk fitur netmgmt,
pakai AD_ENCRYPTION_KEY yang sudah di-generate (lihat `generate_ad_key`).
Hasilnya (string base64) disimpan di .env sebagai AD_BIND_PASSWORD_ENCRYPTED.

Jalankan:
    python manage.py encrypt_ad_password
"""
import getpass

from django.core.management.base import BaseCommand

from netmgmt.crypto_utils import NetmgmtCryptoError, encrypt_ad_password


class Command(BaseCommand):
    help = (
        'Enkripsi password service account AD (hasil disimpan sbg AD_BIND_PASSWORD_ENCRYPTED). '
        'Perlu AD_ENCRYPTION_KEY sudah diisi lebih dulu (lihat generate_ad_key).'
    )

    def handle(self, *args, **options):
        password = getpass.getpass('Masukkan password service account AD (tidak akan tampil di layar): ')
        if not password:
            self.stdout.write(self.style.ERROR('Password tidak boleh kosong.'))
            return

        try:
            encrypted = encrypt_ad_password(password)
        except NetmgmtCryptoError as exc:
            self.stdout.write(self.style.ERROR(str(exc)))
            return

        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS('Password berhasil dienkripsi. Simpan baris berikut di .env:'))
        self.stdout.write('')
        self.stdout.write(f'AD_BIND_PASSWORD_ENCRYPTED={encrypted}')
        self.stdout.write('')
