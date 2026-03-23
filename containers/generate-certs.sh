#!/usr/bin/env bash
set -euo pipefail

CERT_DIR="${1:-./.runtime/certs}"
CERT_FILE="$CERT_DIR/server.crt"
KEY_FILE="$CERT_DIR/server.key"

if [ -f "$CERT_FILE" ] && [ -f "$KEY_FILE" ]; then
    echo "[certs] Self-signed certs already exist at $CERT_DIR — skipping."
    exit 0
fi

mkdir -p "$CERT_DIR"
openssl req -x509 -nodes -days 365 \
    -newkey rsa:2048 \
    -keyout "$KEY_FILE" \
    -out "$CERT_FILE" \
    -subj "/CN=localhost/O=RAG-Dev/C=US" \
    -addext "subjectAltName=DNS:localhost,IP:127.0.0.1"

# Ensure cert permissions are correct for rootless container runtimes.
chmod 644 "$CERT_FILE"
chmod 600 "$KEY_FILE"

echo "[certs] Generated self-signed cert at $CERT_DIR"
