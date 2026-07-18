from django import forms

from .models import MobilePool, MobilePoolLoc, PoolDeviceFunction

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


class MobilePoolForm(forms.ModelForm):
    """
    Tambah 1 record MobilePool MANUAL -- BUKAN alur normal (yang seharusnya
    lewat sinkronisasi `sync_mobile_pool`), murni utk keperluan TESTING
    (mis. bikin 1 pool percobaan). Data manual ini akan HILANG/TERTIMPA
    begitu sinkronisasi berikutnya jalan (`sync_mobile_pool` mirror penuh --
    lihat catatan di command-nya), jadi cuma cocok utk uji coba sementara,
    bukan data permanen.
    """
    class Meta:
        model = MobilePool
        fields = ['PoolID', 'PoolCode', 'PoolName', 'Latitude', 'Longitude', 'Radius']
        widgets = {
            'PoolID': _text(placeholder='mis. TEST1 (maks 5 karakter)'),
            'PoolCode': _text(placeholder='opsional'),
            'PoolName': _text(placeholder='mis. Kantor Test'),
            'Latitude': _text(placeholder='mis. -6.200000'),
            'Longitude': _text(placeholder='mis. 106.816666'),
            'Radius': _text(placeholder='opsional -- sudah TIDAK dipakai geofence (lihat Mobile Pool Location)'),
        }

    def clean_PoolID(self):
        pool_id = self.cleaned_data['PoolID'].strip()
        if MobilePool.objects.filter(PoolID=pool_id).exists():
            raise forms.ValidationError(f"PoolID '{pool_id}' sudah ada.")
        return pool_id


class MobilePoolLocForm(forms.ModelForm):
    """
    Tambah 1 TITIK polygon MANUAL ke MobilePoolLoc -- sama seperti
    MobilePoolForm, murni utk TESTING (bikin geofence percobaan), akan
    HILANG/TERTIMPA begitu `sync_mobile_pool_loc` jalan lagi.

    Utk bikin 1 polygon lengkap, tambahkan MINIMAL 3 titik dengan PoolID
    yang SAMA (Urut berbeda-beda, urut sesuai keliling polygon).
    """
    class Meta:
        model = MobilePoolLoc
        fields = ['PoolID', 'Urut', 'Latitude', 'Longitude']
        widgets = {
            'PoolID': _text(placeholder='mis. TEST1 -- sama utk semua titik 1 polygon'),
            'Urut': _text(placeholder='mis. 1, 2, 3, ... (urutan keliling polygon)'),
            'Latitude': _text(placeholder='mis. -6.199900'),
            'Longitude': _text(placeholder='mis. 106.816500'),
        }

    def clean(self):
        cleaned = super().clean()
        pool_id = cleaned.get('PoolID')
        urut = cleaned.get('Urut')
        if pool_id and urut is not None and MobilePoolLoc.objects.filter(PoolID=pool_id, Urut=urut).exists():
            raise forms.ValidationError(f"Titik dengan PoolID '{pool_id}' & Urut '{urut}' sudah ada.")
        return cleaned


class PoolDeviceFunctionForm(forms.ModelForm):
    """
    Kelola mapping PoolID -> function type (KANTIN / Bukan KANTIN) --
    BEDA dengan MobilePoolForm/MobilePoolLocForm (yang murni utk testing,
    data dari sini AKAN disinkronkan/tertimpa) -- tabel ini SENGAJA tidak
    disinkronkan dari mana pun, jadi form ini adalah cara UTAMA (bukan
    cuma testing) untuk mengelola data ini.
    """
    class Meta:
        model = PoolDeviceFunction
        fields = ['PoolID', 'function_type']
        widgets = {
            'PoolID': _text(placeholder='mis. 114 (harus sama dengan PoolID di Mobile Pool)'),
            'function_type': _select(),
        }

    def clean_PoolID(self):
        pool_id = self.cleaned_data['PoolID'].strip()
        qs = PoolDeviceFunction.objects.filter(PoolID=pool_id)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError(f"PoolID '{pool_id}' sudah ada mapping-nya.")
        return pool_id
