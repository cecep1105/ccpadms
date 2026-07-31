from django.contrib import admin

from .models import ITInfraCategory, NetmgmtRouterDefault

# ITInfraEntry SENGAJA TIDAK didaftarkan di admin -- `data_encrypted`
# adalah TEKS TERENKRIPSI (tidak berguna diedit langsung lewat admin
# generik Django, yg tidak tahu cara enkripsi/dekripsinya) -- kelola
# entry LEWAT FRONTEND (netmgmt/itinfra_view.py), BUKAN Django Admin.
# Kategori TETAP didaftarkan di sini (field-nya simpel, aman diedit langsung).


@admin.register(NetmgmtRouterDefault)
class NetmgmtRouterDefaultAdmin(admin.ModelAdmin):
    list_display = ('page_key', 'router_ip')


@admin.register(ITInfraCategory)
class ITInfraCategoryAdmin(admin.ModelAdmin):
    list_display = ('name',)
