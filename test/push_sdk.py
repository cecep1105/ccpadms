#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
push_sdk.py -- Emulator device PUSH SDK (ZKTeco/ADMS), versi Python 3.

Konversi dari skrip Python 2.6 lama (`test/push_sdk.py` di repo), dengan
perubahan MENDASAR pada sumber data emulasi:

  - LAMA: transaksi & user di-generate ACAK/sintetis (uid increment, nama
    "用户_<uid>", waktu berjalan terus dari `datetime.now()`).
  - BARU: transaksi di-REPLAY dari data SUNGGUHAN (`test/062026/*.txt`,
    format CSV `SN,PIN,DD/MM/YYYY HH:MM,checktype`) -- setiap device yang
    diemulasikan mengirim ulang riwayat transaksi ASLINYA sendiri (per SN),
    bukan data karangan.

Perbaikan lain dari versi lama (bukan cuma migrasi sintaks py2->py3):
  - HTTP client pakai `urllib.request` (stdlib py3, TIDAK perlu paket
    tambahan `requests` -- penting utk lingkungan Python 3.10 embeddable
    yang biasanya TIDAK punya pip package terpasang).
  - `print` -> `logging` (level jelas: INFO utk aktivitas normal, WARNING
    utk baris data yang di-skip/rusak, ERROR utk request gagal).
  - CLI pakai `argparse` (bukan parsing manual `sys.argv`).
  - Parsing baris data TAHAN terhadap baris rusak (dikonfirmasi ADA di
    data sungguhan -- `test/062026/08.txt` baris 4718 cuma `" 21:03,1"`,
    kehilangan SN & PIN) -- baris begini di-skip dgn warning log, bukan
    bikin proses crash atau berhenti total.
  - Dihapus: kode mati/tidak terpakai dari versi lama (`process_data()`
    yang pakai `types.StringTypes`, khusus Python 2, dan tidak pernah
    dipanggil di skrip aslinya; `create_many_trans`/`post_many_trans` yang
    generate data acak -- digantikan alur replay data sungguhan).
  - `stop` flag jadi `threading.Event` (bukan boolean mentah) -- lebih
    idiomatis Python modern utk sinyal berhenti antar-thread.
  - Pengecekan respons sukses upload jadi lebih longgar: kode LAMA cek
    `res.body[:3] == "OK:"` (dengan titik dua) -- TAPI spesifikasi PUSH
    SDK resmi bilang server balas PERSIS "OK" (tanpa titik dua, lihat
    resume protokol). Kemungkinan ini kebiasaan server LAMA yang dipakai
    sebelumnya. Di versi ini dicek `res.body.strip().startswith("OK")`
    supaya cocok BAIK dengan server yang taat spesifikasi (balas "OK"
    polos) MAUPUN kebiasaan lama ("OK:xxx") -- ⚠️ perlu diverifikasi ulang
    begitu server baru selesai dibangun, sesuaikan kalau ternyata beda.

Constraint lingkungan: didesain utk Python 3.10 embeddable -- HANYA pakai
modul stdlib (tidak ada dependency pip sama sekali).
"""
from __future__ import annotations

import argparse
import csv
import datetime
import logging
import random
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger('push_sdk')

ONE_SECOND = datetime.timedelta(seconds=1)

# ---------------------------------------------------------------------------
# Template fingerprint contoh (dipertahankan dari skrip lama) -- HANYA dipakai
# kalau opsi enrollment user/fingerprint sintetis diaktifkan (--synth-users),
# TIDAK relevan utk alur replay transaksi (fokus utama skrip ini sekarang).
# ---------------------------------------------------------------------------
DEF_TMP = (
    "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",
)


# ---------------------------------------------------------------------------
# HTTP layer
# ---------------------------------------------------------------------------
@dataclass
class DeviceResponse:
    """Hasil 1 request HTTP -- padanan tuple (code, msg, body) di skrip lama."""
    status: int
    message: str
    body: str | None

    @property
    def ok(self) -> bool:
        return self.status == 200


def device_request(url: str, body: str | None = None, timeout: float = 15.0) -> DeviceResponse:
    """
    Kirim 1 request HTTP (GET kalau `body` kosong, POST kalau ada) -- padanan
    `device_request()` di skrip lama, tapi pakai `urllib.request` (stdlib
    Python 3) menggantikan `urllib2` (Python 2 saja).
    """
    data = body.encode('utf-8') if body else None
    req = urllib.request.Request(url, data=data, headers={'Content-type': 'text/plain'})
    logger.debug('%s %s', 'POST' if data else 'GET', url)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return DeviceResponse(resp.status, 'OK', resp.read().decode('utf-8', errors='replace'))
    except urllib.error.HTTPError as exc:
        payload = exc.read().decode('utf-8', errors='replace') if exc.fp else None
        return DeviceResponse(exc.code, exc.reason, payload)
    except urllib.error.URLError as exc:
        return DeviceResponse(-1, str(exc.reason), None)
    except Exception as exc:  # noqa: BLE001 -- sengaja tangkap semua, device fisik hidup terus walau 1 request gagal
        return DeviceResponse(-99999, str(exc), None)


# ---------------------------------------------------------------------------
# Data loading -- REPLAY dari data transaksi SUNGGUHAN (BARU, menggantikan
# generator sintetis/acak di skrip lama)
# ---------------------------------------------------------------------------
@dataclass
class TransactionRecord:
    """1 baris transaksi -- PIN, waktu check, tipe check (STATUS, lihat resume protokol)."""
    pin: str
    timestamp: datetime.datetime
    check_type: str

    def to_attlog_line(self, override_timestamp: datetime.datetime | None = None) -> str:
        """
        Format 1 baris ATTLOG sesuai spesifikasi PUSH SDK: PIN\\tTIME\\tSTATUS\\tVERIFY
        (VERIFY di-hardcode '1' = fingerprint, sesuai kebiasaan skrip lama --
        data sumber tidak punya info mode verifikasi, cuma check_type/STATUS).
        """
        ts = override_timestamp or self.timestamp
        return f"{self.pin}\t{ts.strftime('%Y-%m-%d %H:%M:%S')}\t{self.check_type}\t1"


def _parse_transaction_row(row: list[str], source: str, line_no: int) -> tuple[str, TransactionRecord] | None:
    """
    Parse 1 baris CSV `SN,PIN,DD/MM/YYYY HH:MM,checktype` -> (SN, TransactionRecord).
    Return None (+ log warning) kalau baris ini RUSAK -- dikonfirmasi ADA di
    data sungguhan (mis. test/062026/08.txt baris 4718: " 21:03,1" -- cuma
    2 kolom, kehilangan SN & PIN). Baris rusak SENGAJA di-skip, bukan bikin
    proses berhenti/crash.
    """
    if len(row) != 4:
        logger.warning('%s:%d -- baris rusak (jumlah kolom %d, harus 4), dilewati: %r', source, line_no, len(row), row)
        return None
    sn, pin, ts_str, check_type = (v.strip() for v in row)

    if len(sn)<10:
        return None


    if not sn or not pin:
        logger.warning('%s:%d -- SN/PIN kosong, dilewati: %r', source, line_no, row)
        return None
    try:
        timestamp = datetime.datetime.strptime(ts_str, '%d/%m/%Y %H:%M')
    except ValueError:
        logger.warning('%s:%d -- format waktu tidak valid (%r), dilewati', source, line_no, ts_str)
        return None
    return sn, TransactionRecord(pin=pin, timestamp=timestamp, check_type=check_type)


def load_transactions_from_folder(folder: str | Path) -> dict[str, list[TransactionRecord]]:
    """
    Baca SEMUA file .txt di `folder` (mis. hasil ekstrak test/062026.zip),
    kelompokkan transaksi per SN device, urutkan kronologis PER SN (baris
    di dalam 1 file sudah cenderung urut, tapi 1 SN yang sama bisa muncul
    di BANYAK file/hari berbeda, jadi tetap perlu di-sort ulang gabungan
    semuanya).

    Return: {SN: [TransactionRecord, ...]} -- list per SN SUDAH terurut
    berdasarkan timestamp.
    """
    folder = Path(folder)
    by_sn: dict[str, list[TransactionRecord]] = {}
    txt_files = sorted(folder.glob('*.txt'))
    if not txt_files:
        raise FileNotFoundError(f"Tidak ada file .txt ditemukan di '{folder}' -- pastikan sudah di-ekstrak dari .zip.")

    total_rows = 0
    skipped_rows = 0
    for txt_file in txt_files:
        with open(txt_file, newline='', encoding='utf-8', errors='replace') as f:
            reader = csv.reader(f)
            for line_no, row in enumerate(reader, start=1):
                if not row:
                    continue
                total_rows += 1
                parsed = _parse_transaction_row(row, txt_file.name, line_no)
                if parsed is None:
                    skipped_rows += 1
                    continue
                sn, record = parsed
                by_sn.setdefault(sn, []).append(record)

    for sn, records in by_sn.items():
        records.sort(key=lambda r: r.timestamp)

    logger.info(
        'Data dimuat dari %d file: %d SN unik, %d baris total, %d baris dilewati (rusak).',
        len(txt_files), len(by_sn), total_rows, skipped_rows,
    )
    return by_sn
# ---------------------------------------------------------------------------
# Command parsing (respons GET /iclock/getrequest, format "C:ID:CMD ARGS")
# ---------------------------------------------------------------------------
@dataclass
class ServerCommand:
    cmd_id: str
    name: str
    args: str


def parse_server_commands(response_body: str) -> list[ServerCommand]:
    """
    Parse baris-baris "C:ID:CMD ARGS" dari respons getrequest. Baris "OK"
    (tidak ada command tertunda) atau baris kosong diabaikan.
    """
    commands = []
    for line in response_body.splitlines():
        line = line.strip()
        if not line or line == 'OK':
            continue
        parts = line.split(':', 2)
        if len(parts) != 3 or parts[0] != 'C':
            logger.warning("Baris command tidak dikenali formatnya, dilewati: %r", line)
            continue
        cmd_id = parts[1]
        rest = parts[2].split(' ', 1)
        name = rest[0]
        args = rest[1] if len(rest) > 1 else ''
        commands.append(ServerCommand(cmd_id=cmd_id, name=name, args=args))
    return commands


def parse_config_response(response_body: str) -> dict[str, str]:
    """
    Parse respons GET /iclock/cdata?options=all (baris `Field=Value`) jadi
    dict. Baris tanpa '=' (mis. "GET OPTION FROM: 123456") diabaikan --
    padanan dict-comprehension di skrip lama, tapi TAHAN terhadap value yang
    kebetulan mengandung karakter '=' juga (split cuma di kemunculan PERTAMA).
    """
    params = {}
    for line in response_body.splitlines():
        if '=' in line:
            key, _, value = line.partition('=')
            params[key.strip()] = value.strip()
    return params


# ---------------------------------------------------------------------------
# Device emulator inti
# ---------------------------------------------------------------------------
class DeviceEmulator:
    """
    Emulasi 1 device fisik yang bicara PUSH SDK ke server (`iclock_url`).

    BEDA UTAMA dari skrip lama: sumber transaksi yang di-upload adalah
    REPLAY dari `transactions` (list TransactionRecord SUNGGUHAN utk SN ini,
    lihat `load_transactions_from_folder()`), BUKAN generator acak.
    """

    def __init__(
        self,
        iclock_url: str,
        sn: str,
        transactions: list[TransactionRecord] | None = None,
        synth_user_count: int = 0,
    ):
        self.iclock_url = iclock_url if iclock_url.endswith('/') else iclock_url + '/'
        self.sn = sn
        self.transactions = list(transactions or [])
        self.fw_version = 'Ver 3.60 Feb 20 2010'
        self.stop_event = threading.Event()
        self.sent_count = 0
        self.param: dict[str, str] = {}

        # User/fingerprint sintetis -- OPSIONAL, TIDAK relevan utk replay
        # transaksi (dipertahankan dari skrip lama utk siapa yang mau tes
        # jalur enrollment user/fingerprint juga, lihat --synth-users di CLI).
        self.synth_users: dict[str, dict] = {}
        for i in range(synth_user_count):
            uid = str(19000 + i)
            self.synth_users[uid] = {'name': f'User_{uid}'}

    def stop(self) -> None:
        self.stop_event.set()

    # -- request builder, padanan DeviceEmulate.request() di skrip lama --
    def _request(self, path: str, query: dict | str = '', body: str = '') -> DeviceResponse:
        if isinstance(query, dict):
            query = urllib.parse.urlencode(query)
        sep = '&' if query else ''
        url = f"{self.iclock_url}{path}?SN={self.sn}{sep}{query}"
        return device_request(url, body or None)

    def fetch_config(self) -> DeviceResponse:
        """GET /iclock/cdata?options=all -- baca konfigurasi server (lihat resume protokol §3)."""
        return self._request('cdata', {'options': 'all', 'pushver': '2.0.1', 'language': '69'})

    def poll_commands(self) -> DeviceResponse:
        """GET /iclock/getrequest -- cek command tertunda (lihat resume protokol §5.1)."""
        info = f"{self.fw_version},{len(self.synth_users)},0,{self.sent_count},192.168.1.119"
        return self._request('getrequest', {'INFO': info})

    def post_command_result(self, cmd_id: str, cmd_name: str, ret: str) -> DeviceResponse:
        """POST /iclock/devicecmd -- laporkan hasil eksekusi command (lihat resume protokol §5.2)."""
        return self._request('devicecmd', body=f"ID={cmd_id}&Return={ret}&CMD={cmd_name}")

    def post_cdata(self, stamp_field: str, lines: list[str]) -> bool:
        """
        POST /iclock/cdata?table=...&<stamp_field> -- upload data (ATTLOG/
        OPERLOG, lihat resume protokol §4). `stamp_field` contoh:
        "table=ATTLOG&Stamp=1234567".
        """
        res = self._request('cdata', stamp_field, '\n'.join(lines))
        # ⚠️ Spesifikasi resmi: server balas PERSIS "OK". Skrip Python 2 lama
        # cek "OK:" (dgn titik dua) -- kemungkinan kebiasaan server LAMA.
        # Di sini dicek lebih longgar (startswith) supaya kompatibel dgn
        # keduanya; SESUAIKAN setelah server baru selesai dibangun & responsnya
        # dikonfirmasi persis apa.
        if res.ok and res.body and res.body.strip().startswith('OK'):
            return True
        logger.error('Upload %s gagal/respons tak dikenali: %s', stamp_field, res)
        return False

    def process_pending_commands(self, handler=None) -> None:
        """
        Ambil & proses SEMUA command tertunda dari server (poll_commands()),
        lalu laporkan hasilnya. `handler(cmd_name, args) -> return_code_str`
        opsional -- kalau tidak diisi, semua command otomatis dibalas "0"
        (sukses) tanpa efek nyata (cukup utk tes alur, bukan eksekusi
        sungguhan -- lihat contoh `default_command_handler()` di bawah).
        """
        res = self.poll_commands()
        if not res.ok:
            logger.warning('Poll command gagal utk SN=%s: %s', self.sn, res)
            return
        for cmd in parse_server_commands(res.body or ''):
            logger.info('SN=%s terima command #%s: %s %s', self.sn, cmd.cmd_id, cmd.name, cmd.args)
            ret = handler(cmd.name, cmd.args) if handler else '0'
            self.post_command_result(cmd.cmd_id, cmd.name, ret)

    def run_replay(
        self,
        command_handler=None,
        speed: float = 60.0,
        poll_interval_seconds: float = 5.0,
        batch_size: int = 50,
    ) -> int:
        """
        Jalankan emulasi: replay SEMUA transaksi tersimpan (`self.transactions`,
        sudah terurut kronologis) sesuai jarak waktu ASLINYA, tapi dipercepat
        `speed`x (default 60x -- 1 menit data asli jadi ~1 detik replay).
        Command dari server dicek tiap `poll_interval_seconds` detik (real
        time, TIDAK ikut dipercepat `speed` -- pola polling tetap realistis).

        Return: jumlah transaksi yang BERHASIL di-upload.
        """
        # 1. Baca config server dulu (WAJIB per protokol, lihat resume §2 tahap 1).
        cfg_res = self.fetch_config()
        if not cfg_res.ok:
            logger.error('SN=%s gagal fetch config, batalkan replay: %s', self.sn, cfg_res)
            return 0
        self.param = parse_config_response(cfg_res.body or '')
        logger.info('SN=%s config diterima: Realtime=%s TransInterval=%s Delay=%s',
                    self.sn, self.param.get('Realtime'), self.param.get('TransInterval'), self.param.get('Delay'))

        if not self.transactions:
            logger.warning('SN=%s tidak punya transaksi utk di-replay.', self.sn)
            return 0

        # 2. Jam virtual: mulai dari timestamp transaksi PERTAMA, berjalan
        #    `speed`x lebih cepat dari waktu nyata.
        virtual_clock = self.transactions[0].timestamp
        real_start = time.monotonic()
        last_poll = 0.0
        pending: list[TransactionRecord] = []
        idx = 0
        sent = 0

        while idx < len(self.transactions) and not self.stop_event.is_set():
            elapsed_real = time.monotonic() - real_start
            virtual_clock = self.transactions[0].timestamp + datetime.timedelta(seconds=elapsed_real * speed)

            # Kumpulkan semua transaksi yang timestamp-nya sudah "lewat" di jam virtual.
            while idx < len(self.transactions) and self.transactions[idx].timestamp <= virtual_clock:
                pending.append(self.transactions[idx])
                idx += 1

            if len(pending) >= batch_size or (pending and idx >= len(self.transactions)):
                lines = [r.to_attlog_line() for r in pending]
                stamp = int(time.time())
                if self.post_cdata(f'table=ATTLOG&Stamp={stamp}', lines):
                    sent += len(lines)
                    self.sent_count += len(lines)
                    logger.info('SN=%s upload %d transaksi (total %d/%d)', self.sn, len(lines), sent, len(self.transactions))
                pending = []

            if elapsed_real - last_poll >= poll_interval_seconds:
                self.process_pending_commands(command_handler)
                last_poll = elapsed_real

            time.sleep(0.2)

        # Sisa transaksi yang belum sempat masuk batch (baik karena replay
        # selesai natural, MAUPUN dihentikan manual via stop()) -- SELALU
        # di-flush di sini, supaya stop() tidak diam-diam membuang data yang
        # sudah "siap" tapi belum sempat ter-post (bug yang sempat ketemu
        # saat testing: kondisi lama cuma flush kalau BUKAN karena stop()).
        if pending:
            lines = [r.to_attlog_line() for r in pending]
            if self.post_cdata(f'table=ATTLOG&Stamp={int(time.time())}', lines):
                sent += len(lines)
                self.sent_count += len(lines)

        logger.info('SN=%s replay selesai: %d/%d transaksi terkirim.', self.sn, sent, len(self.transactions))
        return sent


def default_command_handler(cmd_name: str, args: str) -> str:
    """
    Handler contoh utk command dari server -- balas "0" (sukses) generik utk
    semua, KECUALI PutFile (butuh ukuran file sbg return value, padanan
    `p_proc()` di skrip lama) yang dibalas ukuran acak realistis.
    """
    if cmd_name == 'PutFile':
        return str(random.randint(1_000, 400_000))
    return '0'
# ---------------------------------------------------------------------------
# Multi-device runner (padanan DeviceThread/test_run di skrip lama)
# ---------------------------------------------------------------------------
class DeviceThread(threading.Thread):
    """Bungkus 1 DeviceEmulator dalam thread -- supaya banyak device bisa jalan bersamaan."""

    def __init__(self, emulator: DeviceEmulator, speed: float, poll_interval: float, batch_size: int):
        super().__init__(daemon=True)
        self.emulator = emulator
        self._kwargs = dict(speed=speed, poll_interval_seconds=poll_interval, batch_size=batch_size)

    def run(self) -> None:
        self.emulator.run_replay(command_handler=default_command_handler, **self._kwargs)

    def stop_device(self) -> None:
        self.emulator.stop()


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description='Emulator device PUSH SDK -- replay data transaksi sungguhan (CSV SN,PIN,waktu,checktype) ke server iclock.',
    )
    parser.add_argument('--url', required=True, help="URL dasar iclock, mis. http://127.0.0.1:8010/iclock/")
    parser.add_argument('--data-dir', required=True, help="Folder berisi file .txt hasil ekstrak (mis. test/062026/ setelah unzip 062026.zip)")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--sn', help="Emulasikan HANYA 1 device dengan SN ini")
    group.add_argument('--all-devices', action='store_true', help="Emulasikan SEMUA SN yang ditemukan di data-dir sekaligus (1 thread per SN)")
    parser.add_argument('--speed', type=float, default=60.0, help="Kelipatan percepatan replay dibanding waktu asli (default 60x). Nilai besar (mis. 999999) = secepat mungkin, abaikan jeda waktu asli.")
    parser.add_argument('--poll-interval', type=float, default=5.0, help="Detik antar cek command dari server (real time, TIDAK ikut dipercepat --speed). Default 5.")
    parser.add_argument('--batch-size', type=int, default=50, help="Jumlah transaksi maksimum per 1 kali upload POST. Default 50.")
    parser.add_argument('--max-devices', type=int, default=None, help="Batasi jumlah device yang diemulasikan sekaligus saat --all-devices (utk hindari membanjiri server saat tes awal).")
    parser.add_argument('-v', '--verbose', action='store_true', help="Tampilkan log DEBUG (semua request/response mentah).")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format='%(asctime)s %(levelname)-7s %(message)s',
        datefmt='%H:%M:%S',
    )

    by_sn = load_transactions_from_folder(args.data_dir)

    if args.sn:
        if args.sn not in by_sn:
            logger.error("SN '%s' tidak ditemukan di data. SN yang tersedia: %s", args.sn, ', '.join(sorted(by_sn)[:20]))
            return 1
        targets = {args.sn: by_sn[args.sn]}
    else:
        targets = by_sn
        if args.max_devices:
            targets = dict(list(targets.items())[:args.max_devices])

    logger.info('Menjalankan emulasi utk %d device: %s', len(targets), ', '.join(sorted(targets)) if len(targets) <= 10 else f'{len(targets)} SN (terlalu banyak utk ditampilkan)')

    threads = []
    for sn, records in targets.items():
        emulator = DeviceEmulator(iclock_url=args.url, sn=sn, transactions=records)
        thread = DeviceThread(emulator, speed=args.speed, poll_interval=args.poll_interval, batch_size=args.batch_size)
        threads.append(thread)
        thread.start()

    try:
        while any(t.is_alive() for t in threads):
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info('Dihentikan manual (Ctrl+C) -- menghentikan semua device...')
        for t in threads:
            t.stop_device()
        for t in threads:
            t.join(timeout=10)

    total_sent = sum(t.emulator.sent_count for t in threads)
    logger.info('Selesai. Total transaksi terkirim: %d', total_sent)
    return 0


if __name__ == '__main__':
    import sys
    sys.exit(main())