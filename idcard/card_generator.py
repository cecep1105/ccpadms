"""
Gabungkan template background + foto + data (nama/PIN/dll) jadi 1
gambar kartu akhir siap cetak -- posisi SEMUA elemen FIXED (SAMA utk
semua jenis kartu, TIDAK bisa diatur admin, sesuai keputusan desain
di awal), pakai Pillow (PIL).

Ukuran kartu: CR80 PORTRAIT (ukuran kartu ID standar, orientasi
portrait krn dipakai dgn lanyard/tali gantung -- LEBIH UMUM utk badge
karyawan di Indonesia drpd landscape) @ 300 DPI cetak = 638x1013 px
(2.125" x 3.375").
"""
import logging
from pathlib import Path
from io import BytesIO
from django.conf import settings

from PIL import Image, ImageDraw, ImageFont, ImageOps
from barcode import Code128
from barcode.writer import ImageWriter

logger = logging.getLogger(__name__)

CARD_SIZE = (638, 1013)  # (width, height) px @ 300 DPI, CR80 portrait

# Layout FIXED -- SAMA persis utk SEMUA jenis kartu (karyawan/driver/
# visitor/bhl), background BOLEH beda warna/logo per jenis, TAPI posisi
# foto & teks di ATASNYA konsisten. Semua koordinat dlm px, origin
# kiri-atas (konvensi Pillow).
CARD_LAYOUT = {
    'photo_box': settings.IDCARD_PHOTO_BOX,  # (left, top, right, bottom) -- kotak foto, rasio ~3:4.75 (potret)
    'name': {'y': 900, 'font_size': 40, 'bold': True, 'max_width': 580},
    'identifier': {'y': 740,'x': 300, 'font_size': 40, 'bold': True, 'max_width': 580},  # PIN (karyawan/driver) / No. KTP (visitor/bhl)
    'extra': {'y': 645, 'font_size': 20, 'bold': False, 'max_width': 580},  # label tambahan opsional (mis. jabatan/perusahaan)
}

_FONT_REGULAR_PATH = Path(settings.BASE_DIR) / 'idcard' / 'fonts' / 'DejaVuLGCSans.ttf'
_FONT_BOLD_PATH = Path(settings.BASE_DIR) / 'idcard' / 'fonts' / 'DejaVuLGCSans-Bold.ttf'



def _load_font(size, bold=False):
    """
    Font DejaVu Sans -- SUDAH lazim terpasang di distro Linux (Ubuntu/
    Debian, dipakai server produksi ini) sbg bagian paket `fonts-dejavu-core`.
    Kalau TERNYATA tidak ada, FALLBACK ke font bitmap bawaan Pillow --
    kartu TETAP ke-generate, CUMA tampilan teksnya kurang bagus, pesan
    WARNING dicatat.
    """
    path = _FONT_BOLD_PATH if bold else _FONT_REGULAR_PATH
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        logger.warning("Font '%s' tidak ditemukan di server -- pakai font bitmap fallback Pillow (kualitas rendah). Install paket 'fonts-dejavu-core'.", path)
        return ImageFont.load_default()


def _fit_photo_into_box(photo, box):
    """Potong & skala foto supaya PAS mengisi `box` TANPA distorsi (crop tengah, SAMA konsep dgn CSS object-fit: cover)."""
    left, top, right, bottom = box
    box_w, box_h = right - left, bottom - top
    return ImageOps.fit(photo, (box_w, box_h), method=Image.LANCZOS, centering=(0.5, 0.4))

def _draw_text(draw, x, y, text, font, max_width, fill=(20, 20, 20)):
    """
    Gambar teks pada posisi (x, y).
    Jika panjang teks melebihi max_width, akan dipotong dan ditambahkan '...'.
    """
    if not text:
        return

    while draw.textlength(text, font=font) > max_width and len(text) > 3:
        text = text[:-4] + "..."

    draw.text((x, y), text, font=font, fill=fill)

def _draw_centered_barcode_rel(canvas, text, x, y, width, max_height=None):
    barcode = Code128(text, writer=ImageWriter()).render({
        "font_size": 0,
        "module_height": 6,
        "quiet_zone": 2,
        "dpi": 300,
    })

    bw, bh = barcode.size

    # Resize agar lebarnya persis = width
    scale = width / bw
    new_w = int(width)
    new_h = int(bh * scale)

    # Batasi tinggi jika diperlukan
    if max_height and new_h > max_height:
        scale = max_height / new_h
        new_w = int(new_w * scale)
        new_h = int(max_height)

    barcode = barcode.resize((new_w, new_h), Image.LANCZOS)

    # Posisi tengah relatif terhadap area x..x+width
    barcode_x = x + (width - new_w) // 2

    canvas.paste(barcode, (barcode_x, y))

def _draw_centered_text_rel(draw, x, y, width, text, font, fill=(20, 20, 20)):
    """
    Draw text centered horizontally within the rectangle (x, y, width).
    """
    if not text:
        return

    text_width = draw.textlength(text, font=font)
    text_x = x + (width - text_width) / 2

    draw.text((text_x, y), text, font=font, fill=fill)

def _draw_centered_text(draw, canvas_width, y, text, font, max_width, fill=(20, 20, 20)):
    """Teks rata TENGAH horizontal, TRUNCATE dgn '...' kalau kepanjangan (BUKAN wrap ke baris baru)."""
    if not text:
        return
    while draw.textlength(text, font=font) > max_width and len(text) > 3:
        text = text[:-4] + '...'
    text_width = draw.textlength(text, font=font)
    x = (canvas_width - text_width) / 2
    draw.text((x, y), text, font=font, fill=fill)


def generate_card_image(background_bytes, photo_bytes, name, identifier, extra_text=''):
    """
    Titik masuk UTAMA -- kembalikan bytes PNG kartu akhir (background +
    foto + teks tergabung, ukuran CARD_SIZE). `background_bytes`
    diskalakan MENGISI PENUH kartu kalau resolusi aslinya tidak PERSIS
    CARD_SIZE -- admin TIDAK WAJIB upload background dgn resolusi
    pixel-perfect.
    """
    background = Image.open(BytesIO(background_bytes)).convert('RGB')
    background = ImageOps.fit(background, CARD_SIZE, method=Image.LANCZOS)
    canvas = background.copy()

    photo = Image.open(BytesIO(photo_bytes)).convert('RGB')
    fitted_photo = _fit_photo_into_box(photo, CARD_LAYOUT['photo_box'])
    canvas.paste(fitted_photo, CARD_LAYOUT['photo_box'][:2])

    draw = ImageDraw.Draw(canvas)
    name_cfg = CARD_LAYOUT['name']
    _draw_centered_text(draw, CARD_SIZE[0], name_cfg['y'], name.upper(), _load_font(name_cfg['font_size'], name_cfg['bold']), name_cfg['max_width'])

    id_cfg = CARD_LAYOUT['identifier']
    box_cfg = CARD_LAYOUT['photo_box']
    _draw_centered_text_rel(draw, box_cfg[0], box_cfg[3]+10, box_cfg[2] - box_cfg[0], identifier, _load_font(id_cfg['font_size'], id_cfg['bold']))
    _draw_centered_barcode_rel(canvas, identifier, box_cfg[0], box_cfg[3]+50, box_cfg[2] - box_cfg[0], max_height=100)

    if extra_text:
        extra_cfg = CARD_LAYOUT['extra']
        _draw_centered_text(draw, CARD_SIZE[0], extra_cfg['y'], extra_text.upper(), _load_font(extra_cfg['font_size'], extra_cfg['bold']), extra_cfg['max_width'], fill=(90, 90, 90))

    buffer = BytesIO()
    canvas.save(buffer, format='PNG')
    return buffer.getvalue()
