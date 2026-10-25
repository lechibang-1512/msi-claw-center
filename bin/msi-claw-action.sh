#!/usr/bin/env bash
# Helper script for MSI Claw A1M Face Buttons (F16 = MSI Center M, F15 = Quick Settings)
CMD="${1:-toggle-center}"
RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
FIFO_PATH="${RUNTIME_DIR}/msi-claw-cmd"
TMP="${FIFO_PATH}.tmp.$$"

printf '%s\n' "${CMD}" > "${TMP}" && mv -f "${TMP}" "${FIFO_PATH}"
