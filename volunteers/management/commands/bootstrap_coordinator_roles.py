from django.contrib.auth.models import Group, Permission
from django.core.management.base import BaseCommand, CommandError

from volunteers.permissions import ROLE_PERMISSIONS


class Command(BaseCommand):
    help = 'Create or update operational role groups and their default permissions.'

    def handle(self, *args, **options):
        for group_name, codenames in ROLE_PERMISSIONS.items():
            group, _ = Group.objects.get_or_create(name=group_name)
            permissions = Permission.objects.filter(
                content_type__app_label='volunteers',
                codename__in=codenames,
            )
            found = set(permissions.values_list('codename', flat=True))
            missing = codenames - found
            if missing:
                raise CommandError(
                    f'{group_name} permissions are missing: {", ".join(sorted(missing))}'
                )
            group.permissions.add(*permissions)
            self.stdout.write(
                self.style.SUCCESS(
                    f'{group_name}: {permissions.count()} permissions configured'
                )
            )
