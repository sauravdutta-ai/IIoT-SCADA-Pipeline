#!/usr/bin/env bash

set -euo pipefail

export MSYS_NO_PATHCONV=1
export MSYS2_ARG_CONV_EXCL="*"

CERT_DIR="certs"

CA_KEY="$CERT_DIR/ca.key"
CA_CERT="$CERT_DIR/ca.crt"
SERVER_KEY="$CERT_DIR/server.key"
SERVER_CSR="$CERT_DIR/server.csr"
SERVER_CERT="$CERT_DIR/server.crt"
EXT_FILE="$CERT_DIR/server.ext"

DAYS="${CERT_DAYS:-825}"

echo "==> Generating TLS certificates in: $CERT_DIR"

mkdir -p "$CERT_DIR"

if [[ -f "$CA_KEY" || -f "$CA_CERT" || -f "$SERVER_KEY" || -f "$SERVER_CERT" ]]; then
    echo "ERROR: Existing certificate material was found."
    echo "Remove the existing generated certificate files before regenerating."
    exit 1
fi

echo "==> Generating Certificate Authority..."

openssl genrsa \
    -out "$CA_KEY" \
    4096

openssl req \
    -x509 \
    -new \
    -nodes \
    -key "$CA_KEY" \
    -sha256 \
    -days "$DAYS" \
    -out "$CA_CERT" \
    -subj "/C=IN/ST=Assam/L=Local/O=IIOT-SCADA/CN=IIOT-SCADA-Root-CA"

echo "==> Generating Mosquitto server private key..."

openssl genrsa \
    -out "$SERVER_KEY" \
    2048

echo "==> Generating Mosquitto server CSR..."

openssl req \
    -new \
    -key "$SERVER_KEY" \
    -out "$SERVER_CSR" \
    -subj "/C=IN/ST=Assam/L=Local/O=IIOT-SCADA/CN=mosquitto"

cat > "$EXT_FILE" <<EOF
authorityKeyIdentifier=keyid,issuer
basicConstraints=CA:FALSE
keyUsage=digitalSignature,keyEncipherment
extendedKeyUsage=serverAuth
subjectAltName=DNS:mosquitto,DNS:localhost,IP:127.0.0.1
EOF

echo "==> Signing Mosquitto server certificate..."

openssl x509 \
    -req \
    -in "$SERVER_CSR" \
    -CA "$CA_CERT" \
    -CAkey "$CA_KEY" \
    -CAcreateserial \
    -out "$SERVER_CERT" \
    -days "$DAYS" \
    -sha256 \
    -extfile "$EXT_FILE"

rm -f "$EXT_FILE"

echo "==> Verifying server certificate..."

openssl verify \
    -CAfile "$CA_CERT" \
    "$SERVER_CERT"

chmod 600 "$CA_KEY" "$SERVER_KEY"
chmod 644 "$CA_CERT" "$SERVER_CERT"

echo
echo "========================================"
echo "TLS certificate generation successful!"
echo "========================================"
echo
echo "Generated files:"
echo "  CA certificate : $CA_CERT"
echo "  Server cert    : $SERVER_CERT"
echo "  Server key     : $SERVER_KEY"
echo
echo "Private keys must NOT be committed to Git."