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


# Default label dimensions (can be overridden in settings)
DEFAULT_LABEL_WIDTH_MM = 80
DEFAULT_LABEL_HEIGHT_MM = 50


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
    c.setFont('Helvetica-Bold', 14)
    c.setFillColor(colors.black)
    # Truncate if too long
    display_nick = _fit_text(c, username, 'Helvetica-Bold', 14, usable_width)
    c.drawString(margin, y - 14, display_nick)
    y -= 20

    # Full name
    full_name = f'{volunteer.user.first_name} {volunteer.user.last_name}'.strip()
    if full_name:
        c.setFont('Helvetica', 10)
        display_name = _fit_text(c, full_name, 'Helvetica', 10, usable_width)
        c.drawString(margin, y - 10, display_name)
        y -= 14

    # Pronouns
    if volunteer.pronouns:
        c.setFont('Helvetica-Oblique', 8)
        c.setFillColor(colors.HexColor('#555555'))
        c.drawString(margin, y - 8, volunteer.pronouns)
        c.setFillColor(colors.black)
        y -= 12

    # Spoken languages
    languages = volunteer.spoken_languages.all()
    if languages:
        c.setFont('Helvetica', 7)
        c.setFillColor(colors.HexColor('#333333'))
        lang_str = ', '.join(lang.name for lang in languages)
        display_langs = _fit_text(c, f'🗣 {lang_str}', 'Helvetica', 7, usable_width)
        c.drawString(margin, y - 7, display_langs)
        c.setFillColor(colors.black)


def _draw_back_label(c, volunteer, edition, width, height):
    """Draw the back label: task schedule for the current edition."""
    margin = 4 * mm
    usable_width = width - 2 * margin

    y = height - margin

    # Header
    c.setFont('Helvetica-Bold', 8)
    c.setFillColor(colors.HexColor('#8b1a4a'))
    c.drawString(margin, y - 8, f'Schedule — {volunteer.user.username}')
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
        task_name = _fit_text(c, task.name, 'Helvetica', 6, col_name_width)

        x = margin
        c.setFont('Helvetica', 6)
        c.drawString(x, y - 6, day_str)
        x += col_day_width
        c.drawString(x, y - 6, time_str)
        x += col_time_width
        c.drawString(x, y - 6, task_name)

        y -= row_height


def _fit_text(c, text, font_name, font_size, max_width):
    """Truncate text with ellipsis if it exceeds max_width."""
    if c.stringWidth(text, font_name, font_size) <= max_width:
        return text

    while len(text) > 0 and c.stringWidth(text + '…', font_name, font_size) > max_width:
        text = text[:-1]

    return text + '…'
