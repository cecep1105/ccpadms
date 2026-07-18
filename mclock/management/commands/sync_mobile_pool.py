"""
Sinkronisasi tabel Mobile Pool dari MSSQL ke database Django lokal
(tabel `MobilePool`, lihat mclock/models.py).

⚠️ BELUM LENGKAP -- nama tabel sumber MSSQL (beserta server/database-nya)
belum diketahui saat file ini dibuat. Isi 3 konstanta TODO di bawah sebelum
dipakai:
    MOBILE_POOL_SOURCE_SERVER, MOBILE_POOL_SOURCE_DATABASE, MOBILE_POOL_SOURCE_SQL

Query sumbernya HARUS menghasilkan kolom: PoolID, PoolCode, PoolName,
Latitude, Longitude, Radius (persis sama nama & urutan field di model
MobilePool) -- kalau nama kolom di tabel sumber beda, tinggal alias pakai
`AS` di SQL-nya (sama seperti pola di mclock/sources.py).

Untuk sementara dijalankan MANUAL:
    python manage.py sync_mobile_pool
Nanti dijadwalkan otomatis (mis. tiap N menit) via Celery.
"""
from django.core.management.base import BaseCommand
from django.utils import timezone

from mclock.models import MobilePool
from mclock.mssql_client import MSSQLConnectionError, run_query

# Server/database & nama tabel sumber SUDAH DIKONFIRMASI: HBCLOUD3/General,
# tabel `dbo.MsPool` (BUKAN 'dbo.MobilePool' seperti tebakan awal).
MOBILE_POOL_SOURCE_SERVER = 'HBCLOUD3'
MOBILE_POOL_SOURCE_DATABASE = 'General'
MOBILE_POOL_SOURCE_SQL = (
    "SELECT PoolID, PoolCode, PoolName, Latitude, Longitude, Radius FROM dbo.MsPool"
)


def sync_mobile_pool_from_source(server: str, database: str, sql: str, tds_version: str = None):
    """
    Jalankan sinkronisasi SATU KALI dari MSSQL ke tabel MobilePool lokal --
    dipisah dari `Command.handle()` supaya gampang dipanggil ulang (mis. dari
    task Celery nanti) tanpa perlu lewat command line, dan supaya gampang
    diuji terpisah dari argumen CLI.

    PENTING: ini sinkronisasi PENUH (mirror) -- PoolID yang ADA di database
    lokal tapi SUDAH TIDAK ADA lagi di hasil query sumber MSSQL akan
    DIHAPUS. Tanpa ini, pool yang sudah dihapus/dinonaktifkan di sumber
    akan tetap "hidup" selamanya di database lokal (dan tetap dipakai utk
    verifikasi geofence check-in/out -- celah nyata yang pernah terjadi:
    pool yang sudah dihapus dari sumber tapi record lokalnya tidak ikut
    kehapus, sehingga check-in tetap berhasil match ke pool yang seharusnya
    sudah tidak berlaku).

    Return: dict {'created': int, 'updated': int, 'deleted': int, 'total_from_source': int}.
    Raise MSSQLConnectionError kalau gagal ambil data dari MSSQL.
    """
    rows = run_query(sql, server=server, database=database, tds_version=tds_version)

    now = timezone.now()
    created_count = 0
    updated_count = 0
    seen_pool_ids = []
    for row in rows:
        seen_pool_ids.append(row['PoolID'])
        _, created = MobilePool.objects.update_or_create(
            PoolID=row['PoolID'],
            defaults={
                'PoolCode': row.get('PoolCode'),
                'PoolName': row.get('PoolName'),
                'Latitude': row.get('Latitude'),
                'Longitude': row.get('Longitude'),
                'Radius': row.get('Radius'),
                'SyncedAt': now,
            },
        )
        if created:
            created_count += 1
        else:
            updated_count += 1

    # Hapus pool lokal yang PoolID-nya TIDAK ADA di hasil fetch barusan --
    # kalau `rows` KOSONG (mis. query sumber gagal parsial atau kebetulan
    # kosong sesaat), SENGAJA TIDAK menghapus apa pun (lebih aman salah
    # "biarkan pool lama" daripada salah "hapus SEMUA pool" gara-gara
    # sumbernya kebetulan kosong).
    deleted_count = 0
    if rows:
        deleted_count, _ = MobilePool.objects.exclude(PoolID__in=seen_pool_ids).delete()

    return {
        'created': created_count,
        'updated': updated_count,
        'deleted': deleted_count,
        'total_from_source': len(rows),
    }

    return {'created': created_count, 'updated': updated_count, 'total_from_source': len(rows)}


class Command(BaseCommand):
    help = (
        'Sinkronisasi tabel Mobile Pool dari MSSQL ke database Django lokal. '
        'Untuk sementara dijalankan manual, nanti dijadwalkan via Celery.'
    )

    def handle(self, *args, **options):
        if not MOBILE_POOL_SOURCE_SERVER or not MOBILE_POOL_SOURCE_DATABASE:
            self.stdout.write(self.style.ERROR(
                'Server/database sumber Mobile Pool belum dikonfigurasi. Edit konstanta '
                'MOBILE_POOL_SOURCE_SERVER / MOBILE_POOL_SOURCE_DATABASE / MOBILE_POOL_SOURCE_SQL '
                'di file mclock/management/commands/sync_mobile_pool.py dulu, sesuai tabel sumber '
                'Mobile Pool yang sebenarnya di MSSQL.'
            ))
            return

        self.stdout.write(f'Mengambil data dari {MOBILE_POOL_SOURCE_SERVER}/{MOBILE_POOL_SOURCE_DATABASE} ...')
        try:
            result = sync_mobile_pool_from_source(
                MOBILE_POOL_SOURCE_SERVER, MOBILE_POOL_SOURCE_DATABASE, MOBILE_POOL_SOURCE_SQL,
            )
        except MSSQLConnectionError as exc:
            self.stdout.write(self.style.ERROR(f'Gagal mengambil data dari MSSQL: {exc}'))
            return

        self.stdout.write(self.style.SUCCESS(
            f"Sinkronisasi selesai: {result['created']} pool baru, {result['updated']} pool diperbarui, "
            f"{result['deleted']} pool dihapus (sudah tidak ada di sumber) "
            f"(total {result['total_from_source']} record dari MSSQL)."
        ))
