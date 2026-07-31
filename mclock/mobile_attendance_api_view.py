"""
API Mobile Attendance -- 5 submenu (karyawan/driver/mitra/kantin/
kantin-mitra mobile, lihat mclock/sources.py::MOBILE_ATTENDANCE_SOURCES)
DIGABUNG jadi 1 API GENERIK (bukan 5 endpoint terpisah) supaya frontend
bisa 1 halaman dgn dropdown pilih sumber data (sesuai permintaan) --
persis pola yang SAMA dgn view Django lama (mclock/views.py::
mobile_attendance_table, server-rendered, BELUM ada versi Next.js-nya)
-- di sini DIBUNGKUS jadi DRF API supaya bisa dikonsumsi Next.js.

Search/sort/pagination SEMUANYA dikerjakan SERVER-SIDE di MSSQL (lihat
mclock/mssql_client.py::fetch_paginated_from_sql), BUKAN fetch semua
baris ke Python dulu -- konvensi param SAMA dgn netmgmt (_q/_sort_by/
_order/_page/_limit) utk konsistensi & reuse komponen UI Next.js yang sama.
"""
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from api.permissions import IsStaffRole

from .mssql_client import MSSQLConnectionError, fetch_paginated_from_sql
from .sources import (
    MOBILE_ATTENDANCE_COLUMNS,
    MOBILE_ATTENDANCE_SEARCH_COLUMN,
    MOBILE_ATTENDANCE_SOURCES,
)


class MobileAttendanceSourceListView(APIView):
    """GET /api/v1/mclock/mobile-attendance/sources/ -- daftar {slug, title} 5 submenu, utk isi dropdown di frontend."""
    permission_classes = [IsAuthenticated, IsStaffRole]

    def get(self, request):
        sources = [{'slug': slug, 'title': cfg['title']} for slug, cfg in MOBILE_ATTENDANCE_SOURCES.items()]
        return Response({'results': sources}, status=status.HTTP_200_OK)


class MobileAttendanceTableView(APIView):
    """
    GET /api/v1/mclock/mobile-attendance/<slug>/?_q=&_sort_by=&_order=&_page=&_limit=
    -- data submenu tertentu, read-only murni (TANPA edit/aksi apa pun,
    sama spt versi Django lama) -- search kolom 'nik' (alias DibuatOleh/
    NIP di semua sumber), sort & pagination di MSSQL langsung.
    """
    permission_classes = [IsAuthenticated, IsStaffRole]

    def get(self, request, slug=None):
        source = MOBILE_ATTENDANCE_SOURCES.get(slug)
        if not source:
            return Response({'error': f"Sumber data '{slug}' tidak dikenal."}, status=status.HTTP_404_NOT_FOUND)

        search = request.query_params.get('_q', '').strip()

        sort_key = request.query_params.get('_sort_by', 'ttime')
        if sort_key not in MOBILE_ATTENDANCE_COLUMNS:  # whitelist -- nama kolom TIDAK bisa diparameterisasi lewat placeholder SQL biasa
            sort_key = 'ttime'

        direction = request.query_params.get('_order', 'desc')
        if direction not in ('asc', 'desc'):
            direction = 'desc'

        try:
            page = max(1, int(request.query_params.get('_page', 1)))
        except (TypeError, ValueError):
            page = 1
        try:
            page_size = int(request.query_params.get('_limit', 10))
            if page_size < 1:
                page_size = 10
        except (TypeError, ValueError):
            page_size = 10

        try:
            rows, total_count = fetch_paginated_from_sql(
                base_sql=source['base_sql'],
                server=source['server'],
                database=source['database'],
                search_column=MOBILE_ATTENDANCE_SEARCH_COLUMN,
                search_term=search,
                sort_column=sort_key,
                sort_direction=direction,
                page=page,
                page_size=page_size,
                tds_version=source.get('tds_version'),
            )
        except MSSQLConnectionError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

        total_pages = max(1, -(-total_count // page_size)) if page_size else 1
        return Response({
            'count': total_count,
            'page': page,
            'results': rows,
            'next': page + 1 if page < total_pages else None,
            'previous': page - 1 if page > 1 else None,
        }, status=status.HTTP_200_OK)
