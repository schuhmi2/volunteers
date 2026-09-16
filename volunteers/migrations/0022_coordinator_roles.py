from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


PERMISSIONS = {
    'manage_approvals': 'Can manage signup approvals',
    'manage_task_clashes': 'Can manage task clashes',
    'manage_attendance': 'Can manage task attendance',
    'assign_volunteers': 'Can assign volunteers',
    'event_signon': 'Can sign on event volunteers',
    'view_other_schedules': 'Can view other volunteer schedules',
    'view_volunteer_history': 'Can view full volunteer history',
    'export_task_schedules': 'Can export task schedules',
    'manage_labels': 'Can generate volunteer labels',
    'view_tshirt_report': 'Can view T-shirt reports',
    'export_matrix_ids': 'Can export Matrix IDs',
    'send_mass_mail': 'Can send mass mail',
}

ROLE_PERMISSIONS = {
    'Coordinator': {
        'manage_approvals',
        'manage_task_clashes',
        'manage_attendance',
        'assign_volunteers',
        'event_signon',
        'view_other_schedules',
        'export_task_schedules',
    },
    'Logistics': {
        'manage_labels',
        'view_tshirt_report',
        'export_matrix_ids',
    },
    'Communications': {
        'send_mass_mail',
    },
}


def create_roles(apps, schema_editor):
    ContentType = apps.get_model('contenttypes', 'ContentType')
    Group = apps.get_model('auth', 'Group')
    Permission = apps.get_model('auth', 'Permission')
    db_alias = schema_editor.connection.alias
    content_type, _ = ContentType.objects.using(db_alias).get_or_create(
        app_label='volunteers',
        model='tasktemplate',
    )

    permissions = {}
    for codename, name in PERMISSIONS.items():
        permission, _ = Permission.objects.using(db_alias).update_or_create(
            content_type=content_type,
            codename=codename,
            defaults={'name': name},
        )
        permissions[codename] = permission

    for group_name, codenames in ROLE_PERMISSIONS.items():
        group, _ = Group.objects.using(db_alias).get_or_create(name=group_name)
        group.permissions.add(*(permissions[codename] for codename in codenames))


class Migration(migrations.Migration):

    dependencies = [
        ('volunteers', '0021_remove_private_staff_notes'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='tasktemplate',
            options={
                'ordering': ['name'],
                'permissions': [
                    ('manage_approvals', 'Can manage signup approvals'),
                    ('manage_task_clashes', 'Can manage task clashes'),
                    ('manage_attendance', 'Can manage task attendance'),
                    ('assign_volunteers', 'Can assign volunteers'),
                    ('event_signon', 'Can sign on event volunteers'),
                    ('view_other_schedules', 'Can view other volunteer schedules'),
                    ('view_volunteer_history', 'Can view full volunteer history'),
                    ('export_task_schedules', 'Can export task schedules'),
                    ('manage_labels', 'Can generate volunteer labels'),
                    ('view_tshirt_report', 'Can view T-shirt reports'),
                    ('export_matrix_ids', 'Can export Matrix IDs'),
                    ('send_mass_mail', 'Can send mass mail'),
                ],
                'verbose_name': 'Task Template',
                'verbose_name_plural': 'Task Templates',
            },
        ),
        migrations.AlterField(
            model_name='tasktemplate',
            name='primary',
            field=models.ForeignKey(
                default=1,
                limit_choices_to={'is_staff': True},
                on_delete=django.db.models.deletion.PROTECT,
                related_name='primary_task_templates',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name='tasktemplate',
            name='secondary',
            field=models.ForeignKey(
                blank=True,
                limit_choices_to={'is_staff': True},
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='secondary_task_templates',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddConstraint(
            model_name='tasktemplate',
            constraint=models.CheckConstraint(
                check=~models.Q(primary=models.F('secondary')),
                name='tasktemplate_distinct_responsibles',
            ),
        ),
        migrations.RunPython(create_roles, migrations.RunPython.noop),
    ]
