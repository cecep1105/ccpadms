"""
Aplikasi ID Card -- pembuatan kartu identitas karyawan/driver/visitor/BHL
(buruh harian lepas), dengan template background per jenis kartu
(disimpan di database, bukan file statis) + pencatatan status cetak
(belum cetak/sudah cetak/hilang/cetak ulang).

Alur singkat:
1. Admin upload template BACKGROUND per jenis kartu (IDCardTemplate) --
   posisi foto/nama/dll di atas background FIXED (dirancang di
   idcard/card_generator.py), BUKAN diatur bebas oleh admin.
2. Untuk Karyawan/Driver: data (nama, PIN) diambil dari iclock.employee
   yang SUDAH ada, foto diambil dari FTP eksternal (idcard/photo_utils.py)
   ATAU shoot langsung lewat webcam.
   Untuk Visitor/BHL: TIDAK ada PIN, data diinput manual (IDCardHolder),
   foto WAJIB shoot langsung/upload (tidak ada sumber FTP utk mereka).
3. Kartu di-generate (IDCard, gabungan template + foto + data jadi 1
   gambar akhir siap cetak).
4. Status cetak dicatat & bisa berubah dari waktu ke waktu (IDCardLog) --
   riwayat LENGKAP tersimpan (bukan cuma status TERAKHIR), IDCard.status
   selalu mencerminkan entry IDCardLog PALING BARU.
"""
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _


CARD_TYPE_CHOICES = [
    ('karyawan', _('Karyawan')),
    ('driver', _('Driver')),
    ('visitor', _('Visitor')),
    ('bhl', _('BHL (Buruh Harian Lepas)')),
]
EMPLOYEE_LINKED_CARD_TYPES = {'karyawan', 'driver'}
HOLDER_CARD_TYPES = {'visitor', 'bhl'}

PHOTO_SOURCE_CHOICES = [
    ('ftp', _('Ambil dari FTP')),
    ('shoot', _('Shoot Langsung')),
    ('upload', _('Upload File')),
]

STATUS_CHOICES = [
    ('belum_cetak', _('Belum Cetak')),
    ('sudah_cetak', _('Sudah Cetak')),
    ('hilang', _('Hilang')),
    ('cetak_ulang', _('Cetak Ulang')),
]


class IDCardTemplate(models.Model):
    """Template BACKGROUND per jenis kartu -- posisi foto/nama/PIN/dll di atas background FIXED (idcard/card_generator.py::CARD_LAYOUT), bukan diatur bebas."""
    card_type = models.CharField(_('Jenis Kartu'), max_length=20, choices=CARD_TYPE_CHOICES)
    name = models.CharField(_('Nama Template'), max_length=100, help_text=_('Label pengenal, mis. "Karyawan - Biru 2026"'))
    background_image = models.ImageField(_('Gambar Background'), upload_to='idcard/templates/')
    is_active = models.BooleanField(_('Aktif'), default=True, help_text=_('Kalau nonaktif, template ini tidak muncul sbg pilihan saat generate kartu baru.'))
    created_at = models.DateTimeField(_('Dibuat'), auto_now_add=True)
    updated_at = models.DateTimeField(_('Diperbarui'), auto_now=True)

    class Meta:
        ordering = ['card_type', '-is_active', '-created_at']
        verbose_name = _('Template ID Card')
        verbose_name_plural = _('Template ID Card')

    def __str__(self):
        return f'{self.get_card_type_display()} - {self.name}'


class IDCardHolder(models.Model):
    """Data pemegang kartu utk jenis kartu yang TIDAK punya PIN absensi (Visitor/BHL) -- diinput manual, terpisah dari iclock.employee."""
    card_type = models.CharField(_('Jenis Kartu'), max_length=20, choices=[c for c in CARD_TYPE_CHOICES if c[0] in HOLDER_CARD_TYPES])
    full_name = models.CharField(_('Nama Lengkap'), max_length=150)
    id_number = models.CharField(_('No. KTP/Identitas'), max_length=50, blank=True)
    company = models.CharField(_('Perusahaan/Asal'), max_length=150, blank=True, help_text=_('Utk Visitor: perusahaan asal tamu.'))
    purpose = models.CharField(_('Keperluan/Sponsor'), max_length=255, blank=True, help_text=_('Utk Visitor: tujuan kunjungan/nama yang dituju.'))
    photo = models.ImageField(_('Foto'), upload_to='idcard/holder_photos/', blank=True, null=True)
    valid_from = models.DateField(_('Berlaku Dari'), null=True, blank=True)
    valid_until = models.DateField(_('Berlaku Sampai'), null=True, blank=True, help_text=_('Kosongkan kalau tidak ada batas waktu.'))
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name=_('Dibuat Oleh'), null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    created_at = models.DateTimeField(_('Dibuat'), auto_now_add=True)
    updated_at = models.DateTimeField(_('Diperbarui'), auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = _('Data Pemegang Kartu (Visitor/BHL)')
        verbose_name_plural = _('Data Pemegang Kartu (Visitor/BHL)')

    def __str__(self):
        return f'{self.full_name} ({self.get_card_type_display()})'


class IDCard(models.Model):
    """1 kartu yang sudah digenerate. `employee` XOR `holder` wajib keisi salah satu, tergantung `card_type` (ditegakkan di clean())."""
    card_type = models.CharField(_('Jenis Kartu'), max_length=20, choices=CARD_TYPE_CHOICES)
    employee = models.ForeignKey('iclock.employee', verbose_name=_('Karyawan'), null=True, blank=True, on_delete=models.SET_NULL, related_name='id_cards')
    holder = models.ForeignKey(IDCardHolder, verbose_name=_('Pemegang Kartu'), null=True, blank=True, on_delete=models.SET_NULL, related_name='id_cards')
    template = models.ForeignKey(IDCardTemplate, verbose_name=_('Template'), on_delete=models.PROTECT, related_name='id_cards')

    photo_source = models.CharField(_('Sumber Foto'), max_length=10, choices=PHOTO_SOURCE_CHOICES)
    photo = models.ImageField(_('Foto Sumber'), upload_to='idcard/source_photos/', help_text=_('Foto MENTAH sebelum di-composite ke template (utk arsip/generate ulang).'))
    card_image = models.ImageField(_('Hasil Kartu'), upload_to='idcard/generated/', help_text=_('Gambar akhir siap cetak.'))

    status = models.CharField(_('Status'), max_length=20, choices=STATUS_CHOICES, default='belum_cetak')

    generated_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name=_('Dibuat Oleh'), null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    generated_at = models.DateTimeField(_('Digenerate'), auto_now_add=True)
    updated_at = models.DateTimeField(_('Diperbarui'), auto_now=True)

    class Meta:
        ordering = ['-generated_at']
        verbose_name = _('ID Card')
        verbose_name_plural = _('ID Card')

    def __str__(self):
        holder_label = self.employee.EName if self.employee_id else (self.holder.full_name if self.holder_id else '?')
        return f'{self.get_card_type_display()} - {holder_label}'

    def clean(self):
        is_employee_linked = self.card_type in EMPLOYEE_LINKED_CARD_TYPES
        if is_employee_linked:
            if not self.employee_id:
                raise ValidationError({'employee': _('Kartu jenis ini wajib terkait ke data Employee.')})
            if self.holder_id:
                raise ValidationError({'holder': _('Kartu jenis ini tidak boleh terkait ke Holder (pakai Employee).')})
        else:
            if not self.holder_id:
                raise ValidationError({'holder': _('Kartu jenis ini wajib terkait ke data Holder (Visitor/BHL).')})
            if self.employee_id:
                raise ValidationError({'employee': _('Kartu jenis ini tidak boleh terkait ke Employee (pakai Holder).')})

    @property
    def holder_name(self) -> str:
        if self.employee_id:
            return self.employee.EName or ''
        if self.holder_id:
            return self.holder.full_name
        return ''

    @property
    def holder_identifier(self) -> str:
        """PIN (karyawan/driver) atau No. KTP/Identitas (visitor/BHL)."""
        if self.employee_id:
            return self.employee.PIN
        if self.holder_id:
            return self.holder.id_number
        return ''


class IDCardLog(models.Model):
    """Riwayat lengkap perubahan status 1 kartu -- urutan bebas, tidak ada validasi transisi status."""
    card = models.ForeignKey(IDCard, verbose_name=_('Kartu'), on_delete=models.CASCADE, related_name='logs')
    status = models.CharField(_('Status'), max_length=20, choices=STATUS_CHOICES)
    notes = models.TextField(_('Catatan'), blank=True)
    changed_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name=_('Dicatat Oleh'), null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    changed_at = models.DateTimeField(_('Waktu'), auto_now_add=True)

    class Meta:
        ordering = ['-changed_at']
        verbose_name = _('Log Status ID Card')
        verbose_name_plural = _('Log Status ID Card')

    def __str__(self):
        return f'{self.card_id} -> {self.get_status_display()} ({self.changed_at:%Y-%m-%d %H:%M})'
