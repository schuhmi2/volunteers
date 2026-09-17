# fosdem-volunteers

![build](https://github.com/FOSDEM/volunteers/actions/workflows/main.yml/badge.svg)
![codecov](https://codecov.io/gh/FOSDEM/volunteers/graph/badge.svg)

Volunteers management system for conferences, originally written for FOSDEM.
It helps an event team publish volunteer tasks, collect signups, coordinate
task owners, run check-in/check-out during the event, and keep operational
communication out of ad-hoc spreadsheets and private inboxes.

The application is a Django web app with a public volunteer-facing task list,
authenticated volunteer schedules and profiles, and staff-only operational
dashboards for approvals, attendance, task clashes, communications, labels,
T-shirts, Matrix IDs, and live event triage.

## Features

- **Volunteer task signup:** publish current-edition tasks, show capacity and
  pending-approval state, and let volunteers sign up, request approval, remove
  themselves, or withdraw pending requests.
- **Personal schedules:** volunteers can see their own approved and pending
  tasks, while other volunteers' schedules remain private unless the viewer has
  operational permission.
- **Scoped coordinator roles:** grant staff only the access they need through
  `Coordinator`, `Logistics`, and `Communications` groups, plus task-template
  primary/secondary ownership.
- **Approval workflow:** route approval-required task signups to coordinators,
  with approve/deny controls, prior task experience context, and audit logging.
- **Task clash management:** detect overlapping approved or pending signups,
  review connected clash groups, remove conflicting signups, or email the
  volunteer to resolve the conflict.
- **Attendance and check-in:** track task sign-in/sign-out, manually mark
  attendance, send reminder/sign-out links, and auto-sign-out stale sessions.
- **Runner workflow:** manage runner availability, summon runners by email or
  Matrix, request/approve deployments, and preserve runner history instead of
  destructively moving assignments.
- **Operations dashboard:** provide a read-only live triage view of active and
  starting-soon staffing gaps, check-in anomalies, pending approvals, clashes,
  available runners, and edition readiness.
- **Communications:** compose and preview targeted emails for volunteers signed
  up to a task, category, or edition, with coordinator/superuser permissions.
- **Operational exports:** generate task schedules/CSV, volunteer labels,
  T-shirt reports, and Matrix ID exports with approved-volunteer filtering.
- **Location support:** map task and talk locations to c3nav URLs where
  available, while retaining unmapped locations for manual cleanup.
- **Profile and privacy hardening:** keep contact details and attendance
  history permission-scoped, require email confirmation/privacy-policy consent,
  and support multilingual label rendering.

## Development setup

The production version uses Python 3.11. Continuous integration also runs the
test suite on Python 3.11 for production parity. The application currently
targets Django 5.2 LTS and ReportLab 5.x; dependency versions are pinned in
`requirements.txt`.

After cloning the repo:

1. Create and activate a Python virtual environment. Use Python 3.11 for
   parity with production and CI:

   ```console
   python3.11 -m venv ./venv
   source ./venv/bin/activate
   ```

2. Install dependencies:

   ```console
   pip install -r requirements.txt
   ```

   Use `requirements-dev.txt` instead when you also need the local CI tools
   (`coverage`, `pylint`, and `pylint-django`):

   ```console
   pip install -r requirements-dev.txt
   ```

   On debian these binary dependencies are required: 
   
   ```console
   sudo apt install libxml2-dev libxslt1-dev
   ```

3. Create `volunteer_mgmt/localsettings.py`:

   ```console
   cp volunteer_mgmt/localsettings_example.py volunteer_mgmt/localsettings.py
   ```

   The example uses local SQLite databases (`volunteers.db` and `penta.db`).
   For local development, set `DEBUG = True` in this file. Never commit
   `localsettings.py`, database files, or real secrets.

4. Set up the database and operational role groups:

   ```console
   ./manage.py migrate
   ./manage.py bootstrap_coordinator_roles
   ```

5. Collect static files:

   ```console
   ./manage.py collectstatic
   ```

6. Download the fonts used for printing volunteer labels in non-Latin scripts
   (optional -- this also happens automatically the first time a label PDF
   is generated, but running it up front avoids a delay on first use):

   ```console
   ./manage.py download_fonts
   ```

   See [THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md) for details.

7. Create a superuser:

   ```console
   ./manage.py createsuperuser
   ```

Operational access is granted through the `Coordinator`, `Logistics`, and
`Communications` Django groups. Migrations create these groups without adding
users to them. Their default permissions can be restored idempotently with
`./manage.py bootstrap_coordinator_roles`.

Task-scoped access is granted by selecting staff users as the primary or
secondary responsible on a task template.

8. Optionally import the bundled local task XML files:

   ```console
   ./manage.py import_init_data
   ```

   This requires a current edition to exist first. For a repeatable local
   development setup with users, roles, tasks, signups, and attendance data,
   see [AGENTS.md](AGENTS.md).

9. Run a development server:

   ```console
   ./manage.py runserver
   ```

   Open http://localhost:8000/.

10. In the admin interface at http://localhost:8000/admin/, make sure you
    create an edition before adding tasks manually.

## Testing

Run the Django test suite with:

```console
./manage.py test
```

Before committing dependency or framework changes, also run:

```console
./manage.py check
./manage.py makemigrations --check --dry-run
git diff --check
```

## Production setup

See [the playbook instructions](deployment/playbook/README.md) for more information.


## Third-party assets

See [THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md) for bundled third-party assets and their licenses.


## AI Disclosure

Parts of this codebase were written and reviewed with the assistance of AI tools. All AI-generated code has been proofread by a human developer and manually tested before being committed.
