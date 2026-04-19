#!/usr/bin/env bash
# @summary
# Fixes Docker bridge networking on WSL2 where inter-container TCP is broken.
# Safe to run on any platform — detects WSL2 and no-ops on Linux/macOS.
# On WSL2, must be run with sudo. Add to /etc/wsl.conf [boot] command for
# automatic fix on every WSL2 startup (see README.md for setup instructions).
# Exports: (none — standalone script)
# Deps: iptables, sysctl (WSL2 only)
# @end-summary
set -euo pipefail

# ── Detect environment ───────────────────────────────────────────────
is_wsl2() {
    [[ -f /proc/version ]] && grep -qi "microsoft" /proc/version && \
    [[ "$(uname -r)" == *"microsoft"* || "$(uname -r)" == *"WSL"* ]]
}

if ! is_wsl2; then
    echo "[docker-net] Not WSL2 — no networking fix needed on this platform."
    exit 0
fi

if [[ $EUID -ne 0 ]]; then
    echo "Error: WSL2 networking fix requires root. Run: sudo $0" >&2
    exit 1
fi

echo "[docker-net] WSL2 detected — applying Docker bridge networking fix..."

echo "[docker-net] Enabling IP forwarding..."
sysctl -w net.ipv4.ip_forward=1 >/dev/null
sysctl -w net.bridge.bridge-nf-call-iptables=0 2>/dev/null || true

echo "[docker-net] Setting FORWARD policy to ACCEPT..."
iptables -P FORWARD ACCEPT

echo "[docker-net] Adding FORWARD rules for Docker bridges (if missing)..."
iptables -C FORWARD -i br+ -j ACCEPT 2>/dev/null || iptables -I FORWARD -i br+ -j ACCEPT
iptables -C FORWARD -o br+ -j ACCEPT 2>/dev/null || iptables -I FORWARD -o br+ -j ACCEPT

echo "[docker-net] Restarting Docker daemon to regenerate iptables rules..."
service docker restart

echo "[docker-net] Done. Inter-container networking should now work."
