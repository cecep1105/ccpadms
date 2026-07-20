"""
Sumber lookup NAMA employee dari SQL Server eksternal -- dipakai saat
Employee di-auto-create (iclock/tasks.py::write_attlog_to_db/
write_fplog_to_db) tanpa nama, karena device cuma kirim PIN (ATTLOG/FP
TIDAK punya field nama sama sekali -- lihat resume protokol §4). PIN
PREFIX (karakter pertama, SETELAH leading zero dibuang -- lihat
iclock/services.py::get_raw_device_pin) menentukan sumber MANA yang
dicoba, mis. PIN diawali '8'/'9' -> sumber 'karyawan'.

Pola & kredensial koneksi SAMA dgn mclock/sources.py (server/database
MSSQL per sumber, kredensial MCLOCK_MSSQL_USERNAME/
MCLOCK_MSSQL_PASSWORD_ENCRYPTED yang SAMA dipakai bersama) -- TAPI
`base_sql` di sini query 1 BARIS SPESIFIK (WHERE ...=%s, placeholder
`%s` standar pymssql, DIISI SAAT DIPANGGIL lewat `run_query(params=...)`,
BUKAN f-string yang ke-evaluasi saat modul di-import), bukan listing
banyak baris kayak mclock -- pakai
mclock/mssql_client.py::run_query() yang SUDAH ADA, BUKAN
fetch_paginated_from_sql() (itu utk listing+pagination, bukan lookup 1
baris spesifik).

Cuma kolom NAMA yang di-SELECT (bukan Photo/Posisi/Pool/dst spt versi
awal) -- lookup ini cuma butuh nama, kolom lain di luar itu cuma
menambah beban query & risiko error tanpa manfaat di sini.
"""
from collections import OrderedDict

EMPLOYEE_NAME_LOOKUP_SOURCES = OrderedDict([
    ('karyawan', {
        'title': 'Karyawan',
        'prefix': ['8', '9'],
        'server': 'HUPDBTMS',
        'database': 'dbGeneral',
        'base_sql': "SELECT NamaKaryawan FROM dbo.HRD_MsHCP WHERE NIP=%s",
        'name_column': 'NamaKaryawan',
        'param': lambda nip: (nip,),
    }),
    ('driver-hiba', {
        'title': 'Driver Hiba',
        'prefix': ['1'],
        'server': 'BUBBLE',
        'database': 'dbhusamop',
        'base_sql': "SELECT namasim FROM dbo.datapengemudi WHERE id_absen=%s",
        'name_column': 'namasim',
        'param': lambda nip: (nip,),
    }),
    ('driver-hrc', {
        'title': 'Driver HRC',
        'prefix': ['5', '6'],
        'server': 'BUBBLE',
        'database': 'hiba_fleet',
        'base_sql': "SELECT name FROM dbo.m_driver WHERE code=%s",
        'name_column': 'name',
        # 'code' BUKAN nip mentah -- format 'DRV/{2 digit tengah}/00{digit ke-4 dari belakang}'.
        'param': lambda nip: (f"DRV/{nip[1:3]}/00{nip[-4]}",),
    }),
    ('driver-kba', {
        'title': 'Driver KBA',
        'prefix': ['4'],
        'server': 'HUPDBTMS',
        'database': 'dbBMS',
        'base_sql': "SELECT namapengemudi FROM dbo.MSDriverKBA WHERE id_absen=%s",
        'name_column': 'namapengemudi',
        'param': lambda nip: (nip,),
    }),
])


def get_name_lookup_source(raw_pin: str):
    """
    Cari sumber lookup yang cocok berdasar PIN PREFIX (karakter pertama
    PIN MENTAH, bukan yang sudah di-zero-pad -- lihat
    iclock/services.py::get_raw_device_pin). Return (key, source_dict)
    kalau ketemu, None kalau tidak ada prefix yang cocok.
    """
    if not raw_pin:
        return None
    first_char = raw_pin[0]
    for key, source in EMPLOYEE_NAME_LOOKUP_SOURCES.items():
        if first_char in source['prefix']:
            return key, source
    return None