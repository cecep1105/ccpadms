from celery import shared_task

from mclock.services import (
    sync_mobile_pool_loc_from_source,
    MOBILE_POOL_LOC_SOURCE_SERVER,
    MOBILE_POOL_LOC_SOURCE_DATABASE,
    MOBILE_POOL_LOC_SOURCE_SQL,
)


@shared_task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
)
def sync_mobile_pool_loc_task(self):
    return sync_mobile_pool_loc_from_source(
        server=MOBILE_POOL_LOC_SOURCE_SERVER,
        database=MOBILE_POOL_LOC_SOURCE_DATABASE,
        sql=MOBILE_POOL_LOC_SOURCE_SQL,
    )