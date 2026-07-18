"""
Wrapper tipis di atas pyzk (https://github.com/fananimi/pyzk) untuk konek
LANGSUNG ke mesin fingerprint fisik lewat IP-nya (protokol khusus ZKTeco,
biasanya port 4370) -- BEDA dengan tabel `iclock`/`userinfo` di database kita
yang diisi lewat mekanisme push HTTP dari device.

Dipakai untuk fitur "Show Device User": menampilkan user yang BENAR-BENAR
tersimpan di memori device saat ini secara real-time, bukan cache di database.
"""
import logging
from datetime import datetime

logger = logging.getLogger('iclock')

ZK_DEFAULT_PORT = 4370
ZK_DEFAULT_TIMEOUT = 8  # detik -- dibikin pendek supaya request dashboard tidak nge-hang lama kalau device offline

# Kode privilege dari pyzk (zk.const) -- didefinisikan ulang di sini (bukan
# import langsung) supaya modul ini tetap bisa di-import (dan pesan error
# yang jelas ditampilkan) walau pyzk belum terinstall.
PRIVILEGE_ADMIN = 14
PRIVILEGE_DEFAULT = 0


class DeviceConnectionError(Exception):
    """Gagal konek ke device fisik: offline, network unreachable, timeout, salah IP, dll."""


def privilege_label(privilege_code) -> str:
    try:
        code = int(privilege_code)
    except (TypeError, ValueError):
        return '-'
    return 'Admin' if code == PRIVILEGE_ADMIN else 'User'


def fetch_device_users(ip_address: str, port: int = ZK_DEFAULT_PORT, timeout: int = ZK_DEFAULT_TIMEOUT):
    """
    Konek langsung ke mesin fingerprint via pyzk, ambil daftar user yang
    TERSIMPAN DI DEVICE saat ini (bukan dari tabel employee/userinfo kita).

    Return: list of dict [{uid, user_id, name, privilege, privilege_label, card, group_id}, ...]
    Raise : DeviceConnectionError kalau pyzk belum terinstall, IP kosong, atau
            gagal konek/timeout ke device.
    """
    try:
        from zk import ZK
    except ImportError as exc:
        raise DeviceConnectionError(
            "Library 'pyzk' belum terinstall di server. Jalankan: pip install pyzk"
        ) from exc

    if not ip_address:
        raise DeviceConnectionError('Device ini belum punya IP Address yang tercatat di database.')

    zk_instance = ZK(ip_address, port=port, timeout=timeout, password=0, force_udp=False, ommit_ping=False)
    conn = None
    try:
        conn = zk_instance.connect()
        raw_users = conn.get_users()
    except Exception as exc:  # noqa: BLE001 -- pyzk melempar berbagai jenis exception socket/protokol
        logger.warning('Gagal konek ke device fingerprint %s:%s -> %s', ip_address, port, exc)
        raise DeviceConnectionError(
            f'Tidak bisa terhubung ke device di {ip_address}:{port}. Pastikan device menyala, '
            f'terhubung ke jaringan yang sama dengan server ini, dan port {port} tidak diblokir '
            f'firewall. Detail teknis: {exc}'
        ) from exc
    finally:
        if conn is not None:
            try:
                conn.disconnect()
            except Exception:  # noqa: BLE001
                pass

    users = []
    for u in raw_users:
        privilege = getattr(u, 'privilege', None)
        users.append({
            'uid': getattr(u, 'uid', None),
            'user_id': getattr(u, 'user_id', None),
            'name': (getattr(u, 'name', '') or '').strip() or '(tanpa nama)',
            'privilege': privilege,
            'privilege_label': privilege_label(privilege),
            'card': getattr(u, 'card', None),
            'group_id': getattr(u, 'group_id', None),
        })
    return users


def _find_device_user(conn, user_id):
    """Cari user di device (hasil get_users()) berdasarkan user_id (PIN/badge number)."""
    for u in conn.get_users():
        if str(getattr(u, 'user_id', '')) == str(user_id):
            return u
    return None


def set_user_privilege_on_device(ip_address: str, user_id, new_privilege: int,
                                  port: int = ZK_DEFAULT_PORT, timeout: int = ZK_DEFAULT_TIMEOUT) -> bool:
    """
    Ubah privilege user di device fisik (14=Admin, 0=User biasa), dicari
    berdasarkan `user_id` (PIN/badge number) -- field lain (name, password,
    card, dst) dipertahankan sama seperti yang ada di device saat ini.

    Return True kalau berhasil di-set. Raise DeviceConnectionError kalau user
    tidak ditemukan di device atau gagal konek.
    """
    try:
        from zk import ZK
    except ImportError as exc:
        raise DeviceConnectionError("Library 'pyzk' belum terinstall di server.") from exc
    if not ip_address:
        raise DeviceConnectionError('Device ini belum punya IP Address yang tercatat di database.')

    zk_instance = ZK(ip_address, port=port, timeout=timeout, password=0, force_udp=False, ommit_ping=False)
    conn = None
    try:
        conn = zk_instance.connect()
        target = _find_device_user(conn, user_id)
        if target is None:
            raise DeviceConnectionError(f"User dengan ID '{user_id}' tidak ditemukan di device {ip_address}.")
        conn.set_user(
            uid=target.uid, name=target.name, privilege=new_privilege,
            password=target.password, group_id=target.group_id,
            user_id=target.user_id, card=target.card,
        )
        return True
    except DeviceConnectionError:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.warning('Gagal set privilege user %s di device %s:%s -> %s', user_id, ip_address, port, exc)
        raise DeviceConnectionError(
            f'Gagal mengubah privilege di device {ip_address}:{port}. Detail: {exc}'
        ) from exc
    finally:
        if conn is not None:
            try:
                conn.disconnect()
            except Exception:  # noqa: BLE001
                pass


def delete_user_from_device(ip_address: str, user_id,
                             port: int = ZK_DEFAULT_PORT, timeout: int = ZK_DEFAULT_TIMEOUT) -> bool:
    """
    Hapus user dari device fisik berdasarkan user_id (PIN/badge number).

    Return True kalau user ditemukan & berhasil dihapus, False kalau user
    memang sudah tidak ada di device (dianggap tujuan akhir sudah tercapai,
    bukan error). Raise DeviceConnectionError kalau gagal konek ke device.
    """
    try:
        from zk import ZK
    except ImportError as exc:
        raise DeviceConnectionError("Library 'pyzk' belum terinstall di server.") from exc
    if not ip_address:
        raise DeviceConnectionError('Device ini belum punya IP Address yang tercatat di database.')

    zk_instance = ZK(ip_address, port=port, timeout=timeout, password=0, force_udp=False, ommit_ping=False)
    conn = None
    try:
        conn = zk_instance.connect()
        target = _find_device_user(conn, user_id)
        if target is None:
            return False
        conn.delete_user(uid=target.uid, user_id=target.user_id)
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning('Gagal hapus user %s dari device %s:%s -> %s', user_id, ip_address, port, exc)
        raise DeviceConnectionError(
            f'Gagal menghapus user dari device {ip_address}:{port}. Detail: {exc}'
        ) from exc
    finally:
        if conn is not None:
            try:
                conn.disconnect()
            except Exception:  # noqa: BLE001
                pass


def transfer_fingerprints(source_ip: str, target_ips: list, pins: list,
                           port: int = ZK_DEFAULT_PORT, timeout: int = ZK_DEFAULT_TIMEOUT) -> list:
    """
    Transfer template fingerprint 1 atau lebih user (PIN) dari SATU source
    device ke SATU ATAU LEBIH target device.

    `target_ips` : list of tuple (ip_address, label) -- label cuma buat log,
                    ip_address dipakai buat konek.
    `pins`       : list of string PIN/user_id yang mau ditransfer.

    Return: list of string log/status per langkah -- dipakai buat isi kolom
    "Status Transfer" di form (bukan exception, supaya sebagian sukses/gagal
    tetap bisa dilaporkan lengkap walau ada yang error di tengah proses).

    Catatan penting: transfer template mentah cuma valid kalau source & target
    device pakai versi algoritma fingerprint yang sama/kompatibel -- pyzk tidak
    melakukan konversi format apapun.
    """
    log = []
    try:
        from zk import ZK
    except ImportError:
        return ["GAGAL: library 'pyzk' belum terinstall di server. Jalankan: pip install pyzk"]

    if not source_ip:
        return ["GAGAL: source device belum punya IP Address yang tercatat di database."]
    if not target_ips:
        return ["GAGAL: tidak ada target device (pool tujuan kosong / tidak punya device)."]
    if not pins:
        return ["GAGAL: tidak ada User ID (PIN) yang diisi."]

    # --- 1. Ambil data user + template dari SOURCE device ---
    log.append(f'Menghubungkan ke source device {source_ip}:{port}...')
    src_zk = ZK(source_ip, port=port, timeout=timeout, password=0, force_udp=False, ommit_ping=False)
    src_conn = None
    source_users_by_pin = {}
    templates_by_uid = {}
    try:
        src_conn = src_zk.connect()
        all_users = src_conn.get_users()
        for u in all_users:
            source_users_by_pin[str(u.user_id)] = u
        log.append(f'Terhubung ke source. Total user di source: {len(all_users)}.')

        all_templates = src_conn.get_templates()
        for finger in all_templates:
            templates_by_uid.setdefault(finger.uid, []).append(finger)
        log.append(f'Total template fingerprint tersimpan di source: {len(all_templates)}.')
    except Exception as exc:  # noqa: BLE001
        logger.warning('Gagal ambil data dari source %s:%s -> %s', source_ip, port, exc)
        log.append(f'GAGAL terhubung/membaca source device: {exc}')
        return log
    finally:
        if src_conn is not None:
            try:
                src_conn.disconnect()
            except Exception:  # noqa: BLE001
                pass

    # --- 2. Siapkan data yang mau ditransfer per PIN ---
    transfer_data = {}
    for pin in pins:
        src_user = source_users_by_pin.get(str(pin))
        if not src_user:
            log.append(f'[{pin}] DILEWATI: user tidak ditemukan di source device.')
            continue
        fingers = templates_by_uid.get(src_user.uid, [])
        if not fingers:
            log.append(f'[{pin}] DILEWATI: tidak ada template fingerprint tersimpan di source.')
            continue
        transfer_data[str(pin)] = (src_user, fingers)
        log.append(f'[{pin}] {len(fingers)} template ditemukan, siap ditransfer.')

    if not transfer_data:
        log.append('Tidak ada user valid untuk ditransfer. Proses dihentikan.')
        return log

    # --- 3. Konek ke tiap TARGET device, transfer satu per satu ---
    for target_ip, target_label in target_ips:
        log.append(f'--- Target: {target_label} ({target_ip}:{port}) ---')
        tgt_zk = ZK(target_ip, port=port, timeout=timeout, password=0, force_udp=False, ommit_ping=False)
        tgt_conn = None
        try:
            tgt_conn = tgt_zk.connect()
            target_users_by_pin = {str(u.user_id): u for u in tgt_conn.get_users()}

            for pin, (src_user, fingers) in transfer_data.items():
                try:
                    if pin not in target_users_by_pin:
                        tgt_conn.set_user(
                            name=src_user.name, privilege=src_user.privilege,
                            password=src_user.password, group_id=src_user.group_id,
                            user_id=pin, card=src_user.card,
                        )
                        log.append(f'  [{pin}] User belum ada di target, berhasil dibuat.')
                    tgt_conn.save_user_template(pin, fingers)
                    log.append(f'  [{pin}] Berhasil transfer {len(fingers)} template.')
                except Exception as exc:  # noqa: BLE001
                    logger.warning('Gagal transfer PIN %s ke %s -> %s', pin, target_ip, exc)
                    log.append(f'  [{pin}] GAGAL: {exc}')
        except Exception as exc:  # noqa: BLE001
            logger.warning('Gagal konek ke target %s:%s -> %s', target_ip, port, exc)
            log.append(f'GAGAL terhubung ke target device {target_label}: {exc}')
        finally:
            if tgt_conn is not None:
                try:
                    tgt_conn.disconnect()
                except Exception:  # noqa: BLE001
                    pass

    log.append('Selesai.')
    return log


def fetch_device_users_and_templates(ip_address: str, port: int = ZK_DEFAULT_PORT, timeout: int = ZK_DEFAULT_TIMEOUT):
    """
    Konek SEKALI ke device, ambil semua user + SEMUA template fingerprint
    sekaligus (dipakai untuk fitur "Backup Data Finger").

    Return: (users, templates_by_uid)
      users            : list of dict {uid, user_id, name, privilege, password, group_id, card}
      templates_by_uid : dict {uid: [{fid, valid, template(bytes)}, ...]}
    Raise DeviceConnectionError kalau gagal konek/baca.
    """
    try:
        from zk import ZK
    except ImportError as exc:
        raise DeviceConnectionError("Library 'pyzk' belum terinstall di server. Jalankan: pip install pyzk") from exc
    if not ip_address:
        raise DeviceConnectionError('Device ini belum punya IP Address yang tercatat di database.')

    zk_instance = ZK(ip_address, port=port, timeout=timeout, password=0, force_udp=False, ommit_ping=False)
    conn = None
    try:
        conn = zk_instance.connect()
        raw_users = conn.get_users()
        users = [{
            'uid': u.uid,
            'user_id': str(u.user_id),
            'name': u.name,
            'privilege': u.privilege,
            'password': u.password,
            'group_id': u.group_id,
            'card': u.card,
        } for u in raw_users]

        raw_templates = conn.get_templates()
        templates_by_uid = {}
        for finger in raw_templates:
            templates_by_uid.setdefault(finger.uid, []).append({
                'fid': finger.fid,
                'valid': finger.valid,
                'template': finger.template,
            })
        return users, templates_by_uid
    except Exception as exc:  # noqa: BLE001
        logger.warning('Gagal ambil users+templates dari %s:%s -> %s', ip_address, port, exc)
        raise DeviceConnectionError(
            f'Tidak bisa terhubung/membaca device {ip_address}:{port}. Detail: {exc}'
        ) from exc
    finally:
        if conn is not None:
            try:
                conn.disconnect()
            except Exception:  # noqa: BLE001
                pass


def reboot_device(ip_address: str, port: int = ZK_DEFAULT_PORT, timeout: int = ZK_DEFAULT_TIMEOUT):
    """
    Reboot device fisik via pyzk (`conn.restart()`). Aksi ini DISRUPTIF --
    device akan sempat offline beberapa puluh detik sampai selesai boot ulang.

    Return: (success: bool, message: str) -- tidak melempar exception,
    supaya view pemanggil cukup tampilkan message-nya sebagai flash message
    (sukses/error) tanpa perlu try/except sendiri.
    """
    try:
        from zk import ZK
    except ImportError:
        return False, "Library 'pyzk' belum terinstall di server. Jalankan: pip install pyzk"
    if not ip_address:
        return False, 'Device ini belum punya IP Address yang tercatat di database.'

    zk_instance = ZK(ip_address, port=port, timeout=timeout, password=0, force_udp=False, ommit_ping=False)
    conn = None
    try:
        conn = zk_instance.connect()
        conn.restart()
        return True, f'Perintah reboot berhasil dikirim ke device {ip_address}:{port}.'
    except Exception as exc:  # noqa: BLE001
        logger.warning('Gagal reboot device %s:%s -> %s', ip_address, port, exc)
        return False, f'Gagal reboot device: {exc}'
    finally:
        if conn is not None:
            try:
                conn.disconnect()
            except Exception:  # noqa: BLE001
                # Wajar gagal di sini -- device sudah mulai restart, koneksi
                # lama kemungkinan sudah/segera terputus dari sisi device.
                pass


def sync_device_time(ip_address: str, port: int = ZK_DEFAULT_PORT, timeout: int = ZK_DEFAULT_TIMEOUT):
    """
    Sinkronkan jam device fisik dengan jam SERVER (komputer yang menjalankan
    Django ini) via pyzk (`conn.set_time()`), pakai waktu lokal saat ini
    (`datetime.now()`, naive -- konsisten dengan konvensi USE_TZ=False project
    ini, lihat catatan Attendance Recap di README).

    Return: (success: bool, message: str).
    """
    try:
        from zk import ZK
    except ImportError:
        return False, "Library 'pyzk' belum terinstall di server. Jalankan: pip install pyzk"
    if not ip_address:
        return False, 'Device ini belum punya IP Address yang tercatat di database.'

    zk_instance = ZK(ip_address, port=port, timeout=timeout, password=0, force_udp=False, ommit_ping=False)
    conn = None
    try:
        conn = zk_instance.connect()

        old_time = None
        try:
            old_time = conn.get_time()
        except Exception:  # noqa: BLE001
            pass  # gagal baca jam lama tidak fatal -- tetap lanjut set jam baru

        now = datetime.now()
        conn.set_time(now)

        now_str = now.strftime('%Y-%m-%d %H:%M:%S')
        if old_time:
            return True, f'Jam device berhasil disinkronkan (sebelumnya {old_time}, sekarang {now_str}).'
        return True, f'Jam device berhasil disinkronkan ke {now_str}.'
    except Exception as exc:  # noqa: BLE001
        logger.warning('Gagal sinkronkan jam device %s:%s -> %s', ip_address, port, exc)
        return False, f'Gagal sinkronkan jam device: {exc}'
    finally:
        if conn is not None:
            try:
                conn.disconnect()
            except Exception:  # noqa: BLE001
                pass


def get_device_network_params(ip_address: str, port: int = ZK_DEFAULT_PORT, timeout: int = ZK_DEFAULT_TIMEOUT) -> dict:
    """
    Baca parameter jaringan SEKARANG (IPAddress/NetMask/GATEIPAddress) dari
    device fisik via pyzk (`conn.get_network_params()`, command CMD_OPTIONS_RRQ).
    Return dict {'ip': ..., 'mask': ..., 'gateway': ...}.
    Raise DeviceConnectionError kalau gagal konek/baca.
    """
    try:
        from zk import ZK
    except ImportError as exc:
        raise DeviceConnectionError("Library 'pyzk' belum terinstall di server.") from exc
    if not ip_address:
        raise DeviceConnectionError('Device ini belum punya IP Address yang tercatat di database.')

    zk_instance = ZK(ip_address, port=port, timeout=timeout, password=0, force_udp=False, ommit_ping=False)
    conn = None
    try:
        conn = zk_instance.connect()
        return conn.get_network_params()
    except Exception as exc:  # noqa: BLE001
        logger.warning('Gagal baca network params device %s:%s -> %s', ip_address, port, exc)
        raise DeviceConnectionError(
            f'Tidak bisa membaca parameter jaringan device {ip_address}:{port}. Detail: {exc}'
        ) from exc
    finally:
        if conn is not None:
            try:
                conn.disconnect()
            except Exception:  # noqa: BLE001
                pass


def set_network_params(ip_address: str, new_ip: str = '', new_netmask: str = '', new_gateway: str = '',
                        port: int = ZK_DEFAULT_PORT, timeout: int = ZK_DEFAULT_TIMEOUT):
    """
    Set parameter jaringan (IPAddress/NetMask/GATEIPAddress) device fisik via
    pyzk, pakai command CMD_OPTIONS_WRQ -- sesuai dokumentasi protokol resmi
    ZKTeco (referensi: https://github.com/adrobinoga/zk-protocol/blob/master/sections/terminal.md):

        packet(id=CMD_OPTIONS_WRQ, data="<nama parameter>=<nilai baru>\\x00")
        packet(id=CMD_ACK_OK)
        packet(id=CMD_REFRESHOPTION)
        packet(id=CMD_ACK_OK)

    Cuma parameter yang diisi (bukan string kosong) yang diproses -- admin
    bisa pilih ganti sebagian saja (mis. cuma Gateway, biarkan IP/NetMask
    apa adanya).

    PENTING -- pyzk TIDAK punya method publik untuk operasi generik "set
    parameter konfigurasi apa saja" ini (cuma ada contoh internal
    `set_sdk_build_1()` yang hardcode SATU parameter spesifik, pakai command
    yang sama TAPI tanpa null-terminator `\\x00` di akhir string dan TANPA
    kirim CMD_REFRESHOPTION sesudahnya). Karena dokumentasi protokol resmi
    justru menyertakan keduanya, implementasi di sini MENGIKUTI dokumentasi
    resmi (null-terminator + CMD_REFRESHOPTION di akhir), bukan meniru
    persis contoh internal pyzk yang lebih minimal itu. Untuk mengirim
    command generik CMD_OPTIONS_WRQ/CMD_REFRESHOPTION yang tidak ada method
    publiknya, kita akses method private `_send_command` via name-mangling
    Python (`conn._ZK__send_command`) -- teknik yang sama seperti yang
    dipakai pyzk sendiri secara internal.

    CATATAN JUJUR -- PENTING DIBACA: fungsi ini BELUM diuji terhadap device
    fisik sungguhan (tidak ada hardware ZKTeco yang tersedia untuk verifikasi
    langsung di lingkungan pengembangan ini). Formatnya sudah dicocokkan
    dengan dokumentasi protokol resmi & pola yang sudah terbukti jalan di
    pyzk sendiri (`set_sdk_build_1`), dan sudah diuji lewat mock (urutan
    command & format byte-string benar), TAPI perilaku SUNGGUHAN di device
    fisik -- termasuk apakah device butuh reboot manual supaya IP baru
    benar-benar aktif di jaringan -- belum bisa dipastikan tanpa uji coba
    langsung. SANGAT disarankan diuji hati-hati di SATU device dulu (idealnya
    yang gampang diakses fisik, jaga-jaga kalau perlu di-reset manual) sebelum
    dipakai ke banyak device sekaligus.

    Return: (success: bool, message: str).
    """
    try:
        from zk import ZK, const
    except ImportError:
        return False, "Library 'pyzk' belum terinstall di server. Jalankan: pip install pyzk"
    if not ip_address:
        return False, 'Device ini belum punya IP Address yang tercatat di database.'

    params = [(name, value) for name, value in [
        ('IPAddress', new_ip),
        ('NetMask', new_netmask),
        ('GATEIPAddress', new_gateway),
    ] if value]
    if not params:
        return False, 'Tidak ada parameter (IP Address/NetMask/Gateway) yang diisi.'

    zk_instance = ZK(ip_address, port=port, timeout=timeout, password=0, force_udp=False, ommit_ping=False)
    conn = None
    try:
        conn = zk_instance.connect()
        send_command = getattr(conn, '_ZK__send_command')

        applied = []
        for name, value in params:
            command_string = f'{name}={value}\x00'.encode()
            cmd_response = send_command(const.CMD_OPTIONS_WRQ, command_string)
            if not cmd_response.get('status'):
                return False, (
                    f"Gagal set parameter '{name}'. "
                    f"({'Sebelumnya berhasil: ' + ', '.join(applied) if applied else 'Belum ada yang berhasil.'})"
                )
            applied.append(name)

        # Sesuai protokol resmi: kirim CMD_REFRESHOPTION SEKALI di akhir,
        # setelah semua parameter berhasil di-set, supaya device menerapkan
        # perubahannya.
        refresh_response = send_command(const.CMD_REFRESHOPTION)
        if not refresh_response.get('status'):
            return False, (
                f"Parameter berhasil di-set ({', '.join(applied)}) tapi device tidak merespons "
                f"CMD_REFRESHOPTION dengan sukses -- perubahan mungkin belum benar-benar aktif. "
                f"Coba reboot device secara manual (menu 'REBOOT' di dropdown Aksi)."
            )

        return True, (
            f"Parameter jaringan berhasil di-set & diterapkan: {', '.join(applied)}. "
            f"Kalau device tidak langsung terhubung dengan IP baru, coba REBOOT device secara manual."
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning('Gagal set network params device %s:%s -> %s', ip_address, port, exc)
        return False, f'Gagal set parameter jaringan: {exc}'
    finally:
        if conn is not None:
            try:
                conn.disconnect()
            except Exception:  # noqa: BLE001
                pass


def get_device_param(ip_address: str, param_name: str, port: int = ZK_DEFAULT_PORT, timeout: int = ZK_DEFAULT_TIMEOUT):
    """
    Baca SATU parameter konfigurasi APA SAJA dari device via pyzk
    (command CMD_OPTIONS_RRQ) -- generic, untuk keperluan eksplorasi/testing
    nama parameter yang admin sudah ketahui (mis. dari dokumentasi ZKTeco
    atau SOLUSI), bukan cuma yang sudah "dibungkus" pyzk sendiri
    (`get_network_params()` cuma baca 3 nama parameter yang fixed).

    Return: (success: bool, value_or_message: str) -- kalau sukses,
    string kedua adalah NILAI parameter-nya; kalau gagal, pesan errornya.
    """
    try:
        from zk import ZK, const
    except ImportError:
        return False, "Library 'pyzk' belum terinstall di server. Jalankan: pip install pyzk"
    if not ip_address:
        return False, 'Device ini belum punya IP Address yang tercatat di database.'
    if not param_name:
        return False, 'Nama parameter harus diisi.'

    zk_instance = ZK(ip_address, port=port, timeout=timeout, password=0, force_udp=False, ommit_ping=False)
    conn = None
    try:
        conn = zk_instance.connect()
        send_command = getattr(conn, '_ZK__send_command')
        command_string = f'{param_name}\x00'.encode()
        cmd_response = send_command(const.CMD_OPTIONS_RRQ, command_string, 1024)
        if not cmd_response.get('status'):
            return False, (
                f"Device menolak permintaan baca parameter '{param_name}' "
                f"(kemungkinan nama parameter tidak dikenal/tidak ada di device ini)."
            )
        raw_data = getattr(conn, '_ZK__data')
        value = raw_data.split(b'=', 1)[-1].split(b'\x00')[0].decode(errors='replace')
        return True, value
    except Exception as exc:  # noqa: BLE001
        logger.warning("Gagal baca parameter '%s' dari device %s:%s -> %s", param_name, ip_address, port, exc)
        return False, f"Gagal baca parameter '{param_name}': {exc}"
    finally:
        if conn is not None:
            try:
                conn.disconnect()
            except Exception:  # noqa: BLE001
                pass


def set_device_param(ip_address: str, param_name: str, param_value: str, do_refresh: bool = True,
                      port: int = ZK_DEFAULT_PORT, timeout: int = ZK_DEFAULT_TIMEOUT):
    """
    Set SATU parameter konfigurasi APA SAJA di device via pyzk (command
    CMD_OPTIONS_WRQ, format "<nama>=<nilai>\\x00" sesuai dokumentasi protokol
    resmi) -- generic, untuk keperluan eksplorasi/testing nama parameter yang
    admin sudah ketahui.

    `do_refresh`: kalau True (default), kirim CMD_REFRESHOPTION sesudahnya
    supaya device menerapkan perubahan (lihat catatan di `set_network_params()`
    soal kenapa ini penting). Bisa di-nonaktifkan lewat UI khusus buat
    keperluan eksperimen (mis. mau lihat apakah parameter tertentu perlu
    refresh atau tidak).

    Return: (success: bool, message: str).
    """
    try:
        from zk import ZK, const
    except ImportError:
        return False, "Library 'pyzk' belum terinstall di server. Jalankan: pip install pyzk"
    if not ip_address:
        return False, 'Device ini belum punya IP Address yang tercatat di database.'
    if not param_name:
        return False, 'Nama parameter harus diisi.'

    zk_instance = ZK(ip_address, port=port, timeout=timeout, password=0, force_udp=False, ommit_ping=False)
    conn = None
    try:
        conn = zk_instance.connect()
        send_command = getattr(conn, '_ZK__send_command')
        command_string = f'{param_name}={param_value}\x00'.encode()
        cmd_response = send_command(const.CMD_OPTIONS_WRQ, command_string)
        if not cmd_response.get('status'):
            return False, f"Device menolak set parameter '{param_name}={param_value}'."

        if not do_refresh:
            return True, (
                f"Parameter '{param_name}' berhasil di-set ke '{param_value}' "
                f"(CMD_REFRESHOPTION TIDAK dikirim sesuai pilihan Anda -- perubahan mungkin "
                f"belum aktif sampai ada refresh/reboot)."
            )

        refresh_response = send_command(const.CMD_REFRESHOPTION)
        if not refresh_response.get('status'):
            return False, (
                f"Parameter '{param_name}' berhasil di-set ke '{param_value}' tapi device "
                f"tidak merespons CMD_REFRESHOPTION dengan sukses -- coba reboot manual."
            )
        return True, f"Parameter '{param_name}' berhasil di-set ke '{param_value}' & diterapkan (REFRESHOPTION sukses)."
    except Exception as exc:  # noqa: BLE001
        logger.warning("Gagal set parameter '%s' di device %s:%s -> %s", param_name, ip_address, port, exc)
        return False, f"Gagal set parameter '{param_name}': {exc}"
    finally:
        if conn is not None:
            try:
                conn.disconnect()
            except Exception:  # noqa: BLE001
                pass


def transfer_fingerprints_from_db(pin: str, name: str, privilege: int, password: str, card: int, group_id: str,
                                   db_templates: list, target_ips: list,
                                   port: int = ZK_DEFAULT_PORT, timeout: int = ZK_DEFAULT_TIMEOUT) -> list:
    """
    Transfer template fingerprint dari DATABASE kita (tabel Fingerprint
    Template / fptemp) ke satu/lebih target device -- BEDA dengan
    `transfer_fingerprints()` yang ambil sumbernya LANGSUNG dari device
    fisik. Berguna kalau source device sedang tidak bisa dijangkau tapi
    template-nya sudah pernah di-backup ke database (lihat fitur "Backup
    Data Finger"), atau memang sengaja mau pakai data DB sebagai sumber
    kebenaran alih-alih device tertentu.

    `db_templates`: list of dict {'fid': int, 'valid': int, 'template_b64': str}
    -- 'template_b64' adalah isi field `fptemp.Template` (base64 text, sesuai
    cara `backup_device_fingerprints()` menyimpannya).
    `target_ips`: list of tuple (ip_address, label), sama seperti
    `transfer_fingerprints()`.

    Return: list of log strings.
    """
    import base64

    from zk.finger import Finger

    log = []
    if not db_templates:
        log.append(f"GAGAL: tidak ada template fingerprint tersimpan di DATABASE untuk PIN '{pin}'.")
        return log
    if not target_ips:
        log.append('GAGAL: tidak ada target device (pool tujuan kosong / tidak punya device).')
        return log

    fingers = []
    for tpl in db_templates:
        try:
            raw_template = base64.b64decode(tpl['template_b64'])
        except Exception as exc:  # noqa: BLE001
            log.append(f"  [Jari #{tpl.get('fid')}] DILEWATI: gagal decode base64 template ({exc}).")
            continue
        # uid diisi 0 -- tidak dipakai secara bermakna oleh save_user_template()
        # pyzk (target device selalu pakai uid MILIK TARGET sendiri saat
        # nge-pack ulang paketnya, lihat catatan di transfer_fingerprints()).
        fingers.append(Finger(uid=0, fid=tpl['fid'], valid=tpl['valid'], template=raw_template))

    if not fingers:
        log.append('GAGAL: semua template di database gagal di-decode, tidak ada yang bisa ditransfer.')
        return log

    log.append(f"[{pin}] {len(fingers)} template ditemukan di DATABASE (bukan device fisik), siap ditransfer.")

    try:
        from zk import ZK
    except ImportError:
        return log + ["GAGAL: library 'pyzk' belum terinstall di server. Jalankan: pip install pyzk"]

    for target_ip, target_label in target_ips:
        log.append(f'--- Target: {target_label} ({target_ip}:{port}) ---')
        tgt_zk = ZK(target_ip, port=port, timeout=timeout, password=0, force_udp=False, ommit_ping=False)
        tgt_conn = None
        try:
            tgt_conn = tgt_zk.connect()
            target_users_by_pin = {str(u.user_id): u for u in tgt_conn.get_users()}

            if pin not in target_users_by_pin:
                try:
                    tgt_conn.set_user(
                        name=name, privilege=privilege, password=password,
                        group_id=group_id, user_id=pin, card=card,
                    )
                    log.append(f'  [{pin}] User belum ada di target, berhasil dibuat.')
                except Exception as exc:  # noqa: BLE001
                    log.append(f'  [{pin}] GAGAL bikin user di target: {exc}')
                    continue

            try:
                tgt_conn.save_user_template(pin, fingers)
                log.append(f'  [{pin}] Berhasil transfer {len(fingers)} template (dari database).')
            except Exception as exc:  # noqa: BLE001
                logger.warning('Gagal transfer PIN %s ke %s -> %s', pin, target_ip, exc)
                log.append(f'  [{pin}] GAGAL: {exc}')
        except Exception as exc:  # noqa: BLE001
            logger.warning('Gagal konek ke target %s:%s -> %s', target_ip, port, exc)
            log.append(f'GAGAL terhubung ke target device {target_label}: {exc}')
        finally:
            if tgt_conn is not None:
                try:
                    tgt_conn.disconnect()
                except Exception:  # noqa: BLE001
                    pass

    log.append('Selesai.')
    return log
