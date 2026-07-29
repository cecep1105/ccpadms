# Zentyal Mail API (Python 2.7, Flask) — Setup & Keamanan

API internal kecil (Flask) yang jalan LANGSUNG di server mail Zentyal
(Python 2.7, sesuai batasan OS/library sistem lama) — dikonsumsi oleh
Django (`netmgmt/zentyal_mail_view.py`, server-to-server) untuk
menampilkan/mengelola mail queue, log, transport map, dst.

## File

- `zentyalmail_v2.py` — versi diperbaiki (lihat docstring di bagian atas
  filenya untuk daftar lengkap perbaikan keamanan).
- `zentyal_logd_v2.sh` — versi `zentyal_logd.sh` + shebang & validasi input.

## ⚠️ WAJIB dilakukan sebelum menjalankan di server produksi

### 1. Generate & set token API

```bash
python -c "import os, binascii; print(binascii.hexlify(os.urandom(32)))"
```

Simpan hasilnya sebagai environment variable `ZENTYAL_MAIL_API_TOKEN` —
**JANGAN** commit token ini ke git, JANGAN pakai token pendek/gampang
ditebak. Token ini WAJIB disertakan Django di header `X-API-Token` tiap
request.

### 2. Set environment variable lain

```bash
export ZENTYAL_MAIL_API_TOKEN="<hasil generate di atas>"
export ZENTYAL_MAIL_DB_PASSWORD="<password MySQL zentyal Anda>"
export ZENTYAL_MAIL_DB_HOST="127.0.0.1"      # opsional, ini defaultnya
export ZENTYAL_MAIL_DB_USER="zentyal"        # opsional, ini defaultnya
export ZENTYAL_MAIL_DB_NAME="zentyal"        # opsional, ini defaultnya
export ZENTYAL_MAIL_DEBUG="false"            # WAJIB false di produksi (Werkzeug debugger BERBAHAYA kalau true & listen 0.0.0.0)
```

Cara paling praktis: taruh baris `export` di atas dalam file (mis.
`/etc/zentyalmail.env`), lalu `source` file itu sebelum jalankan app,
atau pakai systemd unit dgn `EnvironmentFile=`.

### 3. Jalankan

```bash
python zentyalmail_v2.py 5100
```

(Sebaiknya jalankan lewat systemd/supervisor, bukan langsung di terminal,
supaya otomatis restart kalau crash — contoh unit systemd bisa diminta
kalau perlu.)

## Perbedaan dari `zentyalmail.py` (versi lama)

Lihat docstring lengkap di bagian atas `zentyalmail_v2.py` — ringkasan:

1. **Shell injection diperbaiki** — parameter dari request (qid, sender,
   email, domain) divalidasi ketat (regex whitelist) SEBELUM masuk ke
   command shell apa pun, plus di-quote sbg lapis kedua.
2. **SQL injection diperbaiki** — query MySQL pakai parameterized query,
   bukan string formatting.
3. **Autentikasi token** — header `X-API-Token` wajib cocok, endpoint
   `/health` dikecualikan (cek hidup doang, tidak expose data).
4. **Kredensial DB & konfigurasi lain** pindah ke environment variable,
   tidak ada lagi yang hardcode di source code.
5. **Debug mode default MATI** (`ZENTYAL_MAIL_DEBUG=false`).
6. Kode duplikat (`MailTransport`, identik dgn `IPViaEmail`) dihapus.
7. Logging terstruktur menggantikan `print`/`except: pass` yang menelan
   semua error diam-diam.

**Semua endpoint & bentuk response TETAP SAMA** — Django/frontend yang
konsumsi API ini tidak perlu berubah, cuma WAJIB kirim header
`X-API-Token` di setiap request sekarang.

## ✅ Sudah diuji

- Semua fungsi validasi (`_validate_qid`/`_validate_email`/
  `_validate_domain`) diuji dgn 6 skenario simulasi serangan shell
  injection (`; rm -rf`, backtick, `$()`, SQL-style quote, `&&` chaining,
  pipe-to-netcat) — **SEMUA berhasil diblokir**.
- `humanbytes()` diuji beberapa kasus termasuk input tidak valid (tidak
  crash).
- `zentyal_logd_v2.sh` diuji: default (hari ini) & argumen custom
  berfungsi, DAN diuji dgn 4 percobaan injection lewat argumen — semua
  ditolak dgn pesan jelas.
- Sintaks Python divalidasi bisa di-parse (AST) — TAPI **saya TIDAK
  bisa menjalankan Python 2.7 sungguhan** di sandbox saya (tidak
  tersedia) — logika sudah ditulis se-hati-hati mungkin utk kompatibel
  py2.7 (tidak ada f-string, tidak ada type hint, `from __future__
  import print_function`, dst), tapi **WAJIB dicoba jalan langsung di
  server Python 2.7 Anda** sebelum dipakai produksi.

## ⚠️ Belum bisa saya uji

- Eksekusi Python 2.7 sungguhan (sandbox saya tidak punya Python 2).
- Koneksi ke MySQL Zentyal & command `mailq`/`postsuper`/`postfix`
  sungguhan.
- Integrasi penuh dgn command `logd` di sistem Anda yang sebenarnya.

**Mohon coba jalankan langsung di server Zentyal Anda (idealnya di
environment TESTING dulu) sebelum menggantikan `zentyalmail.py` yang
lama di produksi.**
