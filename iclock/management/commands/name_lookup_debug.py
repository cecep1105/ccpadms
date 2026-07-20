"""
Tool diagnostik untuk troubleshoot "nama employee auto-create tidak
muncul" -- menelusuri SETIAP langkah alur lookup nama satu-satu: apakah
proses INI (management command) baca versi kode yang benar, apakah
prefix PIN cocok ke sumber manapun, apakah koneksi MSSQL sukses & dapat
baris hasilnya, sampai cek kondisi Employee SEKARANG di database (apakah
sudah ke-auto-create SEBELUM fitur lookup ini ada, sehingga lookup
di-skip).

Contoh pakai:
    python manage.py name_lookup_debug 8326004
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Debug fitur lookup nama employee dari SQL Server (auto-create push protocol).'

    def add_arguments(self, parser):
        parser.add_argument('pin', help='PIN employee (boleh dgn atau tanpa nol di depan)')

    def handle(self, *args, **options):
        raw_pin_input = options['pin'].strip()

        self.stdout.write('=== 1. Cek signature lookup_employee_name() SEBAGAIMANA DIMUAT proses ini ===')
        import inspect

        from iclock.services import get_raw_device_pin, lookup_employee_name, normalize_pin
        sig = inspect.signature(lookup_employee_name)
        source_file = inspect.getfile(lookup_employee_name)
        self.stdout.write(f'  Signature: lookup_employee_name{sig}')
        self.stdout.write(f'  Dimuat dari file: {source_file}')
        if 'raw_pin' not in sig.parameters:
            self.stdout.write(self.style.ERROR(
                "  MASALAH -- fungsi lookup_employee_name TIDAK DITEMUKAN/beda signature! "
                "File iclock/services.py di server ini kemungkinan belum ter-update."
            ))
            return
        self.stdout.write(self.style.SUCCESS('  OK -- fungsi lookup_employee_name ada di iclock/services.py.'))

        self.stdout.write('\n=== 2. Normalisasi & PIN mentah ===')
        raw_pin = get_raw_device_pin(raw_pin_input)
        normalized_pin = normalize_pin(raw_pin_input)
        self.stdout.write(f"  PIN diketik      : '{raw_pin_input}'")
        self.stdout.write(f"  PIN mentah (raw) : '{raw_pin}' (dipakai utk lookup & cocokkan prefix)")
        self.stdout.write(f"  PIN dinormalisasi: '{normalized_pin}' (dipakai utk simpan/cari di tabel Employee)")

        self.stdout.write('\n=== 3. Cek sumber lookup yang cocok (prefix PIN) ===')
        from iclock.sources import EMPLOYEE_NAME_LOOKUP_SOURCES, get_name_lookup_source
        self.stdout.write(f'  Sumber terdaftar: {list(EMPLOYEE_NAME_LOOKUP_SOURCES.keys())}')
        found = get_name_lookup_source(raw_pin)
        if found is None:
            self.stdout.write(self.style.ERROR(
                f"  TIDAK ADA sumber yang cocok utk PIN '{raw_pin}' (prefix '{raw_pin[0] if raw_pin else ''}') "
                "-- lookup TIDAK akan pernah dicoba, Employee auto-create SELALU tanpa nama utk PIN ini."
            ))
            return
        key, source = found
        self.stdout.write(self.style.SUCCESS(f"  Cocok ke sumber '{key}' ({source['title']}) -- server={source['server']}, database={source['database']}"))
        params = source['param'](raw_pin)
        self.stdout.write(f"  Parameter query: {params}")
        self.stdout.write(f"  SQL: {source['base_sql']}")

        self.stdout.write('\n=== 4. Cek kredensial MSSQL (MCLOCK_MSSQL_USERNAME/PASSWORD_ENCRYPTED) ===')
        from django.conf import settings
        username = getattr(settings, 'MCLOCK_MSSQL_USERNAME', None)
        password_encrypted = getattr(settings, 'MCLOCK_MSSQL_PASSWORD_ENCRYPTED', None)
        self.stdout.write(f'  MCLOCK_MSSQL_USERNAME diisi? {bool(username)}')
        self.stdout.write(f'  MCLOCK_MSSQL_PASSWORD_ENCRYPTED diisi? {bool(password_encrypted)}')
        if not username or not password_encrypted:
            self.stdout.write(self.style.ERROR(
                '  MASALAH -- kredensial MSSQL belum diisi di .env. Ini KEMUNGKINAN BESAR penyebab '
                'nama tidak pernah muncul (lookup selalu gagal koneksi, tapi Employee tetap dibuat '
                'tanpa nama -- gagal SENYAP, cuma kelihatan di log warning).'
            ))

        self.stdout.write('\n=== 5. Tes KONEKSI & QUERY MSSQL SUNGGUHAN ===')
        from mclock.mssql_client import MSSQLConnectionError, run_query
        try:
            rows = run_query(source['base_sql'], params=params, server=source['server'], database=source['database'])
            self.stdout.write(self.style.SUCCESS(f'  OK -- query berhasil, {len(rows)} baris hasil.'))
            if rows:
                self.stdout.write(f'  Baris pertama: {rows[0]}')
                name_value = rows[0].get(source['name_column'])
                self.stdout.write(f"  Nilai kolom '{source['name_column']}': {name_value!r}")
                if not name_value:
                    self.stdout.write(self.style.WARNING(
                        f"  Kolom '{source['name_column']}' ADA di hasil tapi KOSONG/None -- cek lagi nama "
                        'kolom di base_sql, mungkin salah ketik/beda dari yang sebenarnya di tabel sumber.'
                    ))
            else:
                self.stdout.write(self.style.WARNING(
                    f"  Query BERHASIL tapi TIDAK ADA baris hasil utk parameter {params} -- PIN ini "
                    'kemungkinan memang tidak ada di tabel sumber, ATAU parameter query-nya (lihat '
                    "param() di iclock/sources.py) tidak cocok format kolom aslinya."
                ))
        except MSSQLConnectionError as exc:
            self.stdout.write(self.style.ERROR(f'  GAGAL -- {exc}'))
            self.stdout.write(self.style.ERROR(
                '  --> Ini penyebab nama tidak muncul. Cek: server/database benar, kredensial benar, '
                'firewall/network dari server Django ke SQL Server tsb terbuka.'
            ))
        except Exception as exc:  # noqa: BLE001
            self.stdout.write(self.style.ERROR(f'  ERROR TAK TERDUGA saat build parameter/query: {type(exc).__name__}: {exc}'))
            self.stdout.write(self.style.ERROR(
                "  --> Kemungkinan param() di iclock/sources.py error (mis. PIN terlalu pendek utk "
                "transformasi khusus driver-hrc, butuh minimal beberapa digit)."
            ))

        self.stdout.write('\n=== 6. Kondisi Employee SEKARANG di database ===')
        from iclock.models import employee
        emp = employee.objects.filter(PIN=normalized_pin).first()
        if emp is None:
            self.stdout.write('  Employee dgn PIN ini BELUM ada di database sama sekali (belum pernah check-in).')
        else:
            self.stdout.write(f"  Employee SUDAH ADA: PIN={emp.PIN}, EName={emp.EName!r}")
            self.stdout.write(self.style.WARNING(
                '  --> PENTING: karena Employee ini SUDAH ADA, `write_attlog_to_db`/`write_fplog_to_db` '
                'TIDAK akan mencoba lookup nama lagi sama sekali (optimasi: lookup MSSQL cukup sekali, '
                'bukan tiap check-in) -- kalau nama-nya kosong, itu karena Employee ini ke-auto-create '
                'SEBELUM fitur lookup dipasang (atau lookup sempat gagal saat itu). Untuk PIN yang SUDAH '
                'terlanjur ada tanpa nama, isi manual lewat dashboard, ATAU hapus dulu barisnya supaya '
                'lookup dicoba ulang saat check-in berikutnya (HANYA relevan utk PIN test, JANGAN hapus '
                'Employee yang datanya sudah dipakai/ada history attendance sungguhan).'
            ))