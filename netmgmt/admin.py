from django.contrib import admin

from .models import NetmgmtRouterDefault


@admin.register(NetmgmtRouterDefault)
class NetmgmtRouterDefaultAdmin(admin.ModelAdmin):
    list_display = ('page_key', 'router_ip')
