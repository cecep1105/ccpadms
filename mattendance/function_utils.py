"""
Penentuan kode fungsi (key dari settings.DEVICEFUNCTION) untuk 1 record
AttendanceLog -- dipakai mengisi field `Function` ('<kode>-<poolcode>').

Urutan prioritas (SESUAI ARAHAN):
1. Cek dulu apakah PoolID yang match geofence terdaftar sebagai KANTIN di
   `mclock.PoolDeviceFunction` -- kalau ya, kode fungsi = 'X' LANGSUNG,
   TIDAK PEDULI PIN user atau jenis check-in-nya (reguler ATAU Check/Meal).
2. Kalau BUKAN KANTIN (atau tidak terdaftar sama sekali di
   PoolDeviceFunction -- dianggap default bukan KANTIN): fallback ke DIGIT
   PERTAMA PIN user (setelah leading zero zero-pad dihilangkan) -- dicari
   key di settings.DEVICEFUNCTION (selain 'X') yang MENGANDUNG digit itu
   sbg salah satu karakternya (mis. key '89' cocok utk digit awal 8 ATAU 9).
"""
from django.conf import settings


def get_pin_first_digit(pin: str):
    """
    Ambil digit PERTAMA dari PIN SETELAH leading zero (zero-pad) dihilangkan.
    Return None kalau PIN kosong/bukan digit murni. PIN yang semua nol
    (edge case) dianggap '0'.
    """
    pin = (pin or '').strip()
    if not pin or not pin.isdigit():
        return None
    stripped = pin.lstrip('0')
    return stripped[0] if stripped else '0'


def determine_function_code(pin: str, pool) -> str:
    """
    Tentukan kode fungsi (key settings.DEVICEFUNCTION, mis. '89', '1', 'X')
    utk 1 check-in, sesuai urutan prioritas di atas.

    `pin`: PIN employee (biasanya dari `user.EmpID.PIN`) -- boleh None/kosong
    kalau user tidak punya Employee terkait (fallback prefix PIN otomatis
    dilewati, cuma cek KANTIN yang tetap jalan).
    `pool`: instance `mclock.MobilePool` yang cocok dgn geofence (atau None).

    Return kode fungsi (str) kalau ketemu, None kalau tidak ada yang cocok
    sama sekali (bukan KANTIN, dan PIN tidak dikenali/tidak ada).
    """
    from mclock.models import PoolDeviceFunction

    # 1. Cek KANTIN dulu -- prioritas TERTINGGI, mengalahkan apa pun.
    if pool is not None:
        mapping = PoolDeviceFunction.objects.filter(PoolID=pool.PoolID).first()
        if mapping and mapping.function_type == PoolDeviceFunction.FunctionType.KANTIN:
            return 'X'

    # 2. Fallback: prefix digit pertama PIN.
    first_digit = get_pin_first_digit(pin)
    if first_digit is None:
        return None

    device_function = getattr(settings, 'DEVICEFUNCTION', {}) or {}
    for code in device_function:
        if code == 'X':
            continue  # 'X' (KANTIN) sudah dicek khusus di langkah 1 di atas
        if first_digit in code:
            return code

    return None
