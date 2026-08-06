import json

from django.db import models
from django.utils.translation import gettext_lazy as _


class NetmgmtRouterDefault(models.Model):
    """
    IP router DEFAULT yang bisa diset admin per-halaman (mis. "default
    dhcpserver ip" utk halaman DHCP Lease, "default fwfilter ip" utk
    halaman Firewall Filter) -- dipakai sbg fallback kalau user BELUM
    pilih router lain lewat dropdown di halaman itu (lihat
    netmgmt/router_choices_view.py & dropdown "Router" di frontend).

    Key-value SEDERHANA (BUKAN 1 field per halaman) supaya gampang
    ditambah halaman/fitur BARU nanti yg jg butuh "default router"
    sendiri, tanpa perlu migration baru tiap kali. Diedit lewat Django
    Admin (paling simpel, tidak perlu UI kustom baru).
    """
    PAGE_CHOICES = [
        ('dhcp', _('DHCP Lease')),
        ('fwfilter', _('Firewall Filter')),
    ]

    page_key = models.CharField(_('Halaman'), max_length=30, unique=True, choices=PAGE_CHOICES)
    router_ip = models.CharField(_('IP Router Default'), max_length=20)

    class Meta:
        verbose_name = _('Router Default (NetMgmt)')
        verbose_name_plural = _('Router Default (NetMgmt)')

    def __str__(self):
        return f'{self.get_page_key_display()} -> {self.router_ip}'


class ITInfraCategory(models.Model):
    """
    Kategori Data IT-Infra (mis. "Internet", "VPS", "Domain", dll) --
    admin BEBAS bikin kategori baru sendiri (BUKAN daftar tetap
    hardcode) lewat form "Tambah Kategori" di frontend/Django Admin.
    """
    name = models.CharField(_('Nama Kategori'), max_length=50, unique=True)

    class Meta:
        verbose_name = _('Kategori Data IT-Infra')
        verbose_name_plural = _('Kategori Data IT-Infra')
        ordering = ['name']

    def __str__(self):
        return self.name


class ITInfraEntry(models.Model):
    """
    1 baris "Data IT-Infra" -- registry BEBAS/fleksibel utk macam-macam
    info infrastruktur (langganan internet: alamat MRTG/username/
    password/SID; VPS: IP public/username/password; domain: registrar/
    tanggal expired/dll) -- field-nya TIDAK DITENTUKAN SKEMA TETAP per
    kategori (beda dari model Django biasa yg field-nya fixed), MELAINKAN
    dictionary bebas (`data`, lihat get_data()/set_data()) supaya admin
    bisa simpan field APA PUN sesuai kebutuhan tiap entry, tanpa perlu
    migration Django tiap kali ada jenis data baru.

    `data` DISIMPAN TERENKRIPSI UTUH (lihat crypto_utils.py::encrypt_itinfra_data)
    -- SERING berisi password di dalam field-nya, BEDA dari JSONField
    Django biasa yg tersimpan plaintext di database.
    """
    category = models.ForeignKey(ITInfraCategory, verbose_name=_('Kategori'), on_delete=models.PROTECT, related_name='entries')
    name = models.CharField(_('Nama'), max_length=150, help_text=_('Label pengenal entry ini, mis. "Internet Kantor Pusat - Biznet"'))
    data_encrypted = models.TextField(_('Data (terenkripsi)'), blank=True, editable=False)
    notes = models.TextField(_('Catatan'), blank=True)
    # Kalau True, entry ini CUMA muncul/bisa diakses staff/admin -- user
    # portal non-staff (walau py izin granular can_view_itinfra) TIDAK
    # akan MELIHAT entry ini SAMA SEKALI (disaring dari list) & DITOLAK
    # kalau coba akses detail-nya langsung (lihat netmgmt/itinfra_view.py::
    # ITInfraEntryListView/ITInfraEntryDetailView) -- utk entry yg memang
    # PALING SENSITIF (mis. kredensial infrastruktur inti) yg admin TIDAK
    # mau tampil ke portal SAMA SEKALI, terlepas dari izin granular umum.
    is_staff_only = models.BooleanField(_('Staff Only'), default=False, help_text=_('Kalau dicentang, entry ini HANYA bisa dilihat staff/admin -- tersembunyi dari user portal non-staff meski mereka punya izin akses fitur ini.'))
    created_at = models.DateTimeField(_('Dibuat'), auto_now_add=True)
    updated_at = models.DateTimeField(_('Diperbarui'), auto_now=True)

    class Meta:
        verbose_name = _('Data IT-Infra')
        verbose_name_plural = _('Data IT-Infra')
        ordering = ['category__name', 'name']

        constraints = [
            models.UniqueConstraint(
                fields=["name", "category"],
                name="unique_name_category",
            )
        ]

    def __str__(self):
        return f'{self.category.name} - {self.name}'

    def set_data(self, data_dict: dict) -> None:
        """Enkripsi & simpan dictionary -- TIDAK langsung .save(), panggil .save() sendiri setelah ini (SAMA pola setter biasa)."""
        from netmgmt.crypto_utils import encrypt_itinfra_data
        self.data_encrypted = encrypt_itinfra_data(json.dumps(data_dict))

    def get_data(self) -> dict:
        """Dekripsi & kembalikan dictionary -- {} kalau kosong/gagal dekripsi (mis. key enkripsi belum diisi/beda) drpd meledak, biar list/detail entry LAIN tetap bisa tampil."""
        if not self.data_encrypted:
            return {}
        from netmgmt.crypto_utils import NetmgmtCryptoError, decrypt_itinfra_data
        try:
            return json.loads(decrypt_itinfra_data(self.data_encrypted))
        except (NetmgmtCryptoError, ValueError):
            return {}
