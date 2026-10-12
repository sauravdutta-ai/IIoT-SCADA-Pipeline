#!/usr/bin/env bash

set -euo pipefail

export MSYS_NO_PATHCONV=1
export MSYS2_ARG_CONV_EXCL="*"

PASSWD_FILE="config/mosquitto/passwd"

echo "==> Generating Mosquitto MQTT credentials..."

if ! command -v docker >/dev/null 2>&1; then
    echo "ERROR: Docker is required."
    exit 1
fi

mkdir -p "$(dirname "$PASSWD_FILE")"

if [[ -f "$PASSWD_FILE" ]]; then
    echo "ERROR: $PASSWD_FILE already exists."
    echo "Remove it first if you want to regenerate the credentials."
    exit 1
fi

echo "==> Creating edge_publisher account..."

docker run --rm -it \
    -v "$(pwd)/config/mosquitto:/work" \
    eclipse-mosquitto:2.0.22 \
    mosquitto_passwd \
    -c \
    /work/passwd \
    edge_publisher

echo "==> Adding gateway_subscriber account..."

docker run --rm -it \
    -v "$(pwd)/config/mosquitto:/work" \
    eclipse-mosquitto:2.0.22 \
    mosquitto_passwd \
    /work/passwd \
    gateway_subscriber

chmod 600 "$PASSWD_FILE"

echo
echo "========================================"
echo "MQTT credential generation successful!"
echo "========================================"
echo
echo "Credential file:"
echo "  $PASSWD_FILE"
echo
echo "Users:"
echo "  edge_publisher"
echo "  gateway_subscriber"
echo
echo "The passwords are stored as hashes in the passwd file."