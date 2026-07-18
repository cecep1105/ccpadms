"""
Konfigurasi sumber data Mobile Attendance -- tiap submenu = 1 sumber data
MSSQL yang bisa beda SERVER & DATABASE-nya, tapi semuanya pakai kredensial
(username/password) yang SAMA (lihat MCLOCK_MSSQL_USERNAME/
MCLOCK_MSSQL_PASSWORD_ENCRYPTED di settings.py).

`base_sql` adalah query SELECT LENGKAP (termasuk WHERE clause-nya sendiri)
persis seperti yang diberikan -- search/sort/pagination diterapkan DI ATAS
query ini lewat CTE wrapping (lihat mclock/mssql_client.py::fetch_paginated_from_sql),
jadi `base_sql` di sini TIDAK PERLU diubah/disesuaikan.

Kolom yang di-SELECT semuanya sudah di-alias konsisten: Id, sn, nik, ttime,
ctype, bProses -- dipakai sebagai daftar kolom yang boleh di-search/sort
(lihat MOBILE_ATTENDANCE_SORTABLE_COLUMNS), supaya aman dari SQL injection
lewat parameter ?sort= di URL (nama kolom TIDAK BISA diparameterisasi lewat
placeholder SQL biasa, jadi WAJIB divalidasi dari whitelist ini).
"""
from collections import OrderedDict

MOBILE_ATTENDANCE_SOURCES = OrderedDict([
    ('karyawan-mobile', {
        'title': 'Karyawan Mobile',
        'server': 'WEBFS2',
        'database': 'dbAbsDigital',
        'base_sql': (
            "SELECT Id,PoolID AS sn,DibuatOleh AS nik, DibuatTanggal AS ttime,"
            "Tipe AS ctype, bProses from dbo.TrAbsensi WHERE bProses=0"
        ),
    }),
    ('driver-mobile', {
        'title': 'Driver Mobile',
        'server': 'HUPDBTMS',
        'database': 'dbBMS',
        'base_sql': (
            "SELECT Id,SN AS sn,NIP AS nik, "
            "convert(datetime,convert(varchar(10),tanggal,121)+' '+jam) AS ttime,"
            "Keterangan AS ctype, bTransfer AS bProses "
            "from dbo.AbsenOtomatis "
            "WHERE bTransfer=0 AND SN IN ('Mobile','101D','102','104','112','113','111')"
        ),
    }),
    ('mitra-mobile', {
        'title': 'Mitra Mobile',
        'server': 'HBCLOUD3',
        'database': 'GeneralMitra',
        'base_sql': (
            "SELECT Id,PoolID AS sn,DibuatOleh AS nik, DibuatTanggal AS ttime,"
            "Tipe AS ctype, bProses "
            "FROM dbo.TrAbsensiMitra "
            "WHERE bProses=0 AND (LEFT(DibuatOleh,2) IN ('31','32','33') OR DibuatOleh LIKE '7%')"
        ),
    }),
    ('kantin-mobile', {
        'title': 'Kantin Mobile',
        'server': 'WEBFS2',
        'database': 'dbAbsDigital',
        'base_sql': (
            "SELECT Id,PoolID AS sn,DibuatOleh AS nik, DibuatTanggal AS ttime,"
            "Tipe AS ctype, bProses from dbo.TrAbsensiMakan WHERE bProses=0"
        ),
    }),
    ('kantin-mitra-mobile', {
        'title': 'Kantin Mitra Mobile',
        'server': 'WEBFS2',
        'database': 'dbAbsDigital',
        'base_sql': (
            "SELECT Id,PoolID AS sn,DibuatOleh AS nik, DibuatTanggal AS ttime,"
            "Tipe AS ctype, bProses from dbo.TrAbsensiMakanMitra WHERE bProses=0"
        ),
    }),
])

# Kolom yang boleh di-search/sort (whitelist -- WAJIB dicek sebelum dipakai
# di SQL, karena nama kolom tidak bisa diparameterisasi seperti value biasa).
MOBILE_ATTENDANCE_COLUMNS = ['Id', 'sn', 'nik', 'ttime', 'ctype', 'bProses']

# Kolom yang dipakai utk search (sesuai permintaan: 'DibuatOleh' / 'NIP',
# yang di semua sumber data di atas sudah konsisten di-alias jadi 'nik').
MOBILE_ATTENDANCE_SEARCH_COLUMN = 'nik'

# Daftar (server, database) UNIK yang dipakai di semua sumber data -- dipakai
# utk fitur "Test Koneksi" supaya tiap kombinasi server/database dicek
# masing-masing (bukan cuma satu, karena ternyata beda-beda per submenu).
MOBILE_ATTENDANCE_UNIQUE_TARGETS = list({
    (src['server'], src['database']) for src in MOBILE_ATTENDANCE_SOURCES.values()
})
