"""
Enkripsi token API Zentyal Mail (harus SAMA PERSIS dgn ZENTYAL_MAIL_API_TOKEN
yang di-set di server Flask, lihat test/README.md), pakai ZENTYAL_MAIL_ENCRYPTION_KEY
yang sudah di-generate (lihat `generate_zentyal_mail_key`). Hasilnya
disimpan di .env sebagai ZENTYAL_MAIL_API_TOKEN_ENCRYPTED.

Jalankan:
    python manage.py encrypt_zentyal_mail_token
"""
import getpass

from django.core.management.base import BaseCommand

from netmgmt.crypto_utils import NetmgmtCryptoError, encrypt_zentyal_mail_token


class Command(BaseCommand):
    help = 'Enkripsi token API Zentyal Mail (hasil disimpan sbg ZENTYAL_MAIL_API_TOKEN_ENCRYPTED).'

    def handle(self, *args, **options):
        token = getpass.getpass('Masukkan token API Zentyal Mail (tidak akan tampil di layar): ')
        if not token:
            self.stdout.write(self.style.ERROR('Token tidak boleh kosong.'))
            return
        try:
            encrypted = encrypt_zentyal_mail_token(token)
        except NetmgmtCryptoError as exc:
            self.stdout.write(self.style.ERROR(str(exc)))
            return
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS('Token berhasil dienkripsi. Simpan baris berikut di .env:'))
        self.stdout.write('')
        self.stdout.write('ZENTYAL_MAIL_API_TOKEN_ENCRYPTED=%s' % encrypted)
        self.stdout.write('')
