# Resume: PUSH SDK Communication Protocol V2.0.1 (ZKTeco/ADMS)

> Referensi untuk refactor implementasi push protocol di app `iclock`.
> Sumber: `PUSH SDK Communication Protocol V2.0.1.doc` (28 halaman, Agustus 2011).
> Dibaca & diverifikasi lengkap dari PDF (tidak ada bagian yang terlewat).

---

## 1. Gambaran Umum

**PUSH SDK** adalah protokol komunikasi berbasis **HTTP** yang dikembangkan ZTE, dipakai mesin
fingerprint/attendance (device) untuk **aktif terhubung ke server** (bukan server yang menghubungi
device). Server yang didukung: **ADMS**, **Time8.0**, **Att2008**.

**Keunggulan** (sesuai dokumen):
1. Update data baru secara aktif (device yang inisiasi).
2. Mendukung resumable download.
3. Memudahkan pengembangan/perluasan fungsi.

**Keterbatasan**: hanya mendukung mode komunikasi TCP/IP (butuh jaringan LAN/WWW yang stabil).

**Level**: dokumen ini ditujukan untuk **WEB development engineers** (sisi server), bukan firmware.

### Prinsip dasar komunikasi
- Semua komunikasi lewat **HTTP GET/POST** biasa, device yang jadi HTTP client.
- Semua data **plain text**, KECUALI isi file (binary) — dipisah dengan line feed `\n`.
- Format umum: `FieldName=Value` — nama field beda-beda tergantung fungsi device.
- Server WAJIB kirim HTTP header standar (device pakai ini buat sinkron waktu & deteksi respons
  valid), contoh:
  ```
  HTTP/1.1 200 OK
  Content-Type: text/plain
  Date: Thu, 19 Feb 2008 15:52:10 GMT
  ```
- Format angka pakai konvensi C (`%d`, `%s`, `%x`/`%X`, `%3d`, `%08d`, dst — padding kiri default,
  field width negatif = padding kanan).

---

## 2. Alur Komunikasi (4 Tahap Inti)

```
1. Device baca konfigurasi server saat start
   GET /iclock/cdata?SN=xxxxxx&options=all&pushver=2.0.1&language=XX
   <- server balas: Stamp, OpStamp, TransFlag, dst (lihat §3)

2. Device polling perintah dari server (default tiap ~30 detik)
   GET /iclock/getrequest?SN=xxxxxx
   <- server balas 0+ baris "C:ID:CMD"

3. Device kirim hasil eksekusi perintah
   POST /iclock/devicecmd?SN=xxxxxx
   body: ID=iiii&Return=vvvv&CMD=ssss

4. Device upload data baru (attendance, user, foto) begitu terdeteksi ada
   POST /iclock/cdata?SN=xxxxxx&table=ATTLOG&Stamp=99999999
   <- server balas "OK" (atau device akan retry kalau gagal/timeout)
```

**Catatan penting utk desain server**: Tahap 1 dijalankan device **tiap kali start**, DAN
periodik sesuai `TransTimes`/`TransInterval`/`Realtime` (lihat §3) — server harus SELALU siap
menjawabnya, bukan cuma sekali di awal.

**Percepatan pengiriman command (Note 1 di dokumen)**: karena command dari server ke device BARU
diambil device saat POLLING (tahap 2, tidak instan), server BISA kirim **UDP ke port 4374** milik
device bersamaan saat command di-buffer, supaya device langsung ambil tanpa nunggu siklus polling
berikutnya. Ini HANYA berlaku kalau server bisa konek langsung ke device (device punya IP publik
di LAN/Internet yang sama).

---

## 3. Tahap 1 — Baca Konfigurasi Server

**Request**:
```
GET /iclock/cdata?SN=xxxxxx&options=all&pushver=2.0.1&language=XX
```
- `SN`: serial number device.
- `pushver`: versi protokol PUSH SDK yang dipakai device (firmware lama tidak kirim ini).
- `language`: ID bahasa firmware (`69`=English, `83`=Chinese, dst).

**Response** (contoh, tiap baris `Field=Value`):
```
GET OPTION FROM: 123456
Stamp=82983982
OpStamp=9238883
PhotoStamp=9238833
ErrorDelay=60
Delay=30
TransTimes=00:00;14:05
TransInterval=1
TransFlag=1111000000
Realtime=1
Encrypt=0
ServerVer=3.4.1 2010-06-07
TableNameStamp=XXXXXX
```

| Field | Arti |
|---|---|
| `GET OPTION FROM` | SN device yang bersangkutan (echo balik) |
| `Stamp` | Timestamp terakhir ATTLOG yang sudah diupload (firmware lama saja) |
| `OpStamp` | Timestamp terakhir OPERLOG yang sudah diupload (firmware lama saja) |
| `PhotoStamp` | Timestamp terakhir ATTPHOTO yang sudah diupload (firmware lama saja) |
| `ErrorDelay` | Detik jeda reconnect setelah koneksi GAGAL |
| `Delay` | Detik jeda antar koneksi normal |
| `TransTimes` | Jadwal cek transfer data (format menit 24-jam, maks 10 slot dipisah `;`) |
| `TransInterval` | Interval menit cek data baru |
| `TransFlag` | String ID/karakter array yang tentukan tipe data apa saja yg auto-upload (lihat §3.1) |
| `Realtime` | `1` = upload data baru instan; `0` = ikut jadwal `TransTimes`/`TransInterval` |
| `Encrypt` | Enkripsi data transfer (0 = tidak; kalau aktif pakai algoritma Grandstream-spesifik) |
| `ServerVer` | Versi & waktu server (opsional, firmware lama saja) |
| `TableNameStamp` | **1 baris per tabel** — timestamp terakhir yg sudah diupload PER TABEL (lihat §3.2), format `<TableName>Stamp=xxxx`, mis. `ATTLOGStamp=82983982` |

### 3.1 TransFlag — Tipe Data yang Di-auto-upload

Firmware lama pakai **character array ID** (mis. `"1111000000"`), firmware baru pakai **string ID**
dipisah tab (mis. `"TransData AttLog\tOpLog\tAttPhoto"`).

| String ID | Character Array ID | Keterangan |
|---|---|---|
| `AttLog` | `0` | Attendance record |
| `OpLog` | `1` | Operation log |
| `AttPhoto` | `2` | Attendance photo |
| `EnrollUser` | `4` | Enroll user baru |
| `ChgUser` | `6` | Ubah info user |
| `EnrollFP` | `3` | Enroll fingerprint baru |
| `ChgFP` | `7` | Ubah fingerprint |
| `FPImag` | `5` | Gambar fingerprint |

⚠️ **Penting**: untuk auto-upload user & fingerprint, **operation log auto-upload HARUS diaktifkan**
juga (`OpLog`/`1`).

### 3.2 Relasi TransTimes / TransInterval / Realtime

1. `Realtime=1` → update data LANGSUNG, tidak peduli 2 setting lain.
2. Kalau `Realtime=0` DAN `TransInterval > 0` → upload sesuai jadwal interval, tidak peduli `TransTimes`.
3. `TransTimes` cuma dipakai kalau 2 setting di atas TIDAK diset dengan nilai valid.

### 3.3 Nama Tabel Standar (`TableNameStamp`)

| Table Name | Fungsi | Auto-upload? |
|---|---|---|
| `ATTLOG` | Attendance record | Ya |
| `OPERLOG` | Operation log (termasuk data user/fingerprint yg diubah) | Ya |
| `ATTPHOTO` | Foto attendance | Ya |
| `SMS` | Pesan SMS | Tidak |
| `USER_SMS` | Daftar user penerima SMS individual | Tidak |
| `USERINFO` | Info user | Tidak |
| `FINGERTMP` | Template fingerprint | Tidak |

---

## 4. Tahap 4 — Upload Data dari Device

### 4.1 Upload Attendance Record (ATTLOG)

```
POST /iclock/cdata?SN=xxxxxx&table=ATTLOG&Stamp=99999999
982 2008-02-25 12:08:21 1 0
982 2008-02-25 18:01:09 1 0
```
Field per baris (dipisah **tab**, beberapa device tidak kirim 3 field terakhir):

| Field | Arti |
|---|---|
| PIN | Nomor absensi user |
| TIME | Waktu absen |
| STATUS | Status attendance (tabel di bawah) |
| VERIFY | Mode verifikasi (tabel di bawah) |
| WORKCODE | Kode kerja |
| RESERVED1 | Cadangan |
| RESERVED2 | Cadangan |

**Verify (mode verifikasi)**: `0`=Password, `1`=Fingerprint, `2`=Card, `9`=Others

**Status (status attendance)**: `0`=Clock in, `1`=Clock out, `2`=Out, `3`=Return from out,
`4`=Clock in overtime, `5`=Clock out overtime, `8`=Meal start, `9`=Meal end

Server balas `OK` — kalau device dapat error (404/500) atau timeout, **device akan kirim ulang data
yang sama**.

### 4.2 Upload User Info & System Log (OPERLOG)

```
POST /iclock/cdata?SN=xxxxxx&table=OPERLOG&Stamp=99999999
USER PIN=982 Name=Richard Passwd=9822 Card=[09E4812202] Grp=1 TZ=

POST /iclock/cdata?SN=xxxxxx&table=OPERLOG&Stamp=99999999
FP PIN=982 FID=1 Valid=1 TMP=ocoRgZPRN8EwJNQxQTY......
```

Tiap record diawali **start tag**:

| Start Tag | Isi | Field |
|---|---|---|
| `USER` | Info dasar user | `PIN`, `Name`, `Passwd`, `Card=[hex]`, `Grp`, `TZ` |
| `FP` | Template fingerprint | `PIN`, `FID` (nomor jari), `Valid`, `TMP` (base64) |
| `OPLOG` | Log operasi admin | Operation code, Admin ID, Time, Object 1-4 (lihat §4.2.1) |

Format Card: `[...]` isi hex ID card lengkap ATAU angka sama seperti yang tampil di layar saat
gesek kartu.

#### 4.2.1 Kode Operasi (OPLOG) — 32 kode

| Kode | Operasi | Parameter (Object 1-4) |
|---|---|---|
| 0 | Power on | - |
| 1 | Power off | - |
| 2 | Verifikasi gagal | Obj1 = PIN (kalau mode 1:1) |
| 3 | Alarm terjadi | Obj1 = sebab (lihat kode di bawah) |
| 4 | Masuk menu | - |
| 5 | Ubah konfigurasi | Obj1=item, Obj2=nilai baru |
| 6 | Enroll fingerprint | Obj1=userID, Obj2=FP SN, Obj3=ukuran template |
| 7 | Enroll password | - |
| 8 | Enroll kartu HID | - |
| 9 | Hapus user | Obj1=userID |
| 10 | Hapus fingerprint | Obj1=userID |
| 11 | Hapus password | Obj1=userID |
| 12 | Hapus kartu RF | Obj1=userID |
| 13 | Purge data | - |
| 14 | Buat kartu MF | - |
| 15 | Enroll kartu MF | - |
| 16 | Register kartu MF | - |
| 17 | Hapus registrasi kartu MF | - |
| 18 | Bersihkan isi kartu MF | - |
| 19 | Pindah data registrasi ke kartu | - |
| 20 | Copy data kartu ke mesin | - |
| 21 | Set waktu | - |
| 22 | Factory setting | - |
| 23 | Hapus record entry/exit | - |
| 24 | Bersihkan privilege admin | - |
| 25 | Ubah setting grup access control | - |
| 26 | Ubah setting akses control user | - |
| 27 | Ubah time segment access control | - |
| 28 | Ubah kombinasi unlock | - |
| 29 | Unlocking | - |
| 30 | Enroll user | - |
| 31 | Ubah atribut fingerprint | - |
| 32 | Duress alarm | - |

**Kode sebab alarm (Operation Code 3)**: `50`=Door Close Detected, `51`=Door Open Detected,
`55`=Machine Been Broken, `53`=Out Door Button, `54`=Door Broken Accidentally,
`58`=Try Invalid Verification, `65535`=Alarm Cancelled

### 4.3 Upload Foto Attendance (ATTPHOTO)

```
POST /iclock/cdata?SN=xxxxxx&table=ATTPHOTO&Stamp=99999999
PIN=iid
SN=xxxxxx
size=ssss
CMD=type\0<BINARY IMAGE DATA .jpg>
```
- `PIN` format `DATETIME-U` (verifikasi sukses, U=PIN user) atau `DATETIME` saja (verifikasi gagal),
  `DATETIME` = `YYYYMMDDHHNNSS`.
- `CMD=uploadphoto` (via background) atau `CMD=realupload` (realtime).
- `\0` = C string terminator sebelum data biner JPG mulai.

---

## 5. Tahap 2 & 3 — Command dari Server ke Device

### 5.1 Polling Command

```
GET /iclock/getrequest?SN=xxxxxx
→ (kalau device baru pertama kali / ada data baru)
GET /iclock/getrequest?SN=xxxx&INFO=<versi HW>,<jml user>,<jml fingerprint>,<jml attlog>,<IP device>
```

Server balas (maks 200 command / 40KB per respons):
```
C:ID1:CMD1
C:ID2:CMD2
```

### 5.2 Kirim Hasil Eksekusi

```
POST /iclock/devicecmd?SN=xxxxxx
ID=iiii&Return=vvvv&CMD=ssss
```
`Return=0` → sukses, `Return=-1` → gagal (nilai lain tergantung command spesifik).

### 5.3 Daftar Command (Server → Device)

| # | Command | Format | Fungsi |
|---|---|---|---|
| 1 | Shell | `SHELL CMD_String` | Eksekusi command sistem di device |
| 2 | Check | `CHECK` | Suruh device cek & upload data baru sekarang |
| 3 | Clear | `CLEAR LOG` / `CLEAR DATA` / `CLEAR PHOTO` | Hapus log/semua data/foto |
| 4 | Info | `INFO` | Minta device kirim info (jumlah user/fp/log, versi FW, dst) |
| 5 | Set Option | `SET OPTION ITEM=VALUE` | Ubah 1 parameter konfigurasi device (lihat §5.4) |
| 6 | Reboot | `REBOOT` | **HARUS jadi command TERAKHIR** dalam 1 batch (command setelahnya diabaikan) |
| 7 | Data | `DATA <SUBCMD>` | Tambah/ubah/hapus/query data (lihat §5.5) |
| 8 | Reload Options | `RELOAD OPTIONS` | Terapkan perubahan config yang belum aktif |
| 9 | Enroll FP | `ENROLL_FP PIN=%d\tFID=%d\tRETRY=%d\tOVERWRITE=%d` | Mulai proses enroll fingerprint di device |
| 10 | Log | `LOG` | Cek & upload data baru instan |
| 11 | Unlock | `AC_UNLOCK` | Keluarkan sinyal unlock (access control) |
| 12 | Cancel Alarm | `AC_UNALARM` | Batalkan sinyal alarm |
| 13 | Get File | `GetFile FilePath` | Minta device kirim 1 file sistemnya ke server |
| 14 | Put File | `PutFile URL FilePath` | Suruh device download file dari server (firmware upgrade dsb, `.tgz` auto-extract) |

### 5.4 SET OPTION — Daftar Item Konfigurasi (lengkap, ~50 item)

Item utama: `IPAddress`, `NetMask`, `GATEIPAddress`, `VOLUME`, `MAC`, `CardKey`, `DeviceID`,
`LockOn`, `AlarmAttLog`, `AlarmReRec`, `RS232BaudRate`, `AutoPowerOff/On/Suspend`,
`AutoAlarm1`~`AutoAlarm50`, `IdlePower`, `IdleMinute`, `RS232On`, `RS485On`, `UnlockPerson`,
`OnlyPINCard`, `HiSpeedNet`, `Must1To1`, `ODD`, `DUHK`/`DU11`/`DU1N`/`DUPWD`/`DUAD` (duress alarm),
`LockPWRButton`, `SUN`, `I1NFrom`/`I1NTo`, `I1H`/`I1G`, `KeyPadBeep`, `WorkCode`, `AAVOLUME`, `DHCP`,
`EnableProxyServer`/`ProxyServerIP`/`ProxyServerPort`, `PrinterOn`, `DefaultGroup`, `GroupFpLimit`,
`WIFI`/`wifidhcp`, `AmPmFormatFunOn`, `AntiPassbackOn`, `MasterSlaveOn`, `ImeFunOn`, `WebServerIP`/
`WebServerPort`, `ApiPort`, `DelRecord`.

> Catatan: sebagian item cuma didukung device tertentu (mis. `AntiPassbackOn` cuma di device access
> control, `WIFI` cuma di device dgn modul WiFi bawaan).

### 5.5 DATA — Subcommand (paling kompleks, dipakai sinkron data 2 arah)

Format umum: `DATA <SUBCMD>` dengan subcommand:

| Subcommand | Fungsi |
|---|---|
| `USER tablename value` | Tambah/ubah data di tabel |
| `DEL_USER tablename key` | Hapus data by key |
| `QUERY tablename key` | Query data by key |

**1) Tambah/ubah user**:
```
DATA USER PIN=%d\tName=%s\tPri=%d\tPasswd=%s\tCard=[%02x%02x%02x%02x%02x]\tGrp=%d\tTZ=%d
```
Cuma `PIN` wajib. `Pri`: `1`=Admin, `0`=User biasa.
Return: `0`=sukses, `-1`=parameter error, `-3`=access error.

**2) Tambah/ubah fingerprint**:
```
DATA FP PIN=%d\tFID=%d\tSize=%d\tValid=%d\tTMP=%s
```
Return: `0`=sukses, `-1`=param error, `-3`=access error, `-9`=ukuran template tidak cocok,
`-10`=PIN belum terdaftar (harus `DATA USER` dulu), `-11`=format template invalid,
`-12`=template invalid.

**3) Hapus user**: `DATA DEL_USER PIN=%d` — return sama dgn di atas (0/-1/-3).

**4) Hapus fingerprint**: `DATA DEL_FP PIN=%d\tFID=%d`

**5) Query info user**: `QUERY USERINFO PIN=%d` (kosongkan PIN = semua user)

**6) Query template fingerprint**: `QUERY FINGERTMP PIN=%d\tFingerID=%d`

**7) Download foto user ke device**: `UPDATE USERPIC PIN=%d\tPIN2=%d PICFILE=%s`

**8) Hapus foto user**: `DELETE USERPIC PIN=%d`

**9) Query attendance record rentang waktu**: `QUERYATTLOG StartTime=%s\tEndTime=%s`

**10) Query foto attendance rentang waktu**: `QUERY ATTPHOTO StartTime=%s\tEndTime=%s`

**11) Tambah/ubah time zone**: `UPDATE TIMEZONE TZID=%d\tITIME=%s\tRESERVE=%s`

**12) Hapus time zone**: `DELETL TIMEZONE TZID=%d` *(typo di dokumen asli: "DELETL")*

**13) Tambah/ubah kombinasi unlock**: `UPDATE GLOCK GLID=%d\tGROUPIDS=%s\tMEMBERCOUNT=%d\tRESERVE=%s`

**14) Hapus kombinasi unlock**: `DELETE GLOCK GLID=%d`

**15) Kirim SMS**: `UPDATE SMS MSG=%s\tTAG=%d\tUID=%d\tMIN=%d\tStartTime=%s`
(`TAG`: `253`=notifikasi, `254`=SMS user personal) + `UPDATE USER_SMS PIN=%d\tUID=%d`

---

## 6. Peta ke Model `iclock` yang Sudah Ada

| Konsep Protokol | Model Django Existing | Catatan |
|---|---|---|
| Device (SN, Alias, IP, dst) | `iclock.models.iclock` (Active Device) | Sudah ada |
| Device belum aktif | `iclock.models.RegisteredDevice` | Sudah ada |
| `USER PIN=...` (OPERLOG) | `iclock.models.employee` | PIN perlu **zero-pad 9 digit** (`normalize_pin`, sudah ada) |
| `FP PIN=...\tFID=...\tTMP=...` | `iclock.models.fptemp` | Template base64, field `FingerID`/`Valid` sudah ada |
| ATTLOG (PIN/TIME/STATUS/VERIFY) | `iclock.models.transaction` | Field `State`/`Verify` — ingat kasus `'I'`/`'O'` vs numeric yang pernah jadi bug |
| `OPLOG` (operation code) | `iclock.models.oplog` | Field `OP`, `Object`, `Param1-3` sudah ada |
| Command dari server (`C:ID:CMD`) & hasil eksekusi | `iclock.models.devcmds` | Field `CmdContent`, `CmdReturn`, dst sudah ada |
| Device log umum | `iclock.models.devlog` | Sudah ada |
| Live update ke browser | `iclock.ws_utils.wsinfo()` | Sudah ada, JANGAN diubah jadi nulis DB (sesuai desain lama) |
| Kontrol device 1-arah (reboot, set param, dst) | `iclock.zk_client` (pyzk) | **BEDA JALUR** — ini native ZKTeco binary protocol via pyzk, BUKAN PUSH SDK (HTTP) ini. Push SDK murni device→server via HTTP GET/POST |

⚠️ **Penting dibedakan**: `iclock/zk_client.py` yang sudah ada (dipakai reboot/sync time/transfer
finger dsb) itu protokol **native ZKTeco binary (lewat pyzk)**, koneksi **server→device**. PUSH SDK
yang mau di-refactor ini protokol **HTTP, device→server** — dua jalur komunikasi yang SEPENUHNYA
BERBEDA meski sama-sama "komunikasi dgn device fisik". Refactor ini akan jadi endpoint HTTP BARU
(`/iclock/cdata`, `/iclock/getrequest`, `/iclock/devicecmd`) yang MENERIMA request dari device,
bukan modifikasi ke `zk_client.py`.

---

## 7. Hal yang Perlu Diputuskan Sebelum Mulai Implementasi

1. **DB write policy** — sejauh ini prinsip "Django cuma observasi, proses push terpisah yang tulis
   DB" (lihat memori/README project). Refactor ini KEMUNGKINAN BESAR mengubah prinsip itu — apakah
   endpoint push protokol yang baru ini akan LANGSUNG menulis ke `transaction`/`employee`/`fptemp`
   dst, atau tetap ada pemisahan?
2. **Multi-device concurrency** — banyak device polling `/getrequest` & upload `/cdata` bersamaan;
   perlu pertimbangan locking/transaction di level DB (terutama utk `Stamp` per tabel per device).
3. **UDP notification (port 4374)** — apakah mau diimplementasikan (percepatan command) atau cukup
   andalkan polling biasa?
4. **Encryption** — dokumen sebut `Encrypt=0` default, algoritma custom kalau aktif. Kemungkinan
   besar tetap `0` kecuali ada kebutuhan spesifik.
5. **Resumable download** (utk `PutFile`, firmware upgrade) — perlu ditangani di endpoint file serving.
6. **Kompatibilitas versi firmware lama vs baru** — TransFlag character-array vs string-ID,
   `Stamp`/`OpStamp`/`PhotoStamp` legacy vs `TableNameStamp` per-tabel.
7. **Load ke Celery?** — proses upload data (terutama ATTPHOTO biner, atau ATTLOG volume besar) bisa
   dipertimbangkan lempar ke Celery worker (pola yang sudah dipakai di `mattendance`), supaya tidak
   membebani proses HTTP utama saat banyak device upload bersamaan.

---

