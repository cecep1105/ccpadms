"""
Data IT-Infra -- registry BEBAS/fleksibel utk macam-macam info
infrastruktur (langganan internet, VPS, domain, dll) -- lihat
netmgmt/models.py::ITInfraEntry utk penjelasan lengkap kenapa field-nya
dictionary bebas (BUKAN skema tetap per kategori) & kenapa dienkripsi.

KEAMANAN TAMPILAN: endpoint LIST (`ITInfraEntryListView`) SENGAJA TIDAK
kirim isi `data` (yang berisi password dkk) -- cuma metadata (kategori/
nama/catatan/waktu). Isi `data` LENGKAP cuma dikirim lewat endpoint
DETAIL (`ITInfraEntryDetailView`, GET 1 entry spesifik pakai ID),
supaya password TIDAK nampang di response daftar (mis. kalau user buka
Network tab browser pas cuma mau lihat daftar, tidak otomatis lihat
SEMUA password sekaligus).
"""
from django.http import Http404
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from api.permissions import HasFeaturePermission, IsStaffRole
from netmgmt.list_utils import paginate_sort_filter, parse_list_params
from netmgmt.models import ITInfraCategory, ITInfraEntry


class ITInfraCategoryListView(APIView):
    """
    GET  /api/v1/netmgmt/itinfra/categories/ -- daftar kategori (utk dropdown).
    POST /api/v1/netmgmt/itinfra/categories/ -- {"name": "..."} -- tambah kategori baru.

    TETAP staff-only (TIDAK diperluas ke izin portal can_view_itinfra) --
    view GET+POST ini SATU CLASS (permission SAMA utk keduanya), & POST
    (bikin kategori baru) di LUAR cakupan portal yang disepakati (view
    only). Halaman portal TIDAK butuh dropdown kategori (tidak ada form
    tambah/edit di sana) -- cari kategori tetap bisa lewat search bar
    biasa (category_name SUDAH ikut di _entry_to_summary()).
    """
    permission_classes = [IsAuthenticated, IsStaffRole]

    def get(self, request):
        categories = ITInfraCategory.objects.all().order_by('name')
        return Response({'results': [{'id': c.id, 'name': c.name} for c in categories]}, status=status.HTTP_200_OK)

    def post(self, request):
        name = (request.data.get('name') or '').strip()
        if not name:
            return Response({'error': "'name' wajib diisi."}, status=status.HTTP_400_BAD_REQUEST)
        category, created = ITInfraCategory.objects.get_or_create(name=name)
        if not created:
            return Response({'error': f"Kategori '{name}' sudah ada."}, status=status.HTTP_400_BAD_REQUEST)
        return Response({'success': True, 'id': category.id, 'name': category.name}, status=status.HTTP_201_CREATED)


def _entry_to_summary(entry: ITInfraEntry) -> dict:
    """TANPA `data` (lihat catatan keamanan di docstring modul) -- dipakai LIST."""
    return {
        'id': entry.id,
        'category_id': entry.category_id,
        'category_name': entry.category.name,
        'name': entry.name,
        'notes': entry.notes,
        'is_staff_only': entry.is_staff_only,
        'updated_at': entry.updated_at.isoformat(),
    }


class ITInfraEntryListView(APIView):
    """
    GET /api/v1/netmgmt/itinfra/entries/?category_id=&_page=&_limit=&_sort_by=&_order=&_q=
    -- daftar entry (TANPA isi `data`, lihat catatan keamanan).

    User NON-STAFF (izin portal can_view_itinfra) TIDAK MELIHAT entry yg
    is_staff_only=True SAMA SEKALI -- difilter di QUERYSET (bukan cuma
    disembunyikan di UI), staff/superuser lihat SEMUA seperti biasa.
    """
    permission_classes = [IsAuthenticated, HasFeaturePermission('iclock.can_view_itinfra')]

    def get(self, request):
        qs = ITInfraEntry.objects.select_related('category').all()
        category_id = request.query_params.get('category_id')
        if category_id:
            qs = qs.filter(category_id=category_id)
        if not (request.user.is_staff or request.user.is_superuser):
            qs = qs.filter(is_staff_only=False)

        entries = [_entry_to_summary(e) for e in qs]
        params = parse_list_params(request)
        if not params['search_fields']:
            params['search_fields'] = ['name', 'notes', 'category_name']
        payload = paginate_sort_filter(entries, **params)
        return Response(payload, status=status.HTTP_200_OK)


class ITInfraEntryDetailView(APIView):
    """
    GET /api/v1/netmgmt/itinfra/entries/<id>/ -- 1 entry LENGKAP termasuk `data` ter-dekripsi (lihat catatan keamanan di docstring modul).

    User NON-STAFF DITOLAK (404, BUKAN 403 -- supaya TIDAK MEMBOCORKAN
    bahwa entry ini ADA tapi disembunyikan, cukup terlihat spt entry ID
    itu memang tidak ada) kalau entry yang diminta is_staff_only=True,
    MESKI mereka py izin portal can_view_itinfra -- filter INI per-entry,
    DI ATAS izin granular umum.
    """
    permission_classes = [IsAuthenticated, HasFeaturePermission('iclock.can_view_itinfra')]

    def get(self, request, entry_id=None):
        entry = get_object_or_404(ITInfraEntry, id=entry_id)
        if entry.is_staff_only and not (request.user.is_staff or request.user.is_superuser):
            raise Http404
        return Response({
            'id': entry.id,
            'category_id': entry.category_id,
            'category_name': entry.category.name,
            'name': entry.name,
            'data': entry.get_data(),
            'notes': entry.notes,
            'is_staff_only': entry.is_staff_only,
            'updated_at': entry.updated_at.isoformat(),
        }, status=status.HTTP_200_OK)


class ITInfraEntryActionView(APIView):
    """
    POST /api/v1/netmgmt/itinfra/entries/action/
    Body tambah: {"action": "add", "category_id": 1, "name": "...", "data": {...}, "notes": "..."}
    Body edit:   {"action": "edit", "entry_id": 5, "category_id": 1, "name": "...", "data": {...}, "notes": "..."}
    Body hapus:  {"action": "delete", "entry_id": 5}
    """
    permission_classes = [IsAuthenticated, IsStaffRole]

    def post(self, request):
        action = request.data.get('action')
        if action not in ('add', 'edit', 'delete'):
            return Response({'error': "'action' wajib 'add', 'edit', atau 'delete'."}, status=status.HTTP_400_BAD_REQUEST)

        if action == 'delete':
            return self._delete(request)

        category_id = request.data.get('category_id')
        name = (request.data.get('name') or '').strip()
        data_dict = request.data.get('data')
        notes = request.data.get('notes') or ''
        is_staff_only = bool(request.data.get('is_staff_only', False))

        if not category_id:
            return Response({'error': "'category_id' wajib diisi."}, status=status.HTTP_400_BAD_REQUEST)
        if not name:
            return Response({'error': "'name' wajib diisi."}, status=status.HTTP_400_BAD_REQUEST)
        if not isinstance(data_dict, dict):
            return Response({'error': "'data' wajib berupa object/dictionary."}, status=status.HTTP_400_BAD_REQUEST)

        category = get_object_or_404(ITInfraCategory, id=category_id)

        if action == 'add':
            entry = ITInfraEntry(category=category, name=name, notes=notes, is_staff_only=is_staff_only)
            entry.set_data(data_dict)
            entry.save()
            return Response({'success': True, 'message': 'Data berhasil ditambahkan.', 'id': entry.id}, status=status.HTTP_201_CREATED)

        # edit
        entry_id = request.data.get('entry_id')
        if not entry_id:
            return Response({'error': "'entry_id' wajib diisi utk edit."}, status=status.HTTP_400_BAD_REQUEST)
        entry = get_object_or_404(ITInfraEntry, id=entry_id)
        entry.category = category
        entry.name = name
        entry.notes = notes
        entry.is_staff_only = is_staff_only
        entry.set_data(data_dict)
        entry.save()
        return Response({'success': True, 'message': 'Data berhasil diperbarui.'}, status=status.HTTP_200_OK)

    def _delete(self, request):
        entry_id = request.data.get('entry_id')
        if not entry_id:
            return Response({'error': "'entry_id' wajib diisi utk hapus."}, status=status.HTTP_400_BAD_REQUEST)
        entry = get_object_or_404(ITInfraEntry, id=entry_id)
        entry.delete()
        return Response({'success': True, 'message': 'Data berhasil dihapus.'}, status=status.HTTP_200_OK)
