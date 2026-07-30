"""
Enkripsi password vCenter, pakai VMWARE_ENCRYPTION_KEY yang sudah
di-generate (lihat `generate_vmware_key`). Hasilnya disimpan di .env
sebagai VMWARE_PASSWORD_ENCRYPTED.

Jalankan:
    python manage.py encrypt_vmware_password
"""
import getpass

from django.core.management.base import BaseCommand

from netmgmt.crypto_utils import NetmgmtCryptoError, encrypt_vmware_password


class Command(BaseCommand):
    help = 'Enkripsi password VMware vCenter (hasil disimpan sbg VMWARE_PASSWORD_ENCRYPTED).'

    def handle(self, *args, **options):
        password = getpass.getpass('Masukkan password vCenter (tidak akan tampil di layar): ')
        if not password:
            self.stdout.write(self.style.ERROR('Password tidak boleh kosong.'))
            return
        try:
            encrypted = encrypt_vmware_password(password)
        except NetmgmtCryptoError as exc:
            self.stdout.write(self.style.ERROR(str(exc)))
            return
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS('Password berhasil dienkripsi. Simpan baris berikut di .env:'))
        self.stdout.write('')
        self.stdout.write('VMWARE_PASSWORD_ENCRYPTED=%s' % encrypted)
        self.stdout.write('')
