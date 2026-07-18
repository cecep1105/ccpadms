"""
Koneksi ke MSSQL Server EKSTERNAL (database sumber data Mobile Attendance,
di luar sistem Django ini) via pymssql -- READ-ONLY murni untuk monitoring.

PENTING: modul ini TIDAK PERNAH menulis/mengubah data apapun di MSSQL. Data
di MSSQL ini sebenarnya dijadwalkan ditarik (sync) ke database Django oleh
proses TERPISAH di luar sistem ini -- halaman Mobile Attendance cuma
menampilkan data yang BELUM diproses, murni untuk pemantauan.

Tiap submenu Mobile Attendance bisa punya SERVER & DATABASE yang BEDA (lihat
mclock/sources.py), tapi semuanya pakai kredensial (username/password) yang
SAMA dari settings -- karena itu `server`/`database` di sini adalah
parameter OPSIONAL yang meng-override nilai default dari settings.

Mendukung SQL Server versi lama (2008/2008 R2) yang PERLU:
1. `tds_version='7.0'` eksplisit saat konek -- tanpa ini beberapa server
   lama menolak koneksi dgn error "Adaptive Server connection failed".
2. Fallback query pagination pakai ROW_NUMBER() -- SQL Server < 2012 TIDAK
   mendukung `OFFSET ... FETCH NEXT ... ROWS ONLY`.
"""
import logging
from functools import lru_cache

from django.conf import settings

from .crypto_utils import MclockCryptoError, decrypt_password

logger = logging.getLogger('mclock')

MSSQL_DEFAULT_TIMEOUT = 10  # detik

# Versi mayor SQL Server minimal yang mendukung OFFSET/FETCH (SQL Server
# 2012 = versi internal 11.x). Di bawah ini (2008=10.x, 2005=9.x) pakai
# fallback ROW_NUMBER().
SQLSERVER_OFFSET_FETCH_MIN_VERSION = 11


class MSSQLConnectionError(Exception):
    """Gagal terhubung atau menjalankan query ke MSSQL Server."""


def get_mssql_connection(server: str = None, database: str = None, tds_version: str = None,
                          timeout: int = MSSQL_DEFAULT_TIMEOUT):
    """
    Buka koneksi BARU ke MSSQL Server pakai kredensial dari settings
    (password didekripsi runtime dari MCLOCK_MSSQL_PASSWORD_ENCRYPTED,
    TIDAK PERNAH disimpan plaintext di mana pun).

    `server`/`database`: opsional, override `MCLOCK_MSSQL_HOST`/
    `MCLOCK_MSSQL_DATABASE` dari settings -- dipakai karena tiap submenu
    Mobile Attendance bisa nunjuk ke server/database MSSQL yang berbeda,
    walau username/password-nya tetap sama.

    `tds_version`: opsional, override `MCLOCK_MSSQL_TDS_VERSION` dari
    settings -- SQL Server versi lama (2008/2008 R2) butuh '7.0' eksplisit,
    kalau tidak koneksi gagal dgn error "Adaptive Server connection failed".

    Caller WAJIB menutup koneksinya sendiri (pakai `with` atau try/finally
    + `.close()`) -- lihat `run_query()` di bawah untuk pola siap-pakai yang
    sudah menangani ini secara otomatis.

    Raise MSSQLConnectionError kalau gagal konek (setting belum lengkap,
    password gagal didekripsi, server tidak terjangkau, dsb).
    """
    host = server or settings.MCLOCK_MSSQL_HOST
    db = database or settings.MCLOCK_MSSQL_DATABASE
    tds = tds_version or settings.MCLOCK_MSSQL_TDS_VERSION

    if not host:
        raise MSSQLConnectionError(
            'Server MSSQL belum diisi (MCLOCK_MSSQL_HOST di .env, atau parameter server tidak diisi).'
        )

    try:
        password = decrypt_password(settings.MCLOCK_MSSQL_PASSWORD_ENCRYPTED)
    except MclockCryptoError as exc:
        raise MSSQLConnectionError(str(exc)) from exc

    try:
        import pymssql
    except ImportError as exc:
        raise MSSQLConnectionError("Library 'pymssql' belum terinstall di server. Jalankan: pip install pymssql") from exc

    try:
        return pymssql.connect(
            server=host,
            port=str(settings.MCLOCK_MSSQL_PORT),
            user=settings.MCLOCK_MSSQL_USERNAME,
            password=password,
            database=db,
            as_dict=True,  # baris hasil query berupa dict {kolom: nilai}, bukan tuple posisional
            timeout=timeout,
            login_timeout=timeout,
            tds_version=tds,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning('Gagal konek ke MSSQL %s:%s/%s (tds_version=%s) -> %s', host, settings.MCLOCK_MSSQL_PORT, db, tds, exc)
        raise MSSQLConnectionError(f'Gagal terhubung ke MSSQL {host}/{db}: {exc}') from exc


def run_query(sql: str, params: tuple = None, server: str = None, database: str = None,
              tds_version: str = None, timeout: int = MSSQL_DEFAULT_TIMEOUT) -> list:
    """
    Jalankan SATU query SELECT read-only ke MSSQL, return list of dict (1 dict
    per baris). Koneksi otomatis dibuka & ditutup dalam fungsi ini -- dipakai
    untuk query sekali-jalan yang sederhana (mis. isi 1 halaman tabel).

    `params`: tuple parameter query (dipakai dengan placeholder %s di `sql`,
    format standar pymssql) -- SELALU pakai ini utk nilai dinamis (search,
    filter, dsb), JANGAN string-format manual ke `sql`, supaya aman dari SQL
    injection.

    Error APAPUN (gagal konek, ATAU query-nya sendiri gagal dieksekusi --
    mis. nama tabel salah, kolom tidak ada, syntax error) dibungkus jadi
    MSSQLConnectionError yang sama, supaya caller cukup tangani SATU jenis
    exception dan dapat pesan yang konsisten & rapi (bukan traceback pymssql
    mentah yang membingungkan).
    """
    conn = None
    try:
        conn = get_mssql_connection(server=server, database=database, tds_version=tds_version, timeout=timeout)
        cursor = conn.cursor()
        cursor.execute(sql, params or ())
        rows = cursor.fetchall()
        cursor.close()
        return rows
    except MSSQLConnectionError:
        raise  # sudah dibungkus rapi dari get_mssql_connection(), teruskan apa adanya
    except Exception as exc:  # noqa: BLE001
        logger.warning('Gagal menjalankan query ke MSSQL %s/%s -> %s', server, database, exc)
        raise MSSQLConnectionError(
            f'Query ke MSSQL {server or "(default)"}/{database or "(default)"} gagal dijalankan: {exc}'
        ) from exc
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass


@lru_cache(maxsize=32)
def get_sqlserver_major_version(server: str, database: str, tds_version: str = None,
                                 timeout: int = MSSQL_DEFAULT_TIMEOUT) -> int:
    """
    Deteksi versi mayor SQL Server (10=2008, 11=2012, 12=2014, dst) --
    di-cache per (server, database) supaya tidak query ulang tiap request
    (versi server praktis tidak pernah berubah selama aplikasi jalan).

    Return 0 kalau gagal deteksi (mis. permission SERVERPROPERTY terbatas)
    -- caller HARUS menganggap 0 sebagai "tidak diketahui, pakai fallback
    paling kompatibel" (ROW_NUMBER()), bukan error fatal.
    """
    try:
        rows = run_query(
            "SELECT CAST(SERVERPROPERTY('ProductVersion') AS VARCHAR(30)) AS ver",
            server=server, database=database, tds_version=tds_version, timeout=timeout,
        )
        if not rows or not rows[0].get('ver'):
            return 0
        return int(str(rows[0]['ver']).split('.')[0])
    except Exception as exc:  # noqa: BLE001
        logger.warning('Gagal deteksi versi SQL Server %s/%s -> %s (pakai fallback ROW_NUMBER)', server, database, exc)
        return 0


def fetch_paginated_from_sql(base_sql: str, server: str, database: str,
                              search_column: str = None, search_term: str = '',
                              sort_column: str = None, sort_direction: str = 'desc',
                              page: int = 1, page_size: int = 10,
                              tds_version: str = None, timeout: int = MSSQL_DEFAULT_TIMEOUT):
    """
    Bungkus `base_sql` (query SELECT LENGKAP, termasuk WHERE clause-nya
    sendiri -- lihat mclock/sources.py) sebagai CTE, lalu terapkan
    search (LIKE) + sort + pagination DI ATASNYA.

    Otomatis pilih strategi pagination sesuai versi SQL Server (dicek sekali
    & di-cache, lihat `get_sqlserver_major_version()`):
    - SQL Server 2012+ (versi mayor >= 11): `OFFSET ... FETCH NEXT ... ROWS ONLY`.
    - SQL Server < 2012 (2008/2005, ATAU gagal dideteksi versinya): fallback
      `ROW_NUMBER() OVER (ORDER BY ...)` + `WHERE rn BETWEEN ...`, yang
      didukung SQL Server 2005+ jadi jauh lebih kompatibel.

    Dipakai khusus utk Mobile Attendance, di mana tiap submenu punya query
    dasar yang beda-beda (tabel & kondisi WHERE spesifik), plus beberapa di
    antaranya ternyata jalan di SQL Server versi lama (2008).

    PENTING soal keamanan: `base_sql` HARUS berasal dari konfigurasi TETAP
    di kode (mclock/sources.py), BUKAN dari input user. `search_column`/
    `sort_column` JUGA harus sudah divalidasi terhadap whitelist SEBELUM
    dipanggil ke sini (lihat MOBILE_ATTENDANCE_COLUMNS di sources.py) --
    nama kolom tidak bisa diparameterisasi lewat placeholder SQL biasa
    (beda dengan NILAI/value, yang aman lewat `search_term`).

    Return: (rows: list[dict], total_count: int).
    """
    where_clause = ''
    params: list = []
    if search_term and search_column:
        where_clause = f'WHERE {search_column} LIKE %s'
        params = [f'%{search_term}%']

    count_sql = f'WITH base_q AS ({base_sql}) SELECT COUNT(*) AS cnt FROM base_q {where_clause}'
    count_rows = run_query(count_sql, tuple(params), server=server, database=database,
                            tds_version=tds_version, timeout=timeout)
    total_count = count_rows[0]['cnt'] if count_rows else 0

    order_col = sort_column or 'ttime'
    order_dir = 'DESC' if str(sort_direction).lower() == 'desc' else 'ASC'
    offset = max(page - 1, 0) * page_size

    major_version = get_sqlserver_major_version(server, database, tds_version=tds_version, timeout=timeout)

    if major_version >= SQLSERVER_OFFSET_FETCH_MIN_VERSION:
        # SQL Server 2012+
        data_sql = (
            f'WITH base_q AS ({base_sql}) SELECT * FROM base_q {where_clause} '
            f'ORDER BY {order_col} {order_dir} '
            f'OFFSET %s ROWS FETCH NEXT %s ROWS ONLY'
        )
        data_params = tuple(params) + (offset, page_size)
    else:
        # SQL Server 2005/2008/2008 R2, ATAU versi gagal dideteksi (fallback
        # paling kompatibel) -- OFFSET/FETCH belum ada, pakai ROW_NUMBER().
        start_row = offset + 1
        end_row = offset + page_size
        data_sql = (
            f'WITH base_q AS ({base_sql}), '
            f'numbered AS ('
            f'  SELECT *, ROW_NUMBER() OVER (ORDER BY {order_col} {order_dir}) AS rn '
            f'  FROM base_q {where_clause}'
            f') '
            f'SELECT * FROM numbered WHERE rn BETWEEN %s AND %s ORDER BY rn'
        )
        data_params = tuple(params) + (start_row, end_row)

    rows = run_query(data_sql, data_params, server=server, database=database,
                      tds_version=tds_version, timeout=timeout)
    # Kolom 'rn' (nomor urut internal dari ROW_NUMBER()) tidak perlu tampil
    # ke pengguna -- buang kalau ada (cuma muncul di jalur fallback).
    for row in rows:
        row.pop('rn', None)
    return rows, total_count
