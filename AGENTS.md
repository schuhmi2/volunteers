# Agent local development guide

This file is for coding agents and maintainers who need a clean local
FOSDEM Volunteers environment with realistic sample data. Keep all commands
repo-root relative. Do not commit `volunteer_mgmt/localsettings.py`,
`volunteers.db`, `penta.db`, `secret.txt`, generated static files, or real
personal data.

## Fast setup

Use Python 3.11 for parity with production and CI. The app targets Django
5.2 LTS and ReportLab 5.x; do not downgrade framework or PDF dependencies
without an explicit compatibility reason.

```bash
python3.11 -m venv venv
source venv/bin/activate
pip install -r requirements-dev.txt
cp volunteer_mgmt/localsettings_example.py volunteer_mgmt/localsettings.py
```

Use `requirements.txt` for app-only environments and `requirements-dev.txt`
for coding-agent/CI-style validation. The dev requirements include the app
pins plus `coverage`, `pylint`, and `pylint-django`.

Edit `volunteer_mgmt/localsettings.py` for local development:

```python
DEBUG = True
SECRET_KEY = 'local-dev-only'
EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'
```

Then initialize Django:

```bash
venv/bin/python manage.py migrate
venv/bin/python manage.py bootstrap_coordinator_roles
venv/bin/python manage.py collectstatic --noinput
```

Optional, but useful for label/PDF work:

```bash
venv/bin/python manage.py download_fonts
```

## Populate local sample data

The following command creates a current edition, operational users, task
templates, representative tasks, approved/pending/denied signups, and
attendance records. It is idempotent enough for normal local iteration:
rerunning updates/reuses the same named objects.

```bash
venv/bin/python manage.py shell <<'PY'
import datetime

from django.contrib.auth.models import Group, User
from django.utils import timezone

from volunteers.models import (
    CURRENT_PRIVACY_POLICY_VERSION,
    Edition,
    Task,
    TaskAttendance,
    TaskCategory,
    TaskTemplate,
    Volunteer,
    VolunteerTask,
)

today = timezone.localdate()

edition, _ = Edition.objects.update_or_create(
    name='Local Dev Edition',
    defaults={
        'start_date': today,
        'end_date': today + datetime.timedelta(days=2),
        'visible_from': today - datetime.timedelta(days=7),
        'visible_until': today + datetime.timedelta(days=30),
        'enable_task_signin': True,
    },
)

users = {
    'admin': {
        'email': 'admin@example.test',
        'first_name': 'Local',
        'last_name': 'Admin',
        'is_staff': True,
        'is_superuser': True,
    },
    'coordinator': {
        'email': 'coordinator@example.test',
        'first_name': 'Casey',
        'last_name': 'Coordinator',
        'is_staff': True,
    },
    'logistics': {
        'email': 'logistics@example.test',
        'first_name': 'Logan',
        'last_name': 'Logistics',
        'is_staff': True,
    },
    'comms': {
        'email': 'comms@example.test',
        'first_name': 'Morgan',
        'last_name': 'Comms',
        'is_staff': True,
    },
    'alice': {
        'email': 'alice@example.test',
        'first_name': 'Alice',
        'last_name': 'Volunteer',
    },
    'bob': {
        'email': 'bob@example.test',
        'first_name': 'Bob',
        'last_name': 'Runner',
    },
    'carol': {
        'email': 'carol@example.test',
        'first_name': 'Carol',
        'last_name': 'Pending',
    },
    'dana': {
        'email': 'dana@example.test',
        'first_name': 'Dana',
        'last_name': 'Denied',
    },
}

for username, defaults in users.items():
    user, created = User.objects.update_or_create(
        username=username,
        defaults=defaults,
    )
    if created:
        user.set_password('password')
        user.save(update_fields=['password'])
    Volunteer.objects.update_or_create(
        user=user,
        defaults={
            'email_confirmed': True,
            'privacy_policy_accepted_at': timezone.now(),
            'privacy_policy_version': CURRENT_PRIVACY_POLICY_VERSION,
            'matrix_id': f'@{username}:example.test',
            'mobile_nbr': '+32123456789' if username in {'alice', 'bob'} else '',
        },
    )

Group.objects.get(name='Coordinator').user_set.add(User.objects.get(username='coordinator'))
Group.objects.get(name='Logistics').user_set.add(User.objects.get(username='logistics'))
Group.objects.get(name='Communications').user_set.add(User.objects.get(username='comms'))

category, _ = TaskCategory.objects.update_or_create(
    name='Local Operations',
    defaults={'description': 'Local development tasks', 'active': True},
)
template, _ = TaskTemplate.objects.update_or_create(
    name='Local Operations',
    defaults={
        'description': 'Local development task template',
        'category': category,
        'primary': User.objects.get(username='coordinator'),
        'secondary': User.objects.get(username='comms'),
    },
)
approval_template, _ = TaskTemplate.objects.update_or_create(
    name='Approval Required',
    defaults={
        'description': 'Template that requires approval',
        'category': category,
        'primary': User.objects.get(username='coordinator'),
        'requires_approval': True,
    },
)

def make_task(name, start, end, template=template, min_count=1, target=2, max_count=4):
    task, _ = Task.objects.update_or_create(
        edition=edition,
        name=name,
        counter='1',
        defaults={
            'description': f'{name} local development task',
            'location': 'K building',
            'date': today,
            'start_time': start,
            'end_time': end,
            'nbr_volunteers_min': min_count,
            'nbr_volunteers': target,
            'nbr_volunteers_max': max_count,
            'template': template,
        },
    )
    return task

active_task = make_task('Info Desk Local', datetime.time(8, 0), datetime.time(23, 0))
runner_task = make_task('Runner', datetime.time(8, 0), datetime.time(23, 0))
approval_task = make_task(
    'Approval Queue Local',
    datetime.time(9, 0),
    datetime.time(10, 0),
    template=approval_template,
)
future_task = make_task('Future Local Shift', datetime.time(14, 0), datetime.time(16, 0))

def signup(username, task, status='approved'):
    volunteer = User.objects.get(username=username).volunteer
    vt, _ = VolunteerTask.objects.update_or_create(
        volunteer=volunteer,
        task=task,
        defaults={'status': status},
    )
    return vt

alice_active = signup('alice', active_task, 'approved')
bob_runner = signup('bob', runner_task, 'approved')
signup('carol', approval_task, 'pending')
signup('dana', future_task, 'denied')
signup('alice', future_task, 'approved')

TaskAttendance.objects.update_or_create(
    volunteer_task=alice_active,
    defaults={'signed_in_at': timezone.now(), 'signed_out_at': None},
)
TaskAttendance.objects.update_or_create(
    volunteer_task=bob_runner,
    defaults={'signed_in_at': timezone.now(), 'signed_out_at': None},
)

print('Local users: admin/password, coordinator/password, logistics/password, comms/password, alice/password, bob/password, carol/password, dana/password')
print('Local Dev Edition ready:', edition)
PY
```

If you also want the XML-defined generic task set:

```bash
venv/bin/python manage.py import_init_data
```

## Running and validating

Run the app:

```bash
venv/bin/python manage.py runserver 0.0.0.0:8000
```

Useful local URLs:

- Homepage: http://localhost:8000/
- Django admin: http://localhost:8000/admin/
- Tasks: http://localhost:8000/tasks/
- Operations dashboard: http://localhost:8000/admin-operations/
- Attendance dashboard: http://localhost:8000/admin-attendance/
- Approvals: http://localhost:8000/admin-approvals/
- Task clashes: http://localhost:8000/admin-task-clashes/

Before handing work back, run:

```bash
venv/bin/python manage.py test
venv/bin/python manage.py check
venv/bin/python manage.py makemigrations --check --dry-run
git diff --check
```

For dependency/framework changes, also run:

```bash
venv/bin/python -m pip check
DJANGO_SETTINGS_MODULE=volunteer_mgmt.settings venv/bin/pylint --load-plugins pylint_django --fail-under=7 volunteers/
```

Use the smallest targeted test while iterating, then the full suite before a
commit or handoff. If a Django upgrade creates a migration, inspect it before
committing and verify `makemigrations --check --dry-run` is clean afterward.
