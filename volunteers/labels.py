"""
Label PDF generation for volunteer lanyard cards.

Generates two labels per volunteer:
- Front: FOSDEM year, username/nick, full name, pronouns, spoken languages
- Back: Task schedule for the current edition
"""
import io

from django.conf import settings

from reportlab.lib.units import mm
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

from volunteers.fonts_manifest import FONT_MANIFEST, FONT_PRIORITY, ensure_font


# Default label dimensions (can be overridden in settings)
DEFAULT_LABEL_WIDTH_MM = 80
DEFAULT_LABEL_HEIGHT_MM = 50

# Bundled Unicode fonts used to render native-script names (native language
# names, and volunteers' own names/usernames/pronouns) on printed labels.
# Together they cover Latin, Cyrillic, Greek, Armenian, Georgian, Hebrew,
# Arabic (isolated forms), CJK, and most South/Southeast Asian and
# Ethiopic scripts. None of these font files are committed to the repo --
# they are downloaded on demand (see volunteers/fonts_manifest.py and
# `manage.py download_fonts`). See THIRD_PARTY_LICENSES.md for license and
# attribution details.
_font_stack = None  # list of (font_name, glyph_set), in fallback priority order


def _register_font_stack():
    """
    Register every available bundled font with reportlab (downloading any
    that are missing), and build the ordered (font_name, glyph_set) stack
    used to pick a font per character. Cached after first call.
    """
    global _font_stack
    if _font_stack is not None:
        return _font_stack

    stack = []
    for key in FONT_PRIORITY:
        path = ensure_font(key)
        if not path:
            continue
        font_name = key
        try:
            if font_name not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(TTFont(font_name, path))
            face = pdfmetrics.getFont(font_name).face
            stack.append((font_name, set(face.charToGlyph.keys())))
        except Exception:
            continue

    _font_stack = stack
    return _font_stack


def _font_for_char(ch):
    """First registered font (in priority order) that has a glyph for ch, or None."""
    stack = _register_font_stack()
    code = ord(ch)
    for font_name, glyphs in stack:
        if code in glyphs:
            return font_name
    return None


def _font_supports(text):
    """Whether every character in text can be rendered by some bundled font."""
    return all(_font_for_char(ch) is not None for ch in text)


def _split_font_runs(text, primary_font='Helvetica'):
    """
    Split text into (font_name, substring) runs.

    Characters representable in `primary_font` (Helvetica/Helvetica-Bold/
    Helvetica-Oblique cover Latin-1: plain ASCII plus accented Western
    European letters) keep using it, so existing plain-Latin names and
    usernames keep their original look. Any other character is routed to
    the first bundled Unicode font (fallback priority order) that has a
    glyph for it. Characters no font can render fall back to Helvetica
    (shown as a placeholder glyph rather than crashing).
    """
    if not text:
        return []

    runs = []
    current_font = None
    current_chars = []
    for ch in text:
        if ord(ch) < 256:
            font_name = primary_font
        else:
            font_name = _font_for_char(ch) or 'Helvetica'
        if font_name != current_font:
            if current_chars:
                runs.append((current_font, ''.join(current_chars)))
            current_font = font_name
            current_chars = [ch]
        else:
            current_chars.append(ch)
    if current_chars:
        runs.append((current_font, ''.join(current_chars)))
    return runs


def _measure_mixed(c, text, size, primary_font='Helvetica'):
    """Total rendered width of text across its mixed-font runs."""
    return sum(c.stringWidth(run, font, size) for font, run in _split_font_runs(text, primary_font))


def _draw_mixed(c, x, y, text, size, primary_font='Helvetica'):
    """Draw text left-to-right, switching fonts per run as needed. Returns new x."""
    for font, run in _split_font_runs(text, primary_font):
        c.setFont(font, size)
        c.drawString(x, y, run)
        x += c.stringWidth(run, font, size)
    return x


def _fit_mixed_text(c, text, size, max_width, primary_font='Helvetica'):
    """Truncate mixed-script text with an ellipsis if it exceeds max_width."""
    if _measure_mixed(c, text, size, primary_font) <= max_width:
        return text

    while len(text) > 0 and _measure_mixed(c, text + '…', size, primary_font) > max_width:
        text = text[:-1]


    return text + '…'


def _language_label_text(language):
    """
    Native language name for print, falling back to the English name when
    no bundled font can render the native script.
    """
    native = language.label_name
    if native and _font_supports(native):
        return native
    return language.name



def get_label_size():
    """Return label size in points (from settings or defaults)."""
    width_mm = getattr(settings, 'LABEL_WIDTH_MM', DEFAULT_LABEL_WIDTH_MM)
    height_mm = getattr(settings, 'LABEL_HEIGHT_MM', DEFAULT_LABEL_HEIGHT_MM)
    return (width_mm * mm, height_mm * mm)


def generate_labels_pdf(volunteers, edition):
    """
    Generate a PDF containing front and back labels for each volunteer.

    Each volunteer gets two pages:
    - Page 1 (front): FOSDEM year, nick, name, pronouns, languages
    - Page 2 (back): task schedule

    Args:
        volunteers: queryset or list of Volunteer objects
        edition: the Edition object for this print run

    Returns:
        bytes: the PDF content
    """
    buffer = io.BytesIO()
    label_width, label_height = get_label_size()

    c = canvas.Canvas(buffer, pagesize=(label_width, label_height))

    for volunteer in volunteers:
        _draw_front_label(c, volunteer, edition, label_width, label_height)
        c.showPage()
        _draw_back_label(c, volunteer, edition, label_width, label_height)
        c.showPage()

    c.save()
    buffer.seek(0)
    return buffer.getvalue()


def _draw_front_label(c, volunteer, edition, width, height):
    """Draw the front label: FOSDEM year, nick, name, pronouns, languages."""
    margin = 4 * mm
    usable_width = width - 2 * margin

    # Start from top
    y = height - margin

    # FOSDEM Year header
    edition_year = edition.start_date.year
    c.setFont('Helvetica-Bold', 9)
    c.setFillColor(colors.HexColor('#8b1a4a'))  # FOSDEM purple/red
    c.drawString(margin, y - 9, f'FOSDEM {edition_year}')
    y -= 14

    # Separator line
    c.setStrokeColor(colors.HexColor('#8b1a4a'))
    c.setLineWidth(0.5)
    c.line(margin, y, width - margin, y)
    y -= 6

    # Username / nick (large)
    username = volunteer.user.username
    c.setFillColor(colors.black)
    # Truncate if too long
    display_nick = _fit_mixed_text(c, username, 14, usable_width, primary_font='Helvetica-Bold')
    _draw_mixed(c, margin, y - 14, display_nick, 14, primary_font='Helvetica-Bold')
    y -= 20

    # Full name
    full_name = f'{volunteer.user.first_name} {volunteer.user.last_name}'.strip()
    if full_name:
        display_name = _fit_mixed_text(c, full_name, 10, usable_width, primary_font='Helvetica')
        _draw_mixed(c, margin, y - 10, display_name, 10, primary_font='Helvetica')
        y -= 14

    # Pronouns
    if volunteer.pronouns:
        c.setFillColor(colors.HexColor('#555555'))
        display_pronouns = _fit_mixed_text(c, volunteer.pronouns, 8, usable_width, primary_font='Helvetica-Oblique')
        _draw_mixed(c, margin, y - 8, display_pronouns, 8, primary_font='Helvetica-Oblique')
        c.setFillColor(colors.black)
        y -= 12

    # Spoken languages
    languages = volunteer.spoken_languages.all()
    if languages:
        c.setFillColor(colors.HexColor('#333333'))
        lang_str = ', '.join(_language_label_text(lang) for lang in languages)
        display_langs = _fit_mixed_text(c, lang_str, 7, usable_width, primary_font='Helvetica')
        _draw_mixed(c, margin, y - 7, display_langs, 7, primary_font='Helvetica')
        c.setFillColor(colors.black)



def _draw_back_label(c, volunteer, edition, width, height):
    """Draw the back label: task schedule for the current edition."""
    margin = 4 * mm
    usable_width = width - 2 * margin

    y = height - margin

    # Header
    c.setFillColor(colors.HexColor('#8b1a4a'))
    header_text = f'Schedule — {volunteer.user.username}'
    header_text = _fit_mixed_text(c, header_text, 8, usable_width, primary_font='Helvetica-Bold')
    _draw_mixed(c, margin, y - 8, header_text, 8, primary_font='Helvetica-Bold')
    y -= 12

    # Separator
    c.setStrokeColor(colors.HexColor('#8b1a4a'))
    c.setLineWidth(0.5)
    c.line(margin, y, width - margin, y)
    y -= 4

    # Tasks
    tasks = volunteer.tasks.filter(edition=edition).order_by('date', 'start_time')

    if not tasks.exists():
        c.setFont('Helvetica-Oblique', 7)
        c.setFillColor(colors.HexColor('#888888'))
        c.drawString(margin, y - 7, 'No tasks assigned')
        return

    c.setFont('Helvetica', 6)
    c.setFillColor(colors.black)

    row_height = 8
    col_day_width = 12 * mm
    col_time_width = 20 * mm
    col_name_width = usable_width - col_day_width - col_time_width

    for task in tasks:
        if y - row_height < margin:
            # No more space on this label
            c.setFont('Helvetica-Oblique', 5)
            c.drawString(margin, y - 6, '... more tasks (see online)')
            break

        day_str = task.date.strftime('%a')
        time_str = f'{task.start_time.strftime("%H:%M")}-{task.end_time.strftime("%H:%M")}'
        task_name = _fit_mixed_text(c, task.name, 6, col_name_width, primary_font='Helvetica')

        x = margin
        c.setFont('Helvetica', 6)
        c.drawString(x, y - 6, day_str)
        x += col_day_width
        c.drawString(x, y - 6, time_str)
        x += col_time_width
        _draw_mixed(c, x, y - 6, task_name, 6, primary_font='Helvetica')

        y -= row_height
