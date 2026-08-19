"""
Sinkronisasi tabel Mobile Pool Location (titik-titik polygon geofence) dari
MSSQL ke database Django lokal (tabel `MobilePoolLoc`, lihat mclock/models.py).

Server/database & tabel sumber SUDAH DIKONFIRMASI: HBCLOUD3/General,
tabel `dbo.MsPool_Loc` (sama server/database dgn Mobile Pool biasa yang
tabel sumbernya `dbo.MsPool` -- lihat sync_mobile_pool.py).

Untuk sementara dijalankan MANUAL:
    python manage.py sync_mobile_pool_loc
Nanti dijadwalkan otomatis (mis. tiap N menit) via Celery -- sama seperti
`sync_mobile_pool`.
"""
from django.core.management.base import BaseCommand
from django.utils import timezone

from mclock.models import MobilePoolLoc
from mclock.mssql_client import MSSQLConnectionError, run_query

MOBILE_POOL_LOC_SOURCE_SERVER = 'HBCLOUD3'
MOBILE_POOL_LOC_SOURCE_DATABASE = 'General'
MOBILE_POOL_LOC_SOURCE_SQL = (
    "SELECT PoolID, Urut, Latitude, Longitude FROM dbo.MsPool_Loc"
)


def sync_mobile_pool_loc_from_source(server: str, database: str, sql: str, tds_version: str = None):
    """
    Jalankan sinkronisasi SATU KALI dari MSSQL ke tabel MobilePoolLoc lokal
    -- dipisah dari `Command.handle()` supaya gampang dipanggil ulang (mis.
    dari task Celery nanti) & gampang diuji terpisah dari argumen CLI.

    Identitas unik 1 baris = kombinasi (PoolID, Urut) -- BUKAN PoolID saja,
    karena 1 PoolID normalnya punya BANYAK titik (satu polygon = banyak
    vertex, masing-masing row dgn Urut berbeda).

    Sinkronisasi PENUH (mirror), sama seperti `sync_mobile_pool`: titik yang
    ADA di lokal tapi SUDAH TIDAK ADA lagi di hasil fetch MSSQL (baik
    individual titik-nya, MAUPUN seluruh PoolID-nya kalau polygon itu
    dihapus total dari sumber) akan DIHAPUS -- supaya polygon yang sudah
    tidak berlaku tidak terus dipakai verifikasi geofence.

    Return: dict {'created': int, 'updated': int, 'deleted': int, 'total_from_source': int}.
    Raise MSSQLConnectionError kalau gagal ambil data dari MSSQL.
    """
    rows = run_query(sql, server=server, database=database, tds_version=tds_version)

    now = timezone.now()
    created_count = 0
    updated_count = 0
    touched_ids = []

    for row in rows:
        obj, created = MobilePoolLoc.objects.update_or_create(
            PoolID=row['PoolID'],
            Urut=row['Urut'],
            defaults={
                'Latitude': row.get('Latitude'),
                'Longitude': row.get('Longitude'),
                'SyncedAt': now,
            },
        )
        touched_ids.append(obj.pk)
        if created:
            created_count += 1
        else:
            updated_count += 1

    # Hapus titik lokal yang TIDAK ikut ter-touch barusan -- sama seperti
    # sync_mobile_pool, SENGAJA tidak menghapus apa pun kalau `rows` kosong
    # (lebih aman "biarkan data lama" drpd tidak sengaja menghapus semua
    # polygon gara-gara sumbernya kebetulan kosong/gagal parsial).
    deleted_count = 0
    if rows:
        deleted_count, _ = MobilePoolLoc.objects.exclude(pk__in=touched_ids).delete()

    return {
        'created': created_count,
        'updated': updated_count,
        'deleted': deleted_count,
        'total_from_source': len(rows),
    }


class Command(BaseCommand):
    help = (
        'Sinkronisasi tabel Mobile Pool Location (titik polygon geofence) dari MSSQL ke database '
        'Django lokal. Untuk sementara dijalankan manual, nanti dijadwalkan via Celery.'
    )

    def handle(self, *args, **options):
        self.stdout.write(f'Mengambil data dari {MOBILE_POOL_LOC_SOURCE_SERVER}/{MOBILE_POOL_LOC_SOURCE_DATABASE} ...')
        try:
            result = sync_mobile_pool_loc_from_source(
                MOBILE_POOL_LOC_SOURCE_SERVER, MOBILE_POOL_LOC_SOURCE_DATABASE, MOBILE_POOL_LOC_SOURCE_SQL,
            )
        except MSSQLConnectionError as exc:
            self.stdout.write(self.style.ERROR(f'Gagal mengambil data dari MSSQL: {exc}'))
            return

        self.stdout.write(self.style.SUCCESS(
            f"Sinkronisasi selesai: {result['created']} titik baru, {result['updated']} titik diperbarui, "
            f"{result['deleted']} titik dihapus (sudah tidak ada di sumber) "
            f"(total {result['total_from_source']} record dari MSSQL)."
        ))
