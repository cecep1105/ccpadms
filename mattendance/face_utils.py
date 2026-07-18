"""
Utility face recognition (enrollment & verifikasi) pakai library
`face_recognition` (dibangun di atas dlib).

⚠️ INSTALASI DI WINDOWS -- lihat README bagian "Face Verification" untuk
detail lengkap, ringkasnya: `dlib` TIDAK punya wheel prebuilt (dikonfirmasi
langsung -- cuma ada source distribution di PyPI), jadi instalasi WAJIB
compile dari sumber. Ini butuh:
  1. Visual C++ Build Tools terinstall (komponen "Desktop development with C++").
  2. CMake terinstall & ada di PATH.
  3. Waktu tunggu yang cukup lama (bisa 10-30+ menit tergantung spek PC,
     dikonfirmasi lewat percobaan langsung: di lingkungan Linux yang biasanya
     LEBIH MUDAH dari Windows untuk hal ini, kompilasinya sendiri sudah
     makan waktu lebih dari 4.5 menit tanpa selesai).
Kalau instalasi gagal/terlalu lama, pertimbangkan alternatif (OpenCV LBPH
atau cloud API) -- lihat catatan di README.
"""
import base64
import io

FACE_MATCH_TOLERANCE = 0.6  # default face_recognition -- makin kecil, makin ketat (lebih sedikit false-positive, tapi lebih rawan false-negative)


class FaceProcessingError(Exception):
    """Gagal proses gambar wajah (tidak ada wajah terdeteksi, gambar korup, library belum terinstall, dsb)."""


def _import_face_recognition():
    """
    Import `face_recognition` LAZY (baru diimpor saat benar-benar dipakai,
    bukan di top-level module) -- supaya modul lain yang TIDAK butuh face
    recognition (mis. checkin_submit sebelum ada face_image dikirim) tetap
    bisa jalan normal walau library ini belum/gagal terinstall, dan supaya
    pesan errornya jelas (bukan ImportError mentah saat Django startup).
    """
    try:
        import face_recognition
        return face_recognition
    except ImportError as exc:
        raise FaceProcessingError(
            "Library 'face_recognition' (dlib) belum terinstall di server. "
            "Lihat README bagian Face Verification untuk cara instalasi."
        ) from exc


def decode_base64_image(base64_data: str):
    """
    Decode base64 image data (dari <canvas>.toDataURL() browser, format
    'data:image/jpeg;base64,...') jadi numpy array RGB, siap diproses
    face_recognition.

    PENTING soal kompatibilitas dlib: array yang dihasilkan WAJIB uint8 &
    C-contiguous di memori -- dlib (lewat face_recognition) bisa menolak
    array dengan error "RuntimeError: Unsupported image type, must be 8bit
    gray or RGB image" walau shape/dtype-nya SECARA VISUAL sudah terlihat
    benar, kalau array-nya tidak dipaksa uint8 + contiguous secara
    eksplisit (dikonfirmasi lewat laporan komunitas resmi face_recognition/
    dlib -- penyebab paling umum adalah numpy versi >= 2.0 yang tidak
    kompatibel dengan wheel dlib prebuilt yg dikompilasi utk ABI numpy 1.x,
    lihat catatan di requirements.txt).
    """
    try:
        import numpy as np
        from PIL import Image
    except ImportError as exc:
        raise FaceProcessingError("Library 'Pillow'/'numpy' belum terinstall di server.") from exc

    if ',' in base64_data:
        base64_data = base64_data.split(',', 1)[1]
    try:
        image_bytes = base64.b64decode(base64_data)
        image = Image.open(io.BytesIO(image_bytes)).convert('RGB')
        # np.ascontiguousarray() + dtype=uint8 eksplisit -- pengaman
        # tambahan supaya array yang dikirim ke dlib SELALU dalam format
        # yang diterima, terlepas dari versi PIL/numpy yang terinstall.
        return np.ascontiguousarray(np.array(image, dtype=np.uint8))
    except Exception as exc:  # noqa: BLE001
        raise FaceProcessingError(f'Gagal decode gambar: {exc}') from exc


def extract_face_encoding(image_array):
    """
    Deteksi wajah dalam gambar & extract 128-dimension encoding-nya (list
    of float, JSON-serializable, siap disimpan di FaceProfile.encoding).

    Raise FaceProcessingError kalau:
    - tidak ada wajah terdeteksi sama sekali.
    - ada LEBIH DARI 1 wajah (ambigu -- enrollment/verifikasi harus jelas
      1 orang di depan kamera, bukan beberapa wajah sekaligus).
    """
    face_recognition = _import_face_recognition()

    face_locations = face_recognition.face_locations(image_array)
    if not face_locations:
        raise FaceProcessingError(
            'Tidak ada wajah terdeteksi di gambar. Pastikan wajah terlihat jelas, pencahayaan cukup, '
            'dan kamera menghadap langsung ke wajah.'
        )
    if len(face_locations) > 1:
        raise FaceProcessingError(
            f'Terdeteksi {len(face_locations)} wajah sekaligus. Pastikan cuma ada 1 orang di depan kamera.'
        )

    encodings = face_recognition.face_encodings(image_array, known_face_locations=face_locations)
    return encodings[0].tolist()  # numpy array -> list of float, JSON-serializable


def verify_face(image_array, enrolled_encoding, tolerance: float = FACE_MATCH_TOLERANCE):
    """
    Bandingkan wajah di `image_array` dengan `enrolled_encoding` (list of
    float, dari FaceProfile.encoding yang tersimpan saat enrollment).

    Return (matched: bool, distance: float) -- distance adalah jarak
    Euclidean antar 2 encoding (0 = identik, makin besar makin beda).
    Raise FaceProcessingError kalau gagal ekstrak wajah dari image_array
    (tidak ada wajah / lebih dari 1 wajah -- sama seperti extract_face_encoding).
    """
    face_recognition = _import_face_recognition()
    import numpy as np

    new_encoding = extract_face_encoding(image_array)
    distance = face_recognition.face_distance([np.array(enrolled_encoding)], np.array(new_encoding))[0]
    matched = bool(distance <= tolerance)
    return matched, float(distance)


def compare_encodings(encoding_a, encoding_b, tolerance: float = FACE_MATCH_TOLERANCE):
    """
    Bandingkan 2 encoding yang SUDAH DIEKSTRAK sebelumnya SECARA LANGSUNG
    (tanpa perlu decode/ekstrak ulang dari gambar) -- dipakai utk cek
    duplikat wajah (settings.PREVENT_DUPLICATE_FACE): membandingkan
    encoding wajah yang BARU di-enroll terhadap encoding-encoding user LAIN
    yang sudah lebih dulu terdaftar.

    Return (matched: bool, distance: float).
    """
    face_recognition = _import_face_recognition()
    import numpy as np

    distance = face_recognition.face_distance([np.array(encoding_a)], np.array(encoding_b))[0]
    return bool(distance <= tolerance), float(distance)
