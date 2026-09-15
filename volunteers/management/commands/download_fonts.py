from django.core.management.base import BaseCommand

from volunteers.fonts_manifest import FONT_MANIFEST, ensure_font


class Command(BaseCommand):
    help = (
        'Download the open-source Unicode fonts used to render volunteer '
        'names and spoken languages in their native script on printed '
        'labels. Fonts are cached in volunteers/static/fonts/ (not '
        'committed to git) and verified against a pinned checksum; already '
        'present, verified fonts are skipped.'
    )

    def handle(self, *args, **options):
        failures = []
        for key in FONT_MANIFEST:
            path = ensure_font(key, stdout=self.stdout)
            if path is None:
                failures.append(key)

        if failures:
            self.stderr.write(self.style.WARNING(
                f'Could not download {len(failures)} font(s): {", ".join(failures)}. '
                'Native names for the affected scripts will fall back to English '
                'on printed labels until this is retried.'
            ))
        else:
            self.stdout.write(self.style.SUCCESS(
                f'All {len(FONT_MANIFEST)} label fonts are downloaded and verified.'
            ))
