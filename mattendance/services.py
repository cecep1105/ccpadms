"""
Fungsi bantu app mattendance -- SAAT INI cuma 1: jembatani hasil
check-in/out/meal mobile ke konsolidasi tabel `transaction` iclock (device
virtual gabungan 'ABSENDIGITAL01'), TANPA membuat app `iclock` perlu tahu
apa pun soal model mattendance (AttendanceLog) -- cuma data primitif yang
diteruskan (arah dependency: mattendance -> iclock, BUKAN sebaliknya).
"""
import logging

logger = logging.getLogger('mattendance')


def maybe_consolidate_to_iclock(log) -> None:
    """
    Panggil SETELAH AttendanceLog berhasil dibuat (check-in/out/meal
    mobile) -- teruskan ke iclock.services.consolidate_mobile_attendance_to_iclock
    (no-op otomatis kalau device 'ABSENDIGITAL01' belum ada di Active
    Device iclock).

    SENGAJA dibungkus try/except SELUAS FUNGSI INI (bukan cuma di sekitar
    panggilan ke iclock) -- konsolidasi ke iclock ini fitur SEKUNDER,
    kegagalan APA PUN di sini (termasuk bug tak terduga di fungsi ini
    sendiri, bukan cuma error dari sisi iclock) TIDAK BOLEH bikin proses
    check-in/out/meal mobile yang UTAMA (yang sudah berhasil & sudah
    dijawab ke user) ikut gagal/error 500.
    """
    try:
        emp = log.user.EmpID if log.user.EmpID_id else None
        if emp is None:
            logger.info(
                "Konsolidasi ke iclock dilewati utk AttendanceLog #%s: user '%s' tidak terkait Employee (tidak ada PIN).",
                log.pk, log.user.username,
            )
            return

        function_code = (log.Function or '').split('-')[0] if log.Function else ''
        pool_id = log.PoolID_id or ''

        from iclock.services import consolidate_mobile_attendance_to_iclock
        consolidate_mobile_attendance_to_iclock(emp.PIN, log.timestamp, log.check_type, function_code, pool_id)
    except Exception as exc:  # noqa: BLE001
        logger.error("Konsolidasi ke iclock GAGAL utk AttendanceLog #%s: %s", log.pk, exc)