fosdem-volunteers
=================

![build](https://github.com/Logout22/volunteers/actions/workflows/main.yml/badge.svg)
![codecov](https://codecov.io/gh/Logout22/volunteers/graph/badge.svg)

Volunteers management system for conferences, originally written for FOSDEM.

Development setup
=================

The tool has been tested on Python3.10 and Python3.11. Python3.13 is not currently supported.
The production version of this uses Python3.11 (as of Jan 2025).

After cloning the repo do these steps:

1) Create a python environment using python3. 
   eg: `virtualenv -p /usr/bin/python3 ./venv`
   and activate this environment whenever working on the project (all other steps assume this)

   ```console
   source ./venv/bin/activate
   ```

2) Install all dependencies in the environment:

   ```console
   pip install -r requirements-dev.txt

   ```
   On debian these binary dependencies are required: 
   
   ```console
   sudo apt install libxml2-dev libxslt1-dev
   ```

3) create a `volunteer_mgmt/localsettings.py` file
   you can copy volunteer_mgmt/localsettings_example.py as a starting point.
   By default this uses a sqlite3 database.
   When running locally for development, make sure you add the line "DEBUG=True".

4) set up the initial database:
   ```
   ./manage.py migrate
   ```

5) make sure that all static files are collected
   ```
   ./manage.py collectstatic
   ```

6) download the fonts used for printing volunteer labels in non-Latin scripts
   (optional -- this also happens automatically the first time a label PDF
   is generated, but running it up front avoids a delay on first use):
   ```
   ./manage.py download_fonts
   ```
   See [THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md) for details.

7) create a superuser:
   ```
   ./manage.py createsuperuser
   ```

8) run a development server:
   ```
   ./manage.py runserver
   ```
   which should give you: http://localhost:8000/
9) in the admin interface http://localhost:8000/admin/ - make sure you create an edition before adding any other things


Production setup 
================
See [the playbook instructions](deployment/playbook/README.md) for more information.


Third-party assets
===================
See [THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md) for bundled third-party assets and their licenses.


AI Disclosure
=============

Parts of this codebase were written and reviewed with the assistance of AI tools. All AI-generated code has been proofread by a human developer and manually tested before being committed.
