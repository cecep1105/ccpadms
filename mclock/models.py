from django.db import models


class MobilePool(models.Model):
    """
    Data pool/lokasi (titik absensi, mis. utk validasi GPS radius) yang
    disinkronkan dari MSSQL eksternal -- field & isinya SAMA persis dengan
    tabel sumber di MSSQL (lihat management command `sync_mobile_pool`).

    BEDA dengan submenu Mobile Attendance lain (Karyawan/Driver/Mitra/Kantin
    Mobile) yang murni baca LANGSUNG dari MSSQL setiap request -- tabel ini
    DISALIN ke database Django (lewat sync manual/terjadwal), supaya bisa
    dipakai sebagai referensi lokal tanpa bolak-balik ke MSSQL setiap saat.
    """
    PoolID = models.CharField(max_length=5, primary_key=True)
    PoolCode = models.CharField(max_length=50, null=True, blank=True)
    PoolName = models.CharField(max_length=50, null=True, blank=True)
    Latitude = models.CharField(max_length=50, null=True, blank=True)
    Longitude = models.CharField(max_length=50, null=True, blank=True)
    Radius = models.IntegerField(null=True, blank=True)

    # Diisi otomatis oleh management command sync -- kapan terakhir kali
    # record ini disinkronkan dari MSSQL (bukan field dari sumber MSSQL-nya,
    # murni metadata lokal utk monitoring kapan sync terakhir jalan).
    SyncedAt = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'mclock_mobile_pool'
        managed = True
        verbose_name = 'Mobile Pool'
        verbose_name_plural = 'Mobile Pool'
        ordering = ['PoolID']

    def __str__(self):
        return f'{self.PoolID} - {self.PoolName}' if self.PoolName else self.PoolID


class MobilePoolLoc(models.Model):
    """
    Titik-titik (vertex) polygon geofence per PoolID -- disinkronkan dari
    MSSQL eksternal (tabel sumber `MsPool_Loc`, lihat management command
    `sync_mobile_pool_loc`). Semua record dengan `PoolID` yang SAMA,
    diurutkan berdasarkan `Urut`, membentuk titik-titik polygon (dalam
    urutan keliling) yang dipakai utk verifikasi geofence check-in/out --
    MENGGANTIKAN pendekatan radius lingkaran sebelumnya di `MobilePool`
    (lihat mattendance/geofence.py::find_matching_pool_by_polygon).

    `MobilePool` (tabel radius yang lama) TETAP ADA & tetap disinkronkan --
    sekarang dipakai murni sebagai LOOKUP (PoolName/PoolCode dsb utk
    ditampilkan), bukan lagi sumber kebenaran geofence-nya.

    PENTING: `PoolID` di sini SENGAJA bukan ForeignKey ke `MobilePool` --
    kedua tabel disinkronkan independen (bisa beda waktu/frekuensi sync),
    jadi tidak dipaksa constraint referential integrity yang bisa bikin
    sync salah satu gagal gara-gara data satunya belum ada/telat sync.
    """
    PoolID = models.CharField(max_length=5)
    Urut = models.DecimalField(max_digits=18, decimal_places=2, help_text='Urutan titik dalam polygon (menentukan urutan keliling).')
    Latitude = models.TextField(null=True, blank=True)
    Longitude = models.TextField(null=True, blank=True)

    # Diisi otomatis oleh management command sync -- sama seperti MobilePool.
    SyncedAt = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'mclock_mobile_pool_loc'
        managed = True
        verbose_name = 'Mobile Pool Location (Polygon)'
        verbose_name_plural = 'Mobile Pool Location (Polygon)'
        ordering = ['PoolID', 'Urut']
        # 1 nomor urut harus unik PER PoolID (2 titik polygon yang sama
        # tidak boleh berbagi urutan yang sama).
        constraints = [
            models.UniqueConstraint(fields=['PoolID', 'Urut'], name='unique_poolid_urut'),
        ]

    def __str__(self):
        return f'{self.PoolID} #{self.Urut}'


class PoolDeviceFunction(models.Model):
    """
    Mapping PoolID -> apakah device/lokasi itu ber-function KANTIN atau
    BUKAN -- dipakai `mattendance` utk menentukan kode fungsi (settings.
    DEVICEFUNCTION) suatu check-in/out/meal, CEK PRIORITAS PERTAMA sebelum
    fallback ke prefix digit PIN (lihat mattendance/function_utils.py).

    PENTING: BEDA dengan `MobilePool`/`MobilePoolLoc` -- kedua tabel itu
    disinkronkan (mirror penuh) dari MSSQL eksternal, jadi field apa pun
    yang ditambahkan LANGSUNG di sana akan HILANG/TERTIMPA begitu sync
    berikutnya jalan. Tabel INI SENGAJA terpisah & TIDAK disinkronkan dari
    mana pun -- murni dikelola MANUAL sepenuhnya lewat UI aplikasi ini
    (mirip konsep `iclock.Function` per-device, tapi utk Mobile Attendance).

    `PoolID` di sini SENGAJA bukan ForeignKey ke `MobilePool` (sama seperti
    `MobilePoolLoc`) -- supaya tidak ada constraint referential integrity
    yang bisa bikin salah satu proses (sync MobilePool vs kelola mapping
    ini) saling mengganggu.
    """
    class FunctionType(models.TextChoices):
        KANTIN = 'KANTIN', 'KANTIN'
        BUKAN_KANTIN = 'BUKAN_KANTIN', 'Bukan KANTIN'

    PoolID = models.CharField(max_length=5, unique=True, help_text='PoolID dari MobilePool yang dipetakan function-nya.')
    function_type = models.CharField(max_length=20, choices=FunctionType.choices, default=FunctionType.BUKAN_KANTIN)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'mclock_pool_device_function'
        managed = True
        verbose_name = 'Pool Device Function'
        verbose_name_plural = 'Pool Device Function'
        ordering = ['PoolID']

    def __str__(self):
        return f'{self.PoolID} - {self.function_type}'
