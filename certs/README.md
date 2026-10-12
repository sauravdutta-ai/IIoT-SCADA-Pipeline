# MQTT TLS certificates

Generated certificate material is intentionally excluded from Git.

Generate a local CA and Mosquitto server certificate with:

    ./scripts/generate_certs.sh

The server certificate includes SANs for DNS:mosquitto, DNS:localhost,
and IP:127.0.0.1.

Private keys must never be committed.
