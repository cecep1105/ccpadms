"""
Model untuk app 'iclock' (integrasi mesin fingerprint/absensi ZKTeco).

PENTING - model ini diringkas dari models.py legacy yang Anda upload:
- Field & method yang bergantung pada modul `.utils`, custom setting
  `settings.UNIT`, dan cache key legacy (mis. fungsi `getDevice`,
  `deviceCmd`, `removeLastReboot` di file asli) DIHAPUS karena tidak ada di
  scaffold ini dan akan bikin crash saat import (`settings.UNIT` tidak
  didefinisikan, modul `.utils` juga tidak ada di app ini).
- Nama `db_table` & `db_column` DIPERTAHANKAN PERSIS seperti aslinya, supaya
  kalau Anda memang menyambung ke database iclock yang sudah ada (dipakai
  mesin fingerprint fisik), datanya tetap terbaca/tersimpan dengan benar.
- `managed = True` di semua model -> Django BOLEH membuat/mengubah struktur
  tabel ini lewat migration (sudah dites & jalan lewat `makemigrations` +
  `migrate` Anda sendiri). Kalau tabelnya sudah ada & dipakai proses lain
  (server komunikasi device) dan Anda TIDAK mau Django ikut campur ubah
  skemanya, bisa dikembalikan ke `managed = True`.
"""
from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

GENDER_CHOICES = (
    ('M', _('Male')),
    ('F', _('Female')),
)

PRIV_CHOICES = (
    (0, _('Normal')),
    (2, _('Registrar')),
    (6, _('Administrator')),
    (14, _('Supervisor')),
)

BOOLEANS = (
    (0, _('No')),
    (1, _('Yes')),
)

FINGERIDS = (
    (0, _('Right Index Finger')),
    (1, _('Left Index Finger')),
    (2, _('Right Middle Finger')),
    (3, _('Left Middle Finger')),
    (4, _('Right Thumb')),
    (5, _('Left Thumb')),
    (6, _('Right Ring Finger')),
    (7, _('Left Ring Finger')),
    (8, _('Right Little Finger')),
    (9, _('Left Little Finger')),
)

VERIFYS = (
    (0, _('Password')),
    (1, _('Fingerprint')),
    (2, _('Card')),
    (9, _('Other')),
)

ATTSTATES = (
    ('0', _('Check in')),
    ('1', _('Check out')),
    ('2', _('Break out')),
    ('3', _('Break in')),
    ('4', _('Overtime in')),
    ('5', _('Overtime out')),
    ('8', _('Meal start')),
    ('9', _('Meal end')),
)

# Mapping kode operasi (angka) dari mesin -> label yang bisa dibaca manusia.
# Dipakai untuk menampilkan OP di halaman Operation Log (bukan Django
# `choices`, karena field OP aslinya cuma integer bebas dari device).
OPNAMES = {
    0: _('start up'), 1: _('shutdown'), 2: _('validation failure'), 3: _('alarm'),
    4: _('enter the menu'), 5: _('change settings'), 6: _('registration fingerprint'),
    7: _('registration password'), 8: _('card registration'), 9: _('delete User'),
    10: _('delete fingerprints'), 11: _('delete the password'), 12: _('delete RF card'),
    13: _('remove data'), 14: _('MF create cards'), 15: _('MF registration cards'),
    16: _('MF registration cards'), 17: _('MF registration card deleted'),
    18: _('MF clearance card content'), 19: _('moved to the registration card data'),
    20: _('the data in the card copied to the machine'), 21: _('set time'),
    22: _('restore factory settings'), 23: _('delete records access'),
    24: _('remove administrator rights'), 25: _('group set up to amend Access'),
    26: _('modify user access control settings'), 27: _('access time to amend paragraph'),
    28: _('amend unlock Portfolio'), 29: _('unlock'), 30: _('registration of new users'),
    31: _('fingerprint attribute changes'), 32: _('stress alarm'),
}


def op_name(op):
    """Terjemahkan kode operasi device (integer) jadi label yang bisa dibaca."""
    try:
        return OPNAMES[int(op)]
    except (TypeError, ValueError, KeyError):
        return op if op is not None else ''


class department(models.Model):
    """
    Dept/Pool -- dipakai sebagai referensi (FK) oleh iclock, RegisteredDevice,
    dan employee. Punya CRUD sendiri (submenu "Department" di Iclock Management).
    """
    DeptID = models.IntegerField(_('Pool ID'), primary_key=True)
    DeptName = models.CharField(_('Pool Name'), max_length=20)

    # NOT NULL di tabel `departments` yang sebenarnya (dicek dari dump database
    # Anda) -- default tetap diberikan untuk jaga-jaga, tapi sekarang editable
    # lewat form CRUD Department.
    NetID = models.IntegerField(_('Net ID'), default=0)
    DeptRouter = models.CharField(_('Router'), max_length=20, default='192.168.XXX.254')
    DeptSubnet = models.CharField(_('Subnet'), max_length=20, default='192.168.XXX.0/24')

    class Meta:
        db_table = 'departments'
        managed = True
        verbose_name = _('Pool')
        verbose_name_plural = _('Pool')


    def __str__(self):
        return self.DeptName


class iclock(models.Model):
    """Active Device -- mesin fingerprint yang sedang terhubung/aktif."""

    SN = models.CharField(_('Serial Number'), max_length=20, primary_key=True)
    Alias = models.CharField(_('Device Alias'), max_length=20)
    DeptID = models.ForeignKey(
        department, db_column='DeptID', verbose_name=_('Pool'),
        null=True, blank=True, on_delete=models.SET_NULL,
    )
    IPAddress = models.CharField(_('IP Address'), max_length=20, null=True, blank=True)
    MAC = models.CharField(_('MAC Address'), max_length=20, null=True, blank=True)
    TZAdj = models.SmallIntegerField(_('Timezone Offset'), default=8, null=True, blank=True)

    Function = models.CharField(_('Function'), max_length=20, null=True, blank=True, default='0')
    DeviceName = models.CharField(_('Device Name'), max_length=30, null=True, blank=True, editable=False)

    # Field telemetry yang biasanya diisi otomatis oleh proses komunikasi
    # device (bukan diedit manual admin), jadi tidak dimasukkan ke form CRUD.
    State = models.IntegerField(default=1, editable=False)
    LastActivity = models.DateTimeField(_('Last Activity'), null=True, blank=True, editable=False)
    PushVersion = models.CharField(max_length=10, default='0.0', editable=False, null=True, blank=True)

    # Kolom berikut NOT NULL di tabel `iclock` yang sebenarnya tapi memang
    # editable=False juga di file asli Anda -- diberi default supaya INSERT
    # tidak gagal.
    TransInterval = models.IntegerField(
        _('Trans Interval'), default=1,
        help_text=_('Interval (menit) device mengecek & mengirim data baru ke server.'),
    )
    UpdateDB = models.CharField(
        max_length=10, default='1111111100',
        help_text=_(
            "Ini field 'TransFlag' versi lama (nama kolom asli tabel ZKTeco) -- menentukan tipe data "
            "apa saja yang di-auto-upload device (attendance/operation log/foto/dst). Lihat resume "
            "protokol PUSH SDK bagian 3.1 utk arti tiap karakter."
        ),
    )
    LockFunOn = models.SmallIntegerField(db_column='AccFun', default=0, editable=False)
    DelTag = models.SmallIntegerField(default=0, editable=False)

    # --- Field konfigurasi PUSH SDK per-device (baru, lihat test/myrule.md
    # poin 2) -- dikirim ke device sbg respons GET /iclock/cdata?options=all
    # begitu device pertama kali konek/start. SENGAJA dibuat per-device
    # (bukan settings.py global spt implementasi lama Anda) supaya bisa
    # dikustomisasi per-SN dari dashboard admin.
    LogStamp = models.CharField(
        _('Attendance Log Stamp'), max_length=20, null=True, blank=True, default='0',
        help_text=_("Timestamp terakhir ATTLOG yang sudah diupload device ini (protokol lama: 'Stamp', baru: 'ATTLOGStamp')."),
    )
    OpLogStamp = models.CharField(
        _('Operation Log Stamp'), max_length=20, null=True, blank=True, default='0',
        help_text=_("Timestamp terakhir OPERLOG (user/fingerprint/log) yang sudah diupload ('OpStamp'/'OPERLOGStamp')."),
    )
    PhotoStamp = models.CharField(
        _('Photo Stamp'), max_length=20, null=True, blank=True, default='0',
        help_text=_("Timestamp terakhir foto attendance yang sudah diupload ('PhotoStamp'/'ATTPHOTOStamp')."),
    )
    TransTimes = models.CharField(
        _('Trans Times'), max_length=50, null=True, blank=True, default='00:00;14:05',
        help_text=_("Jadwal cek transfer data (format menit 24-jam, maks 10 slot dipisah ';'). Cuma dipakai kalau Realtime=0 & TransInterval=0."),
    )
    ErrorDelay = models.IntegerField(
        _('Error Delay'), default=60,
        help_text=_('Detik jeda reconnect device setelah koneksi ke server GAGAL.'),
    )
    Delay = models.IntegerField(
        _('Delay'), default=30,
        help_text=_('Detik jeda antar koneksi device ke server dalam kondisi normal.'),
    )
    Realtime = models.BooleanField(
        _('Realtime'), default=True,
        help_text=_('True: device upload data baru instan begitu ada. False: ikut jadwal TransTimes/TransInterval.'),
    )
    Encrypt = models.BooleanField(
        _('Encrypt'), default=False,
        help_text=_('Enkripsi data transfer device<->server. Lihat test/myrule.md poin 6 (masih tahap dicoba).'),
    )

    class Meta:
        db_table = 'iclock'
        managed = True
        verbose_name = _('Active Device')
        verbose_name_plural = _('Active Devices')

    def __str__(self):
        return f'{self.SN} ({self.Alias})' if self.Alias else self.SN

    # ------------------------------------------------------------------
    # Cache-aware save/delete (test/myrule.md poin 1) -- pola diadaptasi
    # dari implementasi legacy Anda (test/models.py::iclock.save/delete +
    # getDevice()), disesuaikan ke Django cache framework modern (Redis,
    # sudah dipakai project ini utk Channels/Celery).
    #
    # PENTING dibedakan dari `accounts.middleware`-style caching: ini
    # write-through PENUH (setiap .save() SELALU nulis DB, cache cuma
    # disegarkan mengikuti) -- BEDA dengan throttling utk heartbeat
    # LastActivity yang sangat sering (lihat `save_heartbeat()` di bawah,
    # padanan `checkAndSave()` legacy, YANG throttle penulisan DB-nya).
    # ------------------------------------------------------------------
    CACHE_KEY_PREFIX = 'iclock_device_'
    CACHE_TTL_SECONDS = 300  # cache device SELAMA TIDAK ada aktivitas apa pun (bukan TTL heartbeat)

    @classmethod
    def cache_key(cls, sn: str) -> str:
        return f'{cls.CACHE_KEY_PREFIX}{sn}'

    @classmethod
    def get_cached(cls, sn: str) -> 'iclock | None':
        """
        Read-through cache -- padanan `getDevice(sn)` legacy: cek cache
        dulu, fallback ke DB kalau miss (lalu cache hasilnya), None kalau
        SN memang tidak terdaftar sbg Active Device sama sekali.
        """
        sn = (sn or '').strip()
        if not sn:
            return None
        from django.core.cache import cache
        cached = cache.get(cls.cache_key(sn))
        if cached is not None:
            return cached
        try:
            device = cls.objects.select_related('DeptID').get(SN=sn)
        except cls.DoesNotExist:
            return None
        cache.set(cls.cache_key(sn), device, cls.CACHE_TTL_SECONDS)
        return device

    def save(self, *args, **kwargs):
        """Write-through: SELALU simpan ke DB, cache disegarkan mengikuti (padanan iclock.save() legacy)."""
        from django.core.cache import cache
        if self.DelTag:
            self.DelTag = 0
        super().save(*args, **kwargs)
        cache.set(self.cache_key(self.SN), self, self.CACHE_TTL_SECONDS)

    def delete(self, *args, **kwargs):
        from django.core.cache import cache
        cache.delete(self.cache_key(self.SN))
        return super().delete(*args, **kwargs)

    def save_heartbeat(self) -> None:
        """
        Update `LastActivity` dgn THROTTLE -- padanan `checkAndSave()`
        legacy: cache device (fresh LastActivity) SELALU diperbarui supaya
        `get_cached()` selalu up-to-date, TAPI penulisan ke DB cuma terjadi
        kalau sudah lewat `HEARTBEAT_DB_WRITE_THROTTLE_SECONDS` detik sejak
        DB terakhir ditulis -- device polling tiap ~30 detik (lihat resume
        protokol), tanpa throttle ini tabel `iclock` akan ditulis ULANG
        setiap request dari SETIAP device yang terhubung, sangat boros.
        """
        from django.core.cache import cache
        from django.utils import timezone as dj_timezone

        now = dj_timezone.now()
        self.LastActivity = now
        cache.set(self.cache_key(self.SN), self, self.CACHE_TTL_SECONDS)

        throttle_key = f'{self.CACHE_KEY_PREFIX}la_dbwrite_{self.SN}'
        last_db_write = cache.get(throttle_key)
        if last_db_write is None or (now - last_db_write).total_seconds() > self.HEARTBEAT_DB_WRITE_THROTTLE_SECONDS:
            type(self).objects.filter(SN=self.SN).update(LastActivity=now)
            cache.set(throttle_key, now, self.CACHE_TTL_SECONDS)

    HEARTBEAT_DB_WRITE_THROTTLE_SECONDS = 30

    def LastData(self):
        """

        Waktu transaksi (checkinout) TERAKHIR yang tercatat dari device ini
        -- beda dengan `LastActivity` (waktu request/heartbeat terakhir dari
        protokol push): ini murni query ke tabel `transaction`, jadi
        mencerminkan apakah device benar-benar masih MENGIRIM DATA absensi,
        bukan cuma "hidup"/nge-ping ke server. Return None kalau device ini
        belum pernah punya transaksi sama sekali.

        CATATAN PERFORMA: 1 query terpisah per pemanggilan (per device),
        bukan lewat annotate/subquery di level queryset -- untuk daftar
        Active Device yang dipaginate (biasanya puluhan baris per halaman)
        ini wajar, tapi kalau suatu saat listing-nya jadi sangat besar &
        tidak dipaginate, pertimbangkan pindah ke query ber-anotasi
        (Subquery/OuterRef) di view supaya jadi 1 query total, bukan N.
        """
        return transaction.objects.filter(SN=self).order_by('-TTime').values_list('TTime', flat=True).first()


class RegisteredDevice(models.Model):
    """Registered Device -- daftar master device yang diizinkan terdaftar."""

    SN = models.CharField(_('Serial Number'), max_length=20, unique=True)
    Alias = models.CharField(
        _('Alias'), max_length=20, null=True, blank=True,
        help_text=_('Diisi otomatis dgn IP Address saat device auto-registrasi (Rule 2a) -- admin bisa ubah manual nanti.'),
    )
    DeviceName = models.CharField(_('Device Name'), max_length=30, null=True, blank=True)
    DeptID = models.ForeignKey(
        department, db_column='DeptID', verbose_name=_('Pool'),
        default=1, null=True, blank=True, on_delete=models.CASCADE,
    )
    Function = models.CharField(_('Function'), max_length=20, null=True, blank=True, default='0')
    IPAddress = models.CharField(_('IP Address'), max_length=20, null=True, blank=True)
    MAC = models.CharField(_('MAC Address'), max_length=20, null=True, blank=True)
    IPRouter = models.CharField(_('IP Router'), max_length=20, null=True, blank=True)
    LastActivity = models.DateTimeField(_('Last Activity'), null=True, blank=True, editable=False)

    class Meta:
        db_table = 'iclock_registereddevice'
        managed = True
        verbose_name = _('Registered Device')
        verbose_name_plural = _('Registered Devices')

    def __str__(self):
        return self.DeviceName or self.SN

    # Cache read-through -- padanan `getNewDevice(sn)` legacy (lihat catatan
    # cache di model `iclock` di atas). Cache key TERPISAH dari `iclock`
    # (prefix beda) supaya SN yang sama tidak tabrakan antar 2 tabel ini.
    CACHE_KEY_PREFIX = 'iclock_registered_'
    CACHE_TTL_SECONDS = 300

    @classmethod
    def cache_key(cls, sn: str) -> str:
        return f'{cls.CACHE_KEY_PREFIX}{sn}'

    @classmethod
    def get_cached(cls, sn: str) -> 'RegisteredDevice | None':
        sn = (sn or '').strip()
        if not sn:
            return None
        from django.core.cache import cache
        cached = cache.get(cls.cache_key(sn))
        if cached is not None:
            return cached
        try:
            device = cls.objects.select_related('DeptID').get(SN=sn)
        except cls.DoesNotExist:
            return None
        cache.set(cls.cache_key(sn), device, cls.CACHE_TTL_SECONDS)
        return device

    def save(self, *args, **kwargs):
        from django.core.cache import cache
        super().save(*args, **kwargs)
        cache.set(self.cache_key(self.SN), self, self.CACHE_TTL_SECONDS)


def get_default_department() -> 'department':
    """
    Pool default (DeptID=0, "GUEST") -- dipakai saat device BARU auto-
    registrasi ke RegisteredDevice (belum dikonfigurasi admin, lihat
    test/myrule.md poin 2a), auto-dibuat kalau belum ada baris DeptID=0.
    Padanan `getDefaultDept()` legacy.
    """
    dept, _created = department.objects.get_or_create(
        DeptID=0, defaults={'DeptName': 'GUEST'},
    )
    return dept


class employee(models.Model):
    """Device User -- karyawan/pengguna yang terdaftar di mesin fingerprint."""

    id = models.AutoField(db_column='userid', primary_key=True)
    PIN = models.CharField(_('PIN'), db_column='badgenumber', max_length=20)
    DeptID = models.ForeignKey(
        department, db_column='defaultdeptid', verbose_name=_('Pool'),
        default=1, null=True, blank=True, on_delete=models.CASCADE,
    )
    EName = models.CharField(_('Employee Name'), db_column='name', max_length=40, null=True, blank=True, default=' ')
    Password = models.CharField(_('Password'), max_length=20, null=True, blank=True)
    Card = models.CharField(_('ID Card'), max_length=20, null=True, blank=True)
    Privilege = models.IntegerField(_('Privilege'), null=True, blank=True, choices=PRIV_CHOICES)
    AccGroup = models.IntegerField(_('Access Group'), null=True, blank=True)
    Gender = models.CharField(_('Gender'), max_length=2, choices=GENDER_CHOICES, null=True, blank=True)
    Title = models.CharField(_('Title'), max_length=20, null=True, blank=True)
    Tele = models.CharField(_('Office Phone'), db_column='ophone', max_length=20, null=True, blank=True)
    Mobile = models.CharField(_('Mobile'), db_column='pager', max_length=20, null=True, blank=True)
    SN = models.ForeignKey(
        iclock, db_column='SN', verbose_name=_('Registration Device'),
        null=True, blank=True, on_delete=models.SET_NULL,
    )
    # NOT NULL di tabel `userinfo` yang sebenarnya, editable=False juga di file asli.
    DelTag = models.SmallIntegerField(default=0, editable=False)
    UTime = models.DateTimeField(_('Refresh Time'), null=True, blank=True, editable=False)

    # Field TAMBAHAN (BUKAN kolom asli mesin ZKTeco) -- password login
    # Mobile Attendance (checkin/out/meal + enrollment wajah via PIN,
    # TANPA perlu akun accounts.User terpisah). BEDA dari `Password` di
    # atas (itu password mesin fingerprint, legacy, plaintext pendek).
    # Disimpan HASH (Django password hasher standar, PBKDF2 -- SATU ARAH,
    # bukan enkripsi reversible; ini pilihan yang lebih aman utk data
    # password, meski istilah "dienkripsi" yang dipakai bisa merujuk ke
    # keduanya), max_length 255 supaya cukup utk hash-nya. NULL/kosong
    # berarti "belum pernah ganti dari password default" -- lihat
    # accounts/mobile_backend.py & settings.MOBILE_DEFAULT_PASSWORD.
    mpassword = models.CharField(
        max_length=255, null=True, blank=True,
        help_text='Password (di-hash) login Mobile Attendance via PIN. Kosong = belum pernah diganti dari default.',
    )

    # Field TAMBAHAN -- menampung kode Pool (PoolID mclock.MobilePool)
    # TERAKHIR employee ini check-in/out/meal via MOBILE. Diisi bersamaan
    # dgn SN/UTime saat konsolidasi mobile->iclock (lihat
    # iclock/tasks.py::_refresh_employee_last_seen). Device finger biasa
    # TIDAK mengisi field ini (PoolID-nya sudah terwakili lewat SN device
    # fisik itu sendiri) -- HANYA relevan saat SN == 'ABSENDIGITAL01' (device
    # virtual gabungan mobile, semua PoolID digabung 1 SN yang sama, jadi
    # butuh field terpisah utk tahu PoolID SPESIFIK-nya).
    LastVerify = models.IntegerField(
        _('Last Mobile PoolID'), null=True, blank=True,
        help_text="Kode Pool (PoolID mobile) terakhir -- cuma terisi kalau check-in terakhir lewat mobile (SN='ABSENDIGITAL01').",
    )

    class Meta:
        db_table = 'userinfo'
        managed = True
        verbose_name = _('Device User')
        verbose_name_plural = _('Device Users')

    def __str__(self):
        return f'{self.PIN} - {self.EName}' if self.EName and self.EName.strip() else self.PIN

    def LastPool(self):
        """
        Nama Pool TERAKHIR employee ini check-in/out/meal. Utk device
        finger biasa, diambil dari Pool device tsb (SN.DeptID.DeptName --
        PoolID-nya sudah terwakili lewat device fisik itu sendiri). Utk
        MOBILE (SN == 'ABSENDIGITAL01', device virtual gabungan semua
        mobile), Pool device itu SENDIRI tidak mencerminkan lokasi
        SPESIFIK (semua mobile digabung 1 SN yg sama) -- jadi di-lookup
        dari `LastVerify` (PoolID mobile) ke mclock.MobilePool.PoolName.
        Return None kalau belum pernah check-in sama sekali.
        """
        if self.SN_id is None:
            return None
        if self.SN_id == 'ABSENDIGITAL01':
            if self.LastVerify is None:
                return None
            from mclock.models import MobilePool
            pool = MobilePool.objects.filter(PoolID=str(self.LastVerify)).first()
            return pool.PoolName if pool and pool.PoolName else f'Mobile (Pool {self.LastVerify})'
        if self.SN.DeptID_id:
            return self.SN.DeptID.DeptName
        return None

    def LastDevice(self):
        """
        Device TERAKHIR employee ini check-in/out/meal -- 'Mobile' kalau
        lewat absen mobile (device virtual gabungan 'ABSENDIGITAL01'),
        selain itu Alias device fisiknya. Return None kalau belum pernah
        check-in sama sekali.
        """
        if self.SN_id is None:
            return None
        if self.SN_id == 'ABSENDIGITAL01':
            return f'Mobile-{self.LastVerify}'
        return self.SN.Alias or self.SN_id


class fptemp(models.Model):
    """Template Jari -- data template sidik jari yang tersimpan per karyawan."""

    id = models.AutoField(db_column='templateid', primary_key=True)
    UserID = models.ForeignKey(
        employee, db_column='userid', verbose_name=_('Employee'), on_delete=models.CASCADE,
    )
    Template = models.TextField(_('Template'))
    FingerID = models.SmallIntegerField(_('Finger'), default=0, choices=FINGERIDS)
    Valid = models.SmallIntegerField(_('Valid'), default=1, choices=BOOLEANS)
    DelTag = models.SmallIntegerField(_('Deleted'), default=0, choices=BOOLEANS)
    SN = models.ForeignKey(
        iclock, db_column='SN', verbose_name=_('Registration Device'),
        null=True, blank=True, on_delete=models.CASCADE,
    )
    UTime = models.DateTimeField(_('Refresh Time'), null=True, blank=True, editable=False)

    class Meta:
        db_table = 'template'
        managed = True
        unique_together = (('UserID', 'FingerID'),)
        verbose_name = _('Fingerprint Template')
        verbose_name_plural = _('Fingerprint Templates')

    def __str__(self):
        return f'{self.UserID}, {self.get_FingerID_display()}'


class transaction(models.Model):
    """Transaction -- log absensi (check-in/check-out) dari mesin fingerprint."""

    UserID = models.ForeignKey(
        employee, db_column='userid', verbose_name=_('Employee'), on_delete=models.CASCADE,
    )
    TTime = models.DateTimeField(_('Time'), db_column='checktime')
    State = models.CharField(
        _('State'), db_column='checktype', max_length=1, default='0', choices=ATTSTATES,
    )
    Verify = models.IntegerField(_('Verification'), db_column='verifycode', default=0, choices=VERIFYS)
    SN = models.ForeignKey(
        iclock, db_column='SN', verbose_name=_('Device'), null=True, blank=True, on_delete=models.CASCADE,
    )
    WorkCode = models.CharField(_('Work Code'), max_length=20, null=True, blank=True)
    Reserved = models.CharField(_('Reserved'), max_length=20, null=True, blank=True)

    Function = models.CharField(_('Function'), max_length=20, null=True, blank=True, editable=True)

    def FncName(self):
        """Label yang bisa dibaca dari kode Function (mis. '89' -> 'KARYAWAN'), sesuai settings.DEVICEFUNCTION."""
        try:
            return settings.DEVICEFUNCTION[self.Function]
        except (KeyError, AttributeError):
            return self.Function

    class Meta:
        db_table = 'checkinout'
        managed = True
        unique_together = (('UserID', 'TTime'),)
        verbose_name = _('Transaction')
        verbose_name_plural = _('Transactions')

    def __str__(self):
        return f'{self.UserID}, {self.TTime}'


class oplog(models.Model):
    """Operation Log -- log operasi yang dilakukan admin langsung di mesin fingerprint."""

    SN = models.ForeignKey(
        iclock, db_column='SN', verbose_name=_('Device'), null=True, blank=True, on_delete=models.CASCADE,
    )
    admin = models.IntegerField(_('Device Administrator'), default=0)
    OP = models.SmallIntegerField(_('Operation Code'), default=0)
    OPTime = models.DateTimeField(_('Time'))
    Object = models.IntegerField(_('Object'), null=True, blank=True)
    Param1 = models.IntegerField(_('Parameter 1'), null=True, blank=True)
    Param2 = models.IntegerField(_('Parameter 2'), null=True, blank=True)
    Param3 = models.IntegerField(_('Parameter 3'), null=True, blank=True)

    class Meta:
        db_table = 'iclock_oplog'
        managed = True
        unique_together = (('SN', 'OPTime'),)
        verbose_name = _('Device Operation Log')
        verbose_name_plural = _('Device Operation Logs')

    def op_name(self):
        return op_name(self.OP)

    def __str__(self):
        return f'{self.SN}, {self.OP}, {self.OPTime}'


class devlog(models.Model):
    """Device Log -- log ringkasan data yang diupload device ke server (jumlah record, dll)."""

    SN = models.ForeignKey(iclock, verbose_name=_('Device'), on_delete=models.CASCADE)
    OP = models.CharField(_('Data Type'), max_length=8, default='TRANSACT')
    Object = models.CharField(_('Object'), max_length=20, null=True, blank=True)
    Cnt = models.IntegerField(_('Record Count'), default=1, blank=True)
    ECnt = models.IntegerField(_('Error Count'), default=0, blank=True)
    OpTime = models.DateTimeField(_('Upload Time'), default=timezone.now)

    class Meta:
        db_table = 'devlog'
        managed = True
        verbose_name = _('Device Log')
        verbose_name_plural = _('Device Logs')

    def __str__(self):
        return f'{self.SN}, {self.OpTime}, {self.OP}'


class devcmds(models.Model):
    """Device Command -- antrean command yang dikirim/akan dikirim ke mesin fingerprint."""

    SN = models.ForeignKey(iclock, verbose_name=_('Device'), on_delete=models.CASCADE)
    CmdContent = models.TextField(_('Command Content'), max_length=2048)
    CmdCommitTime = models.DateTimeField(_('Submit Time'), default=timezone.now)
    CmdTransTime = models.DateTimeField(_('Transfer Time'), null=True, blank=True)
    CmdOverTime = models.DateTimeField(_('Return Time'), null=True, blank=True)
    CmdReturn = models.IntegerField(_('Return Value'), null=True, blank=True)
    User = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name=_('Administrator'),
        null=True, blank=True, editable=False, on_delete=models.CASCADE,
    )

    class Meta:
        db_table = 'devcmds'
        managed = True
        verbose_name = _('Device Command')
        verbose_name_plural = _('Device Commands')

    def __str__(self):
        return f'{self.SN}, {self.CmdCommitTime}'


# ---------------------------------------------------------------------------
# Helper command queue (dipakai endpoint getrequest, akan dibangun tahap
# berikutnya) -- optimasi cache "device tanpa command tertunda", padanan
# `deviceCmd()`/`appendDevCmd()` legacy (test/models.py, test/dataproc.py).
# ---------------------------------------------------------------------------
_NOCMD_DEVICE_CACHE_KEY = 'iclock_nocmd_devices'
_NOCMD_DEVICE_CACHE_TTL = 300


def get_pending_commands(device: 'iclock', limit: int = 1000) -> list:
    """
    Ambil command yang BELUM dieksekusi device ini (`CmdOverTime` masih
    kosong), TAPI cek cache "daftar device tanpa command tertunda" dulu --
    kalau device ini ADA di daftar itu, langsung return [] TANPA query DB
    sama sekali. Device di-poll SETIAP ~30 detik oleh SEMUA device
    terhubung (lihat resume protokol), dan MAYORITAS waktu memang tidak
    ada command tertunda -- tanpa optimasi ini, tabel `devcmds` akan
    di-query berulang-ulang sia-sia oleh setiap device di setiap polling.
    """
    from django.core.cache import cache

    nocmd_devices = cache.get(_NOCMD_DEVICE_CACHE_KEY) or set()
    if device.SN in nocmd_devices:
        return []

    commands = list(
        devcmds.objects.filter(SN=device, CmdOverTime__isnull=True).order_by('id')[:limit]
    )
    if not commands:
        nocmd_devices.add(device.SN)
        cache.set(_NOCMD_DEVICE_CACHE_KEY, nocmd_devices, _NOCMD_DEVICE_CACHE_TTL)
    return commands


def clear_nocmd_cache(sn: str) -> None:
    """
    Keluarkan SN ini dari cache "tanpa command tertunda" -- dipanggil begitu
    ada command BARU ditambahkan utk device ini (append_device_command),
    ATAU begitu device kirim data baru (kemungkinan memicu command reaktif,
    mis. hapus user setelah query info), supaya polling BERIKUTNYA benar2
    mengecek DB lagi alih-alih percaya cache lama.
    """
    from django.core.cache import cache

    nocmd_devices = cache.get(_NOCMD_DEVICE_CACHE_KEY)
    if nocmd_devices and sn in nocmd_devices:
        nocmd_devices.discard(sn)
        cache.set(_NOCMD_DEVICE_CACHE_KEY, nocmd_devices, _NOCMD_DEVICE_CACHE_TTL)


def append_device_command(device: 'iclock', cmd_content: str, commit_time=None) -> 'devcmds':
    """Tambah 1 command baru ke antrean device ini -- padanan `appendDevCmd()` legacy."""
    cmd = devcmds.objects.create(
        SN=device, CmdContent=cmd_content, CmdCommitTime=commit_time or timezone.now(),
    )
    clear_nocmd_cache(device.SN)
    return cmd


class FeaturePermission(models.Model):
    """
    Model 'dummy' TANPA data/tabel sungguhan (managed=False, tidak pernah
    di-query) -- satu-satunya tujuannya adalah tempat menempelkan custom
    permission Django yang tidak terkait CRUD model manapun, supaya bisa
    diberikan ke user NON-STAFF tertentu (lewat halaman "Kelola Izin User"
    di dashboard) untuk mengakses fitur terbatas tertentu tanpa perlu jadi
    admin penuh.

    Cek permission ini di kode lewat `user.has_perm('iclock.can_transfer_finger')`
    dsb (lihat `accounts/permissions.py::permission_or_staff_required`).
    """

    class Meta:
        managed = False
        default_permissions = ()  # matikan add/change/delete/view otomatis -- kita definisikan sendiri
        permissions = [
            ('can_transfer_finger', 'Bisa melakukan Transfer Data Finger'),
            ('can_view_attendance_recap', 'Bisa melihat Rekap Absensi (Attendance Recap)'),
        ]