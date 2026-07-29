from django.urls import path

from .active_directory_dns_view import ADDNSRecordActionView, ADDNSRecordListView, ADDNSZoneListView
from .active_directory_view import (
    ADGroupListView,
    ADGroupMembersView,
    ADGroupMembershipView,
    ADLockedUsersListView,
    ADResetPasswordView,
    ADUserListView,
    ADUserToggleStatusView,
    ADUserUnlockView,
)
from .routeros_api_view import RouterOSCommandView
from .routeros_firewall_view import FirewallGrantAccessView
from .routeros_netwatch_webhook_view import NetwatchWebhookView
from .zentyal_mail_view import (
    ZentyalMailBlockSendersView,
    ZentyalMailControlView,
    ZentyalMailDetailLogView,
    ZentyalMailImapLogsView,
    ZentyalMailIpViaEmailView,
    ZentyalMailLogView,
    ZentyalMailQHeaderView,
    ZentyalMailQueueView,
    ZentyalMailSaslLogsView,
    ZentyalMailTodayLogView,
    ZentyalMailTransportView,
)
from .zentyal_view import (
    ZentyalGroupListView,
    ZentyalGroupMembersView,
    ZentyalGroupMembershipView,
    ZentyalResetPasswordView,
    ZentyalUserListView,
)

app_name = 'netmgmt_api'

urlpatterns = [
    # --- Webhook Netwatch (dipanggil LANGSUNG oleh script RouterOS, BUKAN
    # user login -- lihat netmgmt/routeros_netwatch_webhook_view.py &
    # test/netwatchscript.txt). TANPA trailing slash SENGAJA disamakan
    # persis dgn URL di script Mikrotik (APPEND_SLASH Django bisa bikin
    # redirect 301 utk POST tanpa slash yg BERISIKO kehilangan body di
    # sebagian HTTP client -- termasuk kemungkinan `/tool fetch` RouterOS,
    # jadi disediakan KEDUA varian, dgn & tanpa slash, biar aman apa pun
    # persis URL yg dipakai script Anda).
    path('nwupdate', NetwatchWebhookView.as_view(), name='netwatch-webhook'),
    path('nwupdate/', NetwatchWebhookView.as_view(), name='netwatch-webhook-slash'),

    # --- Mikrotik (RouterOS) -- lihat netmgmt/routeros_api_view.py ---
    # PENTING: 'firewall/grant-access/' WAJIB didaftarkan SEBELUM route
    # generik di bawahnya -- route generik pakai <path:command> yang
    # GREEDY (nangkep APA PUN termasuk "firewall/grant-access"), Django
    # coba pattern SESUAI URUTAN, jadi yang LEBIH SPESIFIK harus duluan.
    path('routeros/<str:host>/firewall/grant-access/', FirewallGrantAccessView.as_view(), name='routeros-firewall-grant-access'),
    path('routeros/<str:host>/<path:command>/', RouterOSCommandView.as_view(), name='routeros-command'),

    # --- Active Directory -- lihat netmgmt/active_directory_view.py ---
    path('ad/users/', ADUserListView.as_view(), name='ad-users'),
    path('ad/groups/', ADGroupListView.as_view(), name='ad-groups'),
    path('ad/groups/<path:group_dn>/members/', ADGroupMembersView.as_view(), name='ad-group-members'),
    path('ad/group-membership/', ADGroupMembershipView.as_view(), name='ad-group-membership'),
    path('ad/reset-password/', ADResetPasswordView.as_view(), name='ad-reset-password'),
    path('ad/users/toggle-status/', ADUserToggleStatusView.as_view(), name='ad-user-toggle-status'),
    path('ad/users/locked/', ADLockedUsersListView.as_view(), name='ad-users-locked'),
    path('ad/users/unlock/', ADUserUnlockView.as_view(), name='ad-user-unlock'),

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

    # --- Zentyal Mail API (Flask, mail queue/log/dst) -- lihat netmgmt/zentyal_mail_view.py ---
    path('zentyal-mail/queue/', ZentyalMailQueueView.as_view(), name='zentyal-mail-queue'),
    path('zentyal-mail/today-log/', ZentyalMailTodayLogView.as_view(), name='zentyal-mail-today-log'),
    path('zentyal-mail/detail-log/', ZentyalMailDetailLogView.as_view(), name='zentyal-mail-detail-log'),
    path('zentyal-mail/qheader/', ZentyalMailQHeaderView.as_view(), name='zentyal-mail-qheader'),
    path('zentyal-mail/log/', ZentyalMailLogView.as_view(), name='zentyal-mail-log'),
    path('zentyal-mail/transport/', ZentyalMailTransportView.as_view(), name='zentyal-mail-transport'),
    path('zentyal-mail/block-senders/', ZentyalMailBlockSendersView.as_view(), name='zentyal-mail-block-senders'),
    path('zentyal-mail/imap-logs/', ZentyalMailImapLogsView.as_view(), name='zentyal-mail-imap-logs'),
    path('zentyal-mail/sasl-logs/', ZentyalMailSaslLogsView.as_view(), name='zentyal-mail-sasl-logs'),
    path('zentyal-mail/ip-via-email/', ZentyalMailIpViaEmailView.as_view(), name='zentyal-mail-ip-via-email'),
    path('zentyal-mail/control/', ZentyalMailControlView.as_view(), name='zentyal-mail-control'),
]
