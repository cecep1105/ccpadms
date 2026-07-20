import re

from django import forms
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.validators import validate_ipv4_address

from .models import RegisteredDevice, department, devcmds, devlog, employee, fptemp, iclock, oplog, transaction

INPUT_CLS = (
    'w-full px-3 py-2 border border-slate-300 dark:border-slate-600 rounded-lg text-sm '
    'bg-white dark:bg-slate-800 text-slate-800 dark:text-slate-200 '
    'focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none'
)


def _text(**extra):
    attrs = {'class': INPUT_CLS}
    attrs.update(extra)
    return forms.TextInput(attrs=attrs)


def _select(**extra):
    attrs = {'class': INPUT_CLS}
    attrs.update(extra)
    return forms.Select(attrs=attrs)


def _device_function_choices(empty_label='-- Pilih Function --'):
    """
    Pilihan combo 'Function' dari settings.DEVICEFUNCTION, dipakai bareng
    oleh ActiveDeviceForm, RegisteredDeviceForm, dan AttendanceRecapFilterForm
    -- supaya kalau DEVICEFUNCTION di settings.py berubah, otomatis ikut
    berubah di semua form ini tanpa perlu edit satu-satu.
    """
    from django.conf import settings
    choices = [('', empty_label)]
    choices += list(getattr(settings, 'DEVICEFUNCTION', {}).items())
    return choices


class DepartmentForm(forms.ModelForm):
    """Form untuk 'department' (Pool). DeptID cuma bisa diisi saat create (primary key)."""

    class Meta:
        model = department
        fields = ['DeptID', 'DeptName', 'NetID', 'DeptRouter', 'DeptSubnet']
        widgets = {
            'DeptID': _text(type='number', placeholder='ID unik pool'),
            'DeptName': _text(placeholder='Nama pool/departemen'),
            'NetID': _text(type='number'),
            'DeptRouter': _text(placeholder='192.168.1.254'),
            'DeptSubnet': _text(placeholder='192.168.1.0/24'),
        }

    def __init__(self, *args, is_create=True, **kwargs):
        super().__init__(*args, **kwargs)
        if not is_create:
            # DeptID adalah primary key -> tidak boleh diubah setelah dibuat
            self.fields['DeptID'].disabled = True


class ActiveDeviceForm(forms.ModelForm):
    """Form untuk 'iclock' (Active Device). SN cuma bisa diisi saat create (primary key)."""

    Function = forms.ChoiceField(label='Function', required=False, widget=_select())

    class Meta:
        model = iclock
        fields = [
            'SN', 'Alias', 'DeptID', 'Function', 'IPAddress', 'MAC', 'TZAdj',
            # Konfigurasi PUSH SDK per-device (test/myrule.md Rule 2) --
            # dikirim ke device sbg respons GET /iclock/cdata?options=all.
            'LogStamp', 'OpLogStamp', 'PhotoStamp', 'TransTimes', 'TransInterval',
            'UpdateDB', 'ErrorDelay', 'Delay', 'Realtime', 'Encrypt',
        ]
        widgets = {
            'SN': _text(placeholder='Serial number mesin'),
            'Alias': _text(placeholder='Nama alias device'),
            'DeptID': _select(),
            'IPAddress': _text(placeholder='192.168.1.100'),
            'MAC': _text(placeholder='00:11:22:33:44:55'),
            'TZAdj': _text(type='number'),
            'LogStamp': _text(placeholder='Timestamp ATTLOG terakhir'),
            'OpLogStamp': _text(placeholder='Timestamp OPERLOG terakhir'),
            'PhotoStamp': _text(placeholder='Timestamp foto terakhir'),
            'TransTimes': _text(placeholder='00:00;14:05'),
            'TransInterval': _text(type='number'),
            'UpdateDB': _text(placeholder='1111111100 (TransFlag)'),
            'ErrorDelay': _text(type='number'),
            'Delay': _text(type='number'),
            'Realtime': forms.CheckboxInput(attrs={'class': 'rounded border-slate-300'}),
            'Encrypt': forms.CheckboxInput(attrs={'class': 'rounded border-slate-300'}),
        }

    def __init__(self, *args, is_create=True, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['DeptID'].required = False
        self.fields['Function'].choices = _device_function_choices()
        if not is_create:
            # SN adalah primary key -> tidak boleh diubah setelah dibuat
            self.fields['SN'].disabled = True


class RegisteredDeviceForm(forms.ModelForm):
    Function = forms.ChoiceField(label='Function', required=False, widget=_select())

    class Meta:
        model = RegisteredDevice
        fields = ['SN', 'DeviceName', 'DeptID', 'Function', 'IPAddress', 'MAC', 'IPRouter']
        widgets = {
            'SN': _text(placeholder='Serial number mesin'),
            'DeviceName': _text(placeholder='Nama device'),
            'DeptID': _select(),
            'IPAddress': _text(placeholder='192.168.1.100'),
            'MAC': _text(placeholder='00:11:22:33:44:55'),
            'IPRouter': _text(placeholder='192.168.1.1'),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['DeptID'].required = False
        self.fields['Function'].choices = _device_function_choices()


class EmployeeForm(forms.ModelForm):
    class Meta:
        model = employee
        fields = [
            'PIN', 'EName', 'DeptID', 'SN', 'Gender', 'Title',
            'Card', 'Privilege', 'Tele', 'Mobile', 'Password',
        ]
        widgets = {
            'PIN': _text(placeholder='PIN / badge number'),
            'EName': _text(placeholder='Nama karyawan'),
            'DeptID': _select(),
            'SN': _select(),
            'Gender': _select(),
            'Title': _text(placeholder='Jabatan'),
            'Card': _text(placeholder='Nomor kartu ID'),
            'Privilege': _select(),
            'Tele': _text(placeholder='Telepon kantor'),
            'Mobile': _text(placeholder='No. HP'),
            'Password': forms.PasswordInput(attrs={'class': INPUT_CLS}, render_value=True),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['DeptID'].required = False
        self.fields['SN'].required = False
        self.fields['Password'].required = False


def _textarea(**extra):
    attrs = {'class': INPUT_CLS, 'rows': 4}
    attrs.update(extra)
    return forms.Textarea(attrs=attrs)


class TransferFingerForm(forms.Form):
    """
    Form transfer fingerprint: 1+ PIN (textarea multiline) dari 1 source
    device ke 1 target device tertentu, atau ke SEMUA device di sebuah pool
    kalau target_device dikosongkan.
    """
    pins = forms.CharField(
        label='User ID (PIN)',
        widget=_textarea(rows=8, placeholder='Satu PIN per baris, mis:\n1001\n1002\n1003'),
    )
    from_device = forms.ModelChoiceField(queryset=iclock.objects.all().order_by('Alias'), label='From Device')
    to_pool = forms.ModelChoiceField(queryset=department.objects.all().order_by('DeptName'), label='To Pool')
    target_device = forms.ModelChoiceField(
        queryset=iclock.objects.none(), required=False, label='Target Device',
        help_text='Kosongkan untuk transfer ke SEMUA device di pool yang dipilih.',
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # PENTING: update attrs widget yang SUDAH ADA (bukan ganti objek widget-nya),
        # supaya link ke `choices` milik ModelChoiceField tidak putus -- kalau
        # widget-nya diganti objek baru, dropdown-nya jadi kosong sama sekali.
        for name in ('from_device', 'to_pool', 'target_device'):
            self.fields[name].widget.attrs.update({'class': INPUT_CLS})

        # target_device querysetnya tergantung to_pool yang dipilih -- ambil
        # dari data yang di-submit (POST) atau dari initial (render awal GET),
        # supaya validasi ModelChoiceField tidak menolak pilihan yang valid.
        pool_id = None
        if self.data.get('to_pool'):
            pool_id = self.data.get('to_pool')
        elif self.initial.get('to_pool'):
            pool_id = self.initial.get('to_pool')
        if pool_id:
            self.fields['target_device'].queryset = iclock.objects.filter(DeptID_id=pool_id).order_by('Alias')

    def clean_pins(self):
        raw = self.cleaned_data['pins']
        pins = [line.strip() for line in raw.splitlines() if line.strip()]
        if not pins:
            raise forms.ValidationError('Isi minimal 1 User ID (PIN), satu per baris.')
        return pins

    def clean(self):
        cleaned = super().clean()
        to_pool = cleaned.get('to_pool')
        target_device = cleaned.get('target_device')
        if target_device and to_pool and target_device.DeptID_id != to_pool.pk:
            raise forms.ValidationError('Target Device yang dipilih bukan bagian dari Pool tujuan.')
        if to_pool and not target_device:
            if not iclock.objects.filter(DeptID=to_pool).exists():
                raise forms.ValidationError(f"Pool '{to_pool}' tidak punya device sama sekali.")
        return cleaned


class EmployeeTransferFingerForm(forms.Form):
    """
    Versi transfer fingerprint khusus dari konteks Employee: PIN tetap 1
    (employee yang dipilih, tidak bisa diedit -- makanya tidak ada field
    'pins' di sini), dan tidak ada combo 'From Device' karena source device
    otomatis dari employee.SN (device tempat dia terdaftar).
    """
    to_pool = forms.ModelChoiceField(queryset=department.objects.all().order_by('DeptName'), label='To Pool')
    target_device = forms.ModelChoiceField(
        queryset=iclock.objects.none(), required=False, label='Target Device',
        help_text='Kosongkan untuk transfer ke SEMUA device di pool yang dipilih.',
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ('to_pool', 'target_device'):
            self.fields[name].widget.attrs.update({'class': INPUT_CLS})

        pool_id = None
        if self.data.get('to_pool'):
            pool_id = self.data.get('to_pool')
        elif self.initial.get('to_pool'):
            pool_id = self.initial.get('to_pool')
        if pool_id:
            self.fields['target_device'].queryset = iclock.objects.filter(DeptID_id=pool_id).order_by('Alias')

    def clean(self):
        cleaned = super().clean()
        to_pool = cleaned.get('to_pool')
        target_device = cleaned.get('target_device')
        if target_device and to_pool and target_device.DeptID_id != to_pool.pk:
            raise forms.ValidationError('Target Device yang dipilih bukan bagian dari Pool tujuan.')
        if to_pool and not target_device:
            if not iclock.objects.filter(DeptID=to_pool).exists():
                raise forms.ValidationError(f"Pool '{to_pool}' tidak punya device sama sekali.")
        return cleaned


def _datetime(**extra):
    attrs = {'class': INPUT_CLS, 'type': 'datetime-local'}
    attrs.update(extra)
    return forms.DateTimeInput(attrs=attrs, format='%Y-%m-%dT%H:%M')


class FingerprintTemplateForm(forms.ModelForm):
    class Meta:
        model = fptemp
        fields = ['UserID', 'FingerID', 'Valid', 'DelTag', 'SN', 'Template']
        widgets = {
            'UserID': _select(),
            'FingerID': _select(),
            'Valid': _select(),
            'DelTag': _select(),
            'SN': _select(),
            'Template': _textarea(placeholder='Data template (base64) dari mesin'),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['SN'].required = False


class TransactionForm(forms.ModelForm):
    class Meta:
        model = transaction
        fields = ['UserID', 'TTime', 'State', 'Verify', 'SN', 'WorkCode', 'Reserved']
        widgets = {
            'UserID': _select(),
            'TTime': _datetime(),
            'State': _select(),
            'Verify': _select(),
            'SN': _select(),
            'WorkCode': _text(),
            'Reserved': _text(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['SN'].required = False


class OperationLogForm(forms.ModelForm):
    class Meta:
        model = oplog
        fields = ['SN', 'admin', 'OP', 'OPTime', 'Object', 'Param1', 'Param2', 'Param3']
        widgets = {
            'SN': _select(),
            'admin': _text(type='number'),
            'OP': _text(type='number', placeholder='Kode operasi (angka)'),
            'OPTime': _datetime(),
            'Object': _text(type='number'),
            'Param1': _text(type='number'),
            'Param2': _text(type='number'),
            'Param3': _text(type='number'),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['SN'].required = False


class DeviceLogForm(forms.ModelForm):
    class Meta:
        model = devlog
        fields = ['SN', 'OP', 'Object', 'Cnt', 'ECnt', 'OpTime']
        widgets = {
            'SN': _select(),
            'OP': _text(placeholder='mis. TRANSACT'),
            'Object': _text(),
            'Cnt': _text(type='number'),
            'ECnt': _text(type='number'),
            'OpTime': _datetime(),
        }


class DeviceCommandForm(forms.ModelForm):
    """User (admin yang submit) di-set otomatis dari request.user di view, tidak lewat form."""

    class Meta:
        model = devcmds
        fields = ['SN', 'CmdContent', 'CmdCommitTime', 'CmdTransTime', 'CmdOverTime', 'CmdReturn']
        widgets = {
            'SN': _select(),
            'CmdContent': _textarea(placeholder='mis. Reboot / GetFile namafile / dll'),
            'CmdCommitTime': _datetime(),
            'CmdTransTime': _datetime(),
            'CmdOverTime': _datetime(),
            'CmdReturn': _text(type='number'),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['CmdTransTime'].required = False
        self.fields['CmdOverTime'].required = False
        self.fields['CmdReturn'].required = False


class BackupFingerForm(forms.Form):
    """
    Form konfirmasi 'Backup Data Finger'. `pin_pattern` opsional -- kalau
    diisi, cuma PIN yang match regex ini yang di-backup (supaya tidak perlu
    proses semua user tiap kali, karena device dengan ribuan user bisa lama
    sekali kalau full backup). Kosongkan untuk backup semua PIN.
    """
    pin_pattern = forms.CharField(
        label='Filter PIN (regex, opsional)',
        required=False,
        widget=_text(placeholder=r'Contoh: ^8 (semua PIN diawali 8), ^88, ^888, atau regex lain'),
        help_text=(
            'Cuma PIN yang cocok pola ini yang akan di-backup. Kosongkan untuk backup SEMUA PIN '
            '(bisa lama sekali kalau device-nya banyak user).'
        ),
    )

    def clean_pin_pattern(self):
        pattern = self.cleaned_data.get('pin_pattern', '').strip()
        if not pattern:
            return ''
        try:
            re.compile(pattern)
        except re.error as exc:
            raise forms.ValidationError(f'Pola regex tidak valid: {exc}')
        return pattern


class AttendanceRecapFilterForm(forms.Form):
    """Filter untuk halaman Attendance Recap (Rekap Kehadiran)."""

    # PIN diletakkan PALING PERTAMA (posisi paling kiri di form) sesuai
    # permintaan. `pin` = free text (dipakai sbg regex kalau tidak pilih
    # lookup), `pin_exact` = hidden field, diisi JS cuma kalau user benar2
    # klik salah satu hasil autocomplete -- pemicu mode "card" 1 karyawan.
    pin = forms.CharField(
        label='PIN', required=False,
        widget=_text(placeholder='Ketik PIN / nama...', autocomplete='off'),
    )
    pin_exact = forms.CharField(required=False, widget=forms.HiddenInput())
    function = forms.ChoiceField(label='Device Function', required=False, widget=_select())
    pool = forms.ModelChoiceField(
        queryset=department.objects.all().order_by('DeptName'), required=False, label='Pool', widget=_select(),
    )
    device = forms.ModelChoiceField(
        queryset=iclock.objects.all().order_by('Alias'), required=False, label='Device', widget=_select(),
    )
    date_from = forms.DateField(
        label='From', widget=forms.DateInput(attrs={'type': 'date', 'class': INPUT_CLS}),
    )
    date_to = forms.DateField(
        label='To', widget=forms.DateInput(attrs={'type': 'date', 'class': INPUT_CLS}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['function'].choices = _device_function_choices(empty_label='-- Semua Function --')

        # Device di-scope ke Pool yang dipilih (kalau ada), sama seperti pola
        # dependent-dropdown Pool -> Target Device di form Transfer Finger.
        pool_id = self.data.get('pool') if self.data else None
        if pool_id:
            self.fields['device'].queryset = iclock.objects.filter(DeptID_id=pool_id).order_by('Alias')

    def clean_pin(self):
        pattern = self.cleaned_data.get('pin', '').strip()
        if not pattern:
            return ''
        try:
            re.compile(pattern)
        except re.error as exc:
            raise forms.ValidationError(f'Pola regex PIN tidak valid: {exc}')
        return pattern

    def clean(self):
        cleaned = super().clean()
        date_from = cleaned.get('date_from')
        date_to = cleaned.get('date_to')
        if date_from and date_to:
            if date_from > date_to:
                raise forms.ValidationError('Tanggal "From" tidak boleh lebih besar dari "To".')
            if (date_to - date_from).days > 62:
                raise forms.ValidationError(
                    'Rentang tanggal maksimal 62 hari (~2 bulan) supaya query & tabelnya tidak terlalu berat.'
                )
        return cleaned


class NetworkParamsForm(forms.Form):
    """
    Form 'Set Network Param' -- ganti IP Address/NetMask/Gateway device
    fisik. Semua field OPSIONAL secara individual (admin bisa isi cuma
    sebagian, mis. cuma ganti Gateway), tapi MINIMAL 1 harus diisi.
    """
    new_ip = forms.CharField(
        label='IP Address Baru', required=False,
        widget=_text(placeholder='mis. 192.168.1.201'),
    )
    new_netmask = forms.CharField(
        label='NetMask Baru', required=False,
        widget=_text(placeholder='mis. 255.255.255.0'),
    )
    new_gateway = forms.CharField(
        label='Gateway Baru', required=False,
        widget=_text(placeholder='mis. 192.168.1.1'),
    )

    def _clean_ip_format(self, field_name, field_label):
        value = self.cleaned_data.get(field_name, '').strip()
        if not value:
            return ''
        try:
            validate_ipv4_address(value)
        except DjangoValidationError:
            raise forms.ValidationError(f"{field_label} '{value}' bukan format IPv4 yang valid.")
        return value

    def clean_new_ip(self):
        return self._clean_ip_format('new_ip', 'IP Address')

    def clean_new_netmask(self):
        return self._clean_ip_format('new_netmask', 'NetMask')

    def clean_new_gateway(self):
        return self._clean_ip_format('new_gateway', 'Gateway')

    def clean(self):
        cleaned = super().clean()
        # PENTING: cek dari self.data (input mentah), BUKAN cleaned_data --
        # kalau salah satu field diisi tapi formatnya invalid, cleaned_data
        # TIDAK akan punya key itu (gagal di clean_new_*), jadi kalau dicek
        # dari cleaned_data, pesan "isi minimal 1" akan muncul REDUNDAN
        # berbarengan dengan pesan format invalid, padahal user sudah isi.
        any_filled = any([
            self.data.get('new_ip', '').strip(),
            self.data.get('new_netmask', '').strip(),
            self.data.get('new_gateway', '').strip(),
        ])
        if not any_filled:
            raise forms.ValidationError('Isi minimal 1 parameter (IP Address/NetMask/Gateway) yang mau diubah.')
        return cleaned


class GenericParamForm(forms.Form):
    """
    Form 'Get/Set Param' generic -- testing bebas nama & nilai parameter
    konfigurasi device (CMD_OPTIONS_RRQ/CMD_OPTIONS_WRQ), untuk admin yang
    sudah tahu daftar nama parameter yang valid (mis. dari dokumentasi
    ZKTeco/SOLUSI) dan mau coba-coba, mis. set 'DHCP' jadi '0'.
    """
    ACTION_CHOICES = [('get', 'Get (baca nilai sekarang)'), ('set', 'Set (ubah nilai)')]

    action = forms.ChoiceField(
        choices=ACTION_CHOICES, initial='get',
        widget=forms.RadioSelect(attrs={'class': 'inline-flex items-center gap-1'}),
    )
    param_name = forms.CharField(
        label='Nama Parameter', widget=_text(placeholder='mis. DHCP, IPAddress, NetMask, GATEIPAddress, ...'),
    )
    param_value = forms.CharField(
        label='Nilai Baru (khusus Set)', required=False, widget=_text(placeholder="mis. 0 atau 1"),
    )
    do_refresh = forms.BooleanField(
        label='Kirim CMD_REFRESHOPTION setelah Set (disarankan tetap dicentang)',
        required=False, initial=True,
        widget=forms.CheckboxInput(attrs={'class': 'h-4 w-4 rounded border-slate-300 text-indigo-600 focus:ring-indigo-500'}),
    )

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('action') == 'set' and not cleaned.get('param_value', '').strip():
            raise forms.ValidationError("Nilai Baru harus diisi kalau action-nya 'Set'.")
        return cleaned