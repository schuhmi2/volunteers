from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('volunteers', '0022_coordinator_roles'),
    ]

    operations = [
        migrations.CreateModel(
            name='RunnerDeployment',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('requested_at', models.DateTimeField(auto_now_add=True)),
                ('reviewed_at', models.DateTimeField(blank=True, null=True)),
                ('deployed_at', models.DateTimeField(blank=True, null=True)),
                ('returned_at', models.DateTimeField(blank=True, null=True)),
                ('status', models.CharField(choices=[('pending', 'Pending Approval'), ('active', 'Deployed'), ('completed', 'Returned'), ('denied', 'Denied'), ('cancelled', 'Cancelled'), ('invalidated', 'Invalidated')], default='pending', max_length=12)),
                ('review_note', models.TextField(blank=True)),
                ('destination_assignment', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='destination_deployments', to='volunteers.volunteertask')),
                ('destination_task', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='runner_deployments', to='volunteers.task')),
                ('requested_by', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='requested_runner_deployments', to=settings.AUTH_USER_MODEL)),
                ('reviewed_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='reviewed_runner_deployments', to=settings.AUTH_USER_MODEL)),
                ('runner_assignment', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='runner_deployments', to='volunteers.volunteertask')),
            ],
            options={
                'verbose_name': 'Runner Deployment',
                'verbose_name_plural': 'Runner Deployments',
                'ordering': ['-requested_at'],
            },
        ),
        migrations.AddConstraint(
            model_name='runnerdeployment',
            constraint=models.UniqueConstraint(
                condition=models.Q(status__in=('pending', 'active')),
                fields=('runner_assignment',),
                name='one_open_runner_deployment',
            ),
        ),
    ]
