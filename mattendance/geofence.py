"""
Logika geofence -- cocokkan koordinat GPS user dengan data MobilePool
(mclock) buat menentukan apakah user berada dalam radius suatu pool.

Asumsi: `MobilePool.Radius` dalam METER (konvensi umum utk geofencing GPS).
Kalau ternyata satuan yang dipakai beda (mis. kilometer), sesuaikan
`RADIUS_UNIT_TO_METERS` di bawah.
"""
import math

RADIUS_UNIT_TO_METERS = 1  # kalau Radius ternyata dalam KM, ganti ke 1000


def haversine_distance_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Jarak great-circle antara 2 titik koordinat (derajat desimal), dalam
    meter -- formula Haversine standar, akurat cukup untuk jarak jarak
    pendek/menengah seperti keperluan geofencing (radius puluhan-ratusan
    meter).
    """
    earth_radius_m = 6371000  # jari-jari rata-rata bumi, meter
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return earth_radius_m * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def find_matching_pool(latitude: float, longitude: float):
    """
    Cari MobilePool yang cocok dengan koordinat user (user berada DALAM
    radius pool tsb). Kalau ada beberapa pool yang cocok (radius overlap),
    pilih yang PALING DEKAT.

    ⚠️ SUDAH TIDAK DIPAKAI sebagai geofence utama (lihat
    `find_matching_pool_by_polygon` di bawah, yang menggantikan pendekatan
    radius lingkaran ini dengan polygon presisi dari MobilePoolLoc) --
    dibiarkan ada di sini (tidak dihapus) untuk referensi/kemungkinan
    dipakai lagi nanti, TAPI tidak lagi dipanggil dari alur check-in aktif.

    Return: (pool: MobilePool|None, distance_meters: float|None) --
    (None, None) kalau tidak ada satupun pool yang cocok, atau semua pool
    tidak punya koordinat/radius valid utk dicek.
    """
    from mclock.models import MobilePool

    best_pool = None
    best_distance = None

    for pool in MobilePool.objects.exclude(Latitude__isnull=True).exclude(Longitude__isnull=True):
        try:
            pool_lat = float(pool.Latitude)
            pool_lon = float(pool.Longitude)
        except (TypeError, ValueError):
            continue  # koordinat pool ini tidak valid/tidak numerik -- lewati
        if pool.Radius is None:
            continue
        radius_m = pool.Radius * RADIUS_UNIT_TO_METERS

        distance = haversine_distance_meters(latitude, longitude, pool_lat, pool_lon)
        if distance <= radius_m and (best_distance is None or distance < best_distance):
            best_pool = pool
            best_distance = distance

    return best_pool, best_distance


def point_in_polygon(lat: float, lon: float, polygon) -> bool:
    """
    Ray-casting algorithm (varian PNPOLY, W. Randolph Franklin) -- cek
    apakah titik (lat, lon) berada DI DALAM polygon.

    `polygon`: list of (lat, lon) tuples, urut sesuai keliling polygon
    (searah atau berlawanan jarum jam, keduanya valid utk algoritma ini).
    Minimal 3 titik (kalau kurang, otomatis False -- bukan polygon valid).

    Catatan: lat/lon diperlakukan sebagai koordinat Cartesian 2D biasa --
    pendekatan standar & cukup akurat utk geofencing area kecil (skala
    gedung/kompleks/parkiran). TIDAK akurat utk polygon yang sangat besar
    (mencakup kelengkungan bumi signifikan, mis. lintas benua).
    """
    n = len(polygon)
    if n < 3:
        return False

    inside = False
    x, y = lon, lat  # konvensi GIS: x=longitude (timur-barat), y=latitude (utara-selatan)
    p1x, p1y = polygon[0][1], polygon[0][0]
    for i in range(1, n + 1):
        p2x, p2y = polygon[i % n][1], polygon[i % n][0]
        if y > min(p1y, p2y):
            if y <= max(p1y, p2y):
                if x <= max(p1x, p2x):
                    xinters = None
                    if p1y != p2y:
                        xinters = (y - p1y) * (p2x - p1x) / (p2y - p1y) + p1x
                    if p1x == p2x or xinters is None or x <= xinters:
                        inside = not inside
        p1x, p1y = p2x, p2y
    return inside


def find_matching_pool_by_polygon(latitude: float, longitude: float):
    """
    Cari MobilePool yang POLYGON-nya (titik-titik dari MobilePoolLoc,
    diurutkan berdasarkan `Urut`) mencakup titik user -- INI geofence yang
    AKTIF dipakai alur check-in/out sekarang (menggantikan
    `find_matching_pool` yang berbasis radius lingkaran).

    `MobilePool` (tabel lama) tetap dipakai di sini murni utk LOOKUP data
    pool-nya (PoolName dsb) setelah PoolID yang cocok ditemukan dari
    polygon -- bukan lagi sumber pengecekan geofence-nya.

    Kalau ada LEBIH DARI 1 polygon yang overlap & sama-sama cocok, fungsi
    ini cuma return yang PERTAMA ketemu (urutan tidak dijamin) -- utk
    kasus yang butuh disambiguasi (mis. Check/Meal, pakai bantuan QR code),
    pakai `find_all_matching_pools_by_polygon()` di bawah, BUKAN fungsi ini.

    Return: MobilePool instance kalau cocok, atau None kalau tidak ada
    polygon manapun yang mencakup titik user (termasuk kalau PoolID yang
    polygon-nya cocok kebetulan tidak ada padanannya di tabel MobilePool --
    tetap return None, karena tidak ada info pool yang bisa ditampilkan).
    """
    matches = find_all_matching_pools_by_polygon(latitude, longitude)
    return matches[0] if matches else None


def find_all_matching_pools_by_polygon(latitude: float, longitude: float) -> list:
    """
    Cari SEMUA MobilePool yang polygon-nya mencakup titik user (bisa lebih
    dari 1 kalau ada geofence yang overlap karena berdekatan posisinya) --
    dipakai khusus utk Check/Meal, yang butuh disambiguasi VIA QR CODE
    (isi QR nentuin PoolCode mana yang seharusnya dipilih di antara
    beberapa geofence yang sama-sama cocok dgn lokasi GPS user).

    Return: list of MobilePool instance, urutan TIDAK dijamin (kosong
    kalau tidak ada satupun yang cocok). PoolID yang polygon-nya cocok
    tapi tidak ada padanan di tabel MobilePool otomatis dilewati (sama
    seperti `find_matching_pool_by_polygon`).
    """
    from mclock.models import MobilePool, MobilePoolLoc

    matched_pool_ids = []
    pool_ids = MobilePoolLoc.objects.values_list('PoolID', flat=True).distinct()
    for pool_id in pool_ids:
        points_qs = MobilePoolLoc.objects.filter(PoolID=pool_id).order_by('Urut')
        polygon = []
        valid = True
        for point in points_qs:
            try:
                p_lat = float(point.Latitude)
                p_lon = float(point.Longitude)
            except (TypeError, ValueError):
                valid = False
                break
            polygon.append((p_lat, p_lon))

        if not valid or len(polygon) < 3:
            continue  # data titik polygon ini tidak lengkap/valid -- lewati PoolID ini

        if point_in_polygon(latitude, longitude, polygon):
            matched_pool_ids.append(pool_id)

    if not matched_pool_ids:
        return []
    # Urutan hasil query TIDAK harus sama dgn urutan matched_pool_ids -- tapi
    # itu tidak masalah, caller (mis. Check/Meal) cuma peduli SET pool yang
    # cocok, bukan urutannya.
    return list(MobilePool.objects.filter(PoolID__in=matched_pool_ids))
