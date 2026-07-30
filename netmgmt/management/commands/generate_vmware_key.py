"""
Generate encryption key (Fernet) KHUSUS password vCenter (SOAP API via
pyVmomi, lihat netmgmt/vmware_view.py) -- hasilnya disimpan di .env
sebagai VMWARE_ENCRYPTION_KEY.

Jalankan:
    python manage.py generate_vmware_key
"""
from cryptography.fernet import Fernet
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Generate encryption key (Fernet) baru untuk enkripsi password VMware vCenter (netmgmt).'

    def handle(self, *args, **options):
        key = Fernet.generate_key().decode()
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS('Key berhasil dibuat. Simpan baris berikut di .env:'))
        self.stdout.write('')
        self.stdout.write('VMWARE_ENCRYPTION_KEY=%s' % key)
        self.stdout.write('')
