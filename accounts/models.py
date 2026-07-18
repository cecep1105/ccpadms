from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    class AuthSource(models.TextChoices):
        LOCAL = 'local', 'Local'
        LDAP = 'ldap', 'LDAP'
        MOBILE_PIN = 'mobile_pin', 'Mobile (PIN Employee)'

    auth_source = models.CharField(
        max_length=10,
        choices=AuthSource.choices,
        default=AuthSource.LOCAL,
        help_text='Sumber identitas user: dibuat manual (local), sinkron dari LDAP, atau otomatis dari login mobile via PIN.',
    )
    must_change_password = models.BooleanField(
        default=False,
        help_text='True kalau password baru saja di-reset admin / dibuat baru, wajib ganti.',
    )
    is_mobile_only = models.BooleanField(
        default=False,
        help_text=(
            'True kalau akun ini dibuat OTOMATIS lewat login Mobile Attendance via PIN Employee '
            '(accounts/mobile_backend.py), BUKAN akun biasa yang dibuat admin/LDAP. Akses dibatasi '
            'HANYA ke check-in/out/meal & enrollment wajah -- lihat accounts/middleware.py.'
        ),
    )

    # Field profil tambahan (dipakai di halaman "Update Profile")
    phone_number = models.CharField(max_length=30, blank=True)
    department = models.CharField(max_length=100, blank=True)
    title = models.CharField(max_length=100, blank=True)

    # Link OPSIONAL ke data Employee di iclock (mis. utk kaitkan akun login
    # user non-staff dengan data karyawan fisiknya -- dipakai kalau nanti
    # perlu tahu "user ini mewakili employee yang mana"). String reference
    # ('iclock.employee') dipakai supaya tidak perlu import langsung model
    # iclock ke sini (menghindari kemungkinan circular import antar app).
    #
    # PENTING: FK ini merujuk ke primary key ASLI employee (`id`/`userid`),
    # BUKAN ke `PIN` -- karena PIN di tabel employee TIDAK unique (1 PIN
    # yang sama bisa terdaftar di beberapa device berbeda, tiap kombinasi
    # jadi row employee terpisah dengan `id` sendiri-sendiri). Kalau
    # butuh tampilkan/cari berdasarkan PIN, akses lewat `user.EmpID.PIN`
    # (relasi), jangan asumsikan `user.EmpID_id` sama dengan nilai PIN.
    EmpID = models.ForeignKey(
        'iclock.employee', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='user_accounts', verbose_name='Employee',
        help_text='Link opsional ke data Employee (iclock) yang berkaitan dengan akun user ini.',
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'accounts_user'
        ordering = ['username']

    @property
    def is_admin_role(self) -> bool:
        return self.is_staff or self.is_superuser

    @property
    def full_name(self) -> str:
        return self.get_full_name() or self.username

    def __str__(self) -> str:
        return self.username
