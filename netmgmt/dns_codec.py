"""
Encoder/decoder format BINARY PROPRIETARY Microsoft utk record DNS
tersimpan di Active Directory (atribut `dnsRecord`, multi-value) --
format ini didokumentasikan Microsoft sbg protokol **MS-DNSP** (bukan
format DNS wire biasa spt di RFC 1035, BEDA TOTAL).

⚠️ INI BAGIAN PALING KRITIS & BERISIKO dari fitur DNS management --
kalau encoding-nya SALAH, record yang disimpan bisa RUSAK (DNS
resolution gagal di seluruh domain/forest). Sudah diuji ROUND-TRIP
(encode lalu decode balik menghasilkan nilai LOGIS yang sama) utk semua
tipe record yang didukung -- TAPI belum diuji ke server AD SUNGGUHAN
(cuma bisa diverifikasi struktur byte-nya benar sesuai spesifikasi).

Struktur DNS_RPC_RECORD (per record, 1 attribute value `dnsRecord`
BISA berisi BANYAK value -- 1 value = 1 record):

    Offset  Size  Field          Byte Order
    0       2     wDataLength    little-endian  (panjang bagian "Data" di bawah)
    2       2     wType          little-endian  (1=A, 28=AAAA, 5=CNAME, 16=TXT, 15=MX, 33=SRV, 2=NS, 12=PTR, dst)
    4       1     Version        (selalu 5)
    5       1     Rank           (240 utk record "zone", biasa dipakai)
    6       2     Flags          little-endian (biasanya 0)
    8       4     dwSerial       little-endian (nomor serial zone)
    12      4     dwTtlSeconds   BIG-ENDIAN!!  (BEDA dari field lain -- network byte order)
    16      4     dwReserved     (0)
    20      4     dwTimeStamp    little-endian (jam sejak 1601-01-01 -- 0 = record STATIS/non-aging, WAJIB 0 kalau bukan dynamic update)
    24      N     Data           spesifik per-tipe (lihat _encode_data_*/_decode_data_* di bawah), N = wDataLength

Total header tetap = 24 byte, SELALU ada di setiap record apa pun tipenya.
"""
import struct
from dataclasses import dataclass, field
from typing import Any

DNS_TYPE_A = 1
DNS_TYPE_NS = 2
DNS_TYPE_CNAME = 5
DNS_TYPE_SOA = 6
DNS_TYPE_PTR = 12
DNS_TYPE_MX = 15
DNS_TYPE_TXT = 16
DNS_TYPE_AAAA = 28
DNS_TYPE_SRV = 33

DNS_TYPE_NAMES = {
    DNS_TYPE_A: 'A', DNS_TYPE_NS: 'NS', DNS_TYPE_CNAME: 'CNAME', DNS_TYPE_SOA: 'SOA',
    DNS_TYPE_PTR: 'PTR', DNS_TYPE_MX: 'MX', DNS_TYPE_TXT: 'TXT', DNS_TYPE_AAAA: 'AAAA', DNS_TYPE_SRV: 'SRV',
}
DNS_TYPE_BY_NAME = {v: k for k, v in DNS_TYPE_NAMES.items()}

# Tipe record yang DIDUKUNG utk EDIT/HAPUS/TAMBAH lewat fitur ini -- SOA
# SENGAJA TIDAK didukung tulis (1 zone cuma py 1 SOA, edit sembarangan
# bisa rusak replikasi zone -- baca-saja lewat decode biasa kalau ketemu).
SUPPORTED_WRITE_TYPES = {DNS_TYPE_A, DNS_TYPE_AAAA, DNS_TYPE_CNAME, DNS_TYPE_TXT, DNS_TYPE_MX, DNS_TYPE_SRV, DNS_TYPE_NS, DNS_TYPE_PTR}


class DnsCodecError(Exception):
    """Gagal encode/decode record DNS (format tidak dikenal/rusak)."""


@dataclass
class DnsRecord:
    type_name: str  # 'A', 'AAAA', 'CNAME', dst -- lihat DNS_TYPE_NAMES
    data: dict[str, Any] = field(default_factory=dict)  # isi spesifik per-tipe, lihat _encode_data_*/_decode_data_*
    ttl_seconds: int = 3600
    serial: int = 1
    raw_type: int | None = None  # tipe MENTAH (angka) -- diisi otomatis saat decode, dipakai kalau tipe TIDAK dikenal (belum didukung) supaya tetap bisa ditampilkan read-only


def _encode_dns_name(name: str) -> bytes:
    name = name.rstrip('.')
    labels = name.split('.') if name else []
    raw = b''.join(bytes([len(label)]) + label.encode('ascii') for label in labels) + b'\x00'
    if len(raw) > 255:
        raise DnsCodecError(f"Nama DNS '{name}' terlalu panjang (encoded {len(raw)} byte, maks 255).")
    return bytes([len(raw), len(labels)]) + raw


def _decode_dns_name(buf: bytes, offset: int) -> tuple[str, int]:
    total_len = buf[offset]
    label_count = buf[offset + 1]
    raw = buf[offset + 2: offset + 2 + total_len]
    labels = []
    pos = 0
    for _ in range(label_count):
        label_len = raw[pos]
        labels.append(raw[pos + 1: pos + 1 + label_len].decode('ascii', errors='replace'))
        pos += 1 + label_len
    return '.'.join(labels), 2 + total_len


def _encode_data(type_name: str, data: dict[str, Any]) -> bytes:
    if type_name == 'A':
        parts = data['address'].split('.')
        if len(parts) != 4:
            raise DnsCodecError(f"Alamat IPv4 tidak valid: {data['address']!r}")
        return bytes(int(p) for p in parts)

    if type_name == 'AAAA':
        import ipaddress
        return ipaddress.IPv6Address(data['address']).packed

    if type_name in ('CNAME', 'NS', 'PTR'):
        return _encode_dns_name(data['target'])

    if type_name == 'MX':
        return struct.pack('>H', data['preference']) + _encode_dns_name(data['exchange'])

    if type_name == 'SRV':
        return (
            struct.pack('>HHH', data['priority'], data['weight'], data['port'])
            + _encode_dns_name(data['target'])
        )

    if type_name == 'TXT':
        text = data['text']
        chunks = [text[i:i + 255] for i in range(0, len(text), 255)] or ['']
        return b''.join(bytes([len(c.encode('utf-8'))]) + c.encode('utf-8') for c in chunks)

    raise DnsCodecError(f"Tipe record '{type_name}' belum didukung utk ditulis.")


def _decode_data(type_name: str, raw_type: int, buf: bytes) -> dict[str, Any]:
    if type_name == 'A':
        return {'address': '.'.join(str(b) for b in buf[:4])}

    if type_name == 'AAAA':
        import ipaddress
        return {'address': str(ipaddress.IPv6Address(bytes(buf[:16])))}

    if type_name in ('CNAME', 'NS', 'PTR'):
        name, _ = _decode_dns_name(buf, 0)
        return {'target': name}

    if type_name == 'MX':
        (preference,) = struct.unpack('>H', buf[:2])
        exchange, _ = _decode_dns_name(buf, 2)
        return {'preference': preference, 'exchange': exchange}

    if type_name == 'SRV':
        priority, weight, port = struct.unpack('>HHH', buf[:6])
        target, _ = _decode_dns_name(buf, 6)
        return {'priority': priority, 'weight': weight, 'port': port, 'target': target}

    if type_name == 'TXT':
        chunks = []
        pos = 0
        while pos < len(buf):
            chunk_len = buf[pos]
            chunks.append(buf[pos + 1: pos + 1 + chunk_len].decode('utf-8', errors='replace'))
            pos += 1 + chunk_len
        return {'text': ''.join(chunks)}

    return {'raw_hex': buf.hex(), 'raw_type': raw_type}


def encode_record(record: DnsRecord) -> bytes:
    if record.type_name not in DNS_TYPE_BY_NAME:
        raise DnsCodecError(f"Tidak bisa encode tipe '{record.type_name}' -- tidak dikenal.")
    data_bytes = _encode_data(record.type_name, record.data)
    header = struct.pack(
        '<HHBBHI',
        len(data_bytes), DNS_TYPE_BY_NAME[record.type_name], 5, 240, 0, record.serial,
    )
    ttl = struct.pack('>I', record.ttl_seconds)
    reserved_and_timestamp = struct.pack('<II', 0, 0)
    return header + ttl + reserved_and_timestamp + data_bytes


def decode_record(raw: bytes) -> DnsRecord:
    if len(raw) < 24:
        raise DnsCodecError(f'Data record terlalu pendek ({len(raw)} byte, minimal 24 byte header).')
    data_length, raw_type, version, rank, flags, serial = struct.unpack('<HHBBHI', raw[:12])
    (ttl_seconds,) = struct.unpack('>I', raw[12:16])
    data_buf = raw[24:24 + data_length]
    type_name = DNS_TYPE_NAMES.get(raw_type, f'TYPE{raw_type}')
    decoded_data = _decode_data(type_name, raw_type, data_buf)
    return DnsRecord(type_name=type_name, data=decoded_data, ttl_seconds=ttl_seconds, serial=serial, raw_type=raw_type)
