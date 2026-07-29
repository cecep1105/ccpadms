# -*- coding: utf-8 -*-
"""
API internal utk monitoring & manajemen mail server Zentyal (Postfix +
Dovecot) -- HARUS Python 2.7 (batasan OS/lib sistem Zentyal 3.4 lama,
TIDAK BISA diupgrade ke Python 3 di server ini).

Konsumen API ini adalah Django (netmgmt/zentyal_mail_view.py, server-to-
server, BUKAN diakses langsung dari browser) -- lihat README di folder
ini utk cara jalankan & konfigurasi.

===========================================================================
PERUBAHAN UTAMA dari versi sebelumnya (perbaikan keamanan & robustness)
===========================================================================

1. **SHELL INJECTION DIPERBAIKI** -- versi SEBELUMNYA masukkan parameter
   dari request (qid, sender, email, domain) LANGSUNG ke string shell
   (`subprocess.Popen([".. %s .." % qid], shell=True)`) TANPA VALIDASI
   SAMA SEKALI -- siapa pun yang bisa panggil endpoint ini bisa eksekusi
   PERINTAH SHELL SEMBARANG di server (mis. qid="a; rm -rf /; echo a").
   Sekarang SEMUA parameter yang masuk ke shell command DIVALIDASI KETAT
   dgn regex whitelist SEBELUM dipakai (lihat _validate_* di bawah), dan
   kalaupun sudah divalidasi, TETAP di-quote dgn `pipes.quote()` sbg
   lapisan pertahanan kedua (defense in depth).

2. **SQL INJECTION DIPERBAIKI** -- versi SEBELUMNYA masukkan date_from/
   date_to LANGSUNG ke query SQL via string formatting (rawan injection
   kalau parameter itu dari request tanpa validasi ketat). Sekarang pakai
   PARAMETERIZED QUERY (`cursor.execute(query, params)`), pymysql yang
   urus escaping dgn benar.

3. **AUTENTIKASI TOKEN** -- versi SEBELUMNYA SAMA SEKALI TIDAK ADA
   autentikasi (siapa pun yg bisa akses network ke port ini bisa panggil
   SEMUA endpoint, termasuk yg DESTRUKTIF spt hapus mail queue). Sekarang
   WAJIB header `X-API-Token` cocok dgn `ZENTYAL_MAIL_API_TOKEN` (env
   var) -- lightweight (bukan OAuth/session penuh, sesuai kebutuhan
   "internal API dipanggil 1 backend Django saja"), TAPI CUKUP utk
   mencegah akses sembarangan. Generate token acak yg panjang, JANGAN
   dipakai token pendek yg gampang ditebak.

4. **KREDENSIAL DB PINDAH KE ENV VAR** -- versi SEBELUMNYA hardcode
   password MySQL LANGSUNG di source code (`'8vp8972n'`). Sekarang baca
   dari `ZENTYAL_MAIL_DB_PASSWORD` env var.

5. **DEBUG MODE DIMATIKAN DEFAULT** -- versi SEBELUMNYA `app.run(debug=True, host="0.0.0.0")`
   -- Werkzeug debugger MENGIZINKAN EKSEKUSI KODE ARBITRARY lewat
   halaman error kalau tidak di-PIN dgn benar, SANGAT BERBAHAYA di
   listen 0.0.0.0. Sekarang default `debug=False`, cuma aktif kalau
   `ZENTYAL_MAIL_DEBUG=true` di env (utk development LOKAL saja, JANGAN
   pernah true di server produksi).

6. **Kode duplikat dihapus** -- class `MailTransport` (persis sama dgn
   `IPViaEmail`, tidak pernah didaftarkan ke routing) dihapus.

7. **Logging terstruktur** -- ganti `print`/`print >>sys.stderr` &
   bare `except: pass` yg menelan semua error diam-diam, dgn `logging`
   module + exception message yg jelas (tetap gampang di-debug, tidak
   menyembunyikan error).

TETAP DIPERTAHANKAN (kompatibilitas, TIDAK diubah perilakunya):
- Semua endpoint & response shape yg sudah ada (frontend/Django yg
  konsumsi API ini SEHARUSNYA tidak perlu berubah, cuma tambah header
  X-API-Token wajib).
- Ketergantungan pada command `logd` (asumsi ke `zentyal_logd.sh` yg
  sudah ada di sistem, lihat ZENTYAL_LOGD_CMD di bawah kalau perlu
  arahkan ke path lain).
- Python 2.7 (subprocess.Popen dgn shell=True TETAP DIPAKAI utk pipeline
  `logd|grep|awk` dst -- yang diperbaiki HANYA validasi input sebelum
  masuk ke command itu, BUKAN mengganti keseluruhan pendekatan shell
  pipeline, supaya tidak perlu refactor besar-besaran yg berisiko utk
  sistem produksi yg sudah jalan).
"""
from __future__ import print_function

import datetime
import json
import logging
import os
import pipes  # py2.7 -- shlex.quote() di py3, pipes.quote() di py2
import re
import subprocess
import sys
from functools import wraps

from flask import Flask, jsonify, request
from flask_restful import Api, Resource

# ---------------------------------------------------------------------------
# Konfigurasi via ENVIRONMENT VARIABLE (BUKAN hardcode di source) -- lihat
# README.md sebelah file ini utk contoh systemd unit / cara set env var ini.
# ---------------------------------------------------------------------------
API_TOKEN = os.environ.get('ZENTYAL_MAIL_API_TOKEN', '')
DB_HOST = os.environ.get('ZENTYAL_MAIL_DB_HOST', '127.0.0.1')
DB_USER = os.environ.get('ZENTYAL_MAIL_DB_USER', 'zentyal')
DB_PASSWORD = os.environ.get('ZENTYAL_MAIL_DB_PASSWORD', '')
DB_NAME = os.environ.get('ZENTYAL_MAIL_DB_NAME', 'zentyal')
DEBUG_MODE = os.environ.get('ZENTYAL_MAIL_DEBUG', 'false').strip().lower() == 'true'
# Command dasar utk baca log mail -- default "logd" (asumsi sudah ada di
# PATH, symlink/alias ke zentyal_logd.sh yg sudah berjalan di sistem Anda
# -- lihat test/zentyal_logd.sh). Kalau mau lebih robust (TIDAK bergantung
# PATH), set env var ini ke PATH LENGKAP mis. "/opt/skrip/zentyal_logd.sh".
LOGD_CMD = os.environ.get('ZENTYAL_MAIL_LOGD_CMD', 'logd')
TRANSPORT_FILE = os.environ.get('ZENTYAL_MAIL_TRANSPORT_FILE', '/etc/postfix/acls/transport')
BLOCKSENDERS_FILE = os.environ.get('ZENTYAL_MAIL_BLOCKSENDERS_FILE', '/etc/postfix/conf/blocksenders.regxp')
ADDTRANSPORT_SCRIPT = os.environ.get('ZENTYAL_MAIL_ADDTRANSPORT_SCRIPT', '/opt/skrip/addtransport.sh')

logging.basicConfig(
    level=logging.DEBUG if DEBUG_MODE else logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
)
logger = logging.getLogger('zentyalmail')

if not API_TOKEN:
    logger.warning(
        'ZENTYAL_MAIL_API_TOKEN BELUM DI-SET -- API INI TIDAK TERPROTEKSI SAMA SEKALI! '
        'Set env var ZENTYAL_MAIL_API_TOKEN (string acak panjang) SEBELUM expose ke jaringan mana pun.'
    )

app = Flask(__name__)
api = Api(app)

port = 5100
if len(sys.argv) > 1:
    port = sys.argv[1]


# ---------------------------------------------------------------------------
# Autentikasi -- LIGHTWEIGHT (token statis di header), BUKAN OAuth/session
# penuh. Cukup utk skenario "1 backend Django yg konsumsi API ini",
# TIDAK cocok kalau nanti ada BANYAK konsumen beda hak akses (kalau itu
# terjadi, pertimbangkan per-konsumen token + rate limiting tambahan).
# ---------------------------------------------------------------------------
def require_token(view_method):
    @wraps(view_method)
    def wrapper(*args, **kwargs):
        if not API_TOKEN:
            # Belum di-set -- SUDAH di-warning di startup, tapi TETAP
            # TOLAK request drpd diam-diam buka akses tanpa proteksi.
            return {'error': 'Server belum dikonfigurasi (ZENTYAL_MAIL_API_TOKEN kosong) -- hubungi admin.'}, 503
        provided = request.headers.get('X-API-Token', '')
        if provided != API_TOKEN:
            logger.warning('Percobaan akses dgn token salah/kosong dari %s', request.remote_addr)
            return {'error': 'Token tidak valid.'}, 401
        return view_method(*args, **kwargs)
    return wrapper


# ---------------------------------------------------------------------------
# Validasi input KETAT (whitelist regex) -- SEMUA nilai dari request yang
# akan masuk ke shell command WAJIB lolos salah satu fungsi ini dulu.
# Kalau tidak lolos, request DITOLAK (400), TIDAK diteruskan ke shell
# dalam bentuk apa pun.
# ---------------------------------------------------------------------------
_QID_PATTERN = re.compile(r'^[A-Za-z0-9]{1,32}$')  # Postfix queue ID -- alfanumerik pendek
_EMAIL_PATTERN = re.compile(r'^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$')
_DOMAIN_PATTERN = re.compile(r'^[A-Za-z0-9.\-]{1,253}$')


def _validate_qid(qid):
    if not qid or not _QID_PATTERN.match(qid):
        return None
    return qid


def _validate_email(email):
    if not email or not _EMAIL_PATTERN.match(email):
        return None
    return email


def _validate_domain(domain):
    if not domain or not _DOMAIN_PATTERN.match(domain):
        return None
    return domain


class ValidationError(Exception):
    """Input dari request tidak lolos validasi whitelist -- endpoint HARUS tangkap ini & balas 400."""


# ---------------------------------------------------------------------------
# Helper subprocess -- bungkus subprocess.Popen dgn logging error yg
# konsisten (BUKAN bare except/pass spt versi sebelumnya).
# ---------------------------------------------------------------------------
def _get_json_body():
    """
    Ambil body JSON dari request POST -- KOMPATIBEL ke berbagai versi
    Flask/Werkzeug lama (server ini py2.7, versi Flask-nya BISA SANGAT
    LAWAS drpd yang dites di sandbox pengembangan).

    Kenapa fungsi terpisah (bukan langsung `request.get_json(...)`):
    DITEMUKAN LANGSUNG di server -- versi Flask/Werkzeug yang terpasang
    di sistem ini TERNYATA Request object-nya TIDAK PUNYA method
    `get_json()` sama sekali (AttributeError), method itu baru ada di
    versi Werkzeug yang lebih baru. Fungsi ini coba BEBERAPA cara
    berurutan, dari yang paling modern ke paling dasar/manual, supaya
    JALAN di versi Flask APA PUN (termasuk yang sangat lawas):
      1. `request.get_json(silent=True)` -- API modern, kalau ADA.
      2. `request.json` -- property versi Flask lebih lama (masih ada
         konsep parsing JSON otomatis, tapi lewat property bukan method).
      3. Manual: `json.loads(request.get_data())` atau `request.data` --
         cara PALING DASAR, parsing manual dari raw body, JALAN di semua
         versi Werkzeug (get_data()/.data SELALU ada sejak versi lawas).
    """
    try:
        return request.get_json(silent=True) or {}
    except AttributeError:
        pass

    try:
        return request.json or {}
    except AttributeError:
        pass

    try:
        raw = request.get_data()
    except AttributeError:
        raw = request.data
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except ValueError:
        logger.warning('Gagal parse body JSON (raw): %r', raw[:200])
        return {}


def _run_shell(cmd):
    """Jalankan 1 command shell (STRING, boleh mengandung pipe |) -- WAJIB semua bagian variabel di dalam `cmd` SUDAH divalidasi/di-quote SEBELUM dipanggil fungsi ini."""
    try:
        proc = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        stdout, stderr = proc.communicate()
        if proc.returncode not in (0, 1):  # grep return 1 kalau tidak ketemu match -- itu NORMAL, bukan error
            logger.warning('Command "%s" exit code %s, stderr: %s', cmd, proc.returncode, stderr.strip())
        return stdout.splitlines()
    except Exception:
        logger.exception('Gagal menjalankan command: %s', cmd)
        return []


def humanbytes(size_bytes):
    """Return the given bytes as a human friendly KB, MB, GB, or TB string."""
    try:
        value = float(size_bytes)
    except (TypeError, ValueError):
        return ''
    kb, mb, gb, tb = 1024.0, 1024.0 ** 2, 1024.0 ** 3, 1024.0 ** 4
    if value < kb:
        return '%d Bytes' % value
    if value < mb:
        return '%.0f KB' % (value / kb)
    if value < gb:
        return '%.0f MB' % (value / mb)
    if value < tb:
        return '%.0f GB' % (value / gb)
    return '%.0f TB' % (value / tb)


# ---------------------------------------------------------------------------
# Logic mail log/queue -- SAMA seperti versi sebelumnya, TAPI parameter yg
# masuk ke shell command SUDAH divalidasi ketat oleh pemanggilnya (lihat
# masing2 Resource class di bawah).
# ---------------------------------------------------------------------------
def getdetaillogs(qid):
    """qid WAJIB SUDAH divalidasi _validate_qid() oleh pemanggil -- di sini di-quote lagi sbg lapisan kedua."""
    safe_qid = pipes.quote(qid)
    return _run_shell("%s | grep -v amavis | grep %s" % (LOGD_CMD, safe_qid))


def gettodaylogs():
    lines = _run_shell("%s | grep 'from=' " % LOGD_CMD)
    currentlogs = []
    for raw_line in lines:
        line = raw_line.split()
        if len(line) < 8:
            continue
        try:
            date_str = '%s %s %s %s' % (datetime.datetime.now().strftime('%Y'), line[0], line[1], line[2])
            date = datetime.datetime.strptime(date_str, '%Y %b %d %H:%M:%S')
            qid = line[5][:-1]
            sender = line[6][6:-2]
            size = line[7][5:-1]
            total_recipient = 0
            if len(line) > 8:
                try:
                    total_recipient = line[8][6:]
                except (IndexError, ValueError):
                    pass

            if qid == 'NOQUEUE':
                continue
            if sender == '':
                sender = line[6][5:-1]
            if sender == '0':
                continue

            currentlogs.append({
                'date': date.strftime('%Y/%m/%d_%H:%M:%S'),
                'qid': qid,
                'sender': sender,
                'total_recp': total_recipient,
                'size': size,
            })
        except (IndexError, ValueError):
            logger.debug('Baris log tidak sesuai format, dilewati: %s', raw_line)
            continue
    return currentlogs


def _get_db_connection():
    import pymysql
    if not DB_PASSWORD:
        raise RuntimeError('ZENTYAL_MAIL_DB_PASSWORD belum di-set.')
    return pymysql.connect(
        host=DB_HOST, user=DB_USER, password=DB_PASSWORD, db=DB_NAME,
        cursorclass=pymysql.cursors.DictCursor,
    )


def getmaillog(date_from, date_to):
    """date_from/date_to dikirim sbg QUERY PARAMETER (bukan string formatting) -- pymysql yg urus escaping."""
    import ipaddress
    conn = _get_db_connection()
    try:
        query = "SELECT * FROM mail_message WHERE timestamp BETWEEN %s AND %s"
        cursor = conn.cursor()
        cursor.execute(query, (date_from, date_to))
        result = cursor.fetchall()
    finally:
        conn.close()

    rs = []
    for log in result:
        qid = ''
        try:
            qid = log[u'message'].split('queued as')[1].strip()
        except (KeyError, IndexError):
            pass
        try:
            client_ip = str(ipaddress.ip_address(int(log[u'client_host_ip'])))
        except (KeyError, ValueError, TypeError):
            client_ip = ''
        rs.append({
            'status': log.get(u'status'),
            'client_host_ip': client_ip,
            'from_address': log.get(u'from_address'),
            'relay': log.get(u'relay'),
            'timestamp': log[u'timestamp'].strftime('%Y/%m/%d_%H:%M:%S') if log.get(u'timestamp') else None,
            'client_host_name': log.get(u'client_host_name'),
            'event': log.get(u'event'),
            'message_size': log.get(u'message_size'),
            'qid': qid,
            'to_address': log.get(u'to_address'),
            'message': log.get(u'message'),
            'message_type': log.get(u'message_type'),
            'message_id': log.get(u'message_id'),
        })
    return rs


def getmailq():
    try:
        cmd = subprocess.Popen(['mailq'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        stdout, stderr = cmd.communicate()
        if cmd.returncode not in (0, 69):
            logger.warning('mailq exit code %s: %s', cmd.returncode, stderr.strip())
    except Exception:
        logger.exception('Gagal menjalankan mailq')
        return []

    mq = stdout.strip()
    curmsg = None
    msgs = {}
    for line in mq.splitlines():
        if not line or line[:10] == '-Queue ID-' or line[:2] == '--':
            continue
        if line[0] in '0123456789ABCDEF':
            parts = line.split()
            curmsg = parts[0]
            if curmsg[-1] == '*':
                status = 'active'
                curmsg = curmsg[:-1]
            else:
                status = 'deferred'
            msgs[curmsg] = {
                'size': parts[1],
                'rawdate': ' '.join(parts[2:6]),
                'sender': parts[-1],
                'recipient': [],
                'reason': '',
                'status': status,
            }
        elif '@' in line and '<' not in line and curmsg:
            msgs[curmsg]['recipient'].append(line.strip())
        elif line.lstrip(' ')[:1] == '(' and curmsg:
            msgs[curmsg]['reason'] = line.strip()[1:-1].replace('\n', ' ')
        else:
            logger.debug('Baris tidak dikenal di output mailq: %s', line)

    mmq = []
    for k in msgs.keys():
        mmq.append({
            'id': k,
            'size': msgs[k]['size'],
            'rawdate': msgs[k]['rawdate'],
            'sender': msgs[k]['sender'],
            'recipient': " ".join(list(set(msgs[k]['recipient']))),
            'reason': msgs[k]['reason'],
            'status': msgs[k]['status'],
        })
    return mmq


def _read_transport_file():
    ret = []
    try:
        with open(TRANSPORT_FILE, 'r') as f:
            lines = [x.strip() for x in f.read().splitlines()]
    except IOError:
        logger.exception('Gagal membaca %s', TRANSPORT_FILE)
        return ret
    for item in lines:
        try:
            domain, target = item.split('\t')
        except ValueError:
            continue
        status = '0' if domain.startswith('#') else '1'
        domain = domain[1:] if domain.startswith('#') else domain
        ret.append({'domain': domain, 'target': target, 'status': status})
    return ret


def _read_blocksenders_file():
    ret = []
    try:
        with open(BLOCKSENDERS_FILE, 'r') as f:
            lines = [x.strip() for x in f.read().splitlines()]
    except IOError:
        logger.exception('Gagal membaca %s', BLOCKSENDERS_FILE)
        return ret
    for item in lines:
        try:
            email, action = item.split('\t')
        except ValueError:
            continue
        status = '0' if email.startswith('#') else '1'
        ret.append({'email': email[2:-2] if len(email) > 3 else email, 'action': action, 'status': status})
    return ret


# ---------------------------------------------------------------------------
# Resource classes (endpoint HTTP) -- SEMUA pakai @require_token.
# ---------------------------------------------------------------------------
class IPViaEmail(Resource):
    method_decorators = [require_token]

    def get(self):
        lines = _run_shell(LOGD_CMD + " | grep \"rip=192.168\" | awk '{print $8 $10}' | sort | uniq")
        maildata = [x for x in lines if 'user' in x]
        result = []
        for y in maildata:
            try:
                result.append({'user': y.split(',')[0][6:-1], 'ip': y.split(',')[1][4:]})
            except IndexError:
                continue
        return {'result': result}


class POSTFIX(Resource):
    method_decorators = [require_token]

    def get(self):
        command = request.args.get('command', '')

        if command == '':
            return {'result': ''}

        if command == 'today_log':
            return {'result': gettodaylogs()}

        if command == 'detail_log':
            raw_qid = request.args.get('qid', '')
            qid = _validate_qid(raw_qid)
            if qid is None:
                return {'error': "Parameter 'qid' wajib diisi & alfanumerik (maks 32 karakter)."}, 400
            return {'result': getdetaillogs(qid)}

        if command == 'mail_log':
            date_from = request.args.get('date_from', datetime.datetime.now().strftime("%Y-%m-%d 00:00:00"))
            date_to = request.args.get('date_to', datetime.datetime.now().strftime("%Y-%m-%d 23:59:59"))
            try:
                return {'result': getmaillog(date_from, date_to)}
            except Exception as exc:
                logger.exception('Gagal query mail_log')
                return {'error': 'Gagal mengambil mail log: %s' % exc}, 502

        if command == 'transport_map':
            return jsonify({'result': _read_transport_file()})

        if command == 'blocksenders_map':
            return jsonify({'result': _read_blocksenders_file()})

        if command == 'qheader':
            raw_qid = request.args.get('qid', '')
            qid = _validate_qid(raw_qid)
            if qid is None:
                return {'error': "Parameter 'qid' wajib diisi & alfanumerik (maks 32 karakter)."}, 400
            lines = _run_shell("postcat -h -q %s" % pipes.quote(qid))
            return {'result': lines}

        return {'result': ''}

    def post(self):
        payload = _get_json_body()
        command = payload.get('command', '')

        if command == '':
            return {'result': ''}

        if command in ('reload', 'flush'):
            try:
                proc = subprocess.Popen(['postfix', command], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                _, stderr = proc.communicate()
                if proc.returncode != 0:
                    logger.warning('postfix %s exit code %s: %s', command, proc.returncode, stderr.strip())
                return {'result': proc.returncode}
            except Exception as exc:
                logger.exception('Gagal menjalankan postfix %s', command)
                return {'error': str(exc)}, 502

        if command == 'get_transport':
            return jsonify({'result': _read_transport_file()})

        if command == 'set_transport':
            transport_data = payload.get('transport_data', [])
            if not transport_data:
                return {'error': "'transport_data' wajib diisi (list)."}, 400
            lines_out = []
            for item in transport_data:
                domain = item.get('domain', '')
                target = item.get('target', '')
                status = item.get('status')
                prefix = '' if status else '#'
                lines_out.append('%s%-30s\t%s' % (prefix, domain, target))
            try:
                # Tulis ke file SEMENTARA dulu, baru rename (atomic) --
                # supaya kalau proses gagal di tengah jalan, file transport
                # ASLI tidak jadi setengah-tertulis/rusak.
                tmp_path = TRANSPORT_FILE + '.tmp'
                with open(tmp_path, 'w') as f:
                    f.write('\n'.join(lines_out) + '\n')
                os.rename(tmp_path, TRANSPORT_FILE)
            except IOError as exc:
                logger.exception('Gagal menulis %s', TRANSPORT_FILE)
                return {'error': str(exc)}, 502

            for cmd_args in (['postmap', TRANSPORT_FILE], ['postfix', 'reload'], ['postfix', 'flush']):
                try:
                    proc = subprocess.Popen(cmd_args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                    _, stderr = proc.communicate()
                    logger.info('%s exit code %s', ' '.join(cmd_args), proc.returncode)
                except Exception:
                    logger.exception('Gagal menjalankan %s', ' '.join(cmd_args))

            return jsonify({'result': _read_transport_file()})

        if command == 'set_blocksenders':
            raw_email = payload.get('email', '')
            email = _validate_email(raw_email)
            if email is None:
                return {'error': "'email' wajib diisi & format email valid."}, 400
            try:
                with open(BLOCKSENDERS_FILE, 'a') as f:
                    f.write('/^%s$/\tREJECT\n' % email)
            except IOError as exc:
                logger.exception('Gagal menulis %s', BLOCKSENDERS_FILE)
                return {'error': str(exc)}, 502
            return jsonify({'result': _read_blocksenders_file()})

        if command == 'add_biznet_transport':
            raw_domain = payload.get('domain', '')
            domain = _validate_domain(raw_domain)
            if domain is None:
                return {'error': "'domain' wajib diisi & format domain valid."}, 400
            try:
                proc = subprocess.Popen(
                    ['bash', ADDTRANSPORT_SCRIPT, domain, 'Y'],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                )
                stdout, stderr = proc.communicate()
                if proc.returncode != 0:
                    logger.warning('addtransport.sh exit code %s: %s', proc.returncode, stderr.strip())
                return {'result': proc.returncode}
            except Exception as exc:
                logger.exception('Gagal menjalankan addtransport.sh')
                return {'error': str(exc)}, 502

        return {'result': ''}


class MailQ(Resource):
    method_decorators = [require_token]

    def get(self):
        import json as json_module
        mmq = getmailq()
        imaplogs = []
        try:
            with open('/var/emailext/imaplog.json', 'r') as jsonfile:
                data = json_module.load(jsonfile)
                imaplogs = data.get('result', [])
        except (IOError, ValueError):
            logger.debug('Gagal baca /var/emailext/imaplog.json (mungkin belum ada, itu wajar)')
        return {'result': mmq, 'imaplogs': imaplogs}

    def post(self):
        payload = _get_json_body()
        raw_qids = payload.get('qids', [])
        raw_sender = payload.get('sender', '')
        command = payload.get('command', 'DELETE')

        if not raw_qids and not raw_sender:
            return {'result': 'qids atau sender harus diisi'}, 400

        if command == 'DELQFROMSENDER':
            sender = _validate_email(raw_sender)
            if sender is None:
                return {'error': "'sender' wajib format email valid."}, 400
            safe_sender = pipes.quote(sender)
            _run_shell(
                "mailq | tail -n +2 | awk 'BEGIN {RS=\"\"} /%s/ {print $1}' | tr -d '*!' | postsuper -d -" % safe_sender
            )
        else:
            valid_qids = []
            for raw_qid in raw_qids:
                qid = _validate_qid(raw_qid)
                if qid is None:
                    return {'error': "qid '%s' tidak valid (harus alfanumerik, maks 32 karakter)." % raw_qid}, 400
                valid_qids.append(qid)

            action_flag = '-d' if command == 'DELETE' else '-r' if command == 'REQUEUE' else None
            if action_flag is None:
                return {'error': "'command' wajib 'DELETE' atau 'REQUEUE'."}, 400

            try:
                proc = subprocess.Popen(
                    ['postsuper', action_flag] + valid_qids,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                )
                _, stderr = proc.communicate()
                if proc.returncode != 0:
                    logger.warning('postsuper %s exit code %s: %s', action_flag, proc.returncode, stderr.strip())
            except Exception as exc:
                logger.exception('Gagal menjalankan postsuper')
                return {'error': str(exc)}, 502

        return {'result': getmailq()}


def _time_filter_expr(time_arg):
    """'day'/'hour'/lainnya -> pola `date` shell utk filter baris log per satuan waktu (dipakai ImapLogs & SASLLogs)."""
    if time_arg == 'day':
        return 'date +%b" "%e'
    if time_arg == 'hour':
        return 'date +%b" "%e" "%H:'
    return 'date +%b" "%e" "%H:%M'


class ImapLogs(Resource):
    method_decorators = [require_token]

    def get(self):
        time_arg = request.args.get('time', 'minute')
        filter_expr = _time_filter_expr(time_arg)

        lines = _run_shell(
            "%s | grep \"`%s`\" | grep imap-login | grep -v Aborted | grep failed | grep -v rip=127.0.0.1" % (LOGD_CMD, filter_expr)
        )
        logdata = []
        for y in lines:
            try:
                logdata.append({
                    'notes': y.split(':')[4],
                    'email': y.split(',')[1].split('=')[1][1:-1],
                    'date': y.split('mail')[0],
                    'ip': y.split(',')[3].split('=')[1],
                })
            except IndexError:
                try:
                    logdata.append({
                        'notes': y.split(':')[4],
                        'email': '',
                        'date': y.split('mail')[0],
                        'ip': y.split(',')[0].split('=')[1],
                    })
                except IndexError:
                    logger.debug('Baris imap log tidak sesuai format, dilewati: %s', y)
                    continue
        logdata = sorted(logdata, key=lambda d: d['date'])
        return {'result': logdata}


class SASLLogs(Resource):
    method_decorators = [require_token]

    def get(self):
        time_arg = request.args.get('time', 'minute')
        filter_expr = _time_filter_expr(time_arg)

        lines = _run_shell(
            "%s | grep \"`%s`\" | grep -E \"SASL (LOGIN|PLAIN) authentication failed\"" % (LOGD_CMD, filter_expr)
        )
        logdata = []
        for y in lines:
            try:
                notes = y.split(':')[5]
                date = y.split('mail')[0]
                ip = y.split(':')[4].split('[')[1][0:-1]
                existing = next((d for d in logdata if d['ip'] == ip), None)
                if existing is None:
                    logdata.append({'notes': notes, 'date': date, 'ip': ip, 'count': 1})
                else:
                    existing['count'] += 1
            except IndexError:
                logger.debug('Baris SASL log tidak sesuai format, dilewati: %s', y)
                continue
        logdata = sorted(logdata, key=lambda d: d['date'])
        return {'result': logdata}


class Health(Resource):
    """GET /health -- TANPA token (endpoint cek-hidup doang, tidak bocorkan data apa pun) -- dipakai Django utk cek konektivitas sebelum panggil endpoint sungguhan."""

    def get(self):
        return {'status': 'ok'}


api.add_resource(Health, '/health')
api.add_resource(IPViaEmail, '/ipviaemail')
api.add_resource(MailQ, '/mailq')
api.add_resource(ImapLogs, '/imaplogs')
api.add_resource(SASLLogs, '/sasllogs')
api.add_resource(POSTFIX, '/postfix')


if __name__ == '__main__':
    print('Zentyal Mail API berjalan di port: %s (auth: %s, debug: %s)' % (
        port, 'AKTIF' if API_TOKEN else 'TIDAK AKTIF -- BAHAYA', DEBUG_MODE,
    ))
    app.run(debug=DEBUG_MODE, host='0.0.0.0', port=int(port))