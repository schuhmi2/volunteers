# Deploy fosdem-volunteers

## Prerequisites
* A system with SystemD is required.
* An account that can either switch to root via sudo or su; and to another user, is required.
* Python 3.11 must be available on the target host. The default role installs
  `python3.11` and `python3.11-venv`, creates the virtualenv with
  `python3.11`, and recreates an existing virtualenv if it was built with a
  different Python major/minor version. Override `python_version`,
  `python_executable`, and `python_system_packages` if your distribution uses
  different package names.

## Instructions
* Run the provided playbook with the correct inventory.

## Manual actions
* A `localsettings.py` file must still be created. Copy the provided `localsettings_example.py` file and modify it according to your needs.
