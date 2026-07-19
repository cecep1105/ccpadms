

from django.core.exceptions import ObjectDoesNotExist
from django.core.cache import cache
from .utils import *





"""
Model untuk app 'iclock' (integrasi mesin fingerprint/absensi ZKTeco).

PENTING - model ini diringkas dari models.py legacy yang Anda upload:
- Field & method yang bergantung pada modul `.utils`, custom setting
  `settings.UNIT` / `settings.DEVICEFUNCTION`, dan cache key legacy DIHAPUS
  karena tidak ada di scaffold ini dan akan bikin crash saat import.
- Nama `db_table` & `db_column` DIPERTAHANKAN PERSIS seperti aslinya, supaya
  kalau Anda memang menyambung ke database iclock yang sudah ada (dipakai
  mesin fingerprint fisik), datanya tetap terbaca/tersimpan dengan benar.
- `managed = False` di ke-3 model utama -> Django TIDAK akan membuat/mengubah
  struktur tabel ini lewat migration. Ini penting karena tabel-tabel ini
  kemungkinan sudah ada & dipakai proses lain (server komunikasi device).

Kalau ternyata Anda mulai dari database KOSONG (belum ada tabel iclock sama
sekali) dan mau Django yang membuat tabelnya dari nol, ubah `managed = False`
jadi `managed = True` di Meta masing-masing model, lalu jalankan:
    python manage.py makemigrations iclock
    python manage.py migrate
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
    DeviceName = models.CharField(_('Device Name'),max_length=30, null=True, blank=True,editable=False)

    # Field telemetry yang biasanya diisi otomatis oleh proses komunikasi
    # device (bukan diedit manual admin), jadi tidak dimasukkan ke form CRUD.
    State = models.IntegerField(default=1, editable=False)
    LastActivity = models.DateTimeField(_('Last Activity'), null=True, blank=True, editable=False)
    PushVersion = models.CharField(max_length=10, default=0.0, editable=False, null=True, blank=True)    



    # Kolom berikut NOT NULL di tabel `iclock` yang sebenarnya tapi memang
    # editable=False juga di file asli Anda -- diberi default supaya INSERT
    # tidak gagal.
    TransInterval = models.IntegerField(default=1, editable=False)
    UpdateDB = models.CharField(max_length=10, default='1111111100', editable=False)
    LockFunOn = models.SmallIntegerField(db_column='AccFun', default=0, editable=False)
    DelTag = models.SmallIntegerField(default=0, editable=False)
    TransTimes = models.CharField(_('transfer time'),max_length=50, null=True, blank=True, default="00:00;14:05", help_text=_('Setting device for a moment from the plane started to send checks to the new data server. Hh: mm (hours: minutes) format, with a number of time between the semicolon (;) separately'))
    TransInterval = models.IntegerField(_('interval'),default=1, help_text=_('Device set for each interval to check how many minutes to send new data server'))
    LogStamp = models.CharField(_('trans record stamp'),max_length=20, null=True, blank=True, help_text=_('Logo for the latest device to the server send the transactions timestamps'))
    OpLogStamp = models.CharField(_('trans OP stamp'),max_length=20, null=True, blank=True, help_text=_('Marking device for the server to the employee data transfer as timestamps'))
    PhotoStamp = models.CharField(_('trans photo stamp'),max_length=20, null=True, blank=True, help_text=_('Marking device for the server to the picture transfer as timestamps'))
    FWVersion = models.CharField(_('FW Version'),max_length=30, null=True, blank=True,editable=False)
    FPVersion = models.CharField(max_length=10, editable=False, null=True, blank=True)
    FPCount = models.IntegerField(_('FP Count'), null=True, blank=True,editable=False)
    TransactionCount = models.IntegerField(_('Transaction Count'), null=True, blank=True,editable=False)
    UserCount = models.IntegerField(_('User Count'), null=True, blank=True,editable=False)
    MainTime = models.CharField(_('MainTime'),max_length=20, null=True, blank=True,editable=False)
    MaxFingerCount = models.IntegerField(_('MaxFingerCount'), null=True, blank=True,editable=False)
    MaxAttLogCount = models.IntegerField(_('MaxAttLogCount'), null=True, blank=True,editable=False)

    def save(self, raw=None, **kwargs):
        if self.DelTag: self.DelTag=0
        try:
            cache.set("iclock_"+self.SN, self)
        except Exception as exc:
            raise Exception(_(u"Invalid %s")%_(u'serial number')) from exc        
        return models.Model.save(self)
    def clear(self):
        for o in self.model.objects.all().filter(DelTag__isnull=True):
            cache.delete("iclock_"+o.SN)
            o.DelTag=1
            o.save()
        return models.Model.clear(self)
    def delete(self):
        cache.delete("iclock_"+self.SN)
        try:
            cache.set("iclock_"+self.SN, self)
            self.DelTag=1   
        except Exception as exc:
            raise Exception(_(u"Invalid %s")%_(u'serial number')) from exc 
        return models.Model.save(self)





    class Meta:
        db_table = 'iclock'
        managed = True
        verbose_name = _('Active Device')
        verbose_name_plural = _('Active Devices')

    def __str__(self):
        return f'{self.SN} ({self.Alias})' if self.Alias else self.SN
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
    AccGroup = models.IntegerField(_('Access Group'),null=True, blank=True,editable=True)
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
    UTime = models.DateTimeField(_('refresh time'), null=True, blank=True, editable=False)
    
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

    class Meta:
        db_table = 'userinfo'
        managed = True
        verbose_name = _('Device User')
        verbose_name_plural = _('Device Users')

    def __str__(self):
        return f'{self.PIN} - {self.EName}' if self.EName and self.EName.strip() else self.PIN


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

    Function = models.CharField(_('Function'),max_length=20, null=True, blank=True,editable=True)

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


def getStoredFileName(sn, id, fname):
    fname="%s%s/%s"%(settings.ADDITION_FILE_ROOT, sn, fname)
    if id:
        fname, ext=os.path.splitext(fname)
        fname="%s_%s%s"%(fname,id,ext)
    fname.replace("\\\\","/")
    return fname
def getStoredFileURL(sn, id, fname):
    fname="/iclock/file/%s/%s"%(sn, fname)
    if id:
        fname, ext=os.path.splitext(fname)
        fname="%s_%s%s"%(fname,id,ext)
    return fname

def getUploadFileName(sn, id, fname):
    return getStoredFileName('upload/'+sn, id, fname)
def getUploadFileURL(sn, id, fname):
    return getStoredFileURL('upload/'+sn, id, fname)

















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











def getDevice(n):
    n=n and str(n).strip() or ""
    if not n: return None
    dev=cache.get("iclock_"+n)
    if dev:
        return dev
    try:
        dev=iclock.objects.get(SN=n)
    except ObjectDoesNotExist:
        # dev=iclock.objects.get(Alias=n)
        return None
    cache.set("iclock_"+n, dev)
    return dev

def getNewDevice(n):
    n=n and n.strip() or ""
    if not n: return None
    dev=cache.get("iclocknew_"+n)
    if dev:
        return dev
    try:
        dev=RegisteredDevice.objects.get(SN=n)
    except ObjectDoesNotExist:
        dev=None
    cache.set("iclocknew_"+n, dev)
    return dev


def getDefaultDept():
    try:
        dept = department.objects.get(DeptID=0)
    except:
        try:
            dept = department(DeptID=0, DeptName="GUEST", parent=0)
            dept.save()
        except:
            dept = department.objects.all()[0]
    return dept


last_reboot_cname="%s_lastReboot"%settings.UNIT 

def removeLastReboot(ip):
    lastReboot=cache.get(last_reboot_cname)
    if not lastReboot: return
    if ip in lastReboot:
        lastReboot.pop(ip)
        cache.set(last_reboot_cname, lastReboot)



BOOLEANS=((0,_("No")),(1,_("Yes")),)
DEV_STATUS_OK=1
DEV_STATUS_TRANS=2
DEV_STATUS_OFFLINE=3
DEV_STATUS_PAUSE=0
nocmd_device_cname="%s_nocmd_device"%settings.UNIT

def deviceCmd(device):
    nocmd_device=[]
    if nocmd_device_cname in cache:
        nocmd_device=cache.get(nocmd_device_cname)
    if nocmd_device and (device.SN in nocmd_device):
        cmds=[]
    else:
        cmds=devcmds.objects.filter(SN=device,CmdOverTime__isnull=True).order_by('id')[:1000]
        if len(cmds)==0:
            if not nocmd_device: nocmd_device=[]
            nocmd_device.append(device.SN)
            cache.set(nocmd_device_cname, nocmd_device)
        nowCmds=[]
        now=str(datetime.datetime.now())
        for cmd in cmds:
            if str(cmd.CmdCommitTime)<=now: nowCmds.append(cmd)
        return nowCmds
    return cmds


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