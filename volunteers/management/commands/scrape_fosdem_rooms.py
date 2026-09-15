import re
import urllib.error
import urllib.request

from django.core.management.base import BaseCommand

from volunteers.models import Location

# The FOSDEM schedule archive lists every physical room used in a given
# edition, grouped by building, with a link to that room's own page. Each
# room page in turn links out to the matching nav.fosdem.org (c3nav) map
# location. This command is a one-off/occasional helper to prepopulate
# Location rows with candidate nav_slug values - it is NOT run automatically
# on every import, since room assignments and slugs can change between
# editions and should be reviewed by a maintainer (see the Location admin).

ROOMS_URL = 'https://archive.fosdem.org/{year}/schedule/rooms/'
ROOM_PAGE_URL = 'https://archive.fosdem.org/{year}/schedule/room/{slug}/'

# Matches a building header cell, e.g. <th class="building" rowspan="7">K</th>
BUILDING_RE = re.compile(r'<th class="building"[^>]*>([^<]+)</th>')
# Matches a room link cell, e.g. <td><a href="/2025/schedule/room/k1105/">K.1.105 (La Fontaine)</a></td>
ROOM_RE = re.compile(r'<td><a href="/[^"]*/schedule/room/([a-zA-Z0-9_-]+)/">([^<]+)</a></td>')
# Matches the nav.fosdem.org map link on a room's own page.
NAV_LINK_RE = re.compile(r'https://nav\.fosdem\.org/l/([a-zA-Z0-9_-]+)/')


def normalize(name):
    """Lowercase, alphanumeric-only key used to fuzzy-match location names."""
    return re.sub(r'[^a-z0-9]', '', (name or '').lower())


class Command(BaseCommand):
    help = (
        'Scrape the FOSDEM schedule archive for a given year to prepopulate '
        'Location rows with a best-guess nav.fosdem.org (c3nav) slug. This is '
        'a one-off/occasional helper, not part of the regular import pipeline '
        '- results should be reviewed in the Django admin (Location list), '
        'since not every task/talk location is a real, mappable room, and '
        'slugs can change between editions.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--year', type=int, action='append', dest='years', required=True,
            help='FOSDEM edition year to scrape, e.g. --year 2025. Repeat to scrape multiple years.'
        )
        parser.add_argument(
            '--verify-nav-link', action='store_true', dest='verify_nav_link',
            help=(
                'Also fetch each room\'s own page to confirm its nav.fosdem.org slug '
                '(slower - one extra request per room, but more reliable than assuming '
                'the room-list slug matches the c3nav slug).'
            )
        )

    def handle(self, *args, **options):
        years = options['years']
        verify_nav_link = options['verify_nav_link']

        scraped = {}  # normalized key (from name or slug) -> {'name': ..., 'building': ..., 'nav_slug': ...}
        for year in years:
            self.stdout.write(f'Fetching room list for {year}...')
            try:
                html = self._fetch(ROOMS_URL.format(year=year))
            except (urllib.error.URLError, urllib.error.HTTPError) as exc:
                self.stderr.write(self.style.WARNING(f'  Could not fetch {year}: {exc}'))
                continue

            current_building = None
            found_this_year = 0
            # Walk the HTML in document order so we can track which building
            # header a room row falls under (rowspan means it's only present
            # on the first row of each group).
            for match in re.finditer(r'<th class="building"[^>]*>([^<]+)</th>|'
                                      r'<td><a href="/[^"]*/schedule/room/([a-zA-Z0-9_-]+)/">([^<]+)</a></td>',
                                      html):
                building, slug, name = match.group(1), match.group(2), match.group(3)
                if building is not None:
                    current_building = building.strip()
                    continue
                if slug is None:
                    continue
                nav_slug = slug
                if verify_nav_link:
                    nav_slug = self._confirm_nav_slug(year, slug) or slug
                entry = {
                    'name': name.strip(),
                    'building': current_building,
                    'nav_slug': nav_slug,
                }
                # Index by both the normalized full name (e.g. "K.1.105 (La
                # Fontaine)") and the normalized slug (e.g. "k1105"), since
                # our stored location strings are inconsistently formatted
                # and sometimes match one better than the other (our
                # "K1.105" matches the slug "k1105" but not the full name
                # with its parenthetical suffix).
                scraped[normalize(name)] = entry
                scraped.setdefault(normalize(slug), entry)
                found_this_year += 1
            self.stdout.write(f'  Found {found_this_year} room(s) for {year} ({len(scraped)} unique keys so far).')

        if not scraped:
            self.stderr.write(self.style.ERROR('No rooms scraped - nothing to do.'))
            return

        matched, unmatched = self._apply_to_locations(scraped)

        self.stdout.write(self.style.SUCCESS(
            f'Matched {matched} existing Location(s) with a nav.fosdem.org slug.'
        ))
        if unmatched:
            self.stdout.write(self.style.WARNING(
                f'{len(unmatched)} Location(s) still have no nav_slug and need a manual mapping:'
            ))
            for name in unmatched:
                self.stdout.write(f'  - {name}')

    def _fetch(self, url):
        req = urllib.request.Request(url, headers={'User-Agent': 'fosdem-volunteers-room-scraper/1.0'})
        with urllib.request.urlopen(req, timeout=30) as response:
            return response.read().decode('utf-8', errors='replace')

    def _confirm_nav_slug(self, year, slug):
        try:
            html = self._fetch(ROOM_PAGE_URL.format(year=year, slug=slug))
        except (urllib.error.URLError, urllib.error.HTTPError):
            return None
        match = NAV_LINK_RE.search(html)
        return match.group(1) if match else None

    def _apply_to_locations(self, scraped):
        matched = 0
        unmatched = []
        for location in Location.objects.all():
            key = normalize(location.name)
            hit = scraped.get(key)
            if hit:
                location.nav_slug = hit['nav_slug']
                if hit['building'] and not location.building:
                    location.building = hit['building']
                location.save()
                matched += 1
            elif not location.nav_slug:
                unmatched.append(location.name)
        return matched, unmatched
