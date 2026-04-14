#!/usr/bin/env bash
# lint_check.sh — Verilator lint pass for OpenTitan RTL modules
#
# Runs verilator --lint-only on each target SystemVerilog file.
# Exits non-zero if any file produces warnings at or above the threshold.
#
# Usage:
#   ./lint_check.sh [--werror]
#
# Options:
#   --werror   Treat all Verilator warnings as errors (CI mode)

set -euo pipefail

VERILATOR=${VERILATOR:-verilator}
RTL_DIR="${REPO_ROOT:-../..}/hw/ip"
WARNINGS_LOG="lint_warnings.log"
WERROR=0

for arg in "$@"; do
  case "$arg" in
    --werror) WERROR=1 ;;
    *) echo "Unknown argument: $arg"; exit 1 ;;
  esac
done

# Files to lint
SV_TARGETS=(
    "${RTL_DIR}/uart/rtl/uart_tx.sv"
    "${RTL_DIR}/uart/rtl/uart_rx.sv"
    "${RTL_DIR}/gpio/rtl/gpio.sv"
    "${RTL_DIR}/gpio/rtl/gpio_reg_top.sv"
    "${RTL_DIR}/spi_device/rtl/spi_fwmode.sv"
    "${RTL_DIR}/prim/rtl/prim_fifo_sync.sv"
    "${RTL_DIR}/prim/rtl/prim_arbiter_fixed.sv"
    "${RTL_DIR}/prim/rtl/prim_pulse_sync.sv"
    "${RTL_DIR}/prim/rtl/prim_flop_2sync.sv"
)

# Common Verilator flags
VLINT_FLAGS=(
    "--lint-only"
    "--sv"
    "--timing"
    "+incdir+${RTL_DIR}/prim/rtl"
    "-Wall"
    "-Wno-DECLFILENAME"   # allow multi-module files in prim
    "-Wno-UNUSED"         # tolerate unused ports in partial lint
)

if [[ ${WERROR} -eq 1 ]]; then
    VLINT_FLAGS+=("--error-limit" "1")
fi

echo "Running Verilator lint (werror=${WERROR})..."
echo "" > "${WARNINGS_LOG}"

FAIL=0
for sv_file in "${SV_TARGETS[@]}"; do
    if [[ ! -f "${sv_file}" ]]; then
        echo "SKIP (not found): ${sv_file}"
        continue
    fi

    echo -n "  lint: ${sv_file} ... "
    if ${VERILATOR} "${VLINT_FLAGS[@]}" "${sv_file}" 2>>"${WARNINGS_LOG}"; then
        echo "OK"
    else
        echo "FAIL"
        FAIL=1
    fi
done

WARNING_COUNT=$(grep -c "%Warning" "${WARNINGS_LOG}" 2>/dev/null || true)
ERROR_COUNT=$(grep -c "%Error"   "${WARNINGS_LOG}" 2>/dev/null || true)

echo ""
echo "Lint summary: ${WARNING_COUNT} warning(s), ${ERROR_COUNT} error(s)"
echo "Full log: ${WARNINGS_LOG}"

if [[ ${ERROR_COUNT} -gt 0 ]] || [[ ${FAIL} -eq 1 ]]; then
    echo "LINT FAILED"
    exit 1
fi

echo "LINT PASSED"
exit 0
