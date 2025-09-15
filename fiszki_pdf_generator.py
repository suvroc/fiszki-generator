"""
Fiszki PDF generator
Wejście: CSV z kolumnami (dokładnie): TEKST, TŁUMACZENIE, LINK DO OBRAZKA
Wyjście: PDF w orientacji pionowej (A4) z kartami 3x3 (9 kart na stronę).

Wymagania:
pip install reportlab pillow requests

Użycie:
python fiszki_pdf_generator.py input.csv output.pdf

Obsługa:
- Jeśli LINK DO OBRAZKA to URL -> pobiera obraz przez HTTP
- Jeśli to ścieżka lokalna -> otwiera plik
- Jeśli nie ma obrazu lub wystąpi błąd -> rysuje placeholder
- CSV czytane jako UTF-8 (zalecane utf-8-sig)

"""

import csv
import sys
import os
import io
import math
import requests
from PIL import Image, ImageOps
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# --- Konfiguracja wyglądu ---
PAGE_SIZE = A4  # (width, height) w punktach
MARGIN_MM = 12
GAP_MM = 0
COLUMNS = 3
ROWS = 3
CARDS_PER_PAGE = COLUMNS * ROWS

# Margins and gaps in points
MARGIN = MARGIN_MM * mm
GAP = GAP_MM * mm

# Font sizes
WORD_FONT_SIZE = 20
TRANSL_FONT_SIZE = 20

# Image area ratio inside card (fraction of card height reserved for image)
IMAGE_HEIGHT_RATIO = 0.52
IMAGE_MAX_WIDTH_RATIO = 0.9

# Placeholder image size (px)
PLACEHOLDER_SIZE = (800, 600)

# Timeout for image requests
REQUEST_TIMEOUT = 8

# Rejestracja czcionki TrueType obsługującej polskie znaki
FONT_PATH = 'DejaVuSans.ttf'  # Upewnij się, że plik jest w katalogu projektu
try:
    pdfmetrics.registerFont(TTFont('DejaVuSans', FONT_PATH))
    pdfmetrics.registerFont(TTFont('DejaVuSans-Bold', FONT_PATH))
    FONT_NAME = 'DejaVuSans'
    FONT_BOLD_NAME = 'DejaVuSans-Bold'
except Exception:
    # Fallback do Helvetica jeśli nie znaleziono czcionki
    FONT_NAME = 'Helvetica'
    FONT_BOLD_NAME = 'Helvetica-Bold'


def read_csv(path):
    rows = []
    with open(path, newline='', encoding='utf-8-sig') as csvfile:
        reader = csv.DictReader(csvfile)
        # normalize keys
        for i, r in enumerate(reader, start=1):
            # Accept variants of column names
            tekst = r.get('TEKST') or r.get('Tekst') or r.get('tekst') or r.get('WORD') or r.get('WORD'.lower())
            tlum = r.get('TŁUMACZENIE') or r.get('Tlumaczenie') or r.get('TŁUM') or r.get('TLUMACZENIE') or r.get('translation')
            link = r.get('LINK DO OBRAZKA') or r.get('LINK_DO_OBRAZKA') or r.get('LINK') or r.get('IMAGE') or r.get('LINK_DO_OBRAZU')
            if tekst is None and tlum is None and link is None:
                # skip empty rows
                continue
            zdanie_en = r.get('ZDANIE_EN') or r.get('ZDANIE en') or r.get('EN_SENTENCE') or ''
            zdanie_es = r.get('ZDANIE_ES') or r.get('ZDANIE es') or r.get('ES_SENTENCE') or ''
            rows.append({
                'TEKST': (tekst or '').strip(),
                'TŁUMACZENIE': (tlum or '').strip(),
                'LINK DO OBRAZKA': (link or '').strip(),
                'ZDANIE_EN': zdanie_en.strip(),
                'ZDANIE_ES': zdanie_es.strip(),
                'row_index': i
            })
    return rows


def fetch_image(link):
    """Return PIL.Image or raise exception"""
    if not link:
        raise ValueError('Empty link')
    # If it's a local file path
    if link.startswith('file://'):
        path = link[7:]
        return Image.open(path)
    if os.path.exists(link):
        return Image.open(link)

    # Otherwise try HTTP(S)
    if link.lower().startswith('http'):
        resp = requests.get(link, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        return Image.open(io.BytesIO(resp.content))

    # Unknown format -> try open as path anyway (may raise)
    return Image.open(link)


def make_placeholder(text):
    """Create a simple placeholder image with the TEKST centered"""
    img = Image.new('RGB', PLACEHOLDER_SIZE, (240, 240, 240))
    try:
        from PIL import ImageDraw, ImageFont
        draw = ImageDraw.Draw(img)
        # try to use a truetype font, fallback to default
        try:
            font = ImageFont.truetype('DejaVuSans.ttf', 36)
        except Exception:
            font = ImageFont.load_default()
        w, h = draw.textsize(text, font=font)
        draw.text(((PLACEHOLDER_SIZE[0]-w)/2, (PLACEHOLDER_SIZE[1]-h)/2), text, fill=(80,80,80), font=font)
    except Exception:
        pass
    return img


def pil_image_to_reportlab(img, max_width, max_height):
    # Resize preserving aspect ratio
    img = ImageOps.exif_transpose(img)  # respect EXIF orientation
    img.thumbnail((int(max_width), int(max_height)), Image.LANCZOS)
    bio = io.BytesIO()
    img.save(bio, format='PNG')
    bio.seek(0)
    return ImageReader(bio), img.size


def draw_card(c, x, y, w, h, item):
    # Draw border (gray)
    from reportlab.lib.colors import gray
    c.setStrokeColor(gray)
    c.rect(x, y, w, h)
    c.setStrokeColorRGB(0, 0, 0)  # reset to black for other elements if needed

    # Padding inside card
    pad = 6 * mm
    inner_x = x + pad
    inner_y = y + pad
    inner_w = w - 2 * pad
    inner_h = h - 2 * pad

    word = item.get('TEKST', '')
    transl = item.get('TŁUMACZENIE', '')
    zdanie_en = item.get('ZDANIE_EN', '')
    zdanie_es = item.get('ZDANIE_ES', '')

    # TEKST na górze
    c.setFont(FONT_BOLD_NAME, WORD_FONT_SIZE)
    word_y = inner_y + inner_h - WORD_FONT_SIZE - 2  # górna część karty
    c.drawCentredString(x + w / 2, word_y, word)

    # Angielskie zdanie pod TEKST
    sentence_font_size = 10
    c.setFont(FONT_NAME, sentence_font_size)
    sentence_y_en = word_y - sentence_font_size - 10
    if zdanie_en:
        c.drawCentredString(x + w / 2, sentence_y_en, zdanie_en)

    # Oblicz miejsce na obrazek
    img_area_h = inner_h * IMAGE_HEIGHT_RATIO
    img_max_w = inner_w * IMAGE_MAX_WIDTH_RATIO
    img_max_h = img_area_h - 4

    img_reader = None
    img_size = (0, 0)
    try:
        pil_img = fetch_image(item.get('LINK DO OBRAZKA'))
    except Exception:
        pil_img = make_placeholder(word)

    try:
        img_reader, img_size = pil_image_to_reportlab(pil_img, img_max_w, img_max_h)
    except Exception:
        pil_img = make_placeholder(word)
        img_reader, img_size = pil_image_to_reportlab(pil_img, img_max_w, img_max_h)

    # Pozycja obrazka: środek karty
    iw, ih = img_size
    img_x = inner_x + (inner_w - iw) / 2
    img_y = inner_y + (inner_h - img_area_h) / 2 + (img_area_h - ih) / 2
    c.drawImage(img_reader, img_x, img_y, width=iw, height=ih, preserveAspectRatio=True, mask='auto')

    # TŁUMACZENIE na dole
    c.setFont(FONT_NAME, TRANSL_FONT_SIZE)
    transl_y = inner_y + TRANSL_FONT_SIZE + 2  # dolna część karty
    c.drawCentredString(x + w / 2, transl_y, transl)

    # Hiszpańskie zdanie pod TŁUMACZENIE
    c.setFont(FONT_NAME, sentence_font_size)
    sentence_y_es = transl_y + sentence_font_size + 10
    if zdanie_es:
        c.drawCentredString(x + w / 2, sentence_y_es, zdanie_es)

def generate_pdf(data_rows, out_path):
    page_w, page_h = PAGE_SIZE
    c = canvas.Canvas(out_path, pagesize=PAGE_SIZE)

    card_w = (page_w - 2 * MARGIN - (COLUMNS - 1) * GAP) / COLUMNS
    card_h = (page_h - 2 * MARGIN - (ROWS - 1) * GAP) / ROWS

    total = len(data_rows)
    pages = math.ceil(total / CARDS_PER_PAGE) if total > 0 else 1

    idx = 0
    for p in range(pages):
        for r in range(ROWS):
            for col in range(COLUMNS):
                if idx >= total:
                    break
                x = MARGIN + col * (card_w + GAP)
                # from bottom
                y = MARGIN + (ROWS - 1 - r) * (card_h + GAP)
                item = data_rows[idx]
                draw_card(c, x, y, card_w, card_h, item)
                idx += 1
            # end cols
        # end rows
        c.showPage()
    c.save()
    print(f'Zapisano {out_path} ({total} fiszek, {pages} stron)')


def main():
    if len(sys.argv) < 3:
        print('Użycie: python fiszki_pdf_generator.py input.csv output.pdf')
        sys.exit(1)
    in_csv = sys.argv[1]
    out_pdf = sys.argv[2]

    if not os.path.exists(in_csv):
        print('Plik wejściowy nie istnieje:', in_csv)
        sys.exit(1)

    rows = read_csv(in_csv)
    if not rows:
        print('Brak wierszy do przetworzenia')
        sys.exit(1)

    generate_pdf(rows, out_pdf)


if __name__ == '__main__':
    main()
