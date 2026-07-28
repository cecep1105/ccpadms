from django.urls import path

from .active_directory_view import (
    ADGroupListView,
    ADGroupMembersView,
    ADGroupMembershipView,
    ADUserListView,
)
from .routeros_api_view import RouterOSCommandView

app_name = 'netmgmt_api'

urlpatterns = [
    # --- Mikrotik (RouterOS) -- lihat netmgmt/routeros_api_view.py ---
    path('routeros/<str:host>/<path:command>/', RouterOSCommandView.as_view(), name='routeros-command'),

    # --- Active Directory -- lihat netmgmt/active_directory_view.py ---
    path('ad/users/', ADUserListView.as_view(), name='ad-users'),
    path('ad/groups/', ADGroupListView.as_view(), name='ad-groups'),
    # <path:group_dn> (bukan <str:>) -- DN LDAP mengandung karakter "/" JARANG tapi mungkin
    # (mis. dlm CN yg aneh), & PASTI mengandung koma -- <path:> lebih permisif drpd <str:>.
    path('ad/groups/<path:group_dn>/members/', ADGroupMembersView.as_view(), name='ad-group-members'),
    path('ad/group-membership/', ADGroupMembershipView.as_view(), name='ad-group-membership'),
]
