from django.urls import path

from .active_directory_dns_view import ADDNSRecordActionView, ADDNSRecordListView, ADDNSZoneListView
from .active_directory_view import (
    ADGroupListView,
    ADGroupMembersView,
    ADGroupMembershipView,
    ADResetPasswordView,
    ADUserListView,
)
from .routeros_api_view import RouterOSCommandView
from .zentyal_view import (
    ZentyalGroupListView,
    ZentyalGroupMembersView,
    ZentyalGroupMembershipView,
    ZentyalResetPasswordView,
    ZentyalUserListView,
)

app_name = 'netmgmt_api'

urlpatterns = [
    # --- Mikrotik (RouterOS) -- lihat netmgmt/routeros_api_view.py ---
    path('routeros/<str:host>/<path:command>/', RouterOSCommandView.as_view(), name='routeros-command'),

    # --- Active Directory -- lihat netmgmt/active_directory_view.py ---
    path('ad/users/', ADUserListView.as_view(), name='ad-users'),
    path('ad/groups/', ADGroupListView.as_view(), name='ad-groups'),
    path('ad/groups/<path:group_dn>/members/', ADGroupMembersView.as_view(), name='ad-group-members'),
    path('ad/group-membership/', ADGroupMembershipView.as_view(), name='ad-group-membership'),
    path('ad/reset-password/', ADResetPasswordView.as_view(), name='ad-reset-password'),

    # --- Active Directory DNS -- lihat netmgmt/active_directory_dns_view.py ---
    path('ad/dns/zones/', ADDNSZoneListView.as_view(), name='ad-dns-zones'),
    path('ad/dns/zones/<path:zone_dn>/records/', ADDNSRecordListView.as_view(), name='ad-dns-records'),
    path('ad/dns/records/', ADDNSRecordActionView.as_view(), name='ad-dns-record-action'),

    # --- Zentyal LDAP (mail server) -- lihat netmgmt/zentyal_view.py ---
    path('zentyal/users/', ZentyalUserListView.as_view(), name='zentyal-users'),
    path('zentyal/groups/', ZentyalGroupListView.as_view(), name='zentyal-groups'),
    path('zentyal/groups/<path:group_dn>/members/', ZentyalGroupMembersView.as_view(), name='zentyal-group-members'),
    path('zentyal/group-membership/', ZentyalGroupMembershipView.as_view(), name='zentyal-group-membership'),
    path('zentyal/reset-password/', ZentyalResetPasswordView.as_view(), name='zentyal-reset-password'),
]
