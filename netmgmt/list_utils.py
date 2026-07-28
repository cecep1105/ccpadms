"""
Utility pagination/sort/filter GENERIK, dipakai bersama oleh SEMUA fitur
netmgmt yang datanya TIDAK datang dari database Django (RouterOS/Mikrotik,
Active Directory, Zentyal LDAP) -- lihat penjelasan lengkap kenapa
pola ini beda dari tabel Django biasa di netmgmt/routeros_api_view.py.

Konvensi param SERAGAM di semua fitur netmgmt (frontend Next.js pakai
komponen yang SAMA -- src/components/netmgmt/routeros-*.tsx -- utk
ketiganya, walau namanya "routeros-*" krn dibuat pertama kali utk itu,
sekarang dipakai lintas fitur netmgmt):
    _page, _limit       : pagination
    _sort_by, _order     : sorting (_order = "asc"|"desc")
    _q, _search_fields   : pencarian teks bebas
"""
from typing import Any


def paginate_sort_filter(
    rows: list[dict[str, Any]],
    *,
    page: int,
    limit: int,
    sort_by: str,
    order: str,
    search_query: str,
    search_fields: list[str],
) -> dict[str, Any]:
    """
    Terima list of dict MENTAH (SEMUA baris, belum dipotong halaman),
    kembalikan dict siap jadi Response DRF -- format SAMA PERSIS dgn yang
    dipakai RouterOSCommandView (frontend Next.js baca bentuk ini apa
    adanya, lihat components/netmgmt/routeros-pagination-bar.tsx).
    """
    result = rows
    if search_query and search_fields:
        q = search_query.lower()
        result = [
            item for item in result
            if any(q in str(item.get(field, '')).lower() for field in search_fields)
        ]

    result = sorted(result, key=lambda item: str(item.get(sort_by, '')), reverse=(order == 'desc'))

    start = (page - 1) * limit
    paginated = result[start:start + limit]

    return {
        'count': len(result),
        'page': page,
        'results': paginated,
        'next': page + 1 if start + limit < len(result) else None,
        'previous': page - 1 if page > 1 else None,
    }


def parse_list_params(request) -> dict[str, Any]:
    """Baca param kontrol `_page`/`_limit`/`_sort_by`/`_order`/`_q`/`_search_fields` dari request, dgn default yang wajar."""
    return {
        'page': int(request.query_params.get('_page', 1)),
        'limit': int(request.query_params.get('_limit', 10)),
        'sort_by': request.query_params.get('_sort_by', 'id'),
        'order': request.query_params.get('_order', 'asc'),
        'search_query': request.query_params.get('_q', '').strip(),
        'search_fields': [f.strip() for f in request.query_params.get('_search_fields', '').split(',') if f.strip()],
    }
