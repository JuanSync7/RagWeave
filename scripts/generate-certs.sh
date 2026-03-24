#!/usr/bin/env bash
# Generate locally-trusted TLS certs for aion.local + localhost
set -euo pipefail

CERT_DIR="$(cd "$(dirname "$0")/.." && pwd)/certs"
mkdir -p "$CERT_DIR"

if ! command -v mkcert &>/dev/null; then
    echo "Error: mkcert is not installed."
    echo "Install with: sudo apt install mkcert (Debian/Ubuntu) or brew install mkcert (macOS)"
    exit 1
fi

# Install mkcert root CA if not already done
mkcert -install

# Generate cert for both hostnames
mkcert -cert-file "$CERT_DIR/aion.local+1.pem" \
       -key-file  "$CERT_DIR/aion.local+1-key.pem" \
       aion.local localhost 127.0.0.1 ::1

echo ""
echo "Certs written to $CERT_DIR/"
echo ""
echo "Add to /etc/hosts if not already present:"
echo "  127.0.0.1  aion.local"
