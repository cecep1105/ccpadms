"""
Celery task utk proses face recognition (CPU-intensive, pakai dlib) --
dilempar ke WORKER TERPISAH supaya tidak membebani proses Django/Daphne
utama yang juga menangani request HTTP lain + koneksi WebSocket.

Task-task ini SENGAJA tidak me-raise exception ke caller -- semua
error (termasuk FaceProcessingError) ditangkap & dikembalikan sebagai
bagian dari dict hasil (`{'success': False, 'error': '...'}), supaya
caller (view) cukup cek `result['success']` tanpa perlu try/except
tambahan di sisi pemanggilan task.
"""
from celery import shared_task

from .face_utils import FaceProcessingError, compare_encodings, decode_base64_image, extract_face_encoding, verify_face


@shared_task(bind=True, ignore_result=False)
def extract_face_encoding_task(self, base64_image_data: str, existing_encodings: list = None) -> dict:
    """
    Ekstrak face encoding dari gambar (base64) -- dipakai saat enrollment.

    `existing_encodings`: OPSIONAL, list of {'employee_id': int, 'encoding': list}
    -- kalau diisi (dipakai utk settings.PREVENT_DUPLICATE_FACE), task ini
    JUGA membandingkan encoding wajah yang BARU diekstrak terhadap
    SEMUA encoding di list ini -- perbandingan yang CPU-intensive ini
    SENGAJA dilakukan DI SINI (di worker), bukan balik lagi ke proses
    Django, supaya beban itu juga tidak menumpuk di proses utama.

    Return: {'success': bool, 'encoding': list[float]|None, 'error': str|None,
             'duplicate_employee_id': int|None}
    `duplicate_employee_id`: None kalau tidak ada duplikat/tidak diminta cek,
    ATAU id Employee pemilik encoding yang cocok kalau ketemu duplikat.
    """
    try:
        image_array = decode_base64_image(base64_image_data)
        encoding = extract_face_encoding(image_array)
    except FaceProcessingError as exc:
        return {'success': False, 'encoding': None, 'error': str(exc), 'duplicate_employee_id': None}

    duplicate_employee_id = None
    if existing_encodings:
        for item in existing_encodings:
            matched, _distance = compare_encodings(encoding, item['encoding'])
            if matched:
                duplicate_employee_id = item['employee_id']
                break

    return {'success': True, 'encoding': encoding, 'error': None, 'duplicate_employee_id': duplicate_employee_id}


@shared_task(bind=True, ignore_result=False)
def verify_face_task(self, base64_image_data: str, enrolled_encoding: list) -> dict:
    """
    Verifikasi wajah di gambar (base64) terhadap encoding yang sudah
    terdaftar -- dipakai saat check-in/out.

    Return: {'success': bool, 'matched': bool|None, 'distance': float|None, 'error': str|None}
    `success=False` berarti gagal PROSES gambarnya (bukan berarti wajah
    tidak cocok -- itu `matched=False` dengan `success=True`).
    """
    try:
        image_array = decode_base64_image(base64_image_data)
        matched, distance = verify_face(image_array, enrolled_encoding)
        return {'success': True, 'matched': matched, 'distance': distance, 'error': None}
    except FaceProcessingError as exc:
        return {'success': False, 'matched': None, 'distance': None, 'error': str(exc)}
