import re
from django.db import migrations


def extract_info_url(apps, schema_editor):
    Task = apps.get_model('volunteers', 'Task')
    TaskTemplate = apps.get_model('volunteers', 'TaskTemplate')

    pattern = re.compile(r'\n?\s*Read more at (https?://\S+)\s*$', re.MULTILINE)

    for model_class in [Task, TaskTemplate]:
        for obj in model_class.objects.all():
            if obj.description:
                match = pattern.search(obj.description)
                if match:
                    obj.info_url = match.group(1).strip()
                    obj.description = pattern.sub('', obj.description).rstrip()
                    obj.save()


def reverse_extract_info_url(apps, schema_editor):
    Task = apps.get_model('volunteers', 'Task')
    TaskTemplate = apps.get_model('volunteers', 'TaskTemplate')

    for model_class in [Task, TaskTemplate]:
        for obj in model_class.objects.all():
            if obj.info_url:
                if obj.description:
                    obj.description = obj.description + '\nRead more at ' + obj.info_url
                else:
                    obj.description = 'Read more at ' + obj.info_url
                obj.info_url = None
                obj.save()


class Migration(migrations.Migration):

    dependencies = [
        ('volunteers', '0007_task_info_url_tasktemplate_info_url'),
    ]

    operations = [
        migrations.RunPython(extract_info_url, reverse_code=reverse_extract_info_url),
    ]
