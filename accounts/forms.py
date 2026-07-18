from django import forms

from iclock.models import employee

INPUT_CLS = (
    'w-full px-3 py-2 border border-slate-300 dark:border-slate-600 rounded-lg text-sm '
    'bg-white dark:bg-slate-800 text-slate-800 dark:text-slate-200 '
    'focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none'
)
CHECKBOX_CLS = 'h-4 w-4 text-indigo-600 rounded border-slate-300 dark:border-slate-600 focus:ring-indigo-500'


def _text(**extra_attrs):
    attrs = {'class': INPUT_CLS}
    attrs.update(extra_attrs)
    return forms.TextInput(attrs=attrs)


def _email(**extra_attrs):
    attrs = {'class': INPUT_CLS}
    attrs.update(extra_attrs)
    return forms.EmailInput(attrs=attrs)


def _password(**extra_attrs):
    attrs = {'class': INPUT_CLS}
    attrs.update(extra_attrs)
    return forms.PasswordInput(attrs=attrs)


class LoginForm(forms.Form):
    username = forms.CharField(max_length=150, widget=_text(placeholder='username', autofocus=True))
    password = forms.CharField(widget=_password(placeholder='••••••••'))


class LocalUserCreateForm(forms.Form):
    username = forms.CharField(max_length=150, widget=_text(placeholder='username'))
    email = forms.EmailField(required=False, widget=_email(placeholder='nama@perusahaan.com'))
    first_name = forms.CharField(max_length=150, required=False, widget=_text())
    last_name = forms.CharField(max_length=150, required=False, widget=_text())
    password = forms.CharField(widget=_password(placeholder='Minimal 8 karakter'))
    is_staff = forms.BooleanField(required=False, label='Jadikan Admin', widget=forms.CheckboxInput(attrs={'class': CHECKBOX_CLS}))
    # emp_id: HIDDEN -- nilai sungguhan = PIN employee terpilih. Kotak
    # pencarian yg terlihat ("ketik PIN/nama...") murni UI di template/JS
    # (autocomplete, reuse endpoint iclock:ajax_employee_search), yang
    # otomatis isi hidden field ini saat 1 saran diklik.
    emp_id = forms.CharField(required=False, widget=forms.HiddenInput())

    def clean_emp_id(self):
        pin = (self.cleaned_data.get('emp_id') or '').strip()
        if not pin:
            return None
        # PENTING: PIN di tabel employee TIDAK unique (1 PIN bisa terdaftar
        # di beberapa device berbeda -- tiap kombinasi PIN+device jadi row
        # employee terpisah dgn id sendiri-sendiri). Jadi pakai .filter()
        # + .first() (bukan .get(), yg akan crash MultipleObjectsReturned
        # kalau PIN itu kebetulan terdaftar di >1 device) -- ambil match
        # PERTAMA yang ketemu, cukup baik utk keperluan link akun user ke
        # satu representasi employee (bukan device registration spesifik).
        emp = employee.objects.filter(PIN=pin).first()
        if not emp:
            raise forms.ValidationError(f"Employee dengan PIN '{pin}' tidak ditemukan.")
        return emp


class UserEditForm(forms.Form):
    email = forms.EmailField(required=False, widget=_email())
    first_name = forms.CharField(max_length=150, required=False, widget=_text())
    last_name = forms.CharField(max_length=150, required=False, widget=_text())
    phone_number = forms.CharField(max_length=30, required=False, widget=_text())
    department = forms.CharField(max_length=100, required=False, widget=_text())
    title = forms.CharField(max_length=100, required=False, widget=_text())
    emp_id = forms.CharField(required=False, widget=forms.HiddenInput())

    def clean_emp_id(self):
        pin = (self.cleaned_data.get('emp_id') or '').strip()
        if not pin:
            return None
        # PENTING: PIN di tabel employee TIDAK unique (1 PIN bisa terdaftar
        # di beberapa device berbeda -- tiap kombinasi PIN+device jadi row
        # employee terpisah dgn id sendiri-sendiri). Jadi pakai .filter()
        # + .first() (bukan .get(), yg akan crash MultipleObjectsReturned
        # kalau PIN itu kebetulan terdaftar di >1 device) -- ambil match
        # PERTAMA yang ketemu, cukup baik utk keperluan link akun user ke
        # satu representasi employee (bukan device registration spesifik).
        emp = employee.objects.filter(PIN=pin).first()
        if not emp:
            raise forms.ValidationError(f"Employee dengan PIN '{pin}' tidak ditemukan.")
        return emp


class ProfileForm(forms.Form):
    email = forms.EmailField(required=False, widget=_email())
    first_name = forms.CharField(max_length=150, required=False, widget=_text())
    last_name = forms.CharField(max_length=150, required=False, widget=_text())
    phone_number = forms.CharField(max_length=30, required=False, widget=_text())
    department = forms.CharField(max_length=100, required=False, widget=_text())
    title = forms.CharField(max_length=100, required=False, widget=_text())


class ChangePasswordForm(forms.Form):
    old_password = forms.CharField(widget=_password())
    new_password = forms.CharField(widget=_password(placeholder='Minimal 8 karakter'))
    new_password_confirm = forms.CharField(widget=_password())

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('new_password') != cleaned.get('new_password_confirm'):
            raise forms.ValidationError('Konfirmasi password baru tidak cocok')
        return cleaned


class AdminResetPasswordForm(forms.Form):
    new_password = forms.CharField(
        required=False,
        widget=_password(placeholder='Kosongkan untuk generate otomatis'),
    )
