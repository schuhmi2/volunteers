from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('volunteers', '0006_fix_email_confirmed'),
    ]

    operations = [
        migrations.AddField(
            model_name='task',
            name='info_url',
            field=models.URLField(blank=True, help_text='Link to volunteer documentation for this task', null=True),
        ),
        migrations.AddField(
            model_name='tasktemplate',
            name='info_url',
            field=models.URLField(blank=True, help_text='Link to volunteer documentation for this task type', null=True),
        ),
    ]
