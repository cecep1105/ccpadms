from django.utils import timezone
from mclock.models import MobilePoolLoc
from mclock.mssql_client import run_query

MOBILE_POOL_LOC_SOURCE_SERVER = "HBCLOUD3"
MOBILE_POOL_LOC_SOURCE_DATABASE = "General"

MOBILE_POOL_LOC_SOURCE_SQL = """
SELECT
    PoolID,
    Urut,
    Latitude,
    Longitude
FROM dbo.MsPool_Loc
"""


def sync_mobile_pool_loc_from_source(
    server: str,
    database: str,
    sql: str,
    tds_version: str = None,
):
    rows = run_query(
        sql,
        server=server,
        database=database,
        tds_version=tds_version,
    )

    now = timezone.now()

    created_count = 0
    updated_count = 0
    touched_ids = []

    for row in rows:
        obj, created = MobilePoolLoc.objects.update_or_create(
            PoolID=row["PoolID"],
            Urut=row["Urut"],
            defaults={
                "Latitude": row.get("Latitude"),
                "Longitude": row.get("Longitude"),
                "SyncedAt": now,
            },
        )

        touched_ids.append(obj.pk)

        if created:
            created_count += 1
        else:
            updated_count += 1

    deleted_count = 0

    if rows:
        deleted_count, _ = (
            MobilePoolLoc.objects
            .exclude(pk__in=touched_ids)
            .delete()
        )

    return {
        "created": created_count,
        "updated": updated_count,
        "deleted": deleted_count,
        "total_from_source": len(rows),
    }