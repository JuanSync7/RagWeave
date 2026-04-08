#!/usr/bin/env bash
# =============================================================================
# Supply Chain Watchdog — Baseline & Drift Detection
# =============================================================================
# First run:  takes a snapshot of your system's security-relevant state.
# Later runs: compares current state to baseline and flags what changed.
#
# Usage:
#   chmod +x watchdog.sh
#   ./watchdog.sh                    # interactive — baseline or check
#   ./watchdog.sh --baseline         # force new baseline
#   ./watchdog.sh --check            # compare against baseline
#   ./watchdog.sh --check --quiet    # only output if drift found (for cron)
#
# Cron example (daily at 8am, only alerts on drift):
#   0 8 * * * /home/user/watchdog.sh --check --quiet >> /home/user/.watchdog/alerts.log 2>&1
#
# Baseline stored in: ~/.watchdog/baseline/
# =============================================================================

set -uo pipefail

# ─── Config ─────────────────────────────────────────────────────────────────
WATCHDOG_DIR="${HOME}/.watchdog"
BASELINE_DIR="${WATCHDOG_DIR}/baseline"
SCAN_ROOTS=("$HOME")  # Add more paths to monitor, e.g. /opt/projects
QUIET=false
MODE=""

# Parse args
for arg in "$@"; do
    case "$arg" in
        --baseline) MODE="baseline" ;;
        --check)    MODE="check" ;;
        --quiet)    QUIET=true ;;
    esac
done

# ─── Colours ────────────────────────────────────────────────────────────────
RED=$'\033[0;31m'; YELLOW=$'\033[1;33m'; GREEN=$'\033[0;32m'
CYAN=$'\033[0;36m'; BOLD=$'\033[1m'; DIM=$'\033[2m'; NC=$'\033[0m'

DRIFT_COUNT=0

log_drift() {
    DRIFT_COUNT=$((DRIFT_COUNT + 1))
    echo "  ${RED}[DRIFT]${NC}  $1"
    echo "    ${YELLOW}Fix:${NC}    $2"
    echo ""
}

log_ok() {
    $QUIET || echo "  ${GREEN}[OK]${NC}     $1"
}

log_info() {
    $QUIET || echo "  ${CYAN}[INFO]${NC}   $1"
}

section() {
    $QUIET && [[ $DRIFT_COUNT -eq 0 ]] || true
    echo ""
    echo "${BOLD}[$1]${NC} $2"
    echo "$(printf '%.0s─' {1..64})"
}

# ─── Snapshot functions ─────────────────────────────────────────────────────
# Each function outputs a deterministic, sorted, diffable text representation

snapshot_lockfile_hashes() {
    # SHA-256 of every lockfile — any dependency change shows up
    for root in "${SCAN_ROOTS[@]}"; do
        find "$root" -maxdepth 8 \
            \( -name "package-lock.json" -o -name "yarn.lock" -o -name "pnpm-lock.yaml" \) \
            -not -path "*/.git/*" -type f 2>/dev/null | sort | while read -r f; do
            echo "$(sha256sum "$f" | awk '{print $1}')  $f"
        done
    done
}

snapshot_env_permissions() {
    # .env files and their permissions
    for root in "${SCAN_ROOTS[@]}"; do
        find "$root" -maxdepth 8 -name ".env" \
            -not -path "*/node_modules/*" -not -path "*/.git/*" \
            -type f 2>/dev/null | sort | while read -r f; do
            perms=$(stat -c '%a' "$f" 2>/dev/null || echo "???")
            echo "$perms  $f"
        done
    done
}

snapshot_pth_files() {
    # All .pth files in all Python site-packages directories
    find / -path "*/site-packages/*.pth" -type f 2>/dev/null | sort | while read -r f; do
        # Include hash so we detect modified .pth files too
        echo "$(sha256sum "$f" | awk '{print $1}')  $f"
    done
}

snapshot_authorized_keys() {
    # All authorized_keys files and their contents hash
    find /home -name "authorized_keys" -type f 2>/dev/null | sort | while read -r f; do
        count=$(grep -c "^ssh-\|^ecdsa-\|^sk-" "$f" 2>/dev/null) || count=0
        echo "$(sha256sum "$f" | awk '{print $1}')  keys=$count  $f"
    done
}

snapshot_credential_permissions() {
    # Credential files and their permissions
    cred_files=(
        "$HOME/.ssh/id_rsa" "$HOME/.ssh/id_ed25519" "$HOME/.ssh/id_ecdsa"
        "$HOME/.npmrc" "$HOME/.git-credentials" "$HOME/.netrc" "$HOME/.pgpass"
        "$HOME/.aws/credentials" "$HOME/.kube/config" "$HOME/.docker/config.json"
    )
    for f in "${cred_files[@]}"; do
        if [[ -f "$f" ]]; then
            perms=$(stat -c '%a' "$f" 2>/dev/null || echo "???")
            echo "$perms  $f"
        fi
    done | sort
}

snapshot_npm_globals() {
    # Global npm packages
    if command -v npm &>/dev/null; then
        npm ls -g --depth=0 --parseable 2>/dev/null | sort
    fi
}

snapshot_cron_jobs() {
    # User crontab
    crontab -l 2>/dev/null | grep -v "^#" | sort
    # System cron files that reference home dirs
    for f in /etc/crontab /etc/cron.d/*; do
        [[ -f "$f" ]] && grep -v "^#" "$f" 2>/dev/null
    done | sort
}

snapshot_systemd_user_services() {
    # User systemd services
    if [[ -d "$HOME/.config/systemd/user" ]]; then
        find "$HOME/.config/systemd/user" -type f 2>/dev/null | sort | while read -r f; do
            echo "$(sha256sum "$f" | awk '{print $1}')  $f"
        done
    fi
}

snapshot_postinstall_scripts() {
    # node_modules packages with postinstall hooks
    for root in "${SCAN_ROOTS[@]}"; do
        find "$root" -maxdepth 8 -name "package.json" -path "*/node_modules/*" \
            -type f 2>/dev/null | while read -r f; do
            if grep -q '"postinstall"' "$f" 2>/dev/null; then
                pkg_name=$(python3 -c "import json,sys; print(json.load(open('$f')).get('name','unknown'))" 2>/dev/null || echo "unknown")
                echo "$pkg_name  $f"
            fi
        done
    done | sort
}

snapshot_npm_config() {
    # npm security-relevant config
    if command -v npm &>/dev/null; then
        echo "ignore-scripts=$(npm config get ignore-scripts 2>/dev/null)"
    fi
}

snapshot_ssh_config() {
    # SSH config hash
    if [[ -f "$HOME/.ssh/config" ]]; then
        echo "$(sha256sum "$HOME/.ssh/config" | awk '{print $1}')  $HOME/.ssh/config"
    fi
}

# ─── All snapshot names ─────────────────────────────────────────────────────
SNAPSHOTS=(
    "lockfile_hashes"
    "env_permissions"
    "pth_files"
    "authorized_keys"
    "credential_permissions"
    "npm_globals"
    "cron_jobs"
    "systemd_user_services"
    "postinstall_scripts"
    "npm_config"
    "ssh_config"
)

SNAPSHOT_LABELS=(
    "Lockfile hashes (dependency changes)"
    ".env file permissions"
    "Python .pth files (startup hooks)"
    "SSH authorized_keys"
    "Credential file permissions"
    "npm global packages"
    "Cron jobs"
    "Systemd user services"
    "Postinstall scripts in node_modules"
    "npm security config"
    "SSH config"
)

SNAPSHOT_FIXES=(
    "Review changed lockfiles: git diff package-lock.json. If unexpected, revert and run npm ci."
    "Restore permissions: chmod 600 <file>. Something loosened your .env permissions."
    "Investigate new .pth file — could be malicious startup hook. Check contents with: cat <file>"
    "Review new keys in authorized_keys. Remove any you don't recognise."
    "Restore permissions: chmod 600 <file>. Credential files should never be world-readable."
    "Review new global package. If unexpected: npm uninstall -g <package>"
    "Review new cron entry. If unexpected: crontab -e to remove."
    "Review new systemd service. If unexpected: systemctl --user disable <service>"
    "New postinstall hook in dependency — review the script. Consider: npm config set ignore-scripts true"
    "Re-apply: npm config set ignore-scripts true"
    "Review SSH config changes: diff against baseline."
)

# ═══════════════════════════════════════════════════════════════════════════
# BASELINE MODE
# ═══════════════════════════════════════════════════════════════════════════
do_baseline() {
    mkdir -p "$BASELINE_DIR"

    echo ""
    echo "${CYAN}${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo "${CYAN}${BOLD}  Watchdog — Taking Baseline Snapshot${NC}"
    echo "${CYAN}${BOLD}  $(date '+%Y-%m-%d %H:%M:%S')${NC}"
    echo "${CYAN}${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

    for i in "${!SNAPSHOTS[@]}"; do
        name="${SNAPSHOTS[$i]}"
        label="${SNAPSHOT_LABELS[$i]}"
        outfile="${BASELINE_DIR}/${name}.txt"

        "snapshot_${name}" > "$outfile" 2>/dev/null
        count=$(wc -l < "$outfile")
        log_info "$label: $count item(s) baselined"
    done

    # Record baseline timestamp
    date -Iseconds > "${BASELINE_DIR}/timestamp"

    echo ""
    echo "${GREEN}${BOLD}  ✓ Baseline saved to ${BASELINE_DIR}${NC}"
    echo "${DIM}  Run './watchdog.sh --check' to compare against this baseline.${NC}"
    echo "${DIM}  Add to cron: 0 8 * * * $0 --check --quiet >> ~/.watchdog/alerts.log 2>&1${NC}"
    echo ""
}

# ═══════════════════════════════════════════════════════════════════════════
# CHECK MODE
# ═══════════════════════════════════════════════════════════════════════════
do_check() {
    if [[ ! -d "$BASELINE_DIR" ]]; then
        echo "${RED}No baseline found. Run: $0 --baseline${NC}"
        exit 1
    fi

    baseline_time=$(cat "${BASELINE_DIR}/timestamp" 2>/dev/null || echo "unknown")

    $QUIET || {
        echo ""
        echo "${CYAN}${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
        echo "${CYAN}${BOLD}  Watchdog — Drift Check${NC}"
        echo "${CYAN}${BOLD}  Baseline: ${baseline_time}${NC}"
        echo "${CYAN}${BOLD}  Current:  $(date '+%Y-%m-%d %H:%M:%S')${NC}"
        echo "${CYAN}${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    }

    for i in "${!SNAPSHOTS[@]}"; do
        name="${SNAPSHOTS[$i]}"
        label="${SNAPSHOT_LABELS[$i]}"
        fix="${SNAPSHOT_FIXES[$i]}"
        baseline_file="${BASELINE_DIR}/${name}.txt"
        current_file=$(mktemp)

        "snapshot_${name}" > "$current_file" 2>/dev/null

        section "$((i + 1))/${#SNAPSHOTS[@]}" "$label"

        if [[ ! -f "$baseline_file" ]]; then
            log_info "No baseline for $name — skipping"
            rm -f "$current_file"
            continue
        fi

        # Diff baseline vs current
        diff_output=$(diff --unified=0 "$baseline_file" "$current_file" 2>/dev/null || true)

        if [[ -z "$diff_output" ]]; then
            log_ok "No changes"
        else
            # Parse additions and removals
            added=$(echo "$diff_output" | grep "^+" | grep -v "^+++" | sed 's/^+//')
            removed=$(echo "$diff_output" | grep "^-" | grep -v "^---" | sed 's/^-//')

            if [[ -n "$added" ]]; then
                log_drift "New entries detected in: $label" "$fix"
                echo "$added" | while read -r line; do
                    echo "    ${RED}+ $line${NC}"
                done
                echo ""
            fi

            if [[ -n "$removed" ]]; then
                # Removals are less alarming but still worth noting
                echo "  ${YELLOW}[CHANGE]${NC} Removed entries in: $label"
                echo "$removed" | while read -r line; do
                    echo "    ${DIM}- $line${NC}"
                done
                echo ""
            fi
        fi

        rm -f "$current_file"
    done

    # ─── Summary ────────────────────────────────────────────────────────────
    echo ""
    echo "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    if [[ $DRIFT_COUNT -gt 0 ]]; then
        echo "${RED}${BOLD}  ⚠  $DRIFT_COUNT drift(s) detected — review above${NC}"
        echo ""
        echo "  After reviewing and confirming changes are intentional:"
        echo "  ${CYAN}$0 --baseline${NC}  to accept current state as new baseline"
    else
        if $QUIET; then
            # In quiet mode, output nothing if clean
            exit 0
        fi
        echo "${GREEN}${BOLD}  ✓  No drift — system matches baseline${NC}"
    fi
    echo "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo ""
}

# ═══════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════
if [[ -z "$MODE" ]]; then
    # Auto-detect: baseline if none exists, check if it does
    if [[ -d "$BASELINE_DIR" ]]; then
        MODE="check"
    else
        MODE="baseline"
    fi
fi

case "$MODE" in
    baseline) do_baseline ;;
    check)    do_check ;;
esac
