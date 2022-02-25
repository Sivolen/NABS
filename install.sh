#!/bin/bash
# This is a test script for installing NABS, I have not tested it to the end,
# if you have problems when running it, contact me.
# shellcheck disable=SC2164
cd "$(dirname "$0")"
VIRTUALENV="$(pwd -P)/venv"
PYTHON="${PYTHON:-python3}"

# Remove the existing virtual environment (if any)
if [ -d "$VIRTUALENV" ]; then
  COMMAND="rm -rf ${VIRTUALENV}"
  echo "Removing old virtual environment..."
  eval $COMMAND
else
  WARN_MISSING_VENV=1
fi

# Create a new virtual environment
COMMAND="${PYTHON} -m venv ${VIRTUALENV}"
echo "Creating a new virtual environment at ${VIRTUALENV}..."
eval $COMMAND || {
  echo "--------------------------------------------------------------------"
  echo "ERROR: Failed to create the virtual environment. Check that you have"
  echo "the required system packages installed and the following path is"
  echo "writable: ${VIRTUALENV}"
  echo "--------------------------------------------------------------------"
  exit 1
}

# Activate the virtual environment
source "${VIRTUALENV}/bin/activate"

# Upgrade pip
COMMAND="pip install --upgrade pip"
echo "Updating pip ($COMMAND)..."
eval $COMMAND || exit 1
pip -V

# Install necessary system packages
COMMAND="pip install wheel"
echo "Installing Python system packages ($COMMAND)..."
eval $COMMAND || exit 1

# Install required Python packages
COMMAND="pip install -r requirements.txt"
echo "Installing core dependencies ($COMMAND)..."
eval $COMMAND || exit 1

# Init DB
COMMAND="python3 flask db init"
echo "Initialization DB($COMMAND)..."
eval $COMMAND || exit 1

# Migration DB
COMMAND="python3 flask db migrate"
echo "Migration DB ($COMMAND)..."
eval $COMMAND || exit

# Upgrade DB
COMMAND="python3 flask db upgrade"
echo "Upgrade DB ($COMMAND)..."
eval $COMMAND || exit

# Status massage
if [ -v WARN_MISSING_VENV ]; then
  echo "--------------------------------------------------------------------"
  echo "WARNING: No existing virtual environment was detected. A new one has"
  echo "been created. Update your systemd service files to reflect the new"
  echo "Python and gunicorn executables. (If this is a new installation,"
  echo "this warning can be ignored.)"
  echo ""
  echo "nabs.service ExecStart:"
  echo "  ${VIRTUALENV}/bin/gunicorn"
  echo ""
  echo "nabs.service ExecStart:"
  echo "  ${VIRTUALENV}/bin/python"
  echo ""
  echo "After modifying these files, reload the systemctl daemon:"
  echo "  > systemctl daemon-reload"
  echo "--------------------------------------------------------------------"
fi
