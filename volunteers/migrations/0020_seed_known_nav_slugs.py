from django.db import migrations

# Curated nav.fosdem.org (c3nav) slug mappings for the Location rows created by
# 0019_backfill_locations. Populated via a mix of the scrape_fosdem_rooms
# management command (verified against archive.fosdem.org / nav.fosdem.org)
# and manual confirmation from a maintainer for locations the scraper could
# not resolve automatically (non-room or historically-named locations).
#
# Locations intentionally left unmapped (no single nav.fosdem.org room):
# 'H Building', 'K Building', 'U Building' (building-level, not one room),
# 'Kortenberg (not ULB)' (offsite venue), 'Matrix chat.fosdem.org' (virtual),
# 'NOC' (internal service area, not on the public map).
NAV_SLUGS = {
    'Janson': 'janson',
    'K1.105': 'k1105',
    'H2.215': 'h2215',
    'H.2111': 'h2111',
    'UB4.228': 'ub4228',
    'AW Building': 'aw',
    'AW1.125': 'aw1125',
    'Cloakroom K Building': 'cloakroom',
    'H 2.115 (Ferrer)': 'h2215',
    'Infodesk H': 'h2-infodesk',
    'Infodesk K': 'k_infodesk',
}


def apply_nav_slugs(apps, schema_editor):
    Location = apps.get_model('volunteers', 'Location')
    for name, slug in NAV_SLUGS.items():
        Location.objects.filter(name=name).update(nav_slug=slug)


def clear_nav_slugs(apps, schema_editor):
    Location = apps.get_model('volunteers', 'Location')
    Location.objects.filter(name__in=NAV_SLUGS.keys()).update(nav_slug=None)


class Migration(migrations.Migration):

    dependencies = [
        ('volunteers', '0019_backfill_locations'),
    ]

    operations = [
        migrations.RunPython(apply_nav_slugs, clear_nav_slugs),
    ]
