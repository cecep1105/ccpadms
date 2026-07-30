"""
Enkripsi token API Cloudflare (buat di dashboard Cloudflare -> My Profile
-> API Tokens -> Create Token, scope minimal "Zone:DNS:Edit" utk zone
yang mau dikelola), pakai CLOUDFLARE_ENCRYPTION_KEY yang sudah
di-generate (lihat `generate_cloudflare_key`). Hasilnya disimpan di .env
sebagai CLOUDFLARE_API_TOKEN_ENCRYPTED.

Jalankan:
    python manage.py encrypt_cloudflare_token
"""
import getpass

from django.core.management.base import BaseCommand

from netmgmt.crypto_utils import NetmgmtCryptoError, encrypt_cloudflare_token


class Command(BaseCommand):
    help = 'Enkripsi token API Cloudflare (hasil disimpan sbg CLOUDFLARE_API_TOKEN_ENCRYPTED).'

    def handle(self, *args, **options):
        token = getpass.getpass('Masukkan token API Cloudflare (tidak akan tampil di layar): ')
        if not token:
            self.stdout.write(self.style.ERROR('Token tidak boleh kosong.'))
            return
        try:
            encrypted = encrypt_cloudflare_token(token)
        except NetmgmtCryptoError as exc:
            self.stdout.write(self.style.ERROR(str(exc)))
            return
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS('Token berhasil dienkripsi. Simpan baris berikut di .env:'))
        self.stdout.write('')
        self.stdout.write('CLOUDFLARE_API_TOKEN_ENCRYPTED=%s' % encrypted)
        self.stdout.write('')
