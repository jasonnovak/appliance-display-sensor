#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
PROJECT_DIR="$(dirname -- "$SCRIPT_DIR")"
VENV_DIR="$PROJECT_DIR/.venv"

if ! command -v sudo >/dev/null 2>&1; then
    echo "sudo is required to install Raspberry Pi OS packages." >&2
    exit 1
fi

echo "Installing Raspberry Pi OS runtime packages..."
sudo apt-get update
sudo apt-get install -y --no-install-recommends \
    git \
    python3-numpy \
    python3-opencv \
    python3-paho-mqtt \
    python3-picamera2 \
    python3-pip \
    python3-setuptools \
    python3-venv \
    python3-wheel \
    python3-yaml

echo "Creating the project virtual environment..."
python3 -m venv --system-site-packages "$VENV_DIR"

"$VENV_DIR/bin/python" -m pip install \
    --no-build-isolation \
    --no-deps \
    --editable "$PROJECT_DIR"

echo "Running the test suite..."
cd "$PROJECT_DIR"
"$VENV_DIR/bin/python" -m unittest discover -s tests -v

cat <<EOF

Raspberry Pi runtime setup completed successfully.

Activate the environment with:
  source "$VENV_DIR/bin/activate"

The physical camera is not required for these tests. Use the documented finite
live-camera smoke test after connecting and calibrating a camera module.
EOF
