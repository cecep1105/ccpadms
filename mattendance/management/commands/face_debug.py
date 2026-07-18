"""
Tool diagnostik untuk troubleshoot masalah face enrollment/verifikasi.

Pakai ini kalau ada laporan "error saat enrollment tapi check-in tetap
berhasil" (atau sebaliknya, kejanggalan lain terkait FaceProfile) --
akan menampilkan kondisi FaceProfile SEBENARNYA di database, mengecek
apakah face_recognition/dlib bisa dimuat, dan (opsional) tes ekstraksi
encoding dari 1 file gambar langsung.

Contoh pakai:
    python manage.py face_debug                      # semua FaceProfile
    python manage.py face_debug --user budi.santoso   # 1 user spesifik
    python manage.py face_debug --test-image foto.jpg # tes ekstraksi dari file
"""
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from mattendance.models import FaceProfile


class Command(BaseCommand):
    help = 'Debug FaceProfile & kesiapan face_recognition/dlib untuk troubleshooting.'

    def add_arguments(self, parser):
        parser.add_argument('--pin', default=None, help='PIN Employee spesifik (kosongkan utk tampilkan semua)')
        parser.add_argument('--test-image', default=None, help='Path file gambar utk dites ekstraksi encoding-nya langsung')

    def handle(self, *args, **options):
        User = get_user_model()

        self.stdout.write('=== 1. Cek apakah face_recognition/dlib bisa dimuat ===')
        try:
            import face_recognition  # noqa: F401
            self.stdout.write(self.style.SUCCESS('  OK -- face_recognition berhasil diimpor, dlib terinstall dengan benar.'))
        except ImportError as exc:
            self.stdout.write(self.style.ERROR(f'  GAGAL -- face_recognition/dlib BELUM terinstall: {exc}'))
            self.stdout.write(self.style.ERROR(
                '  --> SEMUA enrollment/verifikasi wajah akan gagal sampai ini diperbaiki '
                '(lihat README bagian Face Verification utk cara instalasi).'
            ))

        self.stdout.write('\n=== 2. Cek versi numpy (WAJIB < 2.0 utk kompatibilitas dlib) ===')
        try:
            import numpy as np
            self.stdout.write(f'  numpy versi: {np.__version__}')
            major_version = int(np.__version__.split('.')[0])
            if major_version >= 2:
                self.stdout.write(self.style.ERROR(
                    "  PERINGATAN -- numpy >= 2.0 bisa menyebabkan error "
                    "\"Unsupported image type\" walau shape/dtype sudah benar. "
                    "Jalankan: pip install \"numpy<2\""
                ))
            else:
                self.stdout.write(self.style.SUCCESS('  OK -- versi numpy kompatibel.'))
        except ImportError:
            self.stdout.write(self.style.ERROR('  GAGAL -- numpy belum terinstall.'))

        self.stdout.write('\n=== 3. Daftar FaceProfile di database SEKARANG ===')
        qs = FaceProfile.objects.select_related('employee').all()
        pin_filter = options.get('pin')
        if pin_filter:
            qs = qs.filter(employee__PIN=pin_filter)
            self.stdout.write(f"  (difilter utk PIN '{pin_filter}')")

        profiles = list(qs)
        if not profiles:
            self.stdout.write(self.style.WARNING('  KOSONG -- tidak ada FaceProfile tersimpan sama sekali.'))
        else:
            self.stdout.write(self.style.SUCCESS(f'  Ditemukan {len(profiles)} FaceProfile:'))
            for p in profiles:
                encoding_len = len(p.encoding) if isinstance(p.encoding, list) else 'BUKAN LIST!'
                valid = '✓ valid (128 dimensi)' if encoding_len == 128 else f'⚠️  MENCURIGAKAN (panjang: {encoding_len})'
                self.stdout.write(
                    f'    PIN={p.employee.PIN!r} (nama={p.employee.EName!r}), '
                    f'is_locked={p.is_locked}, '
                    f'enrolled_at={p.enrolled_at:%Y-%m-%d %H:%M:%S}, '
                    f'updated_at={p.updated_at:%Y-%m-%d %H:%M:%S}, '
                    f'encoding: {valid}'
                )
            self.stdout.write(self.style.WARNING(
                '\n  --> Kalau Anda MENGIRA sudah menghapus semua data profil tapi masih ada yang '
                'muncul di atas, itu penyebab "check-in tetap berhasil" -- FaceProfile yang tersisa '
                'ini yang dipakai verifikasi (lihat PIN mana persisnya di atas).'
            ))

        if options.get('test_image'):
            self.stdout.write('\n=== 4. Tes ekstraksi encoding dari file gambar ===')
            path = options['test_image']
            try:
                with open(path, 'rb') as f:
                    import base64
                    b64_data = base64.b64encode(f.read()).decode()
                from mattendance.face_utils import FaceProcessingError, decode_base64_image, extract_face_encoding
                image_array = decode_base64_image(b64_data)
                self.stdout.write(f'  Gambar berhasil didecode, shape: {image_array.shape}, dtype: {image_array.dtype}')
                encoding = extract_face_encoding(image_array)
                self.stdout.write(self.style.SUCCESS(f'  BERHASIL -- encoding {len(encoding)} dimensi berhasil diekstrak.'))
            except FileNotFoundError:
                self.stdout.write(self.style.ERROR(f'  File tidak ditemukan: {path}'))
            except FaceProcessingError as exc:
                self.stdout.write(self.style.ERROR(f'  GAGAL ekstraksi: {exc}'))
            except Exception as exc:  # noqa: BLE001
                self.stdout.write(self.style.ERROR(f'  ERROR TAK TERDUGA: {type(exc).__name__}: {exc}'))

        self.stdout.write('\n=== 5. Cek signature task SEBAGAIMANA DIMUAT proses ini (Django) ===')
        import inspect
        import os
        from datetime import datetime

        from mattendance.tasks import extract_face_encoding_task
        sig = inspect.signature(extract_face_encoding_task.run)
        task_file = inspect.getfile(extract_face_encoding_task.run)
        mtime = datetime.fromtimestamp(os.path.getmtime(task_file))
        self.stdout.write(f'  Signature: extract_face_encoding_task{sig}')
        self.stdout.write(f'  Dimuat dari file: {task_file}')
        self.stdout.write(f'  Waktu modifikasi file ini: {mtime:%Y-%m-%d %H:%M:%S}')
        if 'existing_encodings' in sig.parameters:
            self.stdout.write(self.style.SUCCESS("  OK -- parameter 'existing_encodings' ADA (proses Django ini sudah baca versi kode yang benar)."))
        else:
            self.stdout.write(self.style.ERROR(
                "  MASALAH -- parameter 'existing_encodings' TIDAK ADA! File tasks.py DI SERVER INI "
                "belum ter-update sama sekali -- restart Celery worker TIDAK akan membantu sampai "
                "file-nya sendiri benar-benar ditimpa versi baru. Cek ulang isi file di atas."
            ))

        self.stdout.write('\n=== 6. Tes DISPATCH SUNGGUHAN ke Celery worker (bukti definitif) ===')
        self.stdout.write('  (Mengirim task test lewat broker & menunggu worker proses -- membuktikan WORKER, bukan cuma proses ini, sudah pakai kode baru)')
        tiny_png_b64 = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGP4//8/AAX+Av4N70a4AAAAAElFTkSuQmCC'
        try:
            fake_existing = [{'user_id': 0, 'encoding': [0.0] * 128}]
            result = extract_face_encoding_task.delay(tiny_png_b64, existing_encodings=fake_existing).get(timeout=15)
            self.stdout.write(self.style.SUCCESS(f'  OK -- WORKER menerima parameter existing_encodings tanpa error. Hasil task: {result}'))
            self.stdout.write(self.style.SUCCESS('  (Kalau hasilnya "Tidak ada wajah terdeteksi", itu WAJAR -- gambar test cuma 1 piksel putih. Yang penting: TIDAK ada TypeError.)'))
        except TypeError as exc:
            self.stdout.write(self.style.ERROR(f'  MASALAH DIKONFIRMASI DI WORKER -- {exc}'))
            self.stdout.write(self.style.ERROR(
                '  --> WORKER masih menjalankan kode LAMA meski proses Django ini sudah baca kode baru. '
                'Kemungkinan: (a) worker belum BENAR-BENAR mati sebelum di-restart (cek dgn '
                '`tasklist | findstr celery` di Windows, pastikan TIDAK ada proses celery lama yang '
                'masih nyangkut sebelum start yang baru), (b) ada 2 salinan folder project di server '
                '(worker jalan dari salinan yang beda dgn yang Anda edit), atau (c) worker dijalankan '
                'lewat script/service yang nunjuk ke working directory/virtualenv berbeda.'
            ))
        except Exception as exc:  # noqa: BLE001
            self.stdout.write(self.style.WARNING(f'  Task terkirim, error LAIN (kemungkinan wajar, bukan soal versi kode): {type(exc).__name__}: {exc}'))
