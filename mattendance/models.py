from django.conf import settings
from django.db import models


class AttendanceLog(models.Model):
    """
    Log check-in/check-out mobile attendance -- dibuat kalau verifikasi
    lokasi (geofence) DAN verifikasi wajah (FaceProfile, lihat model di
    bawah) SAMA-SAMA berhasil. Kalau salah satu gagal, TIDAK dicatat --
    konsisten dengan prinsip "hanya catat kalau verifikasi berhasil" yang
    sudah dipakai sejak geofence-only sebelumnya.
    """

    class CheckType(models.TextChoices):
        IN = 'IN', 'Check-in'
        OUT = 'OUT', 'Check-out'
        MEAL = 'MEAL', 'Check/Meal'

    # --- Field inti sesuai permintaan ---
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='attendance_logs',
        help_text='User (accounts) yang melakukan check-in/out ini.',
    )
    timestamp = models.DateTimeField(auto_now_add=True)
    PoolID = models.ForeignKey(
        'mclock.MobilePool', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='attendance_logs',
        help_text='Pool/lokasi yang cocok dengan geofence saat check-in/out ini (kosong kalau tidak ada yang cocok).',
    )
    location_verified = models.BooleanField(
        default=False,
        help_text='True kalau koordinat GPS yang dikirim berada di dalam polygon salah satu MobilePool.',
    )
    face_verified = models.BooleanField(
        default=False,
        help_text='True kalau wajah yang di-capture saat check-in/out cocok dengan FaceProfile user (face_recognition). Selalu False utk Check/Meal (tidak pakai verifikasi wajah, pakai QR).',
    )

    # --- Field tambahan (BUKAN dari spesifikasi asli, ditambahkan untuk
    # kelengkapan praktis -- lihat catatan README) ---
    check_type = models.CharField(max_length=4, choices=CheckType.choices, default=CheckType.IN)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True,
                                    help_text='Koordinat GPS yang DIKIRIM user saat check-in/out (utk audit).')
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    distance_meters = models.FloatField(
        null=True, blank=True,
        help_text='Jarak (meter) ke PoolID yang cocok. Kosong kalau tidak ada pool yang cocok sama sekali.',
    )
    face_distance = models.FloatField(
        null=True, blank=True,
        help_text='Jarak Euclidean antara wajah check-in ini dgn FaceProfile terdaftar (dari face_recognition.face_distance) -- makin kecil makin mirip, 0 = identik. Utk audit.',
    )
    qr_content = models.CharField(
        max_length=100, null=True, blank=True,
        help_text='Isi QR code yang di-scan (khusus Check/Meal) -- utk audit, lihat settings.QRDEVICE.',
    )
    Function = models.CharField(
        max_length=20, null=True, blank=True,
        help_text=(
            "Format '<kode fungsi>-<PoolID>' (mirip iclock.transaction.Function), mis. '89-101' "
            "utk KARYAWAN di PoolID 101, 'X-101' utk Check/Meal di PoolID yang sama. "
            "Kode fungsi merujuk ke settings.DEVICEFUNCTION."
        ),
    )

    class Meta:
        db_table = 'mattendance_log'
        managed = True
        verbose_name = 'Attendance Log'
        verbose_name_plural = 'Attendance Log'
        ordering = ['-timestamp']

    def __str__(self):
        return f'{self.user} - {self.check_type} @ {self.timestamp:%Y-%m-%d %H:%M}'


class FaceProfile(models.Model):
    """
    Profil wajah TERVERIFIKASI milik 1 EMPLOYEE -- dibuat lewat proses
    "enrollment" (mirip daftar wajah pertama kali di mesin fingerprint
    ZKTeco yang punya face recognition): user foto wajahnya sendiri lewat
    webcam, sistem ekstrak "face encoding" (128 angka desimal yang mewakili
    ciri wajah, dihasilkan library `face_recognition`/dlib) dan simpan
    sebagai REFERENSI. Nanti setiap check-in/out, wajah yang di-capture
    dibandingkan terhadap encoding referensi ini (lihat
    mattendance/face_utils.py::verify_face).

    PENTING -- terikat ke `employee` (iclock), BUKAN ke `accounts.User`:
    seorang employee bisa punya LEBIH DARI 1 User terkait (mis. 1 akun
    staff reguler yang di-link admin via EmpID, DAN 1 akun "mobile-only"
    otomatis dari login PIN -- keduanya SAMA-SAMA merujuk ke employee yang
    SAMA). Kalau FaceProfile diikat ke User, wajah yang sama harus
    di-enroll ULANG untuk tiap akun berbeda -- boros & membingungkan.
    Dengan diikat ke `employee` langsung, 1 kali enrollment (dari akun
    MANA PUN, lewat User manapun yang ter-link ke employee tsb) otomatis
    berlaku utk SEMUA akun yang merujuk ke employee yang sama.

    Konsekuensinya: user yang TIDAK terkait employee manapun (User.EmpID
    kosong -- mis. akun IT/admin murni tanpa data karyawan fisik) TIDAK
    BISA mendaftar/pakai verifikasi wajah -- ditolak dgn pesan jelas di
    view (lihat mattendance/views.py::face_enroll_submit/checkin_submit).

    PENTING: yang disimpan cuma encoding NUMERIK (128 angka desimal), BUKAN
    foto wajah aslinya -- secara matematis TIDAK BISA direkonstruksi balik
    jadi foto yang mirip aslinya, tapi tetap data biometrik sensitif, wajib
    dijaga (akses terbatas staff/user pemilik sendiri, tidak pernah
    ditampilkan/diekspos ke user lain).
    """
    employee = models.OneToOneField(
        'iclock.employee', on_delete=models.CASCADE, related_name='face_profile',
        help_text='1 employee cuma boleh punya 1 profil wajah terdaftar (berlaku bersama utk semua akun User yang ter-link ke employee ini).',
    )
    encoding = models.JSONField(
        help_text='128-dimension face encoding dari face_recognition, disimpan sebagai list of float (JSON array).',
    )
    is_locked = models.BooleanField(
        default=False,
        verbose_name='Terkunci (ReadOnly)',
        help_text=(
            'Otomatis diset True begitu 1 kali enrollment berhasil -- "pengambilan wajah hanya '
            'dilakukan sekali". Selama True, user TIDAK BISA mendaftar ulang sendiri (harus hubungi '
            'admin). Admin bisa buka kunci (set False) lewat halaman Face Profile kalau employee '
            'legitimately butuh enroll ulang (mis. wajah berubah signifikan).'
        ),
    )
    enrolled_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'mattendance_face_profile'
        managed = True
        verbose_name = 'Face Profile'
        verbose_name_plural = 'Face Profiles'

    def __str__(self):
        return f'Face Profile: {self.employee}'
