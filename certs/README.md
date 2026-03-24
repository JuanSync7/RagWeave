<!-- @summary
TLS certificates for the nginx HTTPS gateway. Contents are git-ignored; generate with scripts/generate-certs.sh using mkcert.
@end-summary -->

# TLS Certificates

This directory holds TLS certificates for the nginx HTTPS gateway.
Contents are git-ignored except this README and `.gitkeep`.

## Generate certs (one-time)

1. Install mkcert:
   - Ubuntu/Debian: `sudo apt install mkcert`
   - macOS: `brew install mkcert`

2. Run the generation script:
   ```bash
   ./scripts/generate-certs.sh
   ```

3. Add the hosts entry:
   ```bash
   echo "127.0.0.1  aion.local" | sudo tee -a /etc/hosts
   ```

## For production

Swap the mkcert certs with Let's Encrypt or other CA-signed certs.
The filenames must match what `ops/nginx/nginx.conf` expects:
- `aion.local+1.pem` (certificate)
- `aion.local+1-key.pem` (private key)
