"""
Bulk tambah DNS record ke Cloudflare dari file CSV -- dibuat khusus utk
kebutuhan pemindahan/migrasi DNS dengan BANYAK record sekaligus (lihat
netmgmt/cloudflare_view.py utk endpoint API single-record yang dipakai
UI web, command ini REUSE persis helper & validasi yang SAMA, cuma
sumber datanya dari CSV bukan request HTTP satu-satu).

Format CSV (baris pertama HARUS header persis seperti ini):
    zone,type,name,content,ttl,proxied,priority

    zone      : nama domain PERSIS seperti terdaftar di Cloudflare
                (mis. "contoh.com") -- BUKAN zone_id, command ini yang
                akan mencari zone_id-nya otomatis (1x fetch di awal,
                dipakai ulang utk semua baris supaya HEMAT panggilan API).
    type      : A / AAAA / CNAME / MX / TXT / NS (huruf besar/kecil bebas)
    name      : nama record -- boleh subdomain saja (mis. "www") ATAU
                nama lengkap (mis. "www.contoh.com") -- KEDUANYA diterima
                Cloudflare, konsisten dgn field "name" di UI web. Utk
                record di root/apex domain, isi PERSIS sama dgn kolom
                zone (mis. "contoh.com").
    content   : isi record (IP utk A/AAAA, target utk CNAME/MX/NS, teks
                utk TXT)
    ttl       : detik, ATAU "1" utk Auto (default Cloudflare, otomatis
                jadi 300 kalau proxied=true) -- boleh dikosongkan, akan
                dianggap 1 (Auto)
    proxied   : true/false -- CUMA relevan utk A/AAAA/CNAME, DIABAIKAN
                utk tipe lain (boleh dikosongkan)
    priority  : angka, WAJIB diisi kalau type=MX, DIABAIKAN tipe lain

Contoh isi CSV:
    zone,type,name,content,ttl,proxied,priority
    contoh.com,A,www,203.0.113.10,3600,false,
    contoh.com,A,contoh.com,203.0.113.10,3600,true,
    contoh.com,CNAME,blog,www.contoh.com,1,true,
    contoh.com,MX,contoh.com,mail.contoh.com,3600,,10
    contoh.com,TXT,contoh.com,"v=spf1 include:_spf.google.com ~all",3600,,

Jalankan (SELALU coba --dry-run dulu utk migrasi besar, supaya bisa
cek semua baris valid SEBELUM benar-benar membuat ratusan record):
    python manage.py cloudflare_bulk_add_dns records.csv --dry-run
    python manage.py cloudflare_bulk_add_dns records.csv

Opsi:
    --dry-run        Validasi & tampilkan apa yang AKAN dilakukan, TANPA
                      benar-benar memanggil API Cloudflare (tidak ada
                      perubahan apa pun). SANGAT DIANJURKAN dijalankan
                      dulu utk migrasi besar.
    --skip-existing   Kalau record dgn type+name+content PERSIS SAMA
                      sudah ada di zone tsb, LEWATI (tidak error, tidak
                      dobel) -- berguna kalau command ini perlu
                      dijalankan ULANG stlh sebagian baris gagal
                      (mis. koneksi putus di tengah), supaya baris yang
                      SUDAH berhasil sebelumnya tidak dicoba lagi/dobel.

Baris yang GAGAL (validasi ATAU ditolak Cloudflare) TIDAK MENGHENTIKAN
proses -- dilewati, dicatat, lanjut ke baris berikutnya, supaya 1 baris
bermasalah di tengah CSV besar TIDAK menggagalkan ratusan baris lain
yang sudah benar. Ringkasan akhir menampilkan jumlah berhasil/dilewati/
gagal + detail tiap baris gagal (nomor baris CSV, alasan).
"""
import csv

from django.core.management.base import BaseCommand, CommandError

from netmgmt.cloudflare_view import (
    CloudflareAPIError,
    PROXIABLE_RECORD_TYPES,
    SUPPORTED_RECORD_TYPES,
    _fetch_all_pages,
    call_cloudflare_api,
)


def to_bool(value: str) -> bool:
    return (value or "").strip().lower() in ("true","TRUE","1", "yes", "y")


class Command(BaseCommand):
    help = "Bulk tambah DNS record ke Cloudflare dari file CSV (lihat docstring file ini utk format lengkap)."

    def add_arguments(self, parser):
        parser.add_argument("file_csv", type=str, help="Path ke file CSV berisi record yang mau ditambahkan.")
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Validasi & tampilkan rencana TANPA benar-benar memanggil API Cloudflare.",
        )
        parser.add_argument(
            "--skip-existing", action="store_true",
            help="Lewati (bukan error) kalau record type+name+content PERSIS SAMA sudah ada di zone.",
        )

    def handle(self, *args, **options):
        file_csv = options["file_csv"]
        dry_run = options["dry_run"]
        skip_existing = options["skip_existing"]

        try:
            with open(file_csv, newline="", encoding="utf-8-sig") as f:
                rows = list(csv.DictReader(f))
        except FileNotFoundError as exc:
            raise CommandError(f"File tidak ditemukan: {file_csv}") from exc

        if not rows:
            self.stdout.write(self.style.WARNING("File CSV kosong (atau cuma ada header) -- tidak ada yang dikerjakan."))
            return

        required_columns = {"zone", "type", "name", "content"}
        missing_columns = required_columns - set(rows[0].keys())
        if missing_columns:
            raise CommandError(
                f"Kolom wajib tidak ditemukan di header CSV: {sorted(missing_columns)}. "
                f"Header yang ditemukan: {list(rows[0].keys())}. Lihat docstring file ini utk format yang benar."
            )

        self.stdout.write(f"Membaca {len(rows)} baris dari {file_csv}...")
        if dry_run:
            self.stdout.write(self.style.WARNING("=== MODE DRY-RUN -- TIDAK ADA perubahan yang benar-benar dibuat di Cloudflare ==="))

        # Ambil daftar zone SEKALI di awal (bukan per-baris) -- hemat
        # panggilan API drastis utk CSV besar (ratusan/ribuan baris
        # biasanya cuma menyentuh segelintir zone/domain).
        try:
            zones = _fetch_all_pages("/zones")
        except CloudflareAPIError as exc:
            raise CommandError(f"Gagal mengambil daftar zone dari Cloudflare: {exc}") from exc
        zone_id_by_name = {z["name"]: z["id"] for z in zones}
        self.stdout.write(f"Ditemukan {len(zone_id_by_name)} zone yang bisa diakses token ini: {', '.join(sorted(zone_id_by_name)) or '(tidak ada)'}")
        self.stdout.write("")

        # Cache existing records PER ZONE (bukan per-baris) -- 1x fetch
        # per zone yang benar2 dipakai di CSV, dipakai ulang utk cek
        # --skip-existing SEMUA baris di zone yang sama.
        existing_records_by_zone: dict[str, list[dict]] = {}

        succeeded = 0
        skipped = 0
        failed: list[tuple[int, str]] = []

        for i, row in enumerate(rows, start=2):  # baris 2 = baris data pertama (baris 1 = header)
            zone_name = (row.get("zone") or "").strip()
            record_type = (row.get("type") or "").strip().upper()
            name = (row.get("name") or "").strip()
            content = (row.get("content") or "").strip()
            ttl_raw = (row.get("ttl") or "").strip()
            proxied_raw = row.get("proxied") or ""
            priority_raw = (row.get("priority") or "").strip()

            label = f"baris {i}: {record_type} {name} -> {content}"

            if not zone_name or not record_type or not name or not content:
                failed.append((i, f"{label} -- kolom zone/type/name/content tidak boleh kosong."))
                self.stdout.write(self.style.ERROR(f"✗ {label} -- kolom wajib kosong, dilewati."))
                continue

            if record_type not in SUPPORTED_RECORD_TYPES:
                failed.append((i, f"{label} -- tipe '{record_type}' tidak didukung (pilih dari {sorted(SUPPORTED_RECORD_TYPES)})."))
                self.stdout.write(self.style.ERROR(f"✗ {label} -- tipe tidak didukung, dilewati."))
                continue

            zone_id = zone_id_by_name.get(zone_name)
            if not zone_id:
                failed.append((i, f"{label} -- zone '{zone_name}' tidak ditemukan/tidak bisa diakses token ini."))
                self.stdout.write(self.style.ERROR(f"✗ {label} -- zone '{zone_name}' tidak ditemukan, dilewati."))
                continue

            body = {
                "type": record_type,
                "name": name,
                "content": content,
                "ttl": int(ttl_raw) if ttl_raw else 1,
            }
            if record_type in PROXIABLE_RECORD_TYPES:
                body["proxied"] = to_bool(proxied_raw)
            if record_type == "MX":
                if not priority_raw:
                    failed.append((i, f"{label} -- kolom 'priority' wajib diisi utk record MX."))
                    self.stdout.write(self.style.ERROR(f"✗ {label} -- priority MX kosong, dilewati."))
                    continue
                body["priority"] = int(priority_raw)

            if skip_existing:
                if zone_id not in existing_records_by_zone:
                    try:
                        existing_records_by_zone[zone_id] = _fetch_all_pages(f"/zones/{zone_id}/dns_records")
                    except CloudflareAPIError as exc:
                        failed.append((i, f"{label} -- gagal cek record yang sudah ada di zone: {exc}"))
                        self.stdout.write(self.style.ERROR(f"✗ {label} -- gagal cek existing record, dilewati."))
                        continue
                # Cloudflare SELALU mengembalikan `name` dalam bentuk LENGKAP
                # (mis. "www.contoh.com") di respons API-nya, TAPI CSV boleh
                # diisi nama PENDEK (mis. "www") -- keduanya sama2 valid sbg
                # INPUT saat membuat record, tapi kalau dibandingkan APA
                # ADANYA (short vs full) TIDAK AKAN PERNAH cocok, --skip-existing
                # jadi TIDAK PERNAH mendeteksi duplikat utk nama pendek.
                # Normalisasi ke bentuk lengkap DULU sebelum dibandingkan.
                full_name = name if name == zone_name or name.endswith(f".{zone_name}") else f"{name}.{zone_name}"
                already_exists = any(
                    r.get("type") == record_type and r.get("name") == full_name and r.get("content") == content
                    for r in existing_records_by_zone[zone_id]
                )
                if already_exists:
                    skipped += 1
                    self.stdout.write(self.style.WARNING(f"- {label} -- sudah ada persis sama, dilewati (--skip-existing)."))
                    continue

            if dry_run:
                succeeded += 1
                self.stdout.write(f"✓ (dry-run) {label} -- akan dibuat di zone '{zone_name}'.")
                continue

            try:
                call_cloudflare_api("POST", f"/zones/{zone_id}/dns_records", json_body=body)
            except CloudflareAPIError as exc:
                failed.append((i, f"{label} -- ditolak Cloudflare: {exc}"))
                self.stdout.write(self.style.ERROR(f"✗ {label} -- ditolak Cloudflare: {exc}"))
                continue

            succeeded += 1
            self.stdout.write(self.style.SUCCESS(f"✓ {label} -- berhasil dibuat."))

        self.stdout.write("")
        self.stdout.write("=== Ringkasan ===")
        verb = "akan dibuat" if dry_run else "berhasil dibuat"
        self.stdout.write(self.style.SUCCESS(f"{verb}: {succeeded}"))
        if skip_existing:
            self.stdout.write(self.style.WARNING(f"dilewati (sudah ada): {skipped}"))
        if failed:
            self.stdout.write(self.style.ERROR(f"gagal: {len(failed)}"))
            for line_no, reason in failed:
                self.stdout.write(self.style.ERROR(f"  - {reason}"))
        else:
            self.stdout.write("gagal: 0")

        if dry_run and succeeded > 0:
            self.stdout.write("")
            self.stdout.write("Semua baris di atas VALID. Jalankan lagi TANPA --dry-run utk benar-benar membuat record-nya.")
