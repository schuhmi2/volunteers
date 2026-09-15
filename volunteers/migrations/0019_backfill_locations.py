from django.db import migrations


def backfill_locations(apps, schema_editor):
    """Create a Location row for every distinct Task/Talk location string,
    and point location_ref at it. nav_slug is left blank here - populate it
    via the scrape_fosdem_rooms management command and/or the Location
    admin.
    """
    Task = apps.get_model('volunteers', 'Task')
    Talk = apps.get_model('volunteers', 'Talk')
    Location = apps.get_model('volunteers', 'Location')

    names = set()
    names.update(
        Task.objects.exclude(location__isnull=True).exclude(location='')
        .values_list('location', flat=True).distinct()
    )
    names.update(
        Talk.objects.exclude(location__isnull=True).exclude(location='')
        .values_list('location', flat=True).distinct()
    )

    locations_by_name = {}
    for name in names:
        name = name.strip()
        if not name:
            continue
        location, _created = Location.objects.get_or_create(name=name)
        locations_by_name[name] = location

    for name, location in locations_by_name.items():
        Task.objects.filter(location=name, location_ref__isnull=True).update(location_ref=location)
        Talk.objects.filter(location=name, location_ref__isnull=True).update(location_ref=location)


def noop_reverse(apps, schema_editor):
    # Not reversing Location creation/linking - it's non-destructive to leave
    # location_ref set and Location rows in place.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('volunteers', '0018_location_talk_location_ref_task_location_ref'),
    ]

    operations = [
        migrations.RunPython(backfill_locations, noop_reverse),
    ]
