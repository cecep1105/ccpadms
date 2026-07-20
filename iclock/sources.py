from collections import OrderedDict

nip=''

EMPLOYEE_NAME_LOOK_SOURCES = OrderedDict([
    ('karyawan', {
        'title': 'Karyawan',
        'prefix': ['8','9'],
        'server': 'HUPDBTMS',
        'database': 'dbGeneral',
        'base_sql': (
            f"SELECT NamaKaryawan, Posisi, Pool from dbo.HRD_MsHCP WHERE NIP='{nip}'"
        ),
    }),
    ('driver-hiba', {
        'title': 'Driver Hiba',
        'prefix': ['1'],
        'server': 'BUBBLE',
        'database': 'dbhusamop',
        'base_sql': (
            f"SELECT sopirid,namasim,photo,id_absen from dbo.datapengemudi WHERE id_absen='{nip}'"
        ),
    }),
    ('driver-hrc', {
        'title': 'Driver HRC',
        'prefix': ['5','6'],
        'server': 'BUBBLE',
        'database': 'hiba_fleet',
        'base_sql': (
            f"SELECT name,code from dbo.m_driver WHERE code='DRV/{nip[1:3]}/00{nip[-4]}'"
        ),
    }),
    ('driver-kba', {
        'title': 'Driver KBA',
        'prefix': ['4'],
        'server': 'HUPDBTMS',
        'database': 'dbBMS',
        'base_sql': (
	        f"SET TEXTSIZE 2147483647; SELECT id_absen,namapengemudi,Photo,Photo3 FROM dbo.MSDriverKBA WHERE id_absen='{nip}'"
        ),
    }),

])

