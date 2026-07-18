# Django 5 Fullstack Backend — LDAP + Local Auth, MySQL, Dashboard Custom, API untuk Nuxt

Scaffold awal backend Django 5 dengan:

- **Autentikasi ganda**: LDAP diprioritaskan, fallback ke akun lokal.
- **Database MySQL** (via PyMySQL, gampang setup, bisa ganti ke `mysqlclient`).
- **Dashboard custom** (bukan Django admin bawaan) — beda tampilan untuk admin vs user biasa.
- **REST API + JWT** siap dikonsumsi frontend **Nuxt**, semua logic dari service layer yang sama dengan dashboard.

---

## 1. Struktur Project

```
config/         # settings, root urls, wsgi/asgi
accounts/       # User model custom, LDAP client, service layer (BUSINESS LOGIC), auth backend
dashboard/      # UI custom server-rendered (admin & profile user)
api/            # REST API (JWT) untuk Nuxt — tipis, hanya menjembatani ke accounts.services
templates/      # Template dashboard (Tailwind CDN, tanpa build step)
static/         # CSS/JS pendukung dashboard
```

**Kunci arsitektur**: semua business logic (buat user, reset password, autentikasi, dll) ada di
`accounts/services.py`. Baik `dashboard/views.py` (HTML) maupun `api/views.py` (JSON) sama-sama
memanggil fungsi yang sama. Jadi kalau nanti mau tambah endpoint API baru, tinggal bungkus fungsi
service yang sudah ada — logic-nya tidak perlu ditulis ulang.

Sengaja **tidak** memasukkan `django.contrib.admin` ke `INSTALLED_APPS` — dashboard admin dibangun
custom di app `dashboard/`.

---

## 2. Alur Autentikasi (LDAP prioritas, Local fallback)

Diimplementasikan di `accounts/services.py::authenticate_user()`:

```
1. Cek LDAP dulu (search user by username)
   │
   ├── Koneksi LDAP SUKSES
   │     ├── Username DITEMUKAN di LDAP
   │     │     ├── Password BENAR (bind sukses)
   │     │     │     → sinkron/buat user lokal (auth_source=ldap), LOGIN SUKSES
   │     │     └── Password SALAH
   │     │           → error "invalid_credentials"
   │     └── Username TIDAK DITEMUKAN di LDAP
   │           → error "user_not_found" ("User belum ada")
   │
   └── Koneksi LDAP ERROR (server down / timeout / dll)
         → fallback: cek user LOCAL
               ├── User lokal ADA & password cocok → LOGIN SUKSES (pakai akun lokal)
               ├── User lokal ADA, password salah  → error "invalid_credentials"
               └── User lokal TIDAK ADA             → error "no_local_fallback"
```

Ini persis sesuai spesifikasi:
- Login pertama cek LDAP.
- User ada di LDAP tapi belum ada lokal → otomatis dibuatkan user lokal.
- User tidak ada di LDAP (koneksi LDAP sukses) → error "user belum ada".
- Koneksi LDAP error & user lokal ada → pakai user lokal.

File terkait:
- `accounts/ldap_client.py` — wrapper `ldap3`, membedakan **connection error** vs **password salah**.
- `accounts/services.py` — orkestrasi alur di atas + fungsi manajemen user.
- `accounts/backends.py` — Django authentication backend (dipakai `django.contrib.auth.login()`).
- `accounts/exceptions.py` — error terstruktur (code + message) dipakai bareng oleh dashboard & API.

Semua 6 skenario (LDAP ok+ada+benar, LDAP ok+ada+salah, LDAP ok+tidak ada, LDAP down+lokal ada+benar,
LDAP down+lokal ada+salah, LDAP down+lokal tidak ada) sudah diuji otomatis dan lolos.

---

## 3. Setup

### 3.1. Install dependencies

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

> Default driver MySQL adalah **PyMySQL** (pure Python, tidak perlu compile). Untuk produksi dengan
> performa lebih baik, install `mysqlclient` (butuh `libmysqlclient-dev` di OS), lalu hapus 2 baris
> `pymysql.install_as_MySQLdb()` di `config/__init__.py`.

### 3.2. Siapkan `.env`

```bash
cp .env.example .env
```

Edit `.env`: isi kredensial MySQL & LDAP sesuai lingkungan Anda. Field LDAP penting:

| Variable | Keterangan |
|---|---|
| `AUTH_LDAP_SERVER_URI` | `ldap://host:389` atau `ldaps://host:636` |
| `AUTH_LDAP_BIND_DN` / `AUTH_LDAP_BIND_PASSWORD` | Service account untuk search user |
| `AUTH_LDAP_BASE_DN` | Base DN pencarian, mis. `ou=users,dc=example,dc=com` |
| `AUTH_LDAP_USER_SEARCH_FILTER` | Filter, mis. `(uid={username})` atau `(sAMAccountName={username})` untuk AD |
| `AUTH_LDAP_ATTR_EMAIL/FIRST_NAME/LAST_NAME` | Mapping atribut LDAP → field User lokal |

### 3.2.1. Khusus Active Directory

AD punya beberapa perbedaan dari LDAP generik/OpenLDAP yang sering bikin login gagal dengan "User belum ada":

- **Search filter**: AD **tidak punya** atribut `uid`. Pakai `AUTH_LDAP_USER_SEARCH_FILTER=(sAMAccountName={username})`.
- **Base DN**: harus mencakup OU tempat user berada, mis. `DC=corp,DC=local` (root domain) atau lebih spesifik `OU=Karyawan,DC=corp,DC=local`.
- **Bind DN service account**: bisa berupa DN penuh (`CN=Service Account,OU=...,DC=corp,DC=local`) atau format UPN (`svc_ldap@corp.local`). Format `DOMAIN\user` (NTLM) **tidak didukung** oleh simple bind yang dipakai di sini.

**Kalau login LDAP gagal terus**, pakai tool diagnostik yang sudah disiapkan — ini akan menunjukkan persis di
step mana masalahnya (koneksi, bind service account, atau search filter/base DN):

```bash
python manage.py ldap_debug username_yang_dicoba
# atau sekalian tes passwordnya juga:
python manage.py ldap_debug username_yang_dicoba --password "passwordnya"
```

Command ini akan mencetak: konfigurasi yang dipakai, hasil bind service account, hasil search dengan filter
yang dikonfigurasi, dan kalau nol hasil — otomatis mencari beberapa contoh user asli di base DN tersebut
supaya Anda bisa bandingkan atribut apa yang seharusnya dipakai.

### 3.3. Buat database MySQL

```sql
CREATE DATABASE nuxt_backend CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

### 3.4. Migrasi & superuser

```bash
python manage.py makemigrations
python manage.py migrate
python manage.py createsuperuser   # akun local pertama, is_staff & is_superuser otomatis True
```

### 3.5. Jalankan

```bash
python manage.py runserver
```

- Dashboard: `http://127.0.0.1:8000/` (redirect ke `/accounts/login/` kalau belum login)
- API base: `http://127.0.0.1:8000/api/v1/`

---

## 4. Dashboard (server-rendered, custom UI)

| URL | Akses | Fungsi |
|---|---|---|
| `/accounts/login/` | publik | Login (LDAP → local fallback) |
| `/` | login | Redirect otomatis sesuai role |
| `/admin/` | admin | Ringkasan / statistik user |
| `/admin/users/` | admin | List + search + pagination user |
| `/admin/users/create/` | admin | Buat user **lokal** baru |
| `/admin/users/<id>/edit/` | admin | Edit data user |
| `/admin/users/<id>/delete/` | **super admin** | Hapus user permanen |
| `/admin/users/<id>/reset-password/` | admin | Reset password (user lokal saja) |
| `/admin/users/<id>/toggle-active/` | admin | Aktif/nonaktifkan user |
| `/admin/users/<id>/set-staff/` | **super admin** | Jadikan/cabut hak admin |
| `/profile/` | semua user login | Update profil sendiri |
| `/profile/change-password/` | semua user login | Ganti password (khusus akun lokal) |

Catatan aturan bisnis yang sudah diterapkan:
- User **LDAP** tidak bisa reset/ganti password dari aplikasi ini (dikelola server LDAP).
- Hanya **super admin** yang boleh menghapus user atau mengubah role admin — mencegah admin biasa
  saling menghapus/mempromosikan.
- User tidak bisa menghapus/menonaktifkan/mengubah role akun sendiri.

---

## 5. REST API untuk Nuxt Frontend

Base URL: `/api/v1/`. Autentikasi pakai **JWT** (header `Authorization: Bearer <access_token>`).

### Auth
| Method | Endpoint | Body | Keterangan |
|---|---|---|---|
| POST | `/auth/login/` | `{username, password}` | Sama persis alur LDAP→local di atas. Return `{access, refresh, user}` |
| POST | `/auth/refresh/` | `{refresh}` | Refresh access token |
| POST | `/auth/logout/` | `{refresh}` | Blacklist refresh token |

Contoh response error login (status HTTP disesuaikan per kasus):
```json
// LDAP ok, user tidak ditemukan -> 404
{"code": "user_not_found", "message": "User belum ada"}

// password salah -> 401
{"code": "invalid_credentials", "message": "Username atau password salah"}

// LDAP down & tidak ada user lokal -> 503
{"code": "no_local_fallback", "message": "Koneksi LDAP sedang bermasalah dan user lokal tidak ditemukan. Hubungi administrator."}
```

### Profil (semua user login)
| Method | Endpoint | Keterangan |
|---|---|---|
| GET | `/me/` | Data profil sendiri |
| PATCH | `/me/` | Update profil (`email`, `first_name`, `last_name`, `phone_number`, `department`, `title`) |
| POST | `/me/change-password/` | `{old_password, new_password}` (khusus akun lokal) |

### Manajemen User (admin only, `is_staff`)
| Method | Endpoint | Keterangan |
|---|---|---|
| GET | `/users/?q=&page=&page_size=` | List + search + pagination |
| POST | `/users/` | Buat user lokal baru |
| GET | `/users/<id>/` | Detail user |
| PATCH | `/users/<id>/` | Update data user |
| DELETE | `/users/<id>/` | Hapus (super admin only) |
| POST | `/users/<id>/reset-password/` | `{new_password?}` — kosongkan utk generate otomatis |
| POST | `/users/<id>/toggle-active/` | Aktif/nonaktifkan |
| POST | `/users/<id>/set-staff/` | `{is_staff}` (super admin only) |

### Contoh pemakaian dari Nuxt (composable sederhana)

```ts
// composables/useApi.ts
const API_BASE = 'http://localhost:8000/api/v1'

async function login(username: string, password: string) {
  const res = await fetch(`${API_BASE}/auth/login/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  })
  const data = await res.json()
  if (!res.ok) throw new Error(data.message) // "User belum ada", dll
  // simpan data.access & data.refresh (mis. di pinia store / cookie httpOnly via server route)
  return data
}

async function apiFetch(path: string, token: string, options: RequestInit = {}) {
  return fetch(`${API_BASE}${path}`, {
    ...options,
    headers: { ...options.headers, Authorization: `Bearer ${token}` },
  })
}
```

Jangan lupa set `CORS_ALLOWED_ORIGINS` di `.env` sesuai origin Nuxt (default `http://localhost:3000`).

---

## 6. Menambah Endpoint API Baru

Karena logic ada di service layer, menambah endpoint baru cukup 3 langkah:

1. (Kalau perlu) tambah fungsi baru di `accounts/services.py`.
2. Buat serializer di `api/serializers.py`.
3. Buat view tipis di `api/views.py` yang memanggil service tsb, tangkap `ServiceError`, dan daftarkan
   di `api/urls.py`.

---

## 7. App `iclock` (Integrasi Mesin Fingerprint/Absensi)

App tambahan untuk manajemen device & user mesin fingerprint (ZKTeco-style), dengan 3 submenu di
sidebar dashboard (grup "Iclock Management"):

| Submenu | Model | Tabel DB | Keterangan |
|---|---|---|---|
| Department | `iclock.models.department` | `departments` | Pool/departemen, referensi (FK) untuk device & employee |
| Active Device | `iclock.models.iclock` | `iclock` | Mesin yang sedang aktif/terhubung |
| Registered Device | `iclock.models.RegisteredDevice` | `iclock_registereddevice` | Master daftar device yang diizinkan |
| Device User | `iclock.models.employee` | `userinfo` | Karyawan/user yang terdaftar di mesin |
| Fingerprint Template | `iclock.models.fptemp` | `template` | Data template sidik jari per karyawan |
| Transaction | `iclock.models.transaction` | `checkinout` | Log absensi (check-in/check-out) |
| Operation Log | `iclock.models.oplog` | `iclock_oplog` | Log operasi admin langsung di mesin |
| Device Log | `iclock.models.devlog` | `devlog` | Ringkasan data yang diupload device ke server |
| Device Command | `iclock.models.devcmds` | `devcmds` | Antrean command yang dikirim ke device |

> **Perhatian soal hapus Department:** `RegisteredDevice.DeptID` dan `employee.DeptID` pakai
> `on_delete=models.CASCADE` (mengikuti file model asli Anda) — artinya kalau sebuah department
> dihapus, semua Registered Device & Device User yang memakai pool itu **ikut terhapus**, bukan cuma
> kehilangan referensi. `iclock.DeptID` (Active Device) pakai `SET_NULL` jadi lebih aman (device-nya
> tetap ada, cuma pool-nya jadi kosong). Tombol hapus di halaman Department sudah ada dialog konfirmasi
> yang menjelaskan ini, tapi tetap hati-hati.

### Auto-aktivasi: Registered Device -> Active Device

Alur bisnis: saat mesin fingerprint baru pertama kali konek ke sistem, ia masuk ke tabel
`registereddevice` (Registered Device) dengan Pool ID = 0 (dianggap belum diaktifkan/diregister).

Sekarang, kalau admin **mengedit** sebuah Registered Device dan mengubah Pool ID dari **0** ke pool
lain (selain 0), sistem otomatis meng-copy record tersebut ke tabel `iclock` (Active Device) — **kalau
SN-nya belum ada di sana**. Logic ini ada di `iclock/services.py` (fungsi
`maybe_activate_after_pool_change` + `activate_device_to_iclock`), dipakai bersama oleh dashboard
(`iclock/views.py`) **dan** API (`iclock/api_views.py`) supaya tidak duplikasi logic.

Detail perilaku:
- Trigger hanya jalan kalau Pool ID **berubah dari 0 ke non-0** dalam satu submit edit (bukan
  sekadar "Pool ID saat ini non-0").
- Kalau SN tersebut **sudah ada** di Active Device, tidak ada apa-apa yang terjadi (tidak duplikat).
- Field yang di-copy: `SN`, `Alias` (dari `DeviceName`, fallback ke `SN` kalau kosong), `DeptID`,
  `IPAddress`, `MAC`. Field lain di Active Device (State, TZAdj, dll) pakai default model.
- Proses update RegisteredDevice + create Active Device dibungkus `transaction.atomic()` supaya
  konsisten (kalau salah satu gagal, keduanya di-rollback).
- Dashboard: muncul flash message tambahan kalau aktivasi terjadi. API: response `PATCH`/`PUT` ke
  `/api/v1/iclock/registered-device/<id>/` menyertakan field `activated_to_active_device` (`true`/`false`).

## 8. REST API untuk Iclock Management (Nuxt)

Semua 9 entitas di atas juga punya REST API penuh (list/create/retrieve/update/delete), base URL
`/api/v1/iclock/`, auth JWT sama seperti API accounts (`Authorization: Bearer <access_token>`),
khusus staff (`IsStaffRole`, sama seperti akses dashboard).

| Endpoint | Model |
|---|---|
| `/api/v1/iclock/department/` | Department (Pool) |
| `/api/v1/iclock/active-device/` | Active Device |
| `/api/v1/iclock/registered-device/` | Registered Device |
| `/api/v1/iclock/device-user/` | Device User |
| `/api/v1/iclock/fingerprint-template/` | Fingerprint Template |
| `/api/v1/iclock/transaction/` | Transaction |
| `/api/v1/iclock/operation-log/` | Operation Log |
| `/api/v1/iclock/device-log/` | Device Log |
| `/api/v1/iclock/device-command/` | Device Command |

Setiap endpoint mendukung standar DRF `ModelViewSet` (via `DefaultRouter`), jadi otomatis punya:

| Method | URL | Aksi |
|---|---|---|
| GET | `/<endpoint>/` | List (paginated, default DRF `PageNumberPagination`) + `?q=` untuk search, `?page=` |
| POST | `/<endpoint>/` | Create |
| GET | `/<endpoint>/<id>/` | Detail |
| PUT / PATCH | `/<endpoint>/<id>/` | Update / partial update |
| DELETE | `/<endpoint>/<id>/` | Delete |

Catatan implementasi:
- **Search** (`?q=`) per endpoint: Department by nama pool; Active/Registered Device by SN/nama;
  Device User by PIN/nama; Fingerprint Template & Transaction by PIN/nama karyawan; Operation/Device
  Log/Command by SN device (+ isi command untuk Device Command).
- **Field read-only tambahan** untuk kenyamanan Nuxt (tidak perlu request terpisah ke endpoint lain):
  `DeptName` (Department/Active Device/Registered Device/Device User), `EmployeeName` (Fingerprint
  Template/Transaction), `StateDisplay`/`VerifyDisplay` (Transaction), `FingerIDDisplay` (Fingerprint
  Template), `OpName` (Operation Log), `Username` (Device Command).
- **Immutability primary key**: `DeptID` (Department) dan `SN` (Active Device) tidak bisa diubah lewat
  `PATCH`/`PUT` setelah dibuat (mengembalikan HTTP 400 kalau dicoba), sama seperti perilaku form
  dashboard.
- **Registered Device**: response `PATCH`/`PUT` menyertakan `activated_to_active_device` (lihat bagian
  auto-aktivasi di atas).
- **Device Command**: field `User` read-only, otomatis di-set dari user yang login (JWT), sama seperti
  dashboard.

Semua 8 punya CRUD lengkap (list dengan search+pagination, tambah, edit, hapus), diakses lewat
`/admin/iclock/<nama-entitas>/` (mis. `/admin/iclock/transaction/`, `/admin/iclock/device-command/`),
khusus admin, sama seperti Manajemen User.

Catatan khusus **Device Command**: field `User` (admin yang mengajukan command) otomatis di-set dari
`request.user` saat command dibuat lewat dashboard, tidak muncul sebagai field yang bisa dipilih manual
di form (mengikuti `editable=False` di model aslinya).

Catatan khusus **Operation Log**: kode operasi (`OP`) disimpan sebagai angka mentah dari device (bukan
Django `choices`, karena mapping-nya berasal dari dictionary `OPNAMES`, bukan tuple choices) — label
yang bisa dibaca manusia ditampilkan otomatis di kolom list lewat method `op_name()`.

**PENTING — `managed = False`:** semua model di app `iclock` (`iclock`, `RegisteredDevice`, `employee`,
`department`, `fptemp`, `transaction`, `oplog`, `devlog`, `devcmds`) di-set `managed = False` di `Meta`.
Artinya:
- Django **tidak** akan membuat/mengubah/menghapus struktur tabel ini lewat `makemigrations`/`migrate`.
- Tabelnya harus **sudah ada** di database MySQL Anda (nama tabel & kolom sudah disesuaikan persis
  dengan skema legacy: `iclock`, `registereddevice`, `userinfo`, `departments`).
- Ini disengaja karena tabel-tabel ini biasanya sudah dipakai proses lain (server komunikasi device
  fingerprint fisik) — supaya Django tidak tiba-tiba mengubah/menghapus skemanya.

Kalau Anda mulai dari database **kosong** (belum ada tabel-tabel ini sama sekali) dan mau Django yang
membuatnya dari nol, ubah `managed = False` jadi `managed = True` di `iclock/models.py` untuk
model yang bersangkutan, lalu:
```bash
python manage.py makemigrations iclock
python manage.py migrate
```

**Model `department`** dipakai sebagai referensi (FK "Pool") oleh ketiga model di atas, tapi belum
ada menu CRUD tersendiri (di luar scope permintaan). Kalau tabel `departments` masih kosong, isi
dulu minimal 1 baris (mis. lewat `python manage.py shell`) sebelum pakai dropdown Pool di form
Active Device / Registered Device / Device User — kalau kosong, dropdown-nya cuma akan tampil
opsi "kosongkan" (field ini optional, `null=True, blank=True`).

Model asli yang Anda upload berisi banyak field & logic tambahan (cache-based save/delete override,
permission actions seperti reboot/upgrade firmware, kolom telemetry seperti FWVersion/FlashSize, dll)
yang **sengaja tidak disertakan** di versi ini karena bergantung pada modul `.utils` dan custom
setting (`settings.UNIT`, `settings.DEVICEFUNCTION`) yang tidak ada di scaffold ini — kalau
disertakan apa adanya akan bikin `import` gagal. Field inti (SN, Alias, PIN, EName, dst) & nama
tabel/kolom tetap dipertahankan persis, jadi CRUD dasar tetap kompatibel dengan skema database yang
sama. Kalau butuh field/fitur tambahan dari model asli, tinggal tambahkan ke `iclock/models.py`,
`iclock/forms.py`, dan form template terkait mengikuti pola yang sudah ada.

## 9. Show Device User (Koneksi Langsung ke Device via pyzk)

Di tabel **Active Device**, tombol aksi sekarang berupa dropdown ("Aksi ▾") berisi: **Edit**,
**Show Device User**, dan **Hapus**.

**Show Device User** beda dari menu lain — ini **konek langsung ke device fisik** (bukan baca dari
database) lewat protokol native ZKTeco (port 4370) memakai library
[`pyzk`](https://github.com/fananimi/pyzk), dan menampilkan daftar user yang **benar-benar tersimpan
di memori device saat ini secara real-time**. Berguna untuk verifikasi/troubleshooting kalau data di
tabel Device User dicurigai belum sinkron dengan kondisi device sebenarnya.

Implementasi:
- `iclock/zk_client.py` — wrapper tipis di atas `pyzk`, dengan `DeviceConnectionError` khusus supaya
  kegagalan konek (device mati, salah IP, firewall, dll) ditampilkan sebagai pesan yang jelas ke user,
  bukan error 500.
- View `active_device_show_users` (`iclock/views.py`) — pakai IP Address yang tersimpan di kolom
  `IPAddress` pada Active Device, timeout 8 detik (supaya request dashboard tidak menggantung lama
  kalau device offline).
- Ditampilkan sebagai **halaman tersendiri** (bukan popup/modal) — `templates/iclock/active_device_show_users.html`
  — supaya lebih robust untuk operasi network yang bisa gagal/lambat (tidak ada JS/AJAX yang bisa hang).
- Port default 4370 (standar ZKTeco). Kalau device Anda pakai port lain, sesuaikan
  `ZK_DEFAULT_PORT` di `iclock/zk_client.py`.
- Dropdown aksi di tabel pakai `position: fixed` yang dihitung dari posisi tombol (bukan `absolute`),
  supaya tidak terpotong oleh `overflow-x-auto` pada wrapper tabel.

> **Catatan:** `pyzk` butuh device benar-benar reachable dari server (satu jaringan / VPN / port
> forwarding). Kalau server Django jalan di cloud sementara device fingerprint ada di jaringan lokal
> kantor tanpa akses langsung, fitur ini tidak akan bisa konek — itu bukan bug, tapi keterbatasan
> jaringan yang perlu diatur di infrastruktur (VPN site-to-site, dsb).

## 11. Employee (sebelumnya "Device User" di sidebar) — Pagination, Filter, Sort, & Action Dropdown

> **Rename:** menu sidebar yang tadinya "Device User" sekarang jadi **"Employee"** (URL, view, dan
> nama model tetap `device-user`/`device_user_*`/`employee` — cuma label yang berubah), supaya tidak
> rancu dengan fitur **Show Device User** di bagian 12 (yang benar-benar tentang user di device fisik,
> bukan tabel Employee di database kita).

Tabel **Employee** sekarang punya:

- **Filter terpisah**: `?pin=` (User ID/PIN) dan `?name=` (Nama) — dua input berbeda, kombinasi
  keduanya pakai logic AND (bukan satu search box gabungan seperti tabel lain).
- **Semua kolom bisa di-sort**: klik header (PIN, Nama, Pool, Device, Gender, Privilege, Mobile) untuk
  urutkan ascending/descending, ada indikator panah (▲/▼) di kolom yang lagi aktif di-sort. State
  filter & sort dipertahankan saat pindah halaman (pagination).
- **Dropdown "Aksi"** (bukan lagi tombol flat) berisi:
  - **Edit** — form CRUD biasa.
  - **Transfer Data Finger** — *dummy/placeholder* (belum diimplementasikan, sesuai permintaan —
    "menyusul kemudian"). Klik cuma menampilkan pesan info, tidak melakukan apa-apa.
  - **Set as Admin / Set as User** (toggle, labelnya berubah sesuai privilege saat ini) — mengubah
    `Privilege` antara 14 (Admin) dan 0 (User biasa) di database, **dan** sekalian sync ke device
    fisik lewat `pyzk` (kalau user ini terhubung ke sebuah Active Device dengan IP Address).
  - **Delete User** — hapus dari database, **dan** sekalian coba hapus dari device fisik lewat `pyzk`.

**Pola best-effort untuk aksi berbasis pyzk** (Set as Admin/User & Delete User):
1. Perubahan di **database selalu berhasil** duluan (source of truth utama untuk dashboard).
2. Sync ke device fisik bersifat **best-effort** — kalau employee ini tidak terhubung ke Active
   Device manapun (`SN` kosong) atau device-nya tidak punya IP Address, sync dilewati dengan pesan
   yang jelas ("device sync dilewati").
3. Kalau ada IP tapi device gagal dihubungi, perubahan **tetap tersimpan di database**, cuma pesannya
   menyebutkan sync ke device gagal beserta detail errornya.
4. Device dicari via `get_users()` lalu dicocokkan berdasarkan `user_id` (PIN), bukan berdasarkan
   `uid` internal device.

## 12. Show Device User: Kelola User Langsung di Device Tertentu

Di halaman **Show Device User** (dari dropdown Active Device), tabel user yang tampil (live dari
device via pyzk) sekarang **juga punya dropdown "Aksi"** yang sama: **Transfer Data Finger** (dummy),
**Set as Admin / Set as User**, dan **Delete User** — tapi kali ini beroperasi **langsung ke device
tersebut**, bukan lewat tabel Employee.

Beda arah sync dibanding bagian 11:
- Di sini, aksi **langsung menyasar device** (device SUDAH diketahui dari halaman yang sedang dibuka —
  tidak perlu employee.SN untuk tahu device mana).
- Kalau ternyata ada record **Employee** yang cocok (PIN + device yang sama), sekalian ikut disinkronkan
  di database (arah kebalikan dari bagian 11: device → Employee, bukan Employee → device). Kalau tidak
  ada yang cocok, ya sudah, cuma device-nya yang berubah — tidak dianggap error.
- Toggle privilege di sini **tidak perlu query ulang ke device** buat tahu privilege saat ini — nilainya
  sudah ada di layar (dikirim balik lewat hidden input `current_privilege` di form), supaya tidak ada
  round-trip device yang tidak perlu.

Tabel di halaman ini juga punya **filter** (`?pin=`, `?name=`), **sort semua kolom** (UID, User ID,
Nama, Privilege, Kartu), dan **pagination** — sama seperti tabel Employee. Bedanya, karena sumber
datanya list Python biasa dari pyzk (bukan QuerySet Django), filter/sort/pagination-nya diproses
manual di memori (list comprehension + `list.sort()` + `Paginator` langsung di atas list biasa —
`Paginator` Django memang mendukung ini, tidak harus QuerySet).

Implementasi ada di `iclock/views.py` (`active_device_show_users`, `active_device_user_toggle_privilege`,
`active_device_user_delete`, `active_device_user_transfer_finger`) dan
`templates/iclock/active_device_show_users.html`.

## 13. Komponen Pagination (First/Prev/Next/Last + Go to Page)

Semua halaman list yang punya pagination (Manajemen User, Department, Active Device, Registered
Device, Employee, Fingerprint Template, Transaction, Operation Log, Device Log, Device Command, dan
Show Device User) sekarang pakai komponen pagination yang sama: **First, Prev, halaman saat ini,
Next, Last**, plus kotak **"Ke halaman"** untuk loncat langsung ke nomor halaman tertentu — bukan lagi
menampilkan semua nomor halaman satu-satu (yang bisa kepanjangan kalau datanya banyak).

Implementasi:
- `templates/partials/pagination.html` — partial yang di-`{% include %}` di semua halaman list,
  jadi kalau nanti mau ubah tampilan pagination, cukup edit **satu file** ini.
- `dashboard/templatetags/pagination_extras.py` — template tag `{% url_replace %}` yang membangun
  query string berdasarkan `request.GET` saat ini, cuma mengganti/menambah key tertentu (dalam hal
  ini `page`). Ini yang bikin filter & sort tetap kepertahankan pas pindah halaman, tanpa perlu tiap
  view menyusun query string manual satu-satu.
- Tombol First/Prev otomatis "disabled" (jadi `<span>` abu-abu, bukan link) kalau sudah di halaman
  pertama; Next/Last otomatis disabled kalau sudah di halaman terakhir.
- Form "Ke halaman" submit lewat GET dengan semua filter lain dikirim sebagai hidden input, supaya
  tetap konsisten dengan filter/sort yang sedang aktif.

## 14. Transfer Data Finger (dari Show Device User)

Fitur "Transfer Data Finger" (sebelumnya dummy) sekarang **berfungsi sungguhan**, dipicu dari dropdown
Aksi di halaman **Show Device User**. Form-nya 3 kolom:

1. **User ID (PIN)** — textarea multiline, bisa isi lebih dari 1 PIN (satu per baris). Pre-filled
   dengan PIN dari baris yang diklik, tapi bisa ditambah manual.
2. **From Device / To Pool / Target Device** — 3 combo:
   - **From Device**: default device yang lagi dibuka, tapi bisa diganti ke device lain.
   - **To Pool**: pool/departemen tujuan.
   - **Target Device**: otomatis terisi (lewat AJAX) begitu **To Pool** dipilih, berisi device-device
     di pool tersebut. **Dibiarkan kosong = transfer ke SEMUA device di pool itu.**
3. **Status Transfer** — textarea read-only berisi log per-langkah hasil proses (siapa berhasil, siapa
   gagal, siapa dilewati, dan kenapa).

### Cara kerja teknis

Implementasi inti ada di `iclock/zk_client.py::transfer_fingerprints()`:
1. Konek ke **source device**, ambil semua user (`get_users()`) dan semua template fingerprint
   (`get_templates()` — satu kali panggil untuk SEMUA user, lebih efisien daripada query per-user
   per-jari).
2. Untuk tiap PIN yang diminta: cari user & template-nya dari data source di atas. Kalau PIN tidak
   ketemu di source atau tidak punya template tersimpan, di-skip dengan pesan jelas di log (bukan
   dianggap error fatal, proses lanjut ke PIN berikutnya).
3. Untuk tiap **target device** (satu device yang dipilih, atau semua device di pool kalau tidak
   dipilih): konek, cek apakah PIN sudah ada di device itu — kalau belum, dibuatkan dulu (`set_user`,
   uid di-generate otomatis oleh device), baru template-nya ditransfer (`save_user_template`).

### Batasan penting yang perlu Anda tahu

- **Kompatibilitas versi algoritma fingerprint**: `pyzk` cuma memindahkan byte template mentah, TIDAK
  ada konversi format. Kalau source & target device pakai versi algoritma fingerprint yang beda
  (device lama vs baru, atau merek/model beda generasi), template yang "berhasil" ditransfer secara
  teknis bisa saja tidak terbaca / tidak match saat user coba absen di device tujuan. Ini keterbatasan
  hardware/protokol ZKTeco, bukan sesuatu yang bisa diperbaiki di level kode.
- **Sinkron, bukan background job**: proses ini berjalan di dalam satu request Django (nunggu semua
  device selesai baru render hasil). Untuk PIN banyak x device banyak, ini bisa memakan waktu cukup
  lama dan berisiko kena timeout reverse proxy/web server production (umumnya 30-60 detik). Kalau
  skala pemakaiannya besar, pertimbangkan pindah ke background task (Celery + Redis, dsb) supaya
  prosesnya async dan progress-nya bisa di-polling, bukan blocking di satu request.
- Kolom "Status Transfer" saat ini berupa laporan **setelah proses selesai** (bukan live-streaming
  progress baris-per-baris) — konsekuensi dari sinkron di atas.

## 15. Rows per Page (Employee & Show Device User) & Fix Dropdown Aksi di Mobile

**Rows per Page** — selector "Baris/halaman" (10/15/25/50/100), auto-submit begitu diganti, ada di
**dua tempat**: tabel **Employee** dan halaman **Show Device User** (yang realtime dari pyzk). Nilai
divalidasi di server (`_resolve_page_size()` di `iclock/views.py`) — nilai aneh lewat URL otomatis
fallback ke default (15). Kepertahankan otomatis di link sort & pagination.

Form filter di kedua halaman juga sekarang menyertakan `sort`/`dir` sebagai hidden input, supaya klik
"Filter" tidak me-reset urutan sort yang sedang aktif.

**Fix dropdown "Aksi" tidak merespons di mobile — percobaan kedua.** Fix pertama (menunda listener
scroll/resize) ternyata belum menyelesaikan masalahnya. Kali ini pendekatannya diganti total: dropdown
sekarang pakai elemen **`<details>`/`<summary>` asli HTML**, bukan `<div>`/`<button>` + toggle class
lewat JS. Alasannya:

- Buka/tutup dropdown sekarang **100% ditangani browser secara native** — bukan lagi bergantung pada
  event `click` custom yang urutan/timing-nya bisa berbeda-beda antar browser mobile (inilah yang
  paling mungkin jadi biang kerok kenapa fix pertama belum berhasil: kemungkinan ada engine mobile
  tertentu yang tidak konsisten soal `stopPropagation()`/urutan event, di luar teori scroll/resize
  yang sudah dicoba diperbaiki sebelumnya).
- JS di `static/dashboard/js/app.js` sekarang HANYA dipakai untuk 3 hal tambahan (bukan untuk
  toggle itu sendiri): (1) reposisi dropdown jadi `position: fixed` berdasarkan posisi tombol saat
  event native `toggle` terjadi, supaya tidak kepotong `overflow-x-auto` di wrapper tabel; (2) menutup
  dropdown baris lain saat satu baris dibuka; (3) menutup semua dropdown saat klik di luar / tekan
  `Escape`.
- Diterapkan konsisten di ketiga tabel yang punya dropdown aksi: Active Device, Employee, dan Show
  Device User.

> Catatan jujur: karena sandbox pengembangan ini tidak punya akses ke browser mobile sungguhan, fix
> ini tetap berdasarkan analisis kode & pola bug yang umum terjadi (bukan hasil tes langsung di
> perangkat Anda). Pendekatan `<details>`/`<summary>` dipilih karena secara fundamental menghilangkan
> seluruh kelas masalah "custom JS toggle tidak reliable di mobile" — tapi kalau ternyata masih belum
> beres setelah dicoba, tolong kabari detail device/browser persis + apakah dropdown-nya sempat
> kelihatan sekilas atau benar-benar diam, supaya bisa digali lebih spesifik lagi.

## 16. Sort & Rows per Page untuk Active Device, Registered Device, Fingerprint Template

Menyusul Employee & Show Device User, sekarang **Active Device**, **Registered Device**, dan
**Fingerprint Template** juga punya header kolom yang bisa diklik untuk sort (dengan indikator ▲/▼)
dan selector "Baris/halaman" (10/15/25/50/100) — pola & validasi yang sama persis (`_resolve_page_size()`,
`_build_sort_url()`, komponen pagination First/Prev/Next/Last dari bagian 13).

| Tabel | Kolom yang bisa di-sort |
|---|---|
| Active Device | Serial Number, Alias, Pool, IP Address, Last Activity |
| Registered Device | Serial Number, Nama Device, Pool, IP Address, IP Router |
| Fingerprint Template | Karyawan (nama), Jari, Valid, Device, Refresh Time |
| Transaction | Karyawan (nama), Waktu, State, Verifikasi, Device |

Ini penting untuk tabel yang datanya bisa banyak (terutama Fingerprint Template & Active Device kalau
device-nya ratusan) — supaya tidak perlu load semua baris sekaligus tiap buka halaman.

## 17. Loading Spinner di Form Transfer Data Finger

Karena proses transfer bisa makan waktu (konek ke beberapa device fisik satu per satu), sekarang ada
**overlay loading dengan spinner berputar** yang muncul begitu tombol "Mulai Transfer" diklik — supaya
ada kesan jelas kalau proses sedang berjalan, bukan halaman yang macet/nge-hang.

Implementasi murni client-side di `templates/iclock/transfer_finger_form.html`: begitu form disubmit,
JS langsung menampilkan overlay + disable tombol submit (cegah klik dobel) SEBELUM request terkirim.
Karena form ini masih submit biasa (bukan AJAX), overlay-nya otomatis "nempel" sampai halaman hasil
selesai dimuat oleh browser — pas memberi kesan visual proses sedang berjalan tanpa perlu bikin
arsitektur async/polling yang lebih rumit. Animasi spinner-nya CSS murni (`@keyframes`), tidak
tambah dependency JS baru.

## 18. Backup Data Finger (Active Device)

Menu baru di dropdown Aksi **Active Device**: **"Backup Data Finger"** — konek langsung ke device
fisik, ambil user + template fingerprint yang tersimpan di device, lalu **add/modify (upsert)**
ke tabel **Fingerprint Template** (`fptemp`) di database kita.

**Filter PIN (regex, opsional)** — supaya tidak perlu proses SEMUA user tiap kali (device dengan
ribuan user bisa lama sekali kalau full backup), form-nya punya field filter PIN berbasis regex
(`re.match`, dicek dari awal string PIN):
- Contoh: `^8` (semua PIN diawali angka 8), `^88`, `^888`, atau pola regex custom lainnya.
- Regex tidak valid ditolak di server dengan pesan error yang jelas (`re.compile()` divalidasi di
  `clean_pin_pattern()` pada `BackupFingerForm`).
- **Kosongkan untuk full backup** (semua PIN) — tapi begitu tombol diklik dengan filter kosong, ada
  konfirmasi JS (`confirm()`) yang mengingatkan bahwa ini bisa lama, supaya tidak ke-trigger tanpa
  sadar.
- Log status menyertakan jumlah user yang dilewati karena tidak cocok filter, terpisah dari jumlah
  yang dilewati karena memang tidak punya fingerprint tersimpan.

Detail lain:
- Kalau ada user di device (yang lolos filter) yang belum punya record **Employee** yang cocok
  (dicocokkan via PIN), otomatis dibuatkan record Employee dasar dulu (nama, privilege, card ikut
  dari device).
- Template disimpan sebagai **base64 text** (field `Template` = `TextField`, sementara data asli dari
  `pyzk` berbentuk bytes biner) — konsisten dengan cara Fingerprint Template menyimpan data selama ini.
- Idempotent: jalankan berkali-kali tidak bikin data duplikat — dicocokkan via `(UserID, FingerID)`
  (`unique_together` di model), jadi run kedua & seterusnya cuma **update** `Template`/`Valid`/`UTime`,
  bukan bikin baris baru.
- Implementasi: `iclock/services.py::backup_device_fingerprints(device, pin_pattern=...)` (logic + ORM
  writes) + `iclock/zk_client.py::fetch_device_users_and_templates()` (koneksi pyzk, 1x konek ambil
  semua sekaligus, filter PIN diterapkan setelah data diterima -- bukan di level protokol pyzk, karena
  `get_users()`/`get_templates()` pyzk tidak mendukung filter server-side).
- Halaman ini (`templates/iclock/active_device_backup_fingerprints.html`) juga punya spinner loading
  yang sama seperti Transfer Finger, karena proses baca data dari device bisa lumayan lama kalau
  user-nya banyak (walau sudah difilter, proses `get_users()`/`get_templates()` tetap mengambil SEMUA
  data dari device dulu sebelum difilter di sisi Django -- filter ini mengurangi beban DATABASE WRITE,
  bukan mengurangi waktu KONEKSI/BACA dari device itu sendiri).

## 19. Spinner untuk "Show Device User"

Link **"Show Device User"** di dropdown Active Device sekarang juga menampilkan overlay loading
begitu diklik — sebelum halaman baru (yang di baliknya melakukan fetch live ke device via pyzk)
selesai dimuat.

Beda dengan spinner form (yang muncul saat *submit*), ini spesifik untuk **navigasi link biasa**
(`<a href>`, bukan `<form>`). Implementasinya generik & reusable: link mana pun yang butuh loading
overlay saat diklik tinggal ditambah class `show-loading-on-click`, dan JS di `app.js` otomatis
menangani sisanya (overlay-nya sendiri didefinisikan sekali di `templates/base.html`, dipakai bareng
oleh semua halaman). Kalau nanti ada link lain yang juga lambat (konek device dsb), tinggal tambahkan
class yang sama, tidak perlu tulis ulang JS-nya.

## 20. Transfer Data Finger dari tabel Employee

Menu **"Transfer Data Finger"** di dropdown **Employee** sekarang juga berfungsi sungguhan (sebelumnya
dummy), dengan perbedaan dari versi di Active Device:

- **PIN tidak bisa diedit** — cuma employee yang dipilih (1 PIN tetap), bukan textarea multiline.
- **Tidak ada combo "From Device"** — source device otomatis dari `employee.SN` (device tempat
  employee itu terdaftar). Kalau `employee.SN` kosong atau device-nya tidak punya IP Address, muncul
  pesan error dan redirect balik ke list (tidak bisa lanjut ke form).
- Sisanya sama: combo **To Pool** + **Target Device** (opsional, kosongkan = semua device di pool),
  kolom Status Transfer, dan spinner loading saat submit.
- Reuse fungsi inti yang sama (`iclock/zk_client.py::transfer_fingerprints()`) — cuma bedanya di form
  (`EmployeeTransferFingerForm` di `iclock/forms.py`, tanpa field `pins`/`from_device`) dan view
  (`device_user_transfer_finger` di `iclock/views.py`, sudah tidak dummy lagi).

## 21. Cara Mengubah Pilihan "Baris per Halaman"

Semua tabel yang punya selector "Baris/halaman" (Employee, Active Device, Registered Device,
Fingerprint Template, Transaction, Show Device User) **berbagi satu konstanta yang sama** di
`iclock/views.py`:

```python
PAGE_SIZE_OPTIONS = [10, 15, 25, 50, 100]
DEFAULT_PAGE_SIZE = 15
```

Cukup edit **satu tempat ini** untuk mengubah pilihan di SEMUA tabel sekaligus (tidak perlu edit
tiap view/template satu-satu). Misalnya kalau mau tambah opsi 200 atau 500 (biar muat 1 layar penuh
tanpa scroll di monitor Anda):

```python
PAGE_SIZE_OPTIONS = [10, 15, 25, 50, 100, 200, 500]
DEFAULT_PAGE_SIZE = 25  # kalau mau default-nya juga diubah
```

Tidak perlu ubah apa pun di template — dropdown "Baris/halaman" otomatis merender ulang sesuai list
ini (`{% for opt in page_size_options %}` di masing-masing template), dan validasi server
(`_resolve_page_size()`, tepat di bawah `PAGE_SIZE_OPTIONS`) juga otomatis ikut menerima nilai baru
yang Anda tambahkan.

> Catatan: nilai yang terlalu besar (mis. 1000+) untuk tabel yang datanya sungguhan banyak (Transaction,
> Fingerprint Template) tetap bisa bikin loading lumayan berat kalau benar-benar dipilih user, karena
> query & render HTML-nya jadi sebesar itu juga. Kalau tujuannya "tidak perlu scroll", pertimbangkan
> juga kombinasi dengan mengecilkan padding/font tabel di CSS, bukan cuma menaikkan row count-nya.

## 22. Sync Model dari models.py Terbaru Anda + `DEVICEFUNCTION`

File `models.py` yang Anda upload terakhir sudah disinkronkan ke `iclock/models.py`:
- **Semua model** sekarang `managed = True` (sebelumnya `False`) — sesuai keputusan Anda setelah
  `makemigrations`/`migrate` berhasil di sisi Anda.
- Field baru: `iclock.Function`, `iclock.DeviceName` (read-only), `iclock.PushVersion` (read-only),
  `RegisteredDevice.LastActivity` (read-only), `employee.AccGroup`, `employee.UTime` (read-only),
  **`transaction.Function`** + method `FncName()`.
- `Function` juga ditambahkan ke form **Active Device** (sebelumnya cuma ada di Registered Device).

**TIDAK ikut disalin** (dan sengaja dihilangkan lagi, sama seperti sebelumnya): bagian akhir file Anda
yang masih ada `getDevice()`, `getNewDevice()`, `removeLastReboot()`, `deviceCmd()`, dan baris
`last_reboot_cname = "%s_lastReboot" % settings.UNIT` di level modul — ini akan **crash saat import**
karena `settings.UNIT` tidak didefinisikan di scaffold ini, dan beberapa fungsi itu juga masih
bergantung pada `cache`/`ObjectDoesNotExist` dari `from .utils import *` yang tidak ada di app ini.
Kalau fungsi-fungsi itu memang dipakai di bagian lain sistem Anda (mis. server komunikasi device
terpisah), sebaiknya taruh di modul lain yang tidak ikut ke-import oleh dashboard ini.

**`DEVICEFUNCTION`** dipindah dari yang tadinya notasi Django `settings.py` versi lama, ke
`config/settings.py` project ini (bukan di `models.py`, mengikuti konvensi Django yang benar — model
tidak seharusnya membaca konfigurasi langsung dari luar `settings`):
```python
DEVICEFUNCTION = {
    '89': 'KARYAWAN', '1': 'DRIVER-HHHH', '56': 'DRIVER-CCC', 'X': 'KANTIN',
    '2': 'DRIVER-AKAP', '3': 'YAYASAN', '7': 'BHL', '4': 'DRIVER-KBA', '0': 'TESTING',
}
```
Tinggal edit dict ini kalau kode/label Function berubah — otomatis ikut berubah di combo filter
Attendance Recap dan `transaction.FncName()`.

## 23. Attendance Recap (Rekap Kehadiran)

Menu baru di Iclock Management: **Attendance Recap**. Filter: **Device Function** (dari
`settings.DEVICEFUNCTION`), **Pool**, **Device** (dependent dropdown dari Pool, reuse endpoint AJAX
yang sama dengan Transfer Finger), **From**/**To** (date picker), tombol **Query**.

**Tabel hasil**: baris = karyawan (PIN), kolom = tanggal (urut **terbaru dulu**, header 2 baris: nama
hari lokal + tanggal `YYYY/MM/DD`). Tiap sel tanggal berisi 2 nilai: **jam IN** (waktu **paling awal**
hari itu) dan **jam OUT** (waktu **paling akhir**), format `HH:MM|n` (n = jumlah transaksi). Klik salah
satu untuk lihat daftar lengkap semua transaksi IN/OUT hari itu (pakai `<details>`/`<summary>` native,
sama seperti dropdown Aksi — reliable di mobile, sudah terbukti dari perbaikan sebelumnya).

**Definisi IN/OUT** — awalnya saya asumsikan `State='0'` (Check in) / `State='1'` (Check out) sesuai
`ATTSTATES` di model. **Setelah investigasi dengan data produksi asli Anda** (pakai
`python manage.py recap_debug`), ternyata device Anda menulis kode **`'I'`/`'O'`** (huruf), bukan
digit — jadi field-nya sebenarnya bergantung device/firmware, tidak selalu sama dengan `ATTSTATES`.

Sekarang dikonfigurasi lewat `config/settings.py`:
```python
ATTENDANCE_IN_STATE_CODES = ['0', 'I']  # kode State yang dianggap IN; SELAIN ini = OUT
```
Default mencakup KEDUA konvensi (digit `'0'` dari model, dan huruf `'I'` dari data nyata Anda) supaya
kompatibel dengan device manapun. Kalau device lain pakai kode berbeda lagi, tinggal tambahkan ke list
ini — tidak perlu ubah kode. Sesuai instruksi Anda: **apa pun selain kode IN dianggap OUT**, tidak ada
kategori ketiga.

**Soal `USE_TZ`** — juga ketemu lewat investigasi yang sama: timestamp mentah yang ditulis device
fisik ke `checkinout.checktime` adalah **waktu lokal apa adanya** (bukan UTC). Kalau `USE_TZ=True`,
Django keliru mengira nilai itu UTC dan menggeser jamnya (`07:30` jadi `14:30`, bahkan bisa lompat
tanggal). **`USE_TZ` sekarang default `False`** (bisa diatur lewat `.env`, sebelumnya hardcode `True`)
— ini yang benar untuk pola data legacy seperti ini. Kalau suatu saat proses penulisan datanya diubah
supaya benar-benar menyimpan UTC, baru ubah `USE_TZ=True` di `.env`.

**Tool diagnostik** `python manage.py recap_debug [--pin X] [--date YYYY-MM-DD] [--limit N]` — kalau
suatu saat rekap kelihatan salah lagi (jam kosong, kegeser, dsb), jalankan ini dulu terhadap data
asli untuk lihat persis nilai mentah `TTime`/`State` sebelum menebak-nebak.

Detail implementasi lain:
- Filter **Function** memfilter `transaction.Function` langsung (bukan lewat `employee`/`iclock`),
  sesuai field yang baru Anda tambahkan.
- Filter **Pool**/**Device** memfilter berdasarkan **device perekam transaksi** (`transaction.SN`),
  bukan pool karyawan — asumsi ini saya ambil supaya konsisten dengan pola dependent-dropdown Pool →
  Device yang sudah ada. Kalau maksud Anda "Pool" di sini adalah pool KARYAWAN (`employee.DeptID`),
  kabari saya, gampang diubah.
- **Pagination diterapkan ke daftar karyawan (baris)**, bukan ke transaksi mentah — jadi query detail
  transaksi cuma dijalankan untuk karyawan yang tampil di halaman aktif, bukan seluruh hasil filter
  sekaligus. Ini penting untuk performa mengingat volume transaksi absensi biasanya sangat besar.
- Rentang tanggal dibatasi **maksimal 62 hari** per query (validasi form) — supaya tidak ada yang
  tidak sengaja query rentang setahun penuh dan bikin server ngos-ngosan.
- Spinner loading muncul saat form filter di-submit (sama pola dengan Transfer Finger/Backup Finger).

## 24. Cell Fixed-Length Monospace & PIN Lookup + Card Bulanan (Attendance Recap)

**Cell IN/OUT sekarang fixed-length & monospace** — tiap nilai (`HH:MM|n`) dibungkus
`<span class="font-mono w-16 text-center">`, jadi lebar kolomnya konsisten walau isinya beda-beda
panjang. Kalau tidak ada data (mis. belum ada transaksi OUT hari itu), tampilannya jadi placeholder
**`XX:XX`** (bukan `-`), tetap mengisi lebar yang sama supaya grid tabel tidak "loncat-loncat".

**Filter PIN baru** — ditambahkan di posisi **paling kiri** (sebelum Device Function), dengan
autocomplete (AJAX, debounce 300ms, endpoint `iclock:ajax_employee_search`, cari by PIN atau nama).
Dua mode:
1. **Ketik bebas tanpa pilih dari daftar** → diperlakukan sebagai **regex filter PIN**
   (`UserID__PIN__iregex`, diterapkan di level database, bukan Python — supaya tetap ringan walau
   transaksinya banyak), digabung dengan filter lain seperti biasa, hasilnya tetap tabel matrix biasa.
2. **Klik salah satu hasil autocomplete** → field hidden `pin_exact` ke-isi, submit form
   me-redirect ke halaman **card rekap bulanan** khusus karyawan itu — filter lain (Function/Pool/
   Device/tanggal) diabaikan sepenuhnya.

**Card rekap bulanan** (`/admin/iclock/attendance-recap/employee/<PIN>/`):
- Header **selalu terlihat** (info NIP/nama + Periode + tombol Prev/Next bulan) — tidak ikut scroll.
- Isi transaksi di bawahnya **scrollable**, dengan header kolom tabel (`Tanggal/Device/JAM/Type`)
  yang **sticky** relatif terhadap area scroll itu sendiri (pakai `position: sticky` CSS standar,
  bukan trik dua-tabel-terpisah yang rawan salah alignment).
- Kolom **Tanggal** cuma tampil di baris transaksi PERTAMA pada tanggal itu (baris berikutnya di
  tanggal yang sama dikosongkan) — persis pola visual yang Anda contohkan.
- Kolom **Type** menampilkan `C/In` / `C/Out` (berdasarkan `_is_in_state()` yang sama dengan tabel
  utama — jadi konsisten dengan definisi IN/OUT & `ATTENDANCE_IN_STATE_CODES` yang sudah dikonfirmasi).
- Default bulan berjalan; navigasi Prev/Next cukup ganti `?year=&month=` di URL yang sama (tidak perlu
  submit ulang form filter utama).
- **Tidak dipaginate** (beda dari tabel utama) — karena sudah dibatasi ke 1 karyawan + 1 bulan,
  volumenya jauh lebih kecil, dan memang didesain scrollable sesuai permintaan.

## 25. Dark/Light Theme

Toggle tema ada di **dropdown avatar** (pojok kanan atas) — item "Dark Mode"/"Light Mode" dengan
switch visual, di antara "Ubah Password" dan "Logout".

**Cara kerja:**
- Tailwind (CDN) dikonfigurasi `darkMode: 'class'` di `templates/base.html` — jadi tema dikontrol
  lewat ada/tidaknya class `dark` di `<html>`, bukan cuma ikut `prefers-color-scheme` OS.
- State disimpan di `localStorage` (key `theme`, nilai `dark`/`light`). Kalau belum pernah pilih
  manual, default ikut preferensi OS (`prefers-color-scheme: dark`).
- Ada script anti-flash di `<head>` (sama pola dengan collapse sidebar yang sudah ada) — membaca
  preferensi tema SEBELUM `<body>` dirender, supaya tidak kelihatan "kedip" tema salah sekejap saat
  halaman baru dimuat (penting karena dashboard ini server-rendered per halaman, bukan SPA).
- Toggle-nya di `static/dashboard/js/app.js` (`themeToggleBtn`), cuma nge-toggle class `dark` +
  update `localStorage` + ganti ikon/label tombol (🌙 Dark Mode ↔ ☀️ Light Mode).

**Cakupan styling:**
- Seluruh **shell utama** (`base.html`: header, dropdown, flash messages) sudah full dark mode.
  Sidebar TETAP gelap permanen di kedua tema (sudah dari awal `bg-slate-900`) — pola umum di banyak
  dashboard, jadi tidak diubah.
- **Semua input form** dapat dark mode otomatis lewat SATU perubahan di konstanta `INPUT_CLS`
  (`iclock/forms.py` & `accounts/forms.py`) — dipakai oleh seluruh widget form di aplikasi, jadi tidak
  perlu edit form satu-satu.
- **Komponen pagination** (`templates/partials/pagination.html`) sudah dark mode, otomatis berlaku ke
  semua tabel yang pakai komponen ini.
- Untuk **konten tiap halaman** (33 template), dilakukan bulk-patch pola class yang berulang (card
  `bg-white` → `dark:bg-slate-800`, tabel, badge, dropdown, dst) di seluruh template `iclock/` dan
  `dashboard/` — dicek ulang beberapa kali sampai tidak ada lagi pola warna signifikan yang belum
  kebagian varian `dark:`. Beberapa elemen SENGAJA dibiarkan tanpa varian (tombol `bg-slate-800`/
  `bg-indigo-600`, overlay backdrop `bg-slate-900/60`) karena sudah cukup gelap/kontras di kedua tema.

**Keterbatasan pengujian yang jujur perlu disampaikan**: sandbox pengembangan ini tidak punya browser
sungguhan untuk screenshot/pratinjau visual. Yang sudah diverifikasi: struktur HTML mengandung class
`dark:` yang benar di berbagai halaman (dicek via Django test client), dan logika JS toggle (baca/tulis
`localStorage`, toggle class) sudah diuji lewat simulasi Node.js terpisah. Tapi hasil akhir tampilan
visualnya (kontras warna, keterbacaan, dll) **belum saya lihat langsung** — mohon dicoba di browser
Anda, dan kabari kalau ada bagian yang kurang pas supaya bisa disesuaikan lagi.

## 26. WebSocket Real-time (Channels + Redis) & Console Window Active Device

Endpoint baru **`/ws/iclock`** pakai **Django Channels** + **Redis** sebagai channel layer, untuk
broadcast event real-time (mis. device fisik lagi request/heartbeat, atau ada event check-in/out)
ke browser yang lagi buka halaman Active Device.

### Format message (dari protokol push device Anda)
```json
{"sn": "6422144200666", "la": "2026-07-14 09:57:16", "devinfo": ""}
```
- `sn` — Serial Number device (cocok dengan `iclock.SN`).
- `la` — LastActivity, format `YYYY-MM-DD HH:MM:SS`.
- `devinfo` — info tambahan bebas, boleh string kosong.

### Setup yang perlu Anda lakukan
1. **Redis harus jalan** — install & jalankan Redis server (default `127.0.0.1:6379`, bisa diatur
   lewat `.env`: `REDIS_HOST`/`REDIS_PORT`).
2. **Dependency baru**: `channels`, `channels_redis`, `daphne` (sudah ditambahkan ke
   `requirements.txt`) — `pip install -r requirements.txt` lagi setelah update.
3. **`'daphne'` WAJIB ada di `INSTALLED_APPS`, dan HARUS di baris PALING ATAS** (sudah ditambahkan di
   `config/settings.py`). Ini gampang keliru: `channels` sendiri **cuma menyediakan command
   `runworker`**, BUKAN `runserver` — yang menyediakan override `runserver` yang ASGI-aware (bisa
   serve HTTP + WebSocket sekaligus) itu justru package **`daphne`**. Tanpa `daphne` di
   `INSTALLED_APPS`, `python manage.py runserver` diam-diam kembali pakai runserver bawaan Django
   (WSGI-only) dan `/ws/iclock` **tidak akan bisa dikonek** sama sekali saat development — tidak ada
   error yang jelas, cuma koneksi WebSocket gagal terus. Sudah diverifikasi lewat
   `django.core.management.get_commands()['runserver']` yang sekarang benar menunjuk ke `'daphne'`
   (sebelum `daphne` ditambahkan, ini menunjuk ke `'django.contrib.staticfiles'`).
4. **Produksi**: pakai ASGI server sungguhan, mis. `daphne config.asgi:application` atau `uvicorn`
   (`runserver`, termasuk versi daphne-nya, cuma untuk development).

### Arsitektur
- `config/asgi.py` — `ProtocolTypeRouter` yang misahkan HTTP (Django biasa) vs WebSocket
  (`AuthMiddlewareStack` + `URLRouter` dari `iclock/routing.py`). `AuthMiddlewareStack` membaca
  session cookie yang SAMA dengan dashboard, jadi `scope['user']` otomatis terisi kalau browser
  sudah login.
- `iclock/consumers.py` — `IclockConsumer`: koneksi WebSocket **ditolak kalau guest** (belum login,
  `AnonymousUser`), kalau valid langsung di-join ke **group `'iclock'`**.
- `iclock/ws_utils.py` — fungsi umum **`wsinfo(groupname, section, message)`** buat broadcast pesan
  ke semua client yang join di suatu group. `section` bebas (`'device_request'`, `'device_attlog'`, dst — client JS
  yang menentukan cara menampilkannya). Dipanggil dari kode mana pun (view, service, command, atau
  proses komunikasi device fisik Anda yang terpisah).
- `python manage.py ws_simulate --section device_request --sn <SN>` — command buat **simulasi testing**
  tanpa perlu device fisik sungguhan (device komunikasi server aslinya adalah komponen terpisah, di
  luar scope scaffold ini, dikelola sendiri oleh Anda).

> **PENTING — koreksi dari versi sebelumnya**: `wsinfo()` **TIDAK menyentuh database sama sekali**.
> Field `iclock.LastActivity` di database sudah otomatis ter-update oleh protokol push device fisik
> Anda sendiri (komponen terpisah, di luar scaffold ini) — jadi `wsinfo()` di sini murni
> membroadcast pesan ke browser. Update "LastActivity" yang dimaksud adalah **update tampilan**
> (DOM) di kolom Last Activity tabel Active Device secara real-time, BUKAN query ulang ke database
> — supaya terasa live tanpa perlu refresh halaman, sementara data sungguhannya sudah benar duluan
> di database lewat jalur Anda sendiri.

### Console window & update tampilan Last Activity real-time (Active Device)
Toolbar (sejajar search filter) punya checkbox **"🖥️ Tampilkan Console"** — nyalain buat munculin
panel console di bagian bawah halaman. Panel ini nampilin tiap pesan yang diterima dari `/ws/iclock`
(format `[jam] (section) {...isi pesan}`), auto-scroll, dibatasi 500 baris terakhir (biar tidak makan
memori kalau dibiarkan lama), plus tombol "Clear" dan indikator status koneksi (Menghubungkan/
Terhubung/Terputus).

**Terpisah dari console**, setiap kali pesan dengan `section='device_request'` diterima, JS
(`templates/iclock/active_device_list.html`) mencari baris `<tr data-device-row data-sn="...">`
yang `sn`-nya cocok (kalau device itu memang sedang tampil di halaman/hasil filter saat ini — kalau
tidak ada, diamkan saja, tidak error), lalu update teks di cell `.ws-last-activity` pakai nilai `la`
dari message (diformat mirip tampilan Django `d M Y H:i`, mis. `14 Jul 2026 09:57`). Ini murni
manipulasi DOM di browser, tidak ada request HTTP/query database tambahan.

Koneksi WebSocket-nya **tetap jalan di background** walau panel console disembunyikan (checkbox cuma
toggle visibility panel console, bukan connect/disconnect, dan tidak mempengaruhi update Last
Activity yang tetap jalan terus selama halaman terbuka) — jadi kalau panel ditampilkan lagi nanti,
histori pesan yang sudah masuk selama itu tetap ada, tidak ada yang kelewat.

### Sudah diuji
- Koneksi guest (belum login) **ditolak** (`WebsocketCommunicator` test, `connected == False`).
- User yang sudah login **berhasil konek** & ter-join ke group `'iclock'`.
- Broadcast lewat `wsinfo()` **diterima** oleh client yang terhubung, dengan format message
  `{"sn", "la", "devinfo"}` yang benar (persis field & isi yang dikirim).
- **Dikonfirmasi ulang: `wsinfo()` TIDAK mengubah database** — field `iclock.LastActivity` tetap
  `None`/tidak berubah setelah `wsinfo()` dipanggil berkali-kali (assert eksplisit di test).
- Logic `formatLastActivity()` & pencocokan baris via `data-sn` diuji lewat simulasi Node.js
  terpisah: input `"2026-07-14 09:57:16"` terformat jadi `"14 Jul 2026 09:57"`, dan update cuma
  mengenai baris dengan `sn` yang cocok (baris lain tidak ikut berubah).
- Semua diuji dengan **Redis sungguhan** (bukan mock), termasuk lewat pipeline ASGI penuh
  (`config.asgi.application`, bukan cuma consumer telanjang).
- Resolusi command `runserver` diverifikasi menunjuk ke `'daphne'` setelah `daphne` ditambahkan ke
  `INSTALLED_APPS` (sebelumnya salah menunjuk ke `'django.contrib.staticfiles'` -- WSGI-only).

### Indikator device tidak aktif (merah)
Kolom **Last Activity** di tabel Active Device otomatis tampil **merah** kalau selisihnya dari waktu
sekarang **≥ 60 menit** (`ACTIVE_DEVICE_STALE_MINUTES` di `iclock/views.py`), atau device itu **belum
pernah** punya `LastActivity` sama sekali (`None`).

- **Render awal (server)**: dihitung di view (`device.is_stale`), akurat berdasarkan waktu server saat
  halaman di-load.
- **Real-time (client)**: dicek ulang tiap 60 detik lewat `setInterval` di JS, jadi device yang
  "diam" (tidak ada event WS baru sama sekali) tetap ikut berubah merah seiring waktu berjalan, tanpa
  perlu refresh halaman. Begitu ada event `section='device_request'` baru masuk lewat WebSocket untuk device
  itu, warnanya otomatis kembali normal (karena jelas baru saja aktif).
- Ambang batasnya (`ACTIVE_DEVICE_STALE_MINUTES`) dipakai KONSISTEN di server (Python) maupun client
  (JS, dikirim lewat context `stale_minutes`) — ubah di satu tempat (`iclock/views.py`), otomatis
  konsisten di keduanya.
- Sudah diuji: device aktif 5 menit lalu (tidak merah), device diam 2 jam (merah), device belum
  pernah aktif/`None` (merah), device tepat di 59 menit (masih belum merah, di bawah ambang), dan
  device yang baru saja dapat update dari WebSocket (kembali tidak merah).

## 27z-4. Redesign Mobile Attendance — Tampilan App-Like (Bottom Tab Bar) & Link "NIK Login"

Seluruh alur mobile employee (Absen, Check/Meal, Enrollment Wajah, Profil, Ganti Password) dirombak
total dari "mode testing" (banner peringatan, layout form polos) jadi terasa seperti aplikasi native
iOS/Android — **fungsi JS/form di baliknya TIDAK berubah sama sekali** (dikonfirmasi lewat test
end-to-end penuh, cuma tampilannya yang dipoles).

### App shell baru: `templates/mattendance/mobile_app_base.html`

Layout mobile-first dengan **bottom tab bar** (4 tab: 📍 Absen, 🍽️ Makan, 🙂 Wajah, 👤 Profil) —
menggantikan sidebar desktop (`base.html`) yang tidak masuk akal dipakai di HP. Header berisi
sapaan personal ("Halo, {nama}") + tanggal hari ini, gaya kartu rounded-3xl konsisten di semua
halaman, dark mode tetap didukung (reuse mekanisme localStorage yang sama dengan dashboard staff).

### Halaman baru: Profil (`/mattendance/profile/`)

Tab "Profil" — tampilkan nama & PIN Employee, tombol "Ganti Password", tombol "Keluar" (logout).
Ditambahkan ke whitelist `MobileAccessMiddleware` supaya bisa diakses user mobile-only.

### Link "NIK Login" di halaman login staff

`/accounts/login/` sekarang punya tombol terpisah **"NIK Login"** (persis label yang diminta) di
bawah pemisah "atau" — mengarah ke `/mattendance/login/`, supaya karyawan yang salah buka halaman
login staff (biasanya berujung error "User belum ada", lihat bagian 27z) langsung ketemu jalur yang
benar tanpa perlu tahu URL-nya secara manual.

### Halaman login mobile dipoles jadi gaya "splash screen" app

Background gradient indigo penuh, kartu form rounded-3xl mengambang di tengah, ikon app besar di
atas — bukan lagi tampilan form testing polos.

### Sudah diuji (fungsional, bukan cuma visual)
- Login mobile via halaman baru → berhasil, tetap diarahkan ke ganti password sesuai alur yang sudah
  ada sebelumnya (logic TIDAK berubah).
- Halaman Absen: banner "Mode testing" **dikonfirmasi hilang**, bottom tab bar 4-tab render benar,
  sapaan nama tampil, tab aktif ter-highlight sesuai halaman yang dibuka.
- Halaman Check/Meal: library jsQR tetap termuat dengan benar.
- Halaman Profil (baru): nama & PIN tampil benar, tombol Ganti Password & Keluar ada, **dikonfirmasi
  bisa diakses** user mobile-only (tidak ditolak middleware, karena sudah ditambahkan ke whitelist).
- **Full functional end-to-end**: enrollment wajah SUNGGUHAN + check-in SUNGGUHAN (lewat Celery task)
  dikonfirmasi **tetap berhasil** lewat UI yang sudah dirombak total — membuktikan redesign visual
  tidak merusak id elemen/JS/form field yang dipakai logic di baliknya.
- "NIK Login" dikonfirmasi muncul di halaman login staff, mengarah ke URL mobile login yang benar.

## 29. API Lengkap — mattendance, mclock, & Aksi Khusus iclock

Melengkapi API yang sudah ada (`api/` — auth JWT umum & manajemen user, `iclock/api_urls.py` — CRUD
model mentah) dengan **seluruh fitur yang sebelumnya cuma bisa diakses lewat dashboard web**. Urutan
prioritas: **mattendance dulu** (paling siap pakai utk frontend mobile), lalu **mclock**, lalu
**aksi khusus iclock** (device control, Attendance Recap).

### mattendance — `/api/v1/mattendance/`

| Endpoint | Method | Keterangan |
|---|---|---|
| `auth/login/` | POST | Login PIN Employee (`pin`, `mobile_password`) → JWT + `must_change_password` |
| `auth/change-password/` | POST | Ganti password mobile |
| `profile/` | GET | Nama & PIN Employee terkait user login |
| `face/status/` | GET | `has_face_profile`, `is_locked` — utk gating UI client |
| `face/enroll/` | POST | Daftar wajah (sekali seumur hidup, auto-terkunci) |
| `checkin/` | POST | Check-in/out (GPS + wajah) |
| `checkin/meal/` | POST | Check/Meal (GPS + QR) |
| `history/` | GET | Riwayat **milik sendiri** (paginated) |
| `admin/logs/` | GET, DELETE | Staff-only — SEMUA log user |
| `admin/face-profiles/` | GET, DELETE, POST `.../toggle-lock/` | Staff-only — kelola kunci/hapus |

**Penyesuaian penting utk API (stateless/JWT, beda dari web yang berbasis session)**:
`MobilePasswordUpToDate` (permission class baru) menggantikan `MobileAccessMiddleware` versi web —
dicek ULANG di SETIAP request ke `checkin/`, `checkin/meal/`, `face/enroll/` (bukan sekali per
session), supaya user mobile-only yang passwordnya masih default tetap ditolak konsisten walau
lewat API.

### mclock — `/api/v1/mclock/`

CRUD penuh (staff-only) utk `mobile-pool/`, `mobile-pool-loc/`, `pool-device-function/` — validasi
duplikat (PoolID, atau PoolID+Urut) direplikasi persis dari form dashboard.

### iclock — aksi khusus (`/api/v1/iclock/`)

Selain CRUD model mentah yang sudah ada, ditambahkan:

**Attendance Recap** (fitur besar): `attendance-recap/?pin=&function=&pool=&device=&date_from=&date_to=`
(matrix PIN×tanggal), `attendance-recap/<pin>/card/?year=&month=` (rincian 1 employee 1 bulan),
`employee-search/?q=` (autocomplete).

**Aksi device** (sub-resource dari `active-device/<sn>/`, via pyzk — koneksi LANGSUNG ke hardware,
reuse fungsi yang SAMA persis dgn dashboard web di `iclock/zk_client.py`):
`reboot/`, `sync-time/`, `network-params/` (GET baca & POST ubah), `generic-param/`, `live-users/`
(user yang BENAR-BENAR ada di memori device saat ini), `backup-fingerprints/`,
`user-toggle-privilege/`, `user-delete/`, `user-transfer-finger/`.

**Aksi employee** (sub-resource dari `device-user/<pk>/`): `toggle-privilege/` (best-effort sync ke
device fisik kalau online), `transfer-finger/` (sumber dari DB, device employee TIDAK perlu online).

### ⚠️ Keterbatasan pengujian aksi device (sama seperti fitur lain yang butuh hardware fisik)

Aksi device (`reboot`, `sync-time`, `network-params`, dst) **tidak bisa diuji end-to-end** di sandbox
pengembangan ini (tidak ada mesin fingerprint fisik tersedia) — **diuji lewat mock** terhadap fungsi
`iclock/zk_client.py` yang SAMA PERSIS dipakai dashboard web (yang sebelumnya sudah dikonfirmasi
bekerja terhadap hardware sungguhan). Mock memverifikasi: orkestrasi benar (fungsi dipanggil dgn
argumen yang tepat), penanganan error (`DeviceConnectionError` → HTTP 502 rapi, bukan crash), dan
efek samping ke database (sinkronisasi privilege/hapus Employee) benar.

### Sudah diuji menyeluruh (bagian yang TIDAK butuh hardware fisik — DB & orkestrasi logic)
- **mattendance**: alur login PIN lengkap, gate password default per-request (bukan cuma sekali),
  enrollment (sukses, terkunci, tolak duplikat), check-in & Check/Meal (sukses & semua jalur gagal),
  riwayat (isolasi antar user), endpoint admin (akses staff vs ditolak non-staff, toggle-lock, hapus).
- **mclock**: CRUD + validasi duplikat semua 3 model, search, penolakan non-staff.
- **iclock Attendance Recap**: matrix rendering dgn data transaksi sungguhan (jam IN paling awal/OUT
  paling akhir benar), employee search, employee card (1 bulan penuh, urutan transaksi benar), PIN
  tidak ditemukan → 404, non-staff ditolak.
- **iclock aksi device (via mock)**: reboot sukses/gagal, network-params baca & validasi IP invalid,
  generic-param, toggle-privilege (+ sinkronisasi tabel Employee), user-delete (+ sinkronisasi hapus
  Employee), `DeviceConnectionError` → 502 rapi, live-users (filter+sort di Python).
- **iclock aksi employee (via mock)**: toggle-privilege (+ device_synced flag), transfer-finger
  (ditolak jelas kalau belum ada template DB, berhasil kalau sudah ada), backup-fingerprints.

## 27z-4c. Jawaban 2 Pertanyaan Arsitektur: Kenapa Perlu User utk Login PIN, & FaceProfile Diikat ke Employee

### 1. Kenapa login PIN tetap perlu buat `accounts.User`?

Seluruh mekanisme Django (`request.user`, `@login_required`, session, `login()`/`logout()`) terikat
erat ke konsep "instance model User" — tidak ada jalan resmi membuat `request.user` bekerja langsung
dari tabel `employee` tanpa reimplementasi manual seluruh lapisan session/auth Django (risiko
keamanan kalau dibangun dari nol, mengulang hal yang Django sudah uji dengan matang). Jadi user
"shadow" **tetap diperlukan** secara teknis.

**Tapi kekhawatiran soal "kebanyakan akun" itu valid** — diperbaiki dengan menyaring akun
`is_mobile_only=True` KELUAR dari halaman **"Manajemen User"** staff biasa (`accounts/services.py::
list_users()`). Akun shadow tetap ADA di database (dibutuhkan Django), tapi tidak lagi muncul &
membuat penuh daftar yang dikelola admin — hanya akun staff/reguler yang tampil di sana.

Kalau ternyata ini belum cukup dan Anda tetap menginginkan pendekatan **tanpa User sama sekali**
(session custom murni berbasis `employee_id`, TIDAK memakai `login()`/`@login_required`/`request.user`
Django) — itu bisa dilakukan, tapi merupakan rombakan besar (perlu bangun ulang decorator akses,
middleware, dan pola `AttendanceLog`/`FaceProfile` jadi terikat `employee` bukan `User` di semua
tempat) dengan trade-off menjauh dari mekanisme Django yang sudah teruji. Beri tahu kalau memang ini
yang diinginkan.

### 2. FaceProfile sekarang diikat ke `employee`, BUKAN ke `User`

**Ini memang gap nyata** — sebelumnya, kalau 1 employee punya 2 akun berbeda (mis. 1 akun staff
reguler yang di-link admin via `EmpID`, DAN 1 akun "mobile-only" otomatis dari login PIN — **keduanya
merujuk ke employee yang SAMA**), mereka dianggap identitas TERPISAH untuk keperluan wajah — harus
enroll ulang di tiap akun, padahal orangnya sama.

**Diperbaiki**: `FaceProfile.employee` (OneToOneField ke `iclock.employee`) menggantikan
`FaceProfile.user` sepenuhnya. Konsekuensinya:
- **1 kali enrollment (dari akun MANA PUN yang ter-link ke employee tsb) berlaku utk SEMUA akun**
  yang merujuk ke employee yang sama — persis skenario yang Anda gambarkan.
- User yang **tidak** terkait Employee manapun (`User.EmpID` kosong — mis. akun IT/admin murni tanpa
  data karyawan fisik) **tidak bisa** memakai enrollment/verifikasi wajah sama sekali — ditolak
  dengan pesan jelas ("Akun ini tidak terkait data Employee manapun").
- Halaman admin **"Face Profile"** sekarang menampilkan **PIN & nama Employee** langsung (sesuai
  yang diminta), bukan username akun.
- Field `existing_encodings`/`duplicate_*` di Celery task (`extract_face_encoding_task`) diganti
  jadi `employee_id`/`duplicate_employee_id` (dari `user_id`/`duplicate_user_id`) — **⚠️ butuh
  restart Celery worker** setelah update ini (lihat catatan 27z-3 soal ini).

```
python manage.py makemigrations mattendance
python manage.py migrate
```

### Sudah diuji — skenario UTAMA dari pertanyaan Anda, end-to-end penuh
1. Enrollment wajah lewat **akun staff reguler** (`EmpID` di-link admin) → sukses, `FaceProfile`
   tersimpan terikat ke `employee`, bukan ke `User` staff itu.
2. **Login via PIN** → dikonfirmasi membuat shadow `User` **BERBEDA** dari akun staff, tapi
   `EmpID`-nya **sama-sama merujuk employee yang sama**.
3. **Verifikasi utama**: shadow user yang BARU SAJA dibuat ini **langsung** `has_face_profile=True`
   TANPA perlu enroll ulang sama sekali — tombol check-in langsung aktif.
4. Shadow user berhasil **check-in sungguhan** memakai wajah yang di-enroll lewat akun BERBEDA —
   log tercatat dengan `user` yang benar (shadow account, bukan akun staff).
5. Coba enroll ulang lewat akun shadow → ditolak (sudah terkunci dari enrollment akun staff
   sebelumnya) — membuktikan kuncinya juga berlaku LINTAS akun, konsisten dengan "1 employee, 1
   wajah, siapa pun akunnya".
6. User tanpa `EmpID` sama sekali → ditolak jelas, baik saat submit maupun saat buka halaman
   enrollment.
7. Halaman admin Face Profile → dikonfirmasi tampilkan PIN & nama employee dengan benar.
8. Manajemen User → dikonfirmasi akun mobile-only **tidak lagi muncul**, akun staff reguler tetap
   tampil normal.

## 27z-4b. Tiga Penyempurnaan: Kamera Mati Setelah Sukses, Enrollment Sekali Seumur Hidup, Tab Log History

### 1. Kamera dimatikan setelah check-in/out/meal berhasil

Setelah check-in/out/meal SUKSES, stream kamera langsung dihentikan (`getTracks().forEach(track =>
track.stop())`) — tidak perlu lagi menampilkan video begitu prosesnya selesai. Dilakukan di
`checkin_test.html` & `checkin_meal.html` (yang terakhir juga menghentikan loop scan QR-nya).

### 2. Pengambilan wajah hanya sekali — `FaceProfile.is_locked`

Field baru `is_locked` (label "Terkunci (ReadOnly)") — otomatis diset `True` begitu **1 kali**
enrollment berhasil. Selama terkunci:
- User **TIDAK BISA** mendaftar ulang wajahnya sendiri — dicek PALING AWAL (sebelum foto diproses
  sama sekali), pesan jelas "hubungi admin".
- Halaman Enrollment Wajah otomatis **menyembunyikan kamera & tombol capture**, diganti tampilan
  "sudah siap dipakai" + info kapan terkunci.

**Halaman admin baru**: `/mattendance/face-profiles/` (menu sidebar "🔒 Face Profile", staff-only) —
list semua FaceProfile dengan status Terkunci/Terbuka, aksi **"Buka Kunci"** (kalau employee
legitimately butuh enroll ulang) dan **"Hapus"** (reset total, employee enroll dari nol). Begitu
di-unlock & user enroll ulang, otomatis **terkunci lagi** — kebijakan "sekali lalu harus lewat
admin" berlaku konsisten setiap saat, bukan cuma sekali di awal.

### 3. Tab "Riwayat" (Log History) + redirect otomatis setelah check berhasil

Tab ke-5 di bottom nav: **📋 Riwayat** — menampilkan riwayat check-in/out/meal **milik user yang
login sendiri** (BEDA dari halaman "Log Absensi GPS" yang staff-only & tampilkan SEMUA user).
Ditampilkan sebagai kartu (ikon per jenis check, nama pool, tanggal/jam), dengan pagination.

Setelah check-in/out/meal **berhasil**, browser otomatis diarahkan ke tab ini (setelah jeda singkat
supaya pesan sukses sempat terbaca) — user langsung lihat riwayatnya ter-update.

### Sudah diuji
- **Kunci enrollment**: enrollment pertama → sukses & otomatis terkunci; enrollment kedua (masih
  terkunci) → ditolak jelas; halaman enrollment menyembunyikan tombol capture saat terkunci; admin
  buka kunci → user bisa enroll ulang → otomatis **terkunci lagi** (bukan tetap terbuka); admin hapus
  profile → user bisa enroll dari nol; non-staff ditolak akses halaman admin Face Profile.
- **Log History**: hanya tampilkan log MILIK SENDIRI (dikonfirmasi log user lain **tidak bocor** ke
  riwayat user lain — isolasi data antar user diuji eksplisit); tab bar 5-tab render benar, tab
  "Riwayat" ter-highlight saat aktif; halaman bisa diakses user mobile-only (whitelist middleware).
- **Kamera mati**: dikonfirmasi kode `stopCamera()` & redirect ke halaman Riwayat ada di kedua
  template (`checkin_test.html`, `checkin_meal.html`) setelah render.

```
python manage.py makemigrations mattendance
python manage.py migrate
```

## 27z-3. Investigasi: "Error di Pengambilan Face" tapi Check-in Tetap Berhasil, + `face_debug`

**Dilaporkan**: ada error di proses pengambilan wajah; sudah dicoba set `PREVENT_DUPLICATE_FACE=False`
dan hapus data FaceProfile, tapi check-in tetap berhasil.

### ✅ Akar masalah DITEMUKAN & DIKONFIRMASI: Celery worker belum di-restart setelah update kode

Pesan error sungguhan di browser: `got an unexpected keyword argument 'existing_encodings'` —
**dikonfirmasi lewat reproduksi persis** (pesan error identik). Ini **BUKAN bug**, tapi konsekuensi
operasional yang mudah terlewat:

**⚠️ WAJIB DIINGAT KE DEPANNYA: setiap kali `mattendance/tasks.py` (atau modul apa pun yang
diimpornya, mis. `face_utils.py`) berubah, proses Celery worker WAJIB DI-RESTART MANUAL.** Beda
dengan `manage.py runserver` yang auto-reload begitu file berubah, **proses Celery worker TIDAK
otomatis memuat ulang kode** — dia tetap menjalankan versi LAMA sampai proses-nya benar-benar
dihentikan & dijalankan ulang:
```
# Hentikan worker yang sedang jalan (Ctrl+C), lalu:
celery -A config worker --loglevel=info --pool=solo
```

Kasus konkret yang terjadi: saat `PREVENT_DUPLICATE_FACE` ditambahkan (bagian 27y),
`extract_face_encoding_task` (dipanggil saat **enrollment**) diberi parameter baru
`existing_encodings` — tapi worker yang sedang berjalan masih pakai versi LAMA task itu (tanpa
parameter itu), jadi begitu view (yang sudah update) memanggil dengan parameter baru itu, worker
menolak dengan `TypeError`. **`verify_face_task` (dipanggil saat check-in) TIDAK berubah
signature-nya**, jadi check-in tetap normal memakai worker lama sekalipun — inilah yang menjelaskan
kenapa "check-in tetap berhasil" walau enrollment gagal: kalau ada `FaceProfile` LAMA (dari sebelum
update ini), itu tetap valid dipakai verifikasi check-in.

### Update: restart sudah dicoba 2x, error masih sama

Kalau restart worker sudah dicoba tapi error `unexpected keyword argument` masih tetap muncul,
kemungkinannya BUKAN lagi soal restart, tapi **file `mattendance/tasks.py` di server itu sendiri
belum benar-benar ter-update** (salinan lama tertimpa tidak sempurna, ada 2 salinan folder project,
atau worker jalan dari working directory/virtualenv yang berbeda dari yang di-edit).

`face_debug` sekarang punya 2 langkah tambahan yang membuktikan ini secara **definitif**, bukan
dugaan:
- **Langkah 5** — cek signature task & waktu modifikasi file SEBAGAIMANA dibaca proses `manage.py`
  ini sendiri.
- **Langkah 6** — **dispatch task SUNGGUHAN ke Celery worker** (round-trip penuh lewat broker,
  bukan cuma import lokal) — kalau worker MASIH menolak parameter `existing_encodings` di sini,
  errornya PASTI ada di worker (bukan di proses Django), dan disertai daftar kemungkinan penyebab
  konkret (proses lama belum benar-benar mati, salinan folder project ganda, dsb).

**Sudah diuji dengan worker Celery SUNGGUHAN** (bukan mock) — dikonfirmasi dispatch berhasil tanpa
`TypeError` sama sekali (error lain yang muncul murni soal dlib belum terinstall di sandbox
pengujian, bukan soal versi kode) — membuktikan langkah 6 bisa membedakan dengan tepat antara
"worker basi" vs error lain yang wajar.

### Command diagnostik `face_debug`

```
python manage.py face_debug                        # semua FaceProfile
python manage.py face_debug --user <username>       # 1 user spesifik
python manage.py face_debug --test-image foto.jpg   # tes ekstraksi encoding dari file gambar langsung
```

Menampilkan: apakah `face_recognition`/dlib bisa dimuat, versi numpy (peringatan kalau ≥ 2.0),
**daftar SEMUA FaceProfile yang BENAR-BENAR ada di database saat ini** (username, apakah mobile-only,
waktu enroll/update, validitas encoding — 128 dimensi atau mencurigakan), dan opsional tes ekstraksi
encoding langsung dari 1 file gambar.

**Sudah diuji**: mendeteksi FaceProfile yang tersisa dengan benar (username & detail lengkap tampil);
filter `--user` bekerja; mendeteksi encoding yang PANJANGNYA TIDAK 128 (korup/malformed) dengan
peringatan jelas.

**Status**: akar masalah sudah dikonfirmasi (Celery worker belum di-restart, lihat di atas) —
`face_debug` tetap berguna disimpan untuk troubleshoot kejanggalan FaceProfile serupa di masa depan.

## 27z-2. Command Diagnostik Login Mobile (`mobile_login_debug`)

Ditambahkan `python manage.py mobile_login_debug <PIN> [--password <password>]` — tool diagnostik
untuk troubleshoot login mobile gagal, mengikuti pola `ldap_debug` yang sudah ada. Menelusuri
SETIAP langkah alur autentikasi satu-satu: field `mpassword` bisa diakses (migrasi sudah jalan?),
normalisasi PIN, pencarian Employee, status password (masih default/sudah custom), pendaftaran
`AUTHENTICATION_BACKENDS`, pengecekan password manual, sampai tes `authenticate()` end-to-end penuh.

### ⚠️ Temuan penting soal laporan "middleware belum jalan"

**"User belum ada" BUKAN pesan dari backend mobile sama sekali** — dikonfirmasi lewat pencarian
langsung di seluruh codebase, pesan itu berasal dari `accounts/exceptions.py::UserNotFoundInLDAPError`,
bagian dari alur login **STAFF REGULER** (LDAP/local, `/accounts/login/`). Kemungkinan besar PIN
diketik di halaman login staff (mengira PIN sebagai username), bukan di halaman login mobile yang
benar: **`/mattendance/login/`**. Command diagnostik ini menampilkan peringatan ini di baris paling
atas outputnya.

### Sudah diuji
- PIN + password default benar → semua 7 langkah SUKSES, konfirmasi login akan berhasil & user akan
  diminta ganti password (masih default).
- Password salah → langkah 6 & 7 dengan jelas menunjukkan GAGAL, pesan "sesuai dugaan, password
  tidak cocok".
- PIN tidak terdaftar sama sekali → berhenti di langkah 3 dengan pesan jelas + saran query SQL
  manual untuk double-check.
- Tanpa `--password` → langkah 6/7 dilewati dengan rapi, tidak error.
- `AUTHENTICATION_BACKENDS` sengaja di-override TANPA `EmployeeMobileBackend` → langkah 5 terdeteksi
  gagal dengan pesan jelas & solusi.
- Password SUDAH diganti custom: login pakai password default LAMA → gagal (sesuai harusnya); login
  pakai password custom yang benar → berhasil, TIDAK lagi diminta ganti password.

## 27z. Perbaikan: Login Mobile Gagal Kalau PIN Diketik Tanpa Nol di Depan

**Dilaporkan**: login mobile selalu gagal ("user belum ada"/PIN salah) walau PIN & password-nya benar.

**Akar masalah**: `employee.PIN` (kolom `badgenumber`) tersimpan **zero-padded 9 digit** (mis.
`'008113009'`) — tapi karyawan biasanya mengetik PIN **tanpa** nol di depan (mis. `'8113009'`, versi
yang mereka kenal sehari-hari). `EmployeeMobileBackend` sebelumnya mencocokkan PIN yang diketik
APA ADANYA ke `employee.PIN`, jadi PIN tanpa nol di depan tidak pernah ketemu.

**Perbaikan**: pakai `normalize_pin()` (fungsi yang SUDAH ADA & dipakai di tempat lain, mis. backup
fingerprint) untuk zero-pad PIN yang diketik SEBELUM dicocokkan — PIN dengan ATAU tanpa nol di depan
sekarang sama-sama berhasil, dan keduanya dikonfirmasi mengarah ke shadow user mobile-only yang SAMA
(tidak membuat akun duplikat). Ditambahkan juga petunjuk di halaman login: "Boleh diketik dengan
atau tanpa angka 0 di depan."

**Sudah diuji**: PIN tanpa nol depan → berhasil login (skenario yang dilaporkan); PIN lengkap dengan
nol depan → tetap berhasil (backward compatible); keduanya menghasilkan shadow user yang identik,
bukan 2 akun terpisah; PIN yang genuinely tidak terdaftar → tetap gagal dengan benar.

## 27y. Empat Fitur Besar: Cegah Wajah Duplikat, Default 10/Halaman, Batasan QRDEVICE, Login Mobile via PIN

### 1. `PREVENT_DUPLICATE_FACE` — cegah 2 user daftar wajah orang yang sama

Setting baru (`config/settings.py`, default `True`) — kalau aktif, enrollment wajah **ditolak** kalau
wajah yang didaftarkan sudah "mirip" (di bawah tolerance `face_recognition`) dengan wajah user LAIN
yang sudah lebih dulu terdaftar. **Enrollment ulang wajah SENDIRI selalu tetap diizinkan**, terlepas
dari setting ini. Perbandingan (CPU-intensive) dilakukan **di Celery worker** (bukan proses Django),
konsisten dengan pola isolasi proses yang sudah ada. Pesan penolakan **sengaja tidak menyebutkan**
username pemilik wajah yang duplikat (menghindari kebocoran informasi akun).

**Sudah diuji**: user B enroll wajah identik dgn user A (distance=0) → ditolak; user A enroll ulang
wajahnya sendiri → tetap diizinkan; setting dimatikan → user B jadi diizinkan.

### 2. Default baris per halaman = 10 di SEMUA tabel/list

`DEFAULT_PAGE_SIZE` diubah dari 15 → 10 di `mclock/views.py`, `mattendance/views.py`, `iclock/views.py`,
plus default parameter terkait (`iclock/views.py::_paginate()`, `mclock/mssql_client.py`,
`dashboard/views.py` user list, `accounts/services.py::paginate_users()`). `10` sudah ada di semua
`PAGE_SIZE_OPTIONS` sebelumnya, jadi tidak perlu ubah dropdown-nya.

### 3. Check/Meal dibatasi HANYA ke geofence yang PoolCode-nya terdaftar di `QRDEVICE`

Sebelum mencocokkan ke QR spesifik yang di-scan, kandidat geofence (`find_all_matching_pools_by_polygon()`)
sekarang **difilter dulu** — HANYA pool yang `PoolCode`-nya terdaftar sebagai key di `settings.QRDEVICE`
yang dipertimbangkan. Ini menegaskan Check/Meal cuma bisa terjadi di geofence yang memang
dikonfigurasi sebagai lokasi kantin, bukan geofence apa pun yang kebetulan match GPS. Pesan error
sekarang membedakan 2 kasus: "tidak di area kantin manapun yang terdaftar" (gagal di tahap filter ini)
vs "GPS tidak cocok dengan QR yang di-scan" (gagal di tahap cocokkan-ke-QR-spesifik).

**Sudah diuji**: GPS match geofence yang PoolCode-nya TIDAK ada di QRDEVICE → ditolak dgn pesan
spesifik; GPS match geofence yang PoolCode-nya ADA di QRDEVICE + QR sesuai → berhasil.

### 4. Login Mobile Attendance via PIN Employee (`accounts/mobile_backend.py`)

Employee bisa login **tanpa perlu akun `accounts.User`** sama sekali — cukup PIN + password mobile
baru (`employee.mpassword`, field baru, **di-hash pakai Django password hasher standar** — pilihan
SATU ARAH/irreversible, bukan enkripsi reversible, karena ini secara umum lebih aman untuk data
password; istilah "dienkripsi" di permintaan Anda saya artikan sebagai kebutuhan keamanan ini).

**Cara kerja**: `EmployeeMobileBackend` (backend autentikasi TERPISAH, dipanggil dgn kwargs
`pin`/`mobile_password` — beda dari `username`/`password` login reguler, jadi keduanya aman
berdampingan di `AUTHENTICATION_BACKENDS` tanpa saling bentrok) — begitu PIN+password valid, otomatis
cari **ATAU BUAT** 1 User "**mobile-only**" (`is_mobile_only=True`) khusus terkait Employee tsb.
Kalau Employee itu KEBETULAN sudah punya akun staff reguler (link `EmpID` manual oleh admin), shadow
user mobile-only ini **tetap dibuat TERPISAH** (tidak reuse akun staff itu) — memastikan akses login
mobile SELALU terbatas, walau orangnya adalah staff/admin di akun lain.

**Password default**: `123456` (`settings.MOBILE_DEFAULT_PASSWORD`, bisa diubah via `.env`). Selama
`employee.mpassword` masih kosong, login HANYA bisa pakai password default ini. Begitu berhasil
login dengan password yang MASIH default (kosong ATAU representasi `'123456'`), **middleware
memaksa** ke halaman ganti password (`/mattendance/change-password/`) — tidak bisa akses fitur lain
sampai diganti ke sesuatu yang **tidak kosong DAN tidak sama dengan default**.

**Pembatasan akses** (`accounts/middleware.py::MobileAccessMiddleware`) — user mobile-only HANYA
bisa akses: Check-in/Out, Check/Meal, Enrollment Wajah, ganti password mobile, dan logout. Akses ke
HALAMAN LAIN APA PUN (dashboard, admin, Mobile Pool, dst) otomatis dialihkan balik ke halaman
check-in dengan pesan. **User reguler (staff/LDAP/local) sama sekali tidak terpengaruh** middleware
ini — murni no-op untuk mereka.

Halaman login terpisah: `/mattendance/login/` (link timbal-balik dengan halaman login staff biasa).

```
python manage.py makemigrations accounts iclock
python manage.py migrate
```

**Sudah diuji sangat menyeluruh** (fitur paling berisiko dari keempatnya):
- **Autentikasi**: PIN+password default → sukses, shadow user dibuat; password salah/PIN tidak ada
  → ditolak; login ulang PIN sama → pakai shadow user yang SAMA (tidak duplikat); backend REGULER
  (username/password) dikonfirmasi **tidak terganggu** sama sekali oleh backend baru ini.
- **Alur wajib ganti password** (9 skenario end-to-end lewat view sungguhan): login default → dipaksa
  ke halaman ganti password; akses checkin sebelum ganti → tetap dipaksa balik; coba ganti ke
  `'123456'` lagi → ditolak; kosong → ditolak; konfirmasi tidak cocok → ditolak; ganti valid →
  berhasil, `mpassword` tersimpan ter-hash (dikonfirmasi BUKAN plaintext, format PBKDF2 standar
  Django); setelah ganti, akses checkin lancar TANPA dialihkan lagi; login ulang pakai password
  DEFAULT LAMA → sekarang gagal (sudah diganti); login pakai password BARU → berhasil & TIDAK
  diminta ganti lagi.
- **Middleware pembatasan akses**: whitelist (checkin/meal/enrollment) bisa diakses normal; SEMUA
  halaman lain (dashboard, admin, user management, Mobile Pool, dst) dikonfirmasi **ditolak &
  dialihkan** balik ke checkin; logout tetap berfungsi; **dikonfirmasi TIDAK ADA REGRESI** — user
  staff reguler DAN user non-staff biasa (bukan mobile-only) mengakses semua halaman seperti biasa,
  sama sekali tidak terpengaruh middleware ini.
- **Skenario koeksistensi paling penting**: Employee yang **SUDAH punya akun staff reguler** (link
  `EmpID` manual) login via PIN mobile → dikonfirmasi membuat shadow user **TERPISAH** (bukan reuse
  akun staff), akun staff aslinya **tidak terganggu** (`is_staff` tetap `True`).
- **End-to-end fungsional penuh**: user mobile-only berhasil enroll wajah SUNGGUHAN + check-in
  SUNGGUHAN (lewat Celery task, bukan mock langsung), log tercatat dengan `user` yang benar (shadow
  user, bukan akun staff manapun).

## 27x. Koreksi: Format `Function` Pakai PoolID, Bukan PoolCode

Diralat: format `Function` seharusnya `'<kode fungsi>-<PoolID>'` (mis. `'89-101'`), **bukan**
`'<kode fungsi>-<PoolCode>'` seperti implementasi awal (mis. `'89-114'`). Sudah diperbaiki di kedua
alur (check-in/out reguler & Check/Meal).

**Sudah diuji dengan PoolID & PoolCode yang SENGAJA dibuat berbeda jauh** (mis. `PoolID='101'`
dengan `PoolCode='999'`) — supaya kalau salah pakai field yang mana, langsung ketahuan dari hasil
test, bukan cuma diasumsikan benar. Dikonfirmasi hasil akhirnya persis `'89-101'` (pakai PoolID),
dan secara eksplisit dikonfirmasi BUKAN `'89-999'` (yang berarti keliru pakai PoolCode).

## 27w. Penentuan Kode `Function` Dinamis — KANTIN Diprioritaskan, Fallback Prefix PIN

Menggantikan asumsi hardcode sebelumnya (lihat catatan di 27v) — kode fungsi (`AttendanceLog.Function`)
sekarang ditentukan **dinamis**, berlaku SERAGAM untuk check-in/out reguler MAUPUN Check/Meal, sesuai
urutan prioritas:

1. **Cek KANTIN dulu (prioritas tertinggi)** — kalau PoolID yang match geofence terdaftar sebagai
   **KANTIN** (tabel baru `PoolDeviceFunction`, lihat di bawah), kode fungsi = `'X'` **LANGSUNG**,
   TIDAK PEDULI PIN user atau jenis check-in-nya.
2. **Fallback (kalau bukan KANTIN)**: dicek digit **PERTAMA** PIN employee terkait user (setelah
   leading zero zero-pad dihilangkan) — dicocokkan ke key `settings.DEVICEFUNCTION` (selain `'X'`)
   yang **mengandung** digit itu (mis. key `'89'` cocok untuk digit awal `8` ATAU `9`).

### Tabel baru: `PoolDeviceFunction` (mclock)

**BUKAN field tambahan di `MobilePool`/`MobilePoolLoc`** (sesuai arahan Anda) — kedua tabel itu
disinkronkan (mirror penuh) dari MSSQL eksternal, jadi field apa pun yang ditambahkan di sana akan
**hilang/tertimpa** begitu sync berikutnya jalan. `PoolDeviceFunction` sengaja **terpisah & TIDAK
disinkronkan dari mana pun** — murni mapping `PoolID → KANTIN/Bukan KANTIN`, dikelola **manual
sepenuhnya** lewat UI (menu sidebar "Pool Device Function", full CRUD: list, tambah, edit, hapus —
BEDA dari Mobile Pool/Mobile Pool Location yang cuma punya add/delete "testing").

### Sudah diuji
- **CRUD penuh**: tambah, PoolID duplikat (ditolak jelas), edit function type, hapus, search, akses
  non-staff ditolak.
- **Logika inti** (`determine_function_code()`), semua kombinasi:
  - Pool KANTIN → selalu `'X'`, dikonfirmasi **mengalahkan** PIN prefix apa pun (termasuk PIN yang
    seharusnya cocok `'89'`, `'1'`, dst kalau bukan kantin).
  - Pool bukan KANTIN → fallback ke prefix PIN, **semua 8 key** `DEVICEFUNCTION` diuji (`'89'` utk
    prefix 8/9, `'1'`, `'56'` utk 5/6, `'2'`, `'3'`, `'7'`, `'4'`, `'0'` khusus PIN semua-nol).
  - Pool tidak terdaftar sama sekali di `PoolDeviceFunction` → default diperlakukan Bukan KANTIN,
    fallback PIN tetap jalan.
  - Tanpa PIN (user tanpa Employee terkait) + pool bukan KANTIN → `Function=None` (tidak bisa
    ditentukan, field memang nullable).
  - Tanpa PIN + pool KANTIN → **tetap** `'X'` (cek KANTIN tidak butuh PIN sama sekali).
- **Integrasi end-to-end PALING PENTING** (membuktikan prioritas KANTIN > prefix PIN sungguhan,
  bukan cuma logika terisolasi): user dengan PIN prefix `8` check-in di pool **bukan** KANTIN →
  `Function='89-{PoolID}'`; **user & PIN yang SAMA PERSIS** check-in di pool **KANTIN** →
  `Function='X-{poolcode}'` — membuktikan KANTIN benar-benar menang, bukan asumsi di atas kertas.
  Diuji juga Check/Meal menghasilkan `Function` konsisten dengan pola yang sama.

## 27v. Check/Meal — Absen Makan Siang (GPS + QR Code)

Tipe check baru: **"Check/Meal"** — absen makan siang, verifikasi pakai **GPS + QR Code** (BUKAN
wajah, beda dengan check-in/out reguler). QR code dipakai juga untuk **disambiguasi geofence yang
overlap** (mis. kantin berdekatan dengan kantor utama).

> ℹ️ Field `Function` awalnya sempat di-hardcode (asumsi sementara, '89' utk reguler/'X' utk meal) --
> **sudah digantikan logika dinamis yang benar** (cek KANTIN dulu, fallback prefix PIN), lihat bagian
> 27w di bawah.

### Setting `QRDEVICE`
```python
# config/settings.py
QRDEVICE = {
    '114': 'KANTINQR-KANTOR1',
    '272': 'KANTINQR-KANTOR2',
    '250': 'KANTINQR-KANTOR3',
}
```
Format: `{'<poolcode>': '<isi qr code>'}`. `mattendance/qr_utils.py::get_poolcode_from_qr()` melakukan
reverse-lookup (dari isi QR yang di-scan, cari poolcode-nya).

### Alur disambiguasi geofence overlap
1. QR code di-scan (browser, kamera, library **jsQR** dari CDN jsDelivr) → dapat isi QR → cari
   PoolCode-nya lewat `QRDEVICE`. Kalau tidak dikenal → ditolak.
2. Koordinat GPS dicocokkan ke **SEMUA** polygon MobilePoolLoc yang match (`find_all_matching_pools_by_polygon()`,
   BUKAN cuma yang pertama ketemu seperti check-in/out reguler) — bisa lebih dari 1 hasil kalau ada
   overlap geofence.
3. Di antara hasil yang cocok secara GPS, cari yang `PoolCode`-nya **PERSIS SAMA** dengan hasil dari QR.
4. Kalau ketemu → `AttendanceLog` dibuat (`check_type='MEAL'`, `face_verified` selalu `False`,
   `Function='X-{poolcode}'`, `qr_content` disimpan utk audit). Kalau GPS tidak match sama sekali,
   ATAU match tapi tidak ada yang PoolCode-nya sesuai QR → ditolak, TIDAK dicatat (konsisten dgn
   prinsip yang sudah ada).

### Model
- `AttendanceLog.CheckType` — tambah pilihan `MEAL`.
- `AttendanceLog.Function` (baru) — format `'<kode>-<PoolID>'`, lihat `settings.DEVICEFUNCTION`.
- `AttendanceLog.qr_content` (baru) — isi QR yang di-scan, untuk audit.

```
python manage.py makemigrations mattendance
python manage.py migrate
```

### Sudah diuji
- **Skenario UTAMA (disambiguasi overlap)**: 2 geofence sengaja dibuat overlap (kantor besar +
  kantin kecil di dalamnya) — dikonfirmasi titik test match **KEDUA-DUANYA** sekaligus, lalu
  Check/Meal dengan QR kantin **berhasil memilih PoolID yang BENAR** (kantin, bukan kantor),
  `Function` & `qr_content` tersimpan benar.
- QR tidak dikenal → ditolak, tidak ada log.
- GPS tidak match geofence manapun → ditolak.
- GPS match, tapi PoolCode dari QR tidak ada di antara yang cocok (mismatch disambiguasi) → ditolak
  dengan pesan jelas.
- Check-in/out reguler: `Function` field terisi otomatis `'89-{PoolID}'` (mis. '89-101').
- Template list: entri `MEAL` tampil benar (badge "🍽️ Check/Meal", kolom Wajah = "N/A (pakai QR)",
  tidak crash).
- Sidebar, halaman Check/Meal (QR scanner via jsQR), dan card di beranda non-staff — semua muncul benar.

## 27u. Face Recognition Dilempar ke Celery Worker (Isolasi Proses)

Proses face recognition (ekstraksi encoding saat enrollment, verifikasi saat check-in/out) — yang
CPU-intensive karena pakai dlib — sekarang dijalankan di **Celery worker terpisah**, bukan langsung
di proses Django/Daphne utama. Tujuannya: supaya proses berat ini tidak berebut CPU dengan request
HTTP lain + koneksi WebSocket (console real-time Active Device) yang berjalan di proses yang sama.

### Arsitektur
- **`config/celery.py`** — konfigurasi Celery app, terhubung ke Django lewat `config/__init__.py`
  (pola integrasi standar Django+Celery).
- **Reuse Redis yang sama** dengan Django Channels (bukan infrastruktur baru) — DB index beda (`/1`
  vs default Channels `/0`) supaya key tidak tercampur dalam 1 instance Redis.
- **`mattendance/tasks.py`** — 2 task: `extract_face_encoding_task` (enrollment),
  `verify_face_task` (verifikasi check-in/out). Keduanya TIDAK melempar exception ke pemanggil — semua
  error (termasuk `FaceProcessingError`) dikembalikan sebagai bagian dari dict hasil
  (`{'success': False, 'error': '...'}`), supaya view cukup cek `result['success']`.
- **View (`face_enroll_submit`, `checkin_submit`)** — dispatch task via `.delay()`, TUNGGU hasilnya
  via `.get(timeout=15)`. Ini pola HYBRID: request HTTP tetap menunggu hasil (kontrak API ke
  frontend TIDAK berubah, tidak perlu ubah JS/template), TAPI komputasi CPU-intensive-nya sendiri
  terjadi di PROSES LAIN (worker), bukan proses Django yang menangani request-request lain.

### ⚠️ WAJIB dijalankan sebagai proses TERPISAH dari `manage.py runserver`
```
celery -A config worker --loglevel=info --pool=solo
```
**⚠️ WINDOWS**: WAJIB pakai `--pool=solo` (atau `--pool=threads --concurrency=N`) — pool default
Celery ("prefork") butuh `os.fork()` yang **tidak ada di Windows**, worker akan gagal/berperilaku
aneh tanpa flag ini. `--pool=solo` artinya 1 task diproses di satu waktu per worker — kalau butuh
proses beberapa check-in bersamaan, jalankan **beberapa proses worker** sekaligus (bukan ubah pool),
atau pakai `--pool=threads --concurrency=4`.

Tanpa worker ini berjalan, enrollment/check-in akan **menunggu sampai 15 detik lalu gagal** dengan
pesan jelas ("kemungkinan worker Celery belum jalan") — TIDAK hang selamanya, TIDAK crash.

### Sudah diuji (termasuk end-to-end dengan worker Celery SUNGGUHAN, bukan cuma mode eager)
- **Task ter-registrasi dengan benar** lewat jalur aplikasi (import `mattendance.tasks` otomatis
  terjadi saat `views.py` di-load, sesuai pola Django+Celery standar).
- **Mode eager** (`CELERY_TASK_ALWAYS_EAGER=True`, utk testing tanpa worker terpisah, mock
  `face_recognition`): enrollment sukses → `FaceProfile` tersimpan; check-in dgn wajah cocok →
  `AttendanceLog` dibuat lengkap dgn `face_distance`; wajah tidak cocok → gagal, tidak ada log baru.
- **Worker Celery SUNGGUHAN dijalankan** (`celery -A config worker --pool=solo`, proses process
  terpisah, BUKAN mock) — dikonfirmasi lewat log worker: task diterima
  (`Task ... received`) & selesai (`Task ... succeeded in ...s`) dengan format hasil yang benar.
- **Skenario worker TIDAK jalan** — request menunggu PERSIS 15 detik (sesuai `FACE_TASK_TIMEOUT_SECONDS`)
  lalu gagal dengan pesan jelas, bukan hang selamanya.
- **Skenario worker JALAN** (round-trip penuh: HTTP request → dispatch → worker sungguhan proses →
  hasil balik ke response) — respons kembali dalam **0.37 detik** (BUKAN timeout 15 detik),
  membuktikan dispatch-proses-terima-hasil benar-benar berjalan lewat Redis + proses worker terpisah.
  Karena `dlib` belum terinstall di lingkungan pengembangan ini, hasil yang diterima adalah pesan
  error "library belum terinstall" — TAPI ini justru pembuktian yang berharga: proses gagal dengan
  RAPI di level worker (tidak crash worker, tidak crash Django), errornya mengalir balik dengan benar
  ke response HTTP.

### Setup yang perlu Anda lakukan
```
pip install -r requirements.txt   # nambah celery & redis
# Jalankan di TERMINAL TERPISAH dari manage.py runserver:
celery -A config worker --loglevel=info --pool=solo
```
Redis yang SAMA dengan Channels sudah cukup (tidak perlu instance/infrastruktur baru) — pastikan
Redis service jalan sebelum start Django maupun Celery worker.

## 27t. Aksi Add/Delete Manual di Mobile Pool & Mobile Pool Location (Testing)

Ditambahkan tombol **"+ Tambah"** dan **"Hapus"** di kedua tabel (`Mobile Pool`, `Mobile Pool
Location`) — murni untuk **keperluan testing** (mis. bikin 1 geofence percobaan untuk coba check-in/
out tanpa perlu menunggu data sungguhan dari MSSQL). Sesuai catatan Anda: data yang ditambahkan manual
di sini akan **hilang/tertimpa** begitu `sync_mobile_pool`/`sync_mobile_pool_loc` dijalankan lagi
(keduanya mirror penuh) — jadi cuma cocok untuk uji coba sementara, bukan data permanen.

### Mobile Pool
- **"+ Tambah (Testing)"** — form PoolID (wajib unik, maks 5 karakter), PoolCode, PoolName, Latitude,
  Longitude, Radius (opsional — sudah tidak dipakai geofence, murni informasi).
- **Hapus** per baris — staff-only, konfirmasi sebelum submit.

### Mobile Pool Location (polygon)
- **"+ Tambah Titik (Testing)"** — form PoolID, Urut (kombinasi PoolID+Urut wajib unik), Latitude,
  Longitude. Setelah simpan, **kembali ke form yang sama** (bukan ke list) supaya bisa langsung
  tambah titik berikutnya tanpa bolak-balik — cocok untuk isi 1 polygon (minimal 3 titik) berturut-turut.
- **"Hapus Semua"** (per PoolID, di baris utama) — hapus SEMUA titik milik 1 PoolID sekaligus,
  kemudahan untuk bersihkan 1 polygon percobaan penuh.
- **"Hapus"** (per titik, di dalam "Lihat Titik") — hapus 1 titik individual saja.

### Sudah diuji
- Tambah `MobilePool` baru → tersimpan; PoolID duplikat → validation error jelas.
- Tambah 4 titik polygon dengan PoolID sama → tersimpan; titik duplikat (PoolID+Urut sama) →
  validation error jelas.
- **Verifikasi paling penting**: geofence yang baru ditambahkan manual **dikonfirmasi benar-benar
  berhasil dicocokkan** oleh `find_matching_pool_by_polygon()` — membuktikan alur "tambah geofence
  test → langsung bisa dipakai check-in" benar-benar berfungsi end-to-end.
- Hapus 1 titik individual → titik lain milik PoolID yang sama tidak ikut terhapus.
- "Hapus Semua" → seluruh titik PoolID terhapus sekaligus, flash message sebut jumlah yang dihapus;
  setelah itu, check-in di lokasi yang sama **dikonfirmasi gagal** (geofence sudah tidak ada).
- Hapus `MobilePool` → berhasil.
- Non-staff → ditolak akses semua aksi add/delete di kedua tabel.

## 27s. Face Verification — Enrollment & Verifikasi Wajah (`face_recognition`/dlib)

Verifikasi wajah AKTIF sekarang — check-in/out mobile attendance memverifikasi **DUA hal sekaligus**:
lokasi GPS (geofence polygon, sudah ada) **DAN** wajah (baru). Sesuai pilihan Anda: library
`face_recognition` (dlib), kamera lewat browser (`getUserMedia`).

### ⚠️ PENTING — instalasi `dlib` di Windows (dikonfirmasi langsung, bukan asumsi)

Saat membangun fitur ini, saya **coba install `dlib` langsung** untuk memastikan bisa diuji end-to-end
dengan library sungguhan. Temuan konkret:
- **Tidak ada wheel prebuilt DI PyPI** untuk `dlib` — dicek langsung (`pip download`), cuma ada
  *source distribution* (`.tar.gz`). Instalasi lewat `pip install dlib` biasa **selalu** butuh
  kompilasi dari sumber.
- Percobaan kompilasi di lingkungan Linux (yang BIASANYA lebih mudah dari Windows untuk hal ini)
  **masih belum selesai setelah 4.5+ menit**.
- **✅ Tapi ada jalan pintas yang jauh lebih praktis** (dikonfirmasi bekerja): wheel Windows **PREBUILT
  pihak ketiga** (bukan dari PyPI resmi, tapi banyak beredar & umum dipakai, mis. hasil build komunitas)
  seperti `dlib-19.24.1-cp310-cp310-win_amd64.whl` — instalasi lewat `pip install <file>.whl` langsung
  jadi **instan**, tanpa perlu compiler/CMake sama sekali. **Sangat disarankan** cari wheel prebuilt
  yang cocok versi Python Anda (cp310 = Python 3.10, dst) dari sumber terpercaya, daripada compile dari
  sumber.

### ⚠️ Perhatikan versi numpy — WAJIB `< 2.0`

**Ditemukan & dikonfirmasi**: wheel `dlib` prebuilt (seperti di atas) umumnya dikompilasi terhadap ABI
`numpy` versi 1.x. Kalau `numpy` di server ter-upgrade ke versi **2.x**, `face_recognition` akan gagal
dengan:
```
RuntimeError: Unsupported image type, must be 8bit gray or RGB image.
```
...walau shape/dtype array gambarnya **sudah benar** — dikonfirmasi lewat laporan komunitas resmi
`face_recognition`/`dlib` yang PERSIS kasus yang sama (dlib 19.24.99 + numpy 2.0.0 + Windows 11, error
identik). **Solusi**: pastikan `numpy < 2.0` terinstall:
```
pip install "numpy<2"
```
`requirements.txt` sudah disesuaikan (`numpy>=1.26,<2.0`) supaya `pip install -r requirements.txt`
otomatis pasang versi yang kompatibel — tapi kalau `numpy` 2.x SUDAH terlanjur ter-install duluan
(mis. dari dependency lain), perlu **downgrade manual** dengan command di atas.

Sebagai pengaman TAMBAHAN (di luar soal versi numpy), `mattendance/face_utils.py::decode_base64_image()`
sekarang juga secara eksplisit memaksa array jadi `uint8` + `C-contiguous`
(`np.ascontiguousarray(np.array(image, dtype=np.uint8))`) sebelum dikirim ke `face_recognition` —
pengaman umum lain yang sering jadi solusi utk error serupa ini di berbagai laporan komunitas.

Kalau instalasi tetap gagal/terlalu lama walau sudah pakai wheel prebuilt, ada 2 alternatif (butuh
penyesuaian kode kalau mau pindah):
- **OpenCV (`opencv-contrib-python`)** — installable via wheel prebuilt resmi (`pip install` langsung
  jalan, tanpa compiler), tapi akurasinya lebih sederhana (LBPH, bukan deep learning embedding).
- **Cloud API** (Azure Face / AWS Rekognition) — tanpa install ML lokal sama sekali, tapi butuh
  internet aktif & ada biaya per panggilan API.

**Karena keterbatasan ini, saya TIDAK BISA menjalankan test end-to-end dengan `dlib`/`face_recognition`
sungguhan di lingkungan pengembangan** — semua logic wrapper (`mattendance/face_utils.py`) sudah diuji
lewat mock yang meniru API resmi `face_recognition` PERSIS sesuai dokumentasi (lihat bagian "Sudah
diuji" di bawah), plus `decode_base64_image()` sudah diuji dengan gambar SUNGGUHAN (memverifikasi hasil
akhirnya benar `uint8`+`contiguous`) — tapi keseluruhan alur **belum tervalidasi dengan model dlib
sungguhan**. Setelah instalasi & fix numpy selesai di server Anda, mohon uji langsung 1 kali (enroll +
check-in) untuk konfirmasi akhir.

### Alur

1. **Enrollment** (`/mattendance/face/enroll/`, menu sidebar "🙂 Enrollment Wajah") — user foto wajah
   sendiri lewat webcam (mirip daftar wajah di mesin ZKTeco), sistem ekstrak **face encoding** (128
   angka desimal mewakili ciri wajah — **BUKAN foto**, secara matematis tidak bisa direkonstruksi balik
   jadi gambar mirip aslinya, tapi tetap data biometrik sensitif) dan simpan sebagai referensi
   (`FaceProfile`, 1 user = 1 profil, enroll ulang **mengganti** yang lama).
2. **Check-in/out** (`/mattendance/checkin/`) — SEKARANG kamera JUGA aktif bersamaan dengan GPS. Saat
   tombol ditekan: foto wajah di-capture, dikirim bareng koordinat GPS. Server verifikasi **keduanya**:
   - Kalau belum pernah enroll → ditolak, diarahkan ke halaman enrollment.
   - Kalau lokasi di luar polygon pool manapun → ditolak (seperti sebelumnya).
   - Kalau wajah tidak cocok dengan `FaceProfile` (`face_recognition.face_distance` di atas
     `FACE_MATCH_TOLERANCE=0.6`, default resmi library) → ditolak.
   - **Cuma kalau KEDUANYA berhasil** → `AttendanceLog` dibuat (`location_verified=True,
     face_verified=True`, plus `face_distance` buat audit).

### Model & implementasi
- **`FaceProfile`** (baru) — `user` (OneToOne), `encoding` (`JSONField`, list 128 float).
- **`mattendance/face_utils.py`** — `decode_base64_image()` (dari `<canvas>.toDataURL()` browser),
  `extract_face_encoding()`, `verify_face()`. Import `face_recognition` LAZY (baru diimpor saat
  dipakai) supaya sisa aplikasi tetap jalan normal walau library ini belum/gagal terinstall.
- `AttendanceLog.face_distance` (baru) — jarak Euclidean hasil perbandingan, untuk audit.

```
python manage.py makemigrations mattendance
python manage.py migrate
```

### Sudah diuji
- **`decode_base64_image()` diuji dengan GAMBAR SUNGGUHAN** (Pillow/numpy asli, bukan mock — bagian
  ini tidak butuh dlib) — decode data-URI dari canvas, decode tanpa prefix, base64 korup → error rapi,
  **dan hasil akhirnya dikonfirmasi selalu `uint8` + `C-contiguous`** (properti yang WAJIB diterima
  dlib, lihat catatan fix numpy 2.x di atas) lewat pengecekan `.dtype`/`.flags['C_CONTIGUOUS']` langsung.
- **`extract_face_encoding()`/`verify_face()` diuji lewat mock API `face_recognition`** (meniru
  `face_locations`/`face_encodings`/`face_distance` PERSIS sesuai dokumentasi resmi): 1 wajah → sukses;
  0 wajah → error jelas; >1 wajah → error jelas (ambigu); wajah cocok (distance rendah) → matched;
  wajah tidak cocok (distance tinggi) → tidak matched.
- **Dikonfirmasi juga**: tanpa `dlib` terinstall sama sekali (kondisi nyata sandbox ini) → error jelas
  ("library belum terinstall"), BUKAN crash — penting karena ini kemungkinan kondisi awal server Anda
  sebelum instalasi `dlib` selesai.
- **Integrasi penuh di view** (mock `face_recognition`): enrollment sukses & enrollment ulang
  (mengganti, bukan menambah); check-in sukses (lokasi+wajah cocok, log dibuat lengkap dgn
  `face_distance`); geofence OK tapi wajah tidak cocok → gagal, TIDAK ada log; wajah cocok tapi
  geofence gagal → gagal total; belum enroll → ditolak dgn `needs_enrollment`; tidak kirim foto sama
  sekali → 400 jelas.
- Halaman check-in: tombol check-in/out ter-disable otomatis kalau belum enroll, aktif lagi setelah
  enroll berhasil.

## 27r. Perbaikan: Crash saat MobilePool Terkait Log Dihapus, + Aksi Hapus Log

**Bug dilaporkan**: setelah `MobilePool` dihapus (`AttendanceLog.PoolID` otomatis jadi `NULL` lewat
`SET_NULL`), membuka halaman Attendance Log List di browser **error**.

**Direproduksi persis** dan ditemukan akar masalahnya:
```
django.template.base.VariableDoesNotExist: Failed lookup for key [PoolID] in None
```
Di template ada `{{ log.PoolID.PoolName|default:log.PoolID.PoolID|default:"-" }}` — bagian
`log.PoolID.PoolID` dipakai sebagai **argumen filter `default`**, dan ternyata argumen filter TIDAK
mendapat perlindungan "silent failure" yang sama seperti variabel biasa `{{ ... }}` di Django. Begitu
`log.PoolID` bernilai `None`, mengakses `.PoolID` lagi di posisi argumen filter benar-benar melempar
exception (bukan cuma render kosong seperti yang diharapkan).

**Perbaikan**: diganti pakai `{% if log.PoolID %}` eksplisit dulu sebelum mengakses field turunannya
— log yang PoolID-nya sudah `NULL` (pool sumbernya terhapus) sekarang tampil rapi dengan indikator
**"- (pool dihapus)"**, tidak crash.

### Aksi Hapus di tabel Attendance Log

Sesuai permintaan, ditambahkan tombol **Hapus** per baris (staff-only, konfirmasi JS sebelum submit)
— supaya log "yatim" (PoolID sudah `NULL`) atau log manapun yang tidak diperlukan lagi bisa dibersihkan
manual dari UI, tidak harus lewat shell/DB langsung.

### Sudah diuji
- **Bug direproduksi persis** (pesan error identik) sebelum diperbaiki.
- Setelah fix: halaman list render normal (200, bukan 500) dengan log ber-PoolID `NULL`, indikator
  "pool dihapus" tampil, log lain (yang PoolID-nya masih valid) tetap tampil normal.
- Hapus log ber-PoolID `NULL` → berhasil terhapus, flash message sukses, log LAIN tidak ikut terhapus.
- GET (bukan POST) ke endpoint hapus → ditolak 405.
- Hapus log dengan ID yang tidak ada → 404 rapi (bukan crash).
- Non-staff → ditolak akses hapus.

## 27q. Geofence Polygon (Mobile Pool Location) — Menggantikan Radius Lingkaran

Geofence check-in/out sekarang berbasis **polygon presisi**, bukan lagi radius lingkaran dari titik
tunggal. Tabel baru **`MobilePoolLoc`** (submenu sidebar **"Mobile Pool Location"**) menyimpan
titik-titik (vertex) polygon per `PoolID`, disinkronkan dari MSSQL (tabel sumber `dbo.MsPool_Loc`,
server/database sama dengan Mobile Pool: `HBCLOUD3/General`).

```python
PoolID  varchar(5)
Urut    decimal(18,2)   # urutan titik dalam polygon (menentukan urutan keliling)
Latitude  varchar(MAX)  nullable
Longitude varchar(MAX)  nullable
```

**`MobilePool`** (tabel radius yang lama) **tetap ada & tetap disinkronkan** — sekarang murni dipakai
sebagai **lookup** (PoolName/PoolCode untuk ditampilkan setelah polygon yang cocok ditemukan), bukan
lagi sumber pengecekan geofence itu sendiri.

### Koreksi nama tabel sumber (Mobile Pool biasa)

Sekalian dikoreksi: `sync_mobile_pool.py` sebelumnya menebak nama tabel sumber `dbo.MobilePool` —
**sudah dikonfirmasi & diperbaiki jadi `dbo.MsPool`**.

### Algoritma: Ray Casting (point-in-polygon)

`mattendance/geofence.py::point_in_polygon()` — implementasi standar (varian PNPOLY, W. Randolph
Franklin), cek apakah 1 titik GPS berada di dalam polygon dengan vertex sembarang bentuk (termasuk
**cekung/concave**, bukan cuma bentuk convex sederhana). `find_matching_pool_by_polygon()`
mengelompokkan `MobilePoolLoc` per `PoolID` (diurutkan `Urut`), membentuk polygon, lalu cek titik user
ada di dalam polygon mana. Kalau PoolID punya < 3 titik, otomatis dilewati (bukan polygon valid) —
ditandai peringatan "⚠️ belum cukup" di halaman list.

Fungsi radius lama (`find_matching_pool`) **tidak dihapus** (dibiarkan ada di kode untuk
referensi/kemungkinan dipakai lagi), tapi **tidak lagi dipanggil** dari alur check-in aktif
(`mattendance/views.py::checkin_submit`) — digantikan `find_matching_pool_by_polygon`.

`AttendanceLog.distance_meters` sekarang **selalu `None`** untuk check-in baru (konsep "jarak ke
radius" tidak relevan lagi untuk polygon) — field-nya tidak dihapus dari model (kompatibilitas data
lama), cuma tidak lagi diisi.

### Sinkronisasi (mirror, sama seperti Mobile Pool)
```
python manage.py sync_mobile_pool_loc
```
Sama seperti `sync_mobile_pool`: **mirror penuh** — titik yang sudah tidak ada di sumber (baik
individual titiknya, maupun SELURUH PoolID-nya kalau polygon itu dihapus total) ikut terhapus dari
lokal, dengan safety net yang sama (sumber kosong = tidak menghapus apa pun).

### Sudah diuji (rigor sama seperti Haversine sebelumnya)
- **`point_in_polygon()` divalidasi terhadap kasus geometri yang sudah diketahui pasti**: kotak
  sederhana (titik tengah/luar/pojok), segitiga, **polygon cekung (L-shape)** — kasus yang lebih ketat
  dari sekadar bentuk convex, koordinat GPS realistis skala kantor kecil.
- `find_matching_pool_by_polygon()`: titik di tengah polygon → cocok; titik jauh di luar → tidak cocok.
- Check-in end-to-end via view: sukses pakai polygon (bukan radius lagi), `distance_meters` kosong.
- Sync: create/update/delete titik individual, **dan** hapus total kalau seluruh PoolID hilang dari
  sumber — **setelah situasi itu, dikonfirmasi check-in di koordinat lama langsung gagal** (skenario
  identik dengan bug yang pernah dilaporkan untuk Mobile Pool radius, sekarang diverifikasi juga aman
  untuk versi polygon-nya).
- Safety net sumber kosong tidak menghapus data yang masih valid.
- Halaman Mobile Pool Location: grouped per PoolID, expand lihat titik, peringatan kalau < 3 titik.

## 27p. Perbaikan: Pool yang Dihapus dari Sumber Tetap Bisa Dipakai Check-in

**Bug dilaporkan**: check-in/out tetap berhasil match ke suatu PoolID walau PoolID itu sudah dihapus.
**Bukan cache browser** — geofence check-in 100% server-side (browser cuma kirim koordinat GPS
mentah, pencocokan pool terjadi lewat query database saat itu juga, tidak ada yang di-cache di
browser sama sekali).

### Akar masalah

`sync_mobile_pool_from_source()` (dipanggil oleh `python manage.py sync_mobile_pool`) sebelumnya
cuma melakukan **create/update** (`update_or_create`) — kalau suatu PoolID dihapus dari tabel sumber
di MSSQL lalu sync dijalankan ulang, record `MobilePool` lokalnya **TIDAK ikut terhapus**, tetap
"hidup" selamanya di database lokal, dan tetap dipakai untuk verifikasi geofence check-in/out.

### Perbaikan

`sync_mobile_pool_from_source()` sekarang jadi sinkronisasi **penuh (mirror)** — setelah
create/update, PoolID yang ADA di database lokal tapi **sudah tidak ada** di hasil fetch dari MSSQL
akan **dihapus**. Log historis (`AttendanceLog`) yang pernah mereferensikan pool tersebut **tidak
ikut terhapus** (`on_delete=SET_NULL` sudah benar sejak awal) — cuma `PoolID`-nya jadi kosong,
riwayat check-in-nya tetap ada untuk audit.

**Safety net**: kalau hasil fetch dari MSSQL kebetulan **kosong** (mis. query sumber gagal parsial/
koneksi putus di tengah), sync **TIDAK menghapus apa pun** — lebih aman salah "biarkan pool lama"
daripada tidak sengaja menghapus SEMUA pool gara-gara sumbernya kebetulan kosong sesaat.

### Sudah diuji — reproduksi PERSIS skenario yang dilaporkan
1. Sync awal → 2 pool tersimpan lokal.
2. Check-in **berhasil** ke salah satu pool (persis skenario Anda).
3. Pool itu dihapus dari sumber, sync ulang → **dikonfirmasi terhapus** dari lokal, pool lain **tidak
   ikut terhapus**.
4. Log historis check-in tadi **tetap ada** (tidak ikut terhapus), tapi `PoolID`-nya otomatis `NULL`.
5. **Verifikasi utama**: coba check-in lagi di koordinat yang sama → **sekarang gagal** (sebelumnya
   ini yang jadi bug yang Anda laporkan).
6. Sync dengan data sumber kosong → dikonfirmasi **tidak menghapus** pool yang masih valid (safety net).

## 27o. Perbaikan: CSRF Gagal di Belakang nginx (SSL Termination)

Ditemukan & diperbaiki: saat deploy di belakang nginx dengan SSL/HTTPS **diterminasi di nginx**
(nginx pegang sertifikat, proxy ke Django/Daphne via HTTP biasa di belakangnya), login & semua form
POST gagal dengan:
```
Forbidden (Origin checking failed - https://domain-anda does not match any trusted origins.)
```

### Akar masalah

Django 4+ **wajib** memvalidasi header `Origin` request POST terhadap daftar domain yang eksplisit
dipercaya. Tanpa itu, Django membandingkan Origin browser (`https://domain-anda`) dengan origin yang
DIA HITUNG SENDIRI dari request yang diterimanya — dan karena nginx meneruskan sebagai HTTP biasa
(tanpa header tambahan), Django mengira requestnya **HTTP**, bukan HTTPS, sehingga muncul mismatch
`https://` (dari browser) vs `http://` (yang dikira Django) → CSRF ditolak.

**Sudah dibuktikan dengan reproduksi bug PERSIS** (pesan error identik) di lingkungan testing,
lalu diverifikasi 2 komponen fix-nya masing-masing benar-benar menyelesaikan:

### Perbaikan (`config/settings.py` + `.env`)

1. **`CSRF_TRUSTED_ORIGINS`** (WAJIB) — daftar domain publik yang dipercaya, lengkap dengan skema
   `https://`, dipisah koma di `.env`:
   ```
   CSRF_TRUSTED_ORIGINS=https://absensi.perusahaan.com,https://www.perusahaan.com
   ```
2. **`SECURE_PROXY_SSL_HEADER`** — supaya Django tahu request aslinya HTTPS meski diterima sebagai
   HTTP dari nginx (penting juga untuk perilaku lain di luar CSRF: link `https://` yang dihasilkan
   Django, cookie Secure, dll) — **WAJIB dipasangkan dengan config nginx di bawah**, jangan salah satu saja.
3. **`SESSION_COOKIE_SECURE`** / **`CSRF_COOKIE_SECURE`** — otomatis `True` di produksi (`DEBUG=False`),
   supaya cookie session/CSRF cuma dikirim lewat HTTPS.

### Konfigurasi nginx yang WAJIB menyertai (`proxy_set_header`)

`SECURE_PROXY_SSL_HEADER` di Django **TIDAK BERGUNA** (bahkan jadi risiko keamanan) kalau nginx tidak
benar-benar mengirim/menimpa header ini. Pastikan config nginx Anda punya minimal ini di block
`location` yang proxy ke Django:

```nginx
location / {
    proxy_pass http://127.0.0.1:8000;  # ganti sesuai alamat Daphne/gunicorn Anda
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;  # <-- INI YANG PALING PENTING utk fix CSRF di atas
}

# WebSocket (Active Device console real-time, iclock/consumers.py) --
# butuh header upgrade TERPISAH, gampang terlewat kalau cuma copy config HTTP biasa:
location /ws/ {
    proxy_pass http://127.0.0.1:8000;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

⚠️ Kalau `proxy_set_header X-Forwarded-Proto $scheme;` TIDAK ada di config nginx Anda, mengaktifkan
`SECURE_PROXY_SSL_HEADER` di Django **tanpa** ini adalah celah keamanan (client bisa memalsukan header
`X-Forwarded-Proto` sendiri, membuat Django salah percaya request aman padahal tidak) — pastikan
kedua sisi (Django + nginx) diubah bersamaan, bukan salah satu saja.

### Sudah diuji
- **Bug asli direproduksi persis** (pesan error identik: "Origin checking failed - https://... does
  not match any trusted origins") lewat simulasi kondisi nginx SSL termination (Django menerima
  sebagai HTTP, browser kirim `Origin: https://`).
- **`CSRF_TRUSTED_ORIGINS` saja** (tanpa `SECURE_PROXY_SSL_HEADER`) → terverifikasi **menyelesaikan**
  error yang dilaporkan.
- **`SECURE_PROXY_SSL_HEADER` + header nginx yang benar** (tanpa `CSRF_TRUSTED_ORIGINS`) → juga
  terverifikasi **menyelesaikan** (Django jadi tahu requestnya HTTPS, origin self-consistency lolos).
- Kontrol (tanpa kedua fix) → dikonfirmasi tetap 403, membuktikan reproduksi & fix-nya valid.
- Konfigurasi diterapkan bersamaan (rekomendasi produksi) karena `SECURE_PROXY_SSL_HEADER` juga
  memengaruhi hal lain di luar CSRF (link absolut HTTPS, cookie Secure), bukan cuma untuk fix spesifik ini.

## 27n. Mobile Attendance GPS & Face Recognition (app baru `mattendance`)

App Django baru **`mattendance`** — check-in/out absensi mobile pakai **GPS geofence** (aktif &
berfungsi) dan **Face Recognition** (field disiapkan, logic BELUM diimplementasikan — lihat catatan
di bawah). Sesuai arahan Anda: fokus dulu ke geofence yang bisa langsung ditest.

### Model `AttendanceLog`

Field inti sesuai permintaan: `user` (FK ke User), `timestamp`, `PoolID` (FK ke `mclock.MobilePool`),
`location_verified`, `face_verified`. **Field tambahan** (di luar spesifikasi asli, ditambahkan untuk
kelengkapan praktis — hapus/sesuaikan kalau tidak diperlukan):
- `check_type` (IN/OUT) — supaya bisa bedakan check-in vs check-out, tidak eksplisit diminta tapi
  terasa perlu untuk sistem absensi.
- `latitude`/`longitude` — koordinat GPS yang DIKIRIM user (untuk audit/investigasi kalau ada yang
  aneh, mis. kenapa suatu check-in gagal).
- `distance_meters` — jarak ke pool yang cocok, juga untuk audit.

```
python manage.py makemigrations mattendance mclock
python manage.py migrate
```

### Alur check-in/out (geofence)

1. User buka halaman **Check-in/Out** (`/mattendance/checkin/`, menu sidebar "📍 Check-in/Out (GPS)"
   untuk staff, atau card "Check-in/Out (GPS)" di beranda untuk non-staff — **selalu tersedia untuk
   semua user login**, tidak digerbangi permission seperti Transfer Finger/Attendance Recap, karena
   absensi adalah kebutuhan universal).
2. Klik tombol Check-in/Check-out → browser minta izin GPS (`navigator.geolocation`).
3. Koordinat dikirim ke server → dicocokkan dengan **semua MobilePool** (Haversine formula, jarak
   ke titik pool dibandingkan dengan `Radius`-nya — **diasumsikan dalam meter**, konvensi umum GPS
   geofencing; kalau satuan Anda beda, ada 1 baris konstanta yang tinggal diubah di `geofence.py`).
4. **Sesuai permintaan**: HANYA kalau cocok dengan salah satu pool (`location_verified=True`) yang
   dicatat ke `AttendanceLog`, dengan `PoolID` diisi pool yang cocok. Percobaan yang **gagal** (di luar
   radius semua pool) **TIDAK dicatat** — cuma dikembalikan pesan gagal ke user.
5. Kalau ada beberapa pool yang overlap radiusnya, dipilih yang **paling dekat**.

### ⚠️ Face Recognition — BELUM diimplementasikan

Field `face_verified` sudah ada di model (default `False`), tapi **logic verifikasi wajah sungguhan
belum dibuat** — sesuai arahan Anda untuk fokus geofence dulu. Untuk tahap berikutnya, akan perlu
diputuskan: library apa (`face_recognition`/`dlib`, layanan cloud, dsb), bagaimana wajah referensi
disimpan/didaftarkan per user, dan bagaimana foto diambil dari browser (`<input capture="camera">`
atau `getUserMedia`). Beri tahu detailnya kalau sudah siap lanjut ke tahap ini.

### Halaman admin: Attendance Log

`/mattendance/logs/` (staff-only, menu sidebar "📋 Log Absensi GPS") — daftar semua
`AttendanceLog`, search (username/nama/nama pool), sort, pagination standar. Berguna untuk
verifikasi hasil testing geofence.

### Sudah diuji
- **Formula Haversine divalidasi terhadap jarak dunia nyata yang sudah diketahui**: konstanta
  0.01° latitude ≈ 1113m, jarak Monas–Bandara Soekarno-Hatta (~20km), simetri A→B = B→A.
- `find_matching_pool()`: user tepat di lokasi pool (jarak ~0), dalam radius (cocok), di luar radius
  (tidak cocok), pool dengan koordinat/radius korup dilewati tanpa crash, beberapa pool sekaligus.
- Check-in dalam radius → **log dibuat**, `location_verified=True`, `face_verified=False`
  (placeholder), `PoolID` benar.
- Check-out di luar radius → **log TIDAK dibuat** (sesuai permintaan "kalau berhasil baru masuk log").
- Koordinat tidak valid → error 400 jelas, tidak crash.
- GET ke endpoint submit → ditolak 405.
- Non-staff bisa check-in/out, tapi **tidak bisa** akses halaman admin Attendance Log.
- Belum login → ditolak semua akses.
- Card "Check-in/Out (GPS)" muncul di beranda non-staff (tidak digerbangi permission).

### Catatan operasional penting
- **Geolocation API browser butuh HTTPS** (atau `localhost` untuk testing) — tidak akan berfungsi di
  HTTP biasa di production. Pastikan server produksi Anda sudah pakai HTTPS untuk fitur ini berfungsi.
- Asumsi satuan `Radius` = **meter** — kalau ternyata data `MobilePool` Anda pakai kilometer, ubah
  `RADIUS_UNIT_TO_METERS` di `mattendance/geofence.py`.

## 27m. Field `EmpID` di User (Manajemen User) — Link ke Employee

User (`accounts.User`) sekarang punya field **`EmpID`** — link opsional ke tabel `employee` (iclock),
untuk mengaitkan akun login dengan data karyawan fisiknya. Ditambahkan ke **List, Add, dan Edit** di
Manajemen User.

```
python manage.py makemigrations accounts
python manage.py migrate accounts
```
(Migrasi `accounts` akan otomatis membawa migrasi `iclock` juga kalau belum ada, karena FK ini
membuat `accounts` bergantung pada `iclock`.)

### ⚠️ Pertimbangan penting: PIN di `employee` TIDAK unique

Selama implementasi ditemukan: `employee.PIN` **bukan** primary key tabel itu (primary key aslinya
`id`/`userid`) dan **tidak** punya constraint unique — karena satu PIN yang sama bisa terdaftar di
**beberapa device berbeda** (tiap kombinasi PIN+device jadi row `employee` terpisah). Konsekuensinya:

- FK `EmpID` merujuk ke primary key ASLI (`id`), **bukan** ke `PIN` — Django bahkan akan menolak kalau
  dipaksa `to_field='PIN'` karena field itu tidak unique. Kalau butuh PIN/nama karyawannya, akses
  lewat relasi (`user.EmpID.PIN`, `user.EmpID.EName`), **jangan asumsikan** `user.EmpID_id` sama
  dengan nilai PIN.
- Form (create & edit) mencari employee berdasarkan PIN lewat autocomplete, tapi kalau PIN yang
  dipilih ternyata terdaftar di **lebih dari satu device**, sistem **mengambil match pertama** yang
  ketemu (tidak crash `MultipleObjectsReturned`) — cukup baik untuk keperluan "kaitkan akun ke
  representasi karyawan", tapi bukan pemilihan device-registration yang spesifik.

### UI & implementasi
- **Autocomplete search-as-you-type** (bukan `<select>` dropdown biasa, karena jumlah employee bisa
  banyak) — reuse endpoint `iclock:ajax_employee_search` yang sudah ada (dipakai juga oleh Attendance
  Recap), pola JS yang identik: ketik → cari → klik saran → PIN ke-isi ke hidden field.
- Field asli yang disubmit (`emp_id`) adalah **hidden input**; kotak yang terlihat murni UI pencarian.
- **List**: kolom "Employee" baru, tampilkan PIN + Nama (atau "-" kalau belum di-link). Query pakai
  `select_related('EmpID')` supaya tidak N+1.
- **Hapus Employee** → `EmpID` otomatis jadi `NULL` (`on_delete=SET_NULL`), User-nya **tidak ikut
  terhapus** (menghapus data karyawan tidak boleh menghapus akun login orangnya).

### Sudah diuji (termasuk 1 bug nyata yang ditemukan & diperbaiki saat testing)
- **Bug ditemukan**: pola mixin awal (`EmployeeLinkFormMixin`) untuk field `emp_id` **tidak
  ter-collect** oleh metaclass Django Forms (field dari mixin murni/non-`Form` tidak dikenali) —
  diperbaiki dengan duplikasi field langsung di kedua form (`LocalUserCreateForm`/`UserEditForm`),
  dikonfirmasi lewat cek langsung `'emp_id' in form.fields`.
- Create user dengan employee terisi & kosong, PIN tidak ditemukan → validation error jelas.
- Edit: ganti employee, hapus employee (kosongkan) — keduanya ter-update benar di database.
- Pre-fill form edit menampilkan "PIN - Nama" yang benar di kotak pencarian + hidden field.
- Kolom Employee tampil benar di List.
- **PIN duplikat lintas device** — dikonfirmasi tidak crash, berhasil pilih salah satu match.
- Employee dihapus → `EmpID` User terkait otomatis `NULL`, User-nya sendiri tetap ada (tidak ikut terhapus).

## 27l. Perbaikan Koneksi MSSQL Lama (SQL Server 2008) & Fitur Mobile Pool

### Perbaikan koneksi & pagination untuk SQL Server versi lama

Ditemukan (via testing langsung ke `HUPDBTMS/dbBMS`, SQL Server 2008) dua masalah kompatibilitas:

1. **Koneksi gagal** ("Adaptive Server connection failed") — SQL Server 2008 butuh parameter
   `tds_version='7.0'` eksplisit saat konek. Ditambahkan `MCLOCK_MSSQL_TDS_VERSION` (default `'7.0'`
   di `.env`), bisa di-override PER SOURCE lewat key `'tds_version'` di `mclock/sources.py` kalau ada
   server lain yang ternyata butuh versi berbeda.
2. **`OFFSET ... FETCH NEXT ... ROWS ONLY` tidak didukung** — fitur ini baru ada di SQL Server 2012+.
   `mclock/mssql_client.py` sekarang **deteksi versi SQL Server otomatis** (query
   `SERVERPROPERTY('ProductVersion')`, di-cache per server/database pakai `@lru_cache` supaya tidak
   query ulang tiap request — versi server praktis tidak pernah berubah selama aplikasi jalan):
   - **Versi mayor ≥ 11** (SQL Server 2012+): pakai `OFFSET/FETCH` seperti sebelumnya.
   - **Versi mayor < 11** (2008/2008 R2/2005), **atau gagal dideteksi** (mis. permission
     `SERVERPROPERTY` terbatas): fallback ke `ROW_NUMBER() OVER (...)` + `WHERE rn BETWEEN ...`, yang
     didukung SQL Server 2005+ — jauh lebih kompatibel. Kolom `rn` internal otomatis dibuang dari hasil.

Sudah diuji: parsing versi dari string (`'10.50.6000.34'` → 10, `'12.0.2000.8'` → 12), caching bekerja
(query versi cuma sekali meski dipanggil berkali-kali), gagal deteksi versi → fallback aman (bukan
crash), kedua jalur SQL (OFFSET/FETCH vs ROW_NUMBER) menghasilkan query & parameter yang benar.

### Fitur baru: Mobile Pool

Submenu **"Mobile Pool"** (di bawah Mobile Attendance) — BEDA dari submenu lain: ini tabel **lokal**
di database Django (`mclock.MobilePool`, field `PoolID` (PK, varchar 5), `PoolCode`, `PoolName`,
`Latitude`, `Longitude`, `Radius`, plus `SyncedAt` tambahan untuk monitoring kapan sync terakhir),
diisi lewat **sinkronisasi** dari MSSQL, bukan baca langsung ke MSSQL tiap request seperti submenu
lainnya — dipakainya Django ORM biasa (search/sort/pagination standar, sama seperti tabel-tabel
iclock lainnya).

```
python manage.py makemigrations mclock
python manage.py migrate mclock
```

**Status konfigurasi command sync**: `mclock/management/commands/sync_mobile_pool.py` sudah jadi
scaffold penuh (logika create/update, penanganan error, dipisah jadi fungsi
`sync_mobile_pool_from_source()` yang gampang dipanggil ulang dari Celery task nanti). Server/database
sumber sudah **dikonfirmasi**: `HBCLOUD3/General` (bukan `GeneralMitra` yang dipakai submenu Mitra
Mobile — database beda walau server sama).

⚠️ **Nama tabelnya sendiri masih TEBAKAN** — dipakai `dbo.MobilePool` (mengikuti pola nama model
Django-nya), belum dikonfirmasi. Kalau nama tabel sungguhan di MSSQL beda, tinggal ganti di
`MOBILE_POOL_SOURCE_SQL` (kalau nama kolom sumbernya juga beda dari `PoolID`/`PoolCode`/`PoolName`/
`Latitude`/`Longitude`/`Radius`, tinggal alias pakai `AS`, sama seperti pola di `mclock/sources.py`).

Sudah diuji: `sync_mobile_pool_from_source()` (logika inti) → pool baru ter-`create`, pool yang sudah
ada ter-`update` (termasuk `SyncedAt` ter-isi benar) — pakai data mock. Juga diperbaiki:
**error saat query dieksekusi** (mis. nama tabel salah, kolom tidak ada) sekarang dibungkus rapi jadi
`MSSQLConnectionError` yang sama (bukan traceback pymssql mentah) — perbaikan ini berlaku untuk
SEMUA fitur MSSQL (`run_query()`), bukan cuma sync Mobile Pool, supaya kalau tebakan nama tabel di
atas ternyata salah, errornya akan tampil jelas & rapi, bukan crash membingungkan.

## 27k. Mobile Attendance (app baru `mclock`) — Monitoring MSSQL Eksternal

App Django baru **`mclock`** + menu sidebar **"Mobile Attendance"** (submenu expandable, 5 item) —
untuk memantau (read-only) data absensi mobile dari **5 sumber MSSQL eksternal** (di luar database
Django ini). Data ini dijadwalkan ditarik ke database Django oleh proses terpisah di luar sistem ini;
halaman ini murni menampilkan data yang **belum diproses**, tidak ada tulis/edit/hapus/aksi apapun.

### 5 submenu, 3 server MSSQL berbeda (kredensial sama)

| Submenu | Server/Database | Tabel sumber |
|---|---|---|
| Karyawan Mobile | `WEBFS2/dbAbsDigital` | `dbo.TrAbsensi` |
| Driver Mobile | `HUPDBTMS/dbBMS` | `dbo.AbsenOtomatis` |
| Mitra Mobile | `HBCLOUD3/GeneralMitra` | `dbo.TrAbsensiMitra` |
| Kantin Mobile | `WEBFS2/dbAbsDigital` | `dbo.TrAbsensiMakan` |
| Kantin Mitra Mobile | `WEBFS2/dbAbsDigital` | `dbo.TrAbsensiMakanMitra` |

Konfigurasi lengkap (server, database, query SQL persis seperti yang diberikan) ada di
**`mclock/sources.py`** — tinggal edit dict `MOBILE_ATTENDANCE_SOURCES` di situ kalau perlu
menambah/mengubah submenu, tidak perlu sentuh view/template. **Kredensial (username/password) SAMA**
untuk semua submenu (satu set di `.env`), tapi **server & database bisa beda-beda per submenu** —
`mclock/mssql_client.py::get_mssql_connection()` menerima `server`/`database` sebagai parameter
opsional yang meng-override default settings, persis untuk kebutuhan ini.

### Kolom & fitur tiap tabel

Semua submenu punya kolom yang SAMA (sudah di-alias konsisten di query aslinya): **Id, SN, NIK,
Waktu (ttime), Tipe (ctype), Diproses (bProses)**. Tidak ada edit/aksi apapun, murni display:
- **Search** by NIK (`DibuatOleh`/`NIP`, sudah di-alias jadi `nik` di semua query).
- **Sort** di semua kolom (klik header).
- **Pagination** + **rows-per-page** (10/15/25/50/100).

Search/sort/pagination semuanya dijalankan **server-side di MSSQL** (bukan fetch semua baris ke
Python) — query asli dibungkus sebagai CTE (`WITH base_q AS (...)`), lalu search (`LIKE`) + sort
(`ORDER BY`) + pagination (`OFFSET ... FETCH NEXT ... ROWS ONLY`, SQL Server 2012+) diterapkan di
atasnya. Lihat `mclock/mssql_client.py::fetch_paginated_from_sql()`.

**Keamanan**: nama kolom untuk `sort`/`search` (dari parameter URL `?sort=`) **divalidasi terhadap
whitelist** (`MOBILE_ATTENDANCE_COLUMNS` di `sources.py`) sebelum dipakai membangun SQL — dicoba
kirim `?sort=` berisi string SQL berbahaya, hasilnya otomatis fallback ke default (`ttime`), tidak
tembus ke query. `base_sql` sendiri HARUS dari konfigurasi tetap di kode (bukan input user).

### Pagination pakai komponen yang SAMA dengan tabel lain

Karena hasilnya dari raw SQL (bukan Django QuerySet), dibuat **`mclock/pagination.py::SimplePage`**
— objek kecil yang meniru interface `django.core.paginator.Page` secukupnya, supaya bisa langsung
pakai `templates/partials/pagination.html` yang sudah ada (First/Prev/Next/Last + go-to-page) tanpa
duplikasi template.

### Enkripsi password
- **`cryptography.fernet.Fernet`** — password MSSQL tidak pernah disimpan plaintext.
- 2 management command:
  ```
  python manage.py generate_mclock_key       # generate MCLOCK_ENCRYPTION_KEY (jalankan SEKALI di awal)
  python manage.py encrypt_mssql_password     # enkripsi password MSSQL Anda (getpass, tidak tampil di layar)
  ```

### Setup yang perlu Anda lakukan
```
pip install -r requirements.txt   # nambah pymssql & cryptography
python manage.py generate_mclock_key
# copy MCLOCK_ENCRYPTION_KEY ke .env
python manage.py encrypt_mssql_password
# copy MCLOCK_MSSQL_PASSWORD_ENCRYPTED ke .env
# isi juga: MCLOCK_MSSQL_USERNAME, MCLOCK_MSSQL_PORT (default 1433)
```
Lalu buka menu "Mobile Attendance" → halaman utamanya punya tombol **"Test Koneksi"** yang mengecek
KETIGA kombinasi server/database sekaligus (bukan cuma satu), masing-masing dilaporkan status
sukses/gagalnya terpisah.

### Sudah diuji
- Konfigurasi 5 source benar, dan deduplikasi server/database unik benar (3 target, bukan 5, karena
  `WEBFS2/dbAbsDigital` dipakai 3 submenu).
- `fetch_paginated_from_sql()` diverifikasi utk **SEMUA 5 source sungguhan** (bukan cuma 1 sample) —
  SQL CTE yang dibangun benar, `server`/`database` yang dipakai tepat sesuai submenu masing-masing.
- Roundtrip enkripsi/dekripsi password (via command sungguhan, bukan cuma unit test).
- Percobaan koneksi ke hostname sungguhan yang sengaja tidak valid → error tertangani rapi (bukan
  cuma mock).
- Kelima halaman submenu dibuka (mocked data) → render benar, data tampil sesuai.
- Slug tidak dikenal → 404.
- **Percobaan SQL injection lewat parameter `?sort=`** → divalidasi & fallback aman ke default,
  TIDAK tembus ke query.
- Header info sumber (`server/database`) tampil benar di tiap halaman.
- Pagination (page, page_size) diteruskan & diterapkan dengan benar.
- Koneksi MSSQL gagal → pesan error ditampilkan rapi di halaman (status 200, BUKAN crash 500).
- Sidebar: submenu expandable + 5 sub-link semua tampil untuk staff.
- Permission: non-staff ditolak akses.


## 27j. Normalisasi PIN (Zero-Pad 9 Digit) — Backup Data Finger & Sinkronisasi Device

Ditemukan bug nyata: PIN yang didaftarkan LANGSUNG di device fisik biasanya cuma **7-8 digit TANPA
leading zero** (mis. `8113009`), sedangkan konvensi PIN Employee di database kita **9 digit
zero-padded** (mis. `008113009`). Tanpa normalisasi, PIN mentah dari device tidak pernah cocok dengan
Employee yang sudah ada — menyebabkan **Employee duplikat** ke-buat setiap kali "Backup Data Finger"
dijalankan (template fingerprint pun ter-attach ke Employee yang KELIRU, bukan yang seharusnya).

**Perbaikan**: `iclock/services.py::normalize_pin()` — zero-pad PIN numerik jadi 9 digit
(`PIN_ZERO_PAD_LENGTH = 9`, bisa diubah kalau konvensi PIN Anda beda) SEBELUM dipakai untuk
mencocokkan/membuat Employee. Diterapkan di 3 tempat yang mencocokkan PIN mentah dari device fisik
ke `employee.PIN`:
- `backup_device_fingerprints()` — PIN dinormalisasi sebelum `get_or_create()`; filter regex PIN
  (kalau diisi) juga dicocokkan ke PIN yang SUDAH dinormalisasi.
- `_sync_employee_privilege()` — sinkronisasi Privilege saat toggle Admin/User di Show Device User.
- `active_device_user_delete()` — hapus Employee terkait saat user dihapus langsung dari device.

PIN yang bukan angka murni (ada huruf) **tidak** di-zero-pad — dikembalikan apa adanya, karena aturan
ini spesifik untuk PIN numerik.

**Sudah diuji skenario paling kritis**: Employee dengan PIN `008113009` sudah ada di database, device
mengirim PIN mentah `8113009` — dikonfirmasi TIDAK membuat duplikat, template fingerprint ter-attach
ke Employee yang BENAR, dan nama Employee yang sudah ada TIDAK tertimpa data dari device.

### 🔍 Cek data lama yang mungkin sudah terlanjur duplikat

Kalau "Backup Data Finger" sudah pernah dijalankan SEBELUM perbaikan ini, mungkin sudah ada Employee
duplikat (versi zero-padded & versi tidak) tersimpan. Command diagnostik baru:
```
python manage.py find_unpadded_pins
```
Melaporkan semua Employee dengan PIN numerik yang belum 9-digit, DAN menandai mana yang kemungkinan
duplikat dari versi zero-padded-nya (kalau ada). **Command ini cuma melaporkan, tidak mengubah/
menghapus data apapun** — penggabungan/pembersihan duplikat (kalau ditemukan) perlu dilakukan manual
& hati-hati (perlu pindahkan referensi Fingerprint Template & Transaction dulu sebelum hapus record
yang salah).

## 27h. Transfer Data Finger (Employee) — Sumber dari Database, Bukan Device

Transfer Data Finger dari tabel **Employee** sekarang mengambil template fingerprint dari **database**
(tabel Fingerprint Template / `fptemp`), **bukan** konek langsung ke device fisik sumbernya —
beda dengan versi di Active Device yang tetap ambil dari device fisik secara real-time.

- Kalau employee belum punya template tersimpan di database sama sekali, muncul pesan jelas
  ("belum punya template fingerprint tersimpan di database") + saran pakai "Backup Data Finger" dulu
  di Active Device.
- Form-nya sekarang menampilkan **jumlah template di database** (bukan "Source Device" seperti
  sebelumnya), karena employee.SN (device tempat dia terdaftar) tidak lagi perlu online/reachable —
  cukup datanya sudah ada di database.
- Implementasi: `iclock/zk_client.py::transfer_fingerprints_from_db()` — konstruksi objek
  `zk.finger.Finger` langsung dari data database (decode base64 `Template` jadi bytes), TANPA konek
  ke source device sama sekali; target device tetap dikoneksikan seperti biasa untuk menerima
  template-nya.
- Sudah diuji: transfer sukses (user target belum ada → dibuatkan; sudah ada → langsung transfer),
  tidak ada template di DB (gagal jelas tanpa konek device), template base64 corrupt (di-skip per
  jari, tidak crash keseluruhan proses).

## 27i. Fingerprint Template — Tabel Di-Group per Employee

Tabel Fingerprint Template sekarang **di-group per employee** (1 baris per karyawan), bukan 1 baris
per template jari — supaya tidak terlalu panjang kalau 1 karyawan punya beberapa jari terdaftar.
Kolom: No, Karyawan (PIN+Nama), **Jumlah Template**, **Refresh Terakhir** (yang paling baru di antara
semua jari karyawan itu), dan tombol **"Lihat Detail"**.

- Klik "Lihat Detail" → expand baris di bawahnya, menampilkan tabel nested berisi SEMUA jari
  karyawan itu (Jari, Valid, Device, Refresh Time, Edit/Hapus per jari) — toggle pakai
  `document.getElementById()` biasa (BUKAN `CSS.escape()`/selector dinamis), menghindari kelas bug
  yang pernah ditemukan sebelumnya di fitur lain.
- Sort sekarang di level GROUP: PIN, Nama, **Jumlah Template**, **Refresh Terakhir** (2 kolom
  terakhir ini pakai agregasi SQL — `Count()`/`Max()` Django — bukan dihitung manual di Python).
- Pagination diterapkan ke jumlah EMPLOYEE (bukan jumlah baris template mentah) — query detail
  template per jari cuma dijalankan untuk employee yang tampil di halaman aktif, konsisten dengan
  pola efisiensi yang sama dipakai di Attendance Recap.
- "+ Tambah Template" & Edit/Delete individual TETAP berfungsi seperti biasa (di dalam detail yang
  di-expand).
- Sudah diuji: grouping benar (3 jari 1 karyawan jadi 1 baris dgn count=3), sort by count & utime
  bekerja benar, pagination tepat sesuai page_size pada level employee, toggle show/hide JS diverifikasi.

## 27g. Izin Fitur Granular untuk User Non-Staff

User NON-STAFF tertentu sekarang bisa diberi akses ke fitur SPESIFIK (**Transfer Data Finger**,
**Rekap Absensi**) tanpa perlu dijadikan staff/admin penuh — pakai sistem permission BAWAAN Django
(`django.contrib.auth`), bukan sistem custom dari nol.

### Cara pakai
1. Admin buka **User List** → tombol **"Kelola Izin"** di baris user non-staff yang dituju.
2. Centang fitur yang boleh diakses (Transfer Data Finger / Rekap Absensi), simpan.
3. User itu login seperti biasa — begitu login, mereka diarahkan ke **halaman beranda berbentuk
   card/icon button** (`/home/`), bukan dashboard admin. Cuma fitur yang sudah diberi izin yang
   muncul sebagai card; kalau belum ada izin sama sekali, tampil pesan "belum diberi akses".
4. Sidebar admin (navigasi lengkap) **disembunyikan** untuk user non-staff — mereka cuma lihat
   header (avatar dropdown + tema) dan konten halaman, sesuai fitur yang diklik dari card.

### Arsitektur
- **`iclock/models.py::FeaturePermission`** — model "dummy" (`managed=False`, tidak ada tabel/data
  sungguhan) yang cuma jadi tempat menempelkan 2 custom permission Django: `can_transfer_finger` dan
  `can_view_attendance_recap`. **Perlu `python manage.py makemigrations iclock && python manage.py
  migrate`** setelah update ini supaya kedua permission-nya benar-benar dibuat di database
  (`auth_permission` table) — tanpa migrate, permission-nya tidak akan ada dan "Kelola Izin" tidak
  akan berfungsi.
- **`accounts/permissions.py::permission_or_staff_required(*perm_codenames)`** — decorator baru,
  mengizinkan akses kalau user staff/superuser SEPERTI BIASA, ATAU kalau non-staff tapi punya salah
  satu permission yang disebutkan. Dipakai di `device_user_list`, `device_user_transfer_finger`,
  `attendance_recap`, `attendance_recap_employee_card`, dan 2 endpoint AJAX pendukungnya
  (`ajax_devices_by_pool`, `ajax_employee_search`) — menggantikan `@staff_required` yang sebelumnya
  menutup total akses non-staff di view-view ini.
- **`dashboard/views.py::user_home`** + **`templates/dashboard/user_home.html`** — halaman card
  untuk non-staff, isinya dinamis sesuai permission yang dipunya (`user.has_perm(...)`).
- **`dashboard/views.py::user_manage_permissions`** + **`templates/dashboard/user_manage_permissions.html`**
  — halaman admin utk centang/hapus 2 permission ini per user (pakai `user.user_permissions.add()`/
  `.remove()` bawaan Django, bukan tabel custom).
- **`dashboard/views.py::index`** — redirect diubah: non-staff sekarang ke `user_home` (bukan
  langsung ke `profile` seperti sebelumnya).
- **`templates/base.html`** — sidebar & tombol hamburger mobile disembunyikan kalau
  `not user.is_staff and not user.is_superuser`; link "🏠 Beranda" ditambahkan di dropdown avatar
  khusus non-staff (karena tanpa sidebar, perlu cara balik ke card menu).
- **`templates/iclock/device_user_list.html`** — aksi "Tambah Employee"/"Edit"/"Set as Admin"/
  "Delete User" disembunyikan untuk non-staff (di level TEMPLATE); "Transfer Data Finger" tetap
  tampil untuk siapa pun yang berhasil membuka halaman ini (karena akses ke halaman itu sendiri sudah
  digerbangi oleh permission di view). **Proteksi sungguhannya tetap di server** (view Edit/Delete
  masih `@staff_required`), jadi ini cuma penyembunyian UI, bukan satu-satunya lapis keamanan.

### ⚠️ Bug signifikan yang ditemukan & diperbaiki selama pengujian

Saat menguji alur ini end-to-end, `user.has_perm(...)` **selalu mengembalikan `False`** meskipun
permission-nya sudah benar ter-assign ke `user_permissions` (dikonfirmasi lewat query M2M langsung).
Setelah ditelusuri: **`AUTHENTICATION_BACKENDS`** di project ini cuma berisi
`accounts.backends.LDAPOrLocalBackend` (custom, extend `BaseBackend`) — backend ini HANYA menangani
autentikasi (cek username/password), TIDAK punya logic permission sungguhan sama sekali
(`BaseBackend.has_perm()`/`get_all_permissions()` bawaan cuma placeholder kosong). Karena TIDAK ada
`ModelBackend` bawaan Django di `AUTHENTICATION_BACKENDS`, seluruh sistem permission Django (bukan
cuma untuk fitur ini — SEMUA `has_perm()` di manapun di aplikasi) diam-diam tidak pernah berfungsi.

**Perbaikan**: `django.contrib.auth.backends.ModelBackend` ditambahkan ke `AUTHENTICATION_BACKENDS`
(di `config/settings.py`), SETELAH `LDAPOrLocalBackend`. Login tetap memakai `LDAPOrLocalBackend`
seperti biasa (Django mencoba backend berurutan untuk autentikasi, berhenti begitu satu berhasil, jadi
urutan ini tidak mengubah perilaku login) — `ModelBackend` di sini murni menyediakan logic permission
standarnya, tidak ikut campur proses autentikasi.

**Sudah diverifikasi lengkap** (lewat test langsung, bukan cuma cek unit logic terisolasi):
- Sebelum fix: permission ter-assign di M2M tapi `has_perm()` & `get_all_permissions()` tetap kosong.
- Setelah fix: `has_perm()` & `get_all_permissions()` benar mencerminkan permission yang di-assign.
- Non-staff tanpa izin → ditolak di kedua fitur, diarahkan ke `user_home` dengan pesan "belum diberi
  akses".
- Admin kasih 1 izin → user BISA akses fitur itu, TETAP ditolak fitur lain yang belum diizinkan.
- Card di `user_home` muncul/hilang sesuai izin yang di-assign/dicabut secara real (dites tambah &
  cabut izin, masing-masing dicek ulang).
- Di Employee list: aksi admin (Tambah/Edit/Delete/Set as Admin) tersembunyi untuk non-staff,
  "Transfer Data Finger" tetap muncul & berfungsi.
- Staff/superuser TETAP bisa akses semua seperti biasa (bypass permission check), TIDAK terpengaruh
  perubahan ini sama sekali.
- `index()` tetap mengarahkan staff ke `admin_home` seperti sebelumnya (cuma non-staff yang rutenya
  berubah, ke `user_home`).

## 27f. Aksi "Get/Set Param" Generic (Testing) — Active Device

Menu **🧪 Get/Set Param (Testing)** — versi GENERIC dari Set Network Param: bebas isi **nama
parameter apa saja** dan nilainya, untuk baca (`Get`) atau ubah (`Set`) konfigurasi device fisik.
Dibuat khusus untuk eksperimen/coba-coba, mengingat ternyata ada banyak parameter device (bukan cuma
IP/NetMask/Gateway/DHCP) yang mungkin perlu dibaca/diubah sesuai kebutuhan yang belum tentu semuanya
sudah diketahui/dipetakan sebelumnya.

**Contoh pemakaian nyata** (persis kasus yang mengonfirmasi fitur ini dibutuhkan): set parameter
`DHCP` jadi `0` supaya device pakai IP static alih-alih DHCP.

### Cara pakai
- Pilih aksi **Get** (baca nilai sekarang) atau **Set** (ubah nilai).
- Isi **Nama Parameter** bebas (mis. `DHCP`, `IPAddress`, `NetMask`, `GATEIPAddress`, atau parameter
  lain yang Anda tahu dari dokumentasi ZKTeco/SOLUSI).
- Kalau **Set**: isi juga **Nilai Baru**, dan ada checkbox **"Kirim CMD_REFRESHOPTION setelah Set"**
  (default tercentang, disarankan tetap dicentang) — bisa dimatikan khusus untuk keperluan eksperimen
  (mis. mau lihat apakah suatu parameter butuh refresh atau tidak untuk aktif).
- Hasil (nilai yang dibaca, atau status set berhasil/gagal) ditampilkan di kolom Status & sebagai
  flash message.

### Implementasi
- `iclock/zk_client.py::get_device_param()` — `CMD_OPTIONS_RRQ` dengan nama parameter apa saja,
  parsing response sama seperti `get_network_params()` bawaan pyzk (split di `=`, ambil sampai null
  terminator).
- `iclock/zk_client.py::set_device_param()` — `CMD_OPTIONS_WRQ` (format `"<nama>=<nilai>\x00"`) +
  opsional `CMD_REFRESHOPTION`, mekanisme yang SAMA dengan `set_network_params()` (lihat 27e), cuma
  generic untuk nama parameter apa saja alih-alih 3 nama yang di-hardcode.
- Sudah diuji lewat mock: format byte-string persis (termasuk skenario `DHCP=0` yang sudah
  dikonfirmasi jalan di hardware sungguhan Anda), parsing response Get, opsi refresh on/off, validasi
  form (Set butuh Nilai Baru diisi, Get tidak), permission non-admin ditolak.

⚠️ Sama seperti Set Network Param — ini bisa mengubah **parameter apa saja** di device, jadi pastikan
Anda tahu nama & efek parameter yang sedang diubah sebelum menekan "Jalankan".

## 27e. Aksi "Set Network Param" (Active Device) — IP Address / NetMask / Gateway

Menu baru **🌐 Set Network Param** — ganti parameter jaringan (IP Address, NetMask, Gateway) LANGSUNG
di device fisik via `pyzk`. Berguna khusus untuk mesin fingerprint ZKTeco branded SOLUSI yang punya
**IP "bawaan"** (dipakai kalau tidak ada jaringan) yang justru masuk sebagai `Alias` di protokol
push-SDK, bukan IP DHCP-nya — jadi bisa diubah langsung dari portal tanpa perlu akses menu device
secara fisik.

### Protokol yang dipakai

`pyzk` **tidak punya method publik** untuk operasi ini — cuma ada `get_network_params()` (baca, pakai
`CMD_OPTIONS_RRQ`) dan satu contoh internal `set_sdk_build_1()` yang hardcode SATU parameter spesifik
lewat `CMD_OPTIONS_WRQ`. Untuk memastikan formatnya benar, saya cek dokumentasi protokol resmi ZKTeco
([zk-protocol/sections/terminal.md](https://github.com/adrobinoga/zk-protocol/blob/master/sections/terminal.md)),
yang menyebutkan urutan LENGKAP yang benar:

```
packet(id=CMD_OPTIONS_WRQ, data="<nama parameter>=<nilai baru>\x00")
packet(id=CMD_ACK_OK)
packet(id=CMD_REFRESHOPTION)
packet(id=CMD_ACK_OK)
```

**Ini penting**: contoh internal pyzk sendiri (`set_sdk_build_1`) TIDAK menyertakan null-terminator
(`\x00`) di akhir string, dan TIDAK mengirim `CMD_REFRESHOPTION` sesudahnya — tapi dokumentasi resmi
menyertakan keduanya. Implementasi di sini **mengikuti dokumentasi resmi** (bukan meniru persis
contoh minimal pyzk), karena tanpa `CMD_REFRESHOPTION`, ada risiko device menyimpan nilai baru tapi
tidak benar-benar MENERAPKANNYA.

Karena tidak ada method publik pyzk untuk mengirim command generik `CMD_OPTIONS_WRQ`/`CMD_REFRESHOPTION`,
kode ini mengakses method private `_send_command` lewat name-mangling Python (`conn._ZK__send_command`)
— teknik yang sama persis dengan yang dipakai pyzk sendiri secara internal untuk `set_sdk_build_1`.

### ✅ Update: sudah dikonfirmasi jalan di hardware sungguhan

Berhasil diuji langsung ke device fisik ZKTeco (branded SOLUSI) — mekanisme `CMD_OPTIONS_WRQ` +
`CMD_REFRESHOPTION` **terbukti berhasil** meng-set parameter di device sungguhan.

**Temuan penting dari pengujian nyata**: device tidak langsung bisa di-ping pakai IP static yang baru
di-set, karena ada **parameter terpisah `DHCP`** yang menentukan device pakai IP DHCP (`DHCP=1`) atau
IP static (`DHCP=0`). Begitu `DHCP` di-set ke `0` langsung di device fisik, IP static-nya LANGSUNG bisa
di-ping — **tidak perlu reboot**. Ini konfirmasi bagus: mekanisme `CMD_REFRESHOPTION` di atas memang
benar-benar bekerja tanpa perlu restart device, setidaknya untuk parameter `DHCP`.

Karena ternyata ada BANYAK parameter device (bukan cuma IP/NetMask/Gateway/DHCP) yang mungkin perlu
di-set/dibaca sesuai kebutuhan, ditambahkan menu **generic** — lihat bagian 27f di bawah.

### Yang masih belum bisa dipastikan sepenuhnya

- Apakah SEMUA parameter (bukan cuma `DHCP`) langsung aktif tanpa reboot, atau ada yang butuh reboot
  manual — kemungkinan bervariasi per parameter (makanya pesan sukses & UI tetap menyarankan pakai
  menu 🔄 REBOOT kalau suatu parameter tidak langsung berubah).
- Perilaku spesifik lain pada varian ZKTeco branded SOLUSI di luar yang sudah diuji (IP/NetMask/Gateway/DHCP).

**Tetap disarankan**: uji parameter BARU (yang belum pernah dicoba) dulu di satu device yang mudah
diakses fisik, sebelum dipakai ke banyak device sekaligus.

### UI & implementasi

- Form (3 field, semua opsional individual tapi minimal 1 harus diisi): IP Address Baru, NetMask
  Baru, Gateway Baru — validasi format IPv4 di setiap field sebelum dikirim ke device.
- Saat halaman dibuka (GET), sistem coba baca **nilai SEKARANG** dari device (`get_network_params()`)
  untuk ditampilkan sebagai referensi — kalau gagal dibaca, form tetap bisa dipakai (tidak blocking).
- Banner peringatan jelas di halaman (bukan cuma di dokumentasi) karena ini aksi yang berisiko kalau
  salah isi (device bisa jadi tidak terjangkau dari jaringan).
- Spinner loading saat submit (pola sama dengan Transfer Finger/Backup Data Finger/lainnya).
- Implementasi: `iclock/zk_client.py::set_network_params()` & `get_device_network_params()`.

## 27d. Aksi "REBOOT" dan "Update Time" (Active Device)

Dua menu baru di dropdown Aksi Active Device, keduanya konek langsung ke device fisik via `pyzk`:

- **🕐 Update Time** — sinkronkan jam device dengan jam **komputer/server** yang menjalankan Django
  ini (`datetime.now()`, waktu lokal server, konsisten dengan konvensi `USE_TZ=False` project ini).
  Pakai `conn.set_time(datetime)` dari pyzk. Sebelum di-set, coba baca dulu jam LAMA device
  (`conn.get_time()`) untuk ditampilkan di flash message sebagai perbandingan (kalau gagal dibaca,
  tidak fatal — tetap lanjut set jam baru).
- **🔄 REBOOT** — restart device fisik (`conn.restart()` dari pyzk). Ada konfirmasi JS yang jelas
  menyebutkan device akan **sempat offline** beberapa puluh detik, karena ini aksi yang cukup
  disruptif dibanding aksi lain di dropdown yang sama.

Keduanya: form POST sederhana (pola sama dengan tombol "Hapus" yang sudah ada) + `confirm()` dialog
di JS sebelum submit, redirect balik ke list dengan flash message sukses/gagal — **tidak** pakai
halaman/spinner dedicated seperti Transfer Finger atau Backup Data Finger, karena ini aksi instan
satu-langkah (mirip "Set as Admin"/"Hapus" yang sudah ada), bukan proses panjang dengan status log.

Implementasi: `iclock/zk_client.py::reboot_device()` & `sync_device_time()` (keduanya return
`(success: bool, message: str)`, tidak melempar exception — aman dipakai langsung sebagai isi flash
message). View-nya (`iclock/views.py::active_device_reboot` & `active_device_sync_time`) di-guard
`@require_POST` (GET ditolak dengan 405).

Sudah diuji: reboot sukses & gagal (mock pyzk), sync time sukses dengan & tanpa berhasil baca jam
lama, sync time gagal total, device tanpa IP Address, GET ditolak 405, flash message sukses/error
tampil benar, dan permission non-admin ditolak.

## 27c. Kolom "Last Data" (Active Device)

Kolom baru **Last Data** di tabel Active Device — beda dari **Last Activity** (waktu request/heartbeat
terakhir dari protokol push device), kolom ini menampilkan **waktu transaksi/absensi TERAKHIR** yang
benar-benar tercatat dari device tersebut. Berguna untuk mendeteksi device yang "hidup" (masih
heartbeat) tapi sebenarnya **tidak lagi mengirim data absensi** (mis. sensor fingerprint rusak, atau
device dicabut dari penggunaan tapi jaringannya tetap nyala).

- **`iclock.LastData()`** — method baru di model (`iclock/models.py`), query ke tabel `transaction`
  filter by device ini (`SN=self`), ambil `TTime` yang **paling akhir** (`order_by('-TTime').first()`).
  Return `None` kalau device itu belum pernah punya transaksi sama sekali.
  > Catatan performa: 1 query terpisah per device (per baris tabel) — wajar untuk listing yang
  > dipaginate (puluhan baris/halaman), tapi kalau suatu saat butuh tampilkan ribuan device sekaligus
  > tanpa paginasi, pertimbangkan ganti ke query ber-anotasi (`Subquery`/`OuterRef`) di view supaya
  > jadi 1 query total.
- **Warna merah** kalau Last Data lebih lama dari **`ACTIVE_DEVICE_LASTDATA_STALE_MINUTES`** (default
  60 menit, **configurable** di `iclock/views.py` — konstanta terpisah dari `ACTIVE_DEVICE_STALE_MINUTES`
  milik Last Activity, jadi bisa diatur beda-beda sesuai kebutuhan), atau kalau belum pernah ada
  transaksi sama sekali (`None`).
- Sama seperti Last Activity: dicek ulang tiap 60 detik lewat `setInterval` di JS (fungsi
  `applyStaleStyling()`/`recheckAllStale()` sudah digeneralisasi supaya bisa dipakai kedua kolom
  dengan threshold masing-masing).
- **Sekarang real-time juga via WebSocket**, sama seperti Last Activity. Nama section WS diubah:
  - **`section='device_request'`** (sebelumnya `'request'`) — update tampilan **Last Activity**,
    perilaku sama seperti sebelumnya.
  - **`section='device_attlog'`** (baru) — update tampilan **Last Data**, langsung pakai nilai field
    `la` di message yang sama (bukan query ulang ke database), format message yang diharapkan:
    `{"sn": "...", "la": "YYYY-MM-DD HH:MM:SS", ...field lain bebas...}`.
  - Kedua section murni update **tampilan (DOM)**, sama sekali tidak menyentuh database — konsisten
    dengan prinsip yang sama sejak awal (database sudah di-handle protokol push Anda sendiri).
  - Diuji end-to-end (jsdom + Daphne + Redis sungguhan): `device_request` cuma update Last Activity
    (Last Data tidak ikut berubah), `device_attlog` cuma update Last Data (Last Activity tidak ikut
    berubah) — dua kolom ter-update independen sesuai section masing-masing.
- `python manage.py ws_simulate --section device_request --sn <SN>` atau
  `--section device_attlog --sn <SN> --pin <PIN> --state <I/O>` untuk simulasi testing kedua section
  ini tanpa device fisik.
- Kolom ini **tidak sortable** (nilainya method Python, bukan field database langsung).
- Sudah diuji: device dengan 2 transaksi (memilih yang PALING BARU, bukan yang lama), device dengan
  1 transaksi lama (merah), device tanpa transaksi sama sekali (`None`, merah), dan dipastikan
  perubahan ini tidak merusak sinkronisasi real-time Last Activity yang sudah ada (diverifikasi ulang
  lewat test E2E yang sama).

## 27b. Perbaikan: LastActivity Tidak Lagi Sync via WS, & Log Django Dobel

Dua bug nyata ditemukan & diperbaiki setelah dilaporkan, keduanya diverifikasi lewat **server Daphne
sungguhan** (bukan cuma logic terisolasi):

### 1. LastActivity berhenti sync real-time
**Akar masalah**: fungsi `updateDeviceRowLastActivity()` di `active_device_list.html` memakai
`CSS.escape()` untuk membangun CSS selector pencarian baris (`tr[data-sn="${CSS.escape(sn)}"]`).
Diverifikasi lewat test end-to-end pakai jsdom (load halaman asli, eksekusi script asli, konek ke
server Daphne sungguhan, kirim event WS sungguhan via `wsinfo()`) — ternyata `CSS.escape()` bisa
melempar exception di beberapa environment browser, dan karena error itu terjadi di **baris pertama**
fungsi, seluruh proses update (baik teks maupun styling) gagal total tanpa sempat jalan sama sekali.

**Perbaikan**: diganti jadi loop manual (`querySelectorAll('tr[data-device-row]')` + bandingkan
`row.dataset.sn` langsung), sama sekali tidak lagi bergantung `CSS.escape()` atau CSS selector
dinamis — jauh lebih kompatibel di berbagai browser.

**Hasil verifikasi (test E2E ulang, sama persis)**: `LastActivity berhasil ter-sync via WS? true`.

### 2. Log Django jadi dobel setelah WebSocket/Daphne aktif
**Akar masalah**: `daphne` (lewat override command `runserver`) mencatat access log HTTP
(`"HTTP GET ... 200 [...]"`) lewat logger Python bernama **`django.channels.server`**. Logger ini
tidak terdaftar eksplisit di `LOGGING` project ini, jadi dia propagate ke logger `django` (yang
sudah punya `StreamHandler` bawaan dari default Django, karena `disable_existing_loggers: False`),
LALU terus propagate lagi sampai ke `root` (yang juga punya `StreamHandler` dari konfigurasi kita
sendiri) — pesan yang SAMA diproses oleh **2 handler berbeda**, tercetak 2 kali.

Dibuktikan konkret lewat `manage.py runserver` sungguhan:
- **Sebelum fix**: 2 request → **4 baris log** (dobel persis).
- **Setelah fix**: 3 request → **3 baris log** (benar, 1:1).

**Perbaikan**: daftarkan logger `'django'` secara eksplisit di `LOGGING` (`config/settings.py`)
dengan `propagate: False`, supaya cuma ada SATU jalur/handler yang memprosesnya. Sekalian
didefinisikan ulang handler `mail_admins` + filter `require_debug_false` (identik dengan default
Django) supaya notifikasi email ke `ADMINS` saat error 500 di production (`DEBUG=False`) **tetap
jalan seperti semula** — sempat kehapus tanpa sengaja di percobaan awal, sudah dikembalikan &
diverifikasi ulang (`AdminEmailHandler` terkonfirmasi masih terpasang di logger `django`).

## 27. Tabel Dense (Baris Lebih Rapat)

Semua tabel di seluruh aplikasi (33 halaman) sekarang lebih rapat: padding cell `py-3`/`py-2`/`py-1.5`
diseragamkan jadi **`py-1`**, dan font tabel diperkecil dari `text-sm` jadi **`text-xs`**. Placeholder
"belum ada data" (baris kosong) SENGAJA dibiarkan lebih lega (`py-6`/`py-8`) supaya tetap jelas
kebaca sebagai pesan, bukan baris data.

## 28. Yang Perlu Disesuaikan Sebelum Produksi

- [ ] `SECRET_KEY` acak & rahasia, `DEBUG=False`, isi `ALLOWED_HOSTS`.
- [ ] Sesuaikan `AUTH_LDAP_*` dengan direktori LDAP/Active Directory yang sebenarnya.
- [ ] Pertimbangkan `mysqlclient` untuk performa produksi (lihat catatan di `requirements.txt`).
- [ ] Tambahkan HTTPS, `SECURE_*` settings Django, rate-limiting login (mis. `django-axes`) untuk
      mencegah brute force.
- [ ] **Kalau pakai nginx/reverse proxy dengan SSL termination di nginx**: isi `CSRF_TRUSTED_ORIGINS`
      (WAJIB, isi domain publik lengkap `https://`) dan pastikan nginx kirim
      `proxy_set_header X-Forwarded-Proto $scheme;` (dipasangkan dengan `SECURE_PROXY_SSL_HEADER` di
      Django) — lihat bagian 27o untuk detail & config nginx lengkap (termasuk header WebSocket
      terpisah untuk `/ws/iclock`). Tanpa ini, login & semua form POST akan gagal CSRF.
- [ ] Jalankan `python manage.py makemigrations mclock mattendance && python manage.py migrate`
      setelah update Mobile Pool Location/geofence polygon (bagian 27q), lalu
      `python manage.py sync_mobile_pool_loc` untuk isi data polygon-nya.
- [ ] **Face Verification** (bagian 27s): install `dlib`/`face_recognition` di server **SEBELUM**
      user mulai pakai Enrollment Wajah — siapkan Visual C++ Build Tools + CMake dulu, dan waktu
      tunggu yang cukup lama (bisa 10-30+ menit). Uji 1 kali (enroll + check-in) setelah instalasi
      selesai untuk konfirmasi akhir, karena belum sempat diuji dgn model dlib sungguhan di sandbox
      pengembangan (lihat detail di 27s).
- [ ] **Celery worker** (bagian 27u): jalankan `celery -A config worker --loglevel=info --pool=solo`
      sebagai proses TERPISAH dari `manage.py runserver`/Daphne — WAJIB pakai `--pool=solo` di
      Windows. Tanpa worker ini jalan, enrollment/check-in wajah akan gagal setelah menunggu 15 detik.
      Pertimbangkan jalankan sebagai Windows Service supaya otomatis start & tetap jalan.
- [ ] **⚠️ SETIAP kali update kode yang menyentuh `mattendance/tasks.py` (atau modul yang
      diimpornya, mis. `face_utils.py`) — WAJIB restart proses Celery worker secara manual**
      (Ctrl+C lalu jalankan ulang, atau restart service-nya). Beda dengan `runserver`, worker Celery
      TIDAK auto-reload — kalau lupa, akan muncul error semacam
      `got an unexpected keyword argument '...'` (lihat kasus konkret di bagian 27z-3).
- [ ] **Login Mobile via PIN** (bagian 27y): jalankan
      `python manage.py makemigrations accounts iclock && python manage.py migrate` utk field
      `mpassword` (employee) & `is_mobile_only` (User). Sampaikan ke karyawan: login di
      `/mattendance/login/`, password default `123456`, WAJIB diganti saat login pertama.
- [ ] Sesuaikan `CORS_ALLOWED_ORIGINS` ke domain Nuxt produksi.
- [ ] Pertimbangkan Celery/cron untuk sinkronisasi berkala user LDAP → lokal jika diperlukan.
- [ ] **Redis** untuk WebSocket (`REDIS_HOST`/`REDIS_PORT`) harus jalan & reachable di server produksi;
      pakai ASGI server sungguhan (`daphne`/`uvicorn`), bukan `manage.py runserver`.
- [ ] Jalankan `python manage.py makemigrations iclock && python manage.py migrate` setelah update
      izin fitur granular (bagian 27g) — permission `can_transfer_finger`/`can_view_attendance_recap`
      baru benar-benar ada di database setelah migrate ini.
