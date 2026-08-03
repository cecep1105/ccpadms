"""
Ambil foto karyawan/driver dari sumber EKSTERNAL (FTP server & database
SQL Server pihak ketiga) -- DIADAPTASI dari test/photoutils.py (versi
prototype yang diberikan sbg contoh), distrukturkan ulang jadi modul
resmi (error handling lebih baik, docstring, konfigurasi via settings/
env, TIDAK ada perubahan LOGIC inti pencarian foto -- pemetaan
source_key -> lokasi/folder FTP PERSIS SAMA dgn versi asli).

Foto TIDAK diunggah baru lewat aplikasi ini -- HANYA dibaca dari server
yang sudah ada (read-only, TIDAK PERNAH menulis/menghapus apa pun di
FTP/database sumber).
"""
import base64
import logging

from django.conf import settings

logger = logging.getLogger(__name__)


class PhotoFetchError(Exception):
    """Kegagalan JELAS (server tidak terhubung, config kosong, dst) -- BEDA dari 'foto tidak ketemu' (itu list kosong, bukan exception)."""


def _get_kba_driver_photo(pin):
    """
    Sumber foto KHUSUS driver KBA -- BUKAN dari FTP, tapi dari
    DATABASE SQL Server pihak ketiga (tabel MSDriverKBA), diakses via
    pyodbc + IDCARD_KBA_CONNECTION_STRING. Kolom `Photo` di tabel itu
    SUDAH berisi data foto dalam bentuk BASE64 (bukan binary mentah) --
    SAMA persis asumsi versi asli (test/photoutils.py::kbagetphotodriver).
    """
    if not settings.IDCARD_KBA_CONNECTION_STRING:
        raise PhotoFetchError('IDCARD_KBA_CONNECTION_STRING belum dikonfigurasi di server.')
    try:
        import pyodbc
    except ImportError as exc:
        raise PhotoFetchError("Library 'pyodbc' belum terinstall di server.") from exc

    try:
        cnxn = pyodbc.connect(settings.IDCARD_KBA_CONNECTION_STRING, autocommit=True)
        cursor = cnxn.cursor()
        cursor.execute('SET TEXTSIZE 2147483647;')
        cursor.execute(
            'SELECT id_absen, namapengemudi, Photo, Photo3 FROM dbo.MSDriverKBA WHERE id_absen = ?', pin
        )
        columns = [c[0] for c in cursor.description]
        rows = [dict(zip(columns, row)) for row in cursor.fetchall()]
        cnxn.close()
    except Exception as exc:  # noqa: BLE001 -- pyodbc bisa lempar berbagai jenis exception koneksi/driver ODBC
        logger.warning('Gagal query foto driver KBA utk PIN %s: %s', pin, exc)
        raise PhotoFetchError(f'Gagal terhubung ke database driver KBA: {exc}') from exc

    return rows[0]['Photo'] if rows else None


def _list_ftp_files_containing(ftp_location, path, needle):
    """
    LIST 1 folder FTP, kembalikan nama file yang MENGANDUNG `needle`
    (biasanya PIN) di namanya -- pencarian SUBSTRING sederhana (BUKAN
    exact match), SAMA persis logic versi asli (test/photoutils.py::ftpdir).
    """
    from storages.backends.ftp import FTPStorage
    import ftplib

    fs = FTPStorage(location=ftp_location)
    config = fs._config
    matches = []
    try:
        ftp = ftplib.FTP(config['host'], timeout=15)
        ftp.login(config['user'], config['passwd'])
        lines = []
        ftp.retrlines(f'LIST {path}', lines.append)
        ftp.quit()
        for line in lines:
            idx = line.find(needle)
            if idx != -1:
                matches.append(line[idx:])
    except Exception as exc:  # noqa: BLE001 -- ftplib bisa lempar berbagai jenis exception socket/protokol
        logger.warning('Gagal LIST folder FTP %s%s: %s', ftp_location, path, exc)
    return matches


def _read_ftp_file_as_data_uri(ftp_location, directory, filename):
    from storages.backends.ftp import FTPStorage

    fs = FTPStorage(location=f'{ftp_location}{directory}/')
    raw = fs._open(filename).read()
    ext = filename.rsplit('.', 1)[-1].upper() if '.' in filename else ''
    mime = 'image/png' if ext == 'PNG' else 'image/jpeg'
    return f'data:{mime};base64,{base64.b64encode(raw).decode()}'


def _fetch_from_ftp_dirs(ftp_location, dirs, pin, source_label):
    """Cari & baca semua file yg cocok PIN dari SEKUMPULAN folder FTP -- helper dipakai ULANG oleh semua source_key berbasis FTP di bawah (hindari duplikasi loop yg SAMA)."""
    if not ftp_location:
        return []
    results = []
    counter = 0
    for directory in dirs:
        for filename in _list_ftp_files_containing(ftp_location, directory, pin):
            try:
                data_uri = _read_ftp_file_as_data_uri(ftp_location, directory, filename)
            except Exception as exc:  # noqa: BLE001
                logger.warning('Gagal baca file FTP %s/%s: %s', directory, filename, exc)
                continue
            results.append({
                'counter': counter, 'dir': directory, 'path': filename,
                'data': data_uri, 'pin': pin, 'source': source_label,
            })
            counter += 1
    return results


# Pemetaan source_key -> strategi pencarian -- PERSIS SAMA dgn 4 cabang
# di test/photoutils.py::getphoto() (parameter `template` di versi asli),
# CUMA diberi nama key yang lebih jelas & dipisah jadi fungsi kecil2.
def fetch_photos(pin, source_key='default'):
    """
    Cari foto utk 1 PIN dari 1 SUMBER spesifik -- kembalikan LIST (bisa
    lebih dari 1 hasil kalau PIN itu ketemu di beberapa file/folder),
    KOSONG kalau tidak ketemu SAMA SEKALI (BUKAN exception -- "tidak
    ketemu" itu wajar, beda dari "server tidak terhubung").

    source_key yang didukung (SAMA dgn nilai `template` versi asli):
    - 'default'       : FTP1, folder photo/photoinput/phototemp/photocrop (Karyawan umum)
    - 'driver-hu'     : FTP2, folder dataphotosopir/newphoto & originazise
    - 'driver-online' : FTP1, folder photoinput (format nama file khusus, di-parse jadi label PIN|Nama)
    - 'driver-kba'    : Database SQL Server pihak ketiga (BUKAN FTP)
    - 'fallback'      : FTP3, folder DRIVERKBA (kalau PIN diawali '4') atau folder kosong
    """
    if source_key == 'driver-kba':
        photo_b64 = _get_kba_driver_photo(pin)
        if not photo_b64:
            return []
        return [{
            'counter': 0, 'dir': '', 'path': '', 'data': f'data:image/jpeg;base64,{photo_b64}',
            'pin': pin, 'source': 'driver-kba',
        }]

    if source_key == 'driver-hu':
        return _fetch_from_ftp_dirs(settings.IDCARD_FTP2, ['dataphotosopir/newphoto', 'dataphotosopir/originazise'], pin, 'driver-hu')

    if source_key == 'driver-online':
        results = _fetch_from_ftp_dirs(settings.IDCARD_FTP1, ['photoinput'], pin, 'driver-online')
        # Format nama file khusus utk source ini: "<PIN>_<nama_dgn_underscore>.jpg"
        # -- di-parse jadi label "PIN|NAMA" (spasi bukan underscore, huruf
        # besar), SAMA persis versi asli.
        for r in results:
            fn = r['path']
            r['label'] = f"{fn[:5]}|{fn[6:-4].replace('_', ' ').upper()}" if len(fn) > 6 else fn
        return results

    if source_key == 'fallback':
        directory = 'DRIVERKBA' if pin[:1] == '4' else ''
        return _fetch_from_ftp_dirs(settings.IDCARD_FTP3, [directory], pin, 'fallback')

    # 'default' -- Karyawan umum
    return _fetch_from_ftp_dirs(settings.IDCARD_FTP1, ['photo', 'photoinput', 'phototemp', 'photocrop'], pin, 'default')


def fetch_photos_for_card_type(pin, card_type):
    """
    Titik masuk UTAMA dipakai form/view generate kartu -- coba SEMUA
    source_key yang RELEVAN utk `card_type`, GABUNGKAN semua hasil yg
    ketemu jadi 1 list (staf yang generate kartu MEMILIH salah satu dari
    kandidat yg ditemukan, lewat UI) -- kalau SEMUA source relevan
    kosong, coba 'fallback' sbg upaya terakhir (SAMA perilaku versi
    asli: fallback CUMA dicoba kalau hasil utama BENAR2 kosong).
    """
    if card_type == 'driver':
        results = []
        for key in ('driver-kba', 'driver-hu', 'driver-online'):
            try:
                results.extend(fetch_photos(pin, key))
            except PhotoFetchError as exc:
                logger.warning('Sumber foto driver %s gagal utk PIN %s: %s', key, pin, exc)
    else:
        results = fetch_photos(pin, 'default')

    if not results:
        results = fetch_photos(pin, 'fallback')

    return results
