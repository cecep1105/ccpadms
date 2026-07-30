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
