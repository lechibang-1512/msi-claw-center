#!/usr/bin/env bash
# MSI Claw Center — Installer for Fedora / Linux Wayland (KDE Plasma 6 & GNOME Shell)
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
USER_ONLY=0
if [[ "${1:-}" == "--user-only" ]]; then
    USER_ONLY=1
fi

if [[ "${EUID}" -eq 0 ]]; then
    echo "Please run ./install.sh as your regular desktop user (it will elevate via pkexec/sudo only for system files)." >&2
    exit 1
fi

echo "==> [1/3] Installing user binaries (symlinked to ${REPO_DIR}/bin) & desktop integration..."
install -d "${HOME}/.local/bin" \
           "${HOME}/.config/systemd/user" \
           "${HOME}/.local/share/applications" \
           "${HOME}/.local/share/dbus-1/services"

for b in msi-claw-center msi-claw-controller.py msi-claw-rgb msi-claw-action.sh; do
    chmod 0755 "${REPO_DIR}/bin/${b}"
    ln -sfn "${REPO_DIR}/bin/${b}" "${HOME}/.local/bin/${b}"
done

install -m 0644 "${REPO_DIR}/systemd/user/msi-claw-center.service" "${HOME}/.config/systemd/user/msi-claw-center.service"
install -m 0644 "${REPO_DIR}/systemd/user/msi-claw-controller.service" "${HOME}/.config/systemd/user/msi-claw-controller.service"

sed "s|@HOME@|${HOME}|g" "${REPO_DIR}/desktop/msi-claw-center.desktop.in" > "${HOME}/.local/share/applications/msi-claw-center.desktop"
install -m 0644 "${REPO_DIR}/desktop/msi-claw-power-setup.desktop" "${HOME}/.local/share/applications/msi-claw-power-setup.desktop"
sed "s|@HOME@|${HOME}|g" "${REPO_DIR}/desktop/io.msiclaw.Center.service.in" > "${HOME}/.local/share/dbus-1/services/io.msiclaw.Center.service"

if [[ -d "${REPO_DIR}/gnome-extension/claw-controls@msi-claw" ]]; then
    EXT_DST="${HOME}/.local/share/gnome-shell/extensions/claw-controls@msi-claw"
    install -d "${EXT_DST}"
    install -m 0644 "${REPO_DIR}/gnome-extension/claw-controls@msi-claw/"* "${EXT_DST}/"
fi

if [[ "${USER_ONLY}" -eq 0 ]]; then
    echo "==> [2/3] Installing system EC battery-limit, USB keyboard wakeup & power helpers..."
    ELEVATE=(sudo)
    if command -v pkexec >/dev/null 2>&1 && [[ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]]; then
        ELEVATE=(pkexec)
    fi
    "${ELEVATE[@]}" sh -c '
        set -eu
        REPO="$1"
        install -d /usr/local/sbin /etc/polkit-1/rules.d /usr/share/polkit-1/actions \
                   /etc/udev/rules.d /etc/modules-load.d /etc/systemd/system /usr/lib/systemd/system-sleep
        for s in msi-claw-battery-limit msi-claw-usb-wakeup-sync msi-claw-system-power-setup.sh msi-claw-shell-backup-sync; do
            install -m 0755 "${REPO}/sbin/${s}" "/usr/local/sbin/${s}"
        done
        install -m 0644 "${REPO}/system/polkit-actions/io.msiclaw.battery-limit.policy" /usr/share/polkit-1/actions/
        install -m 0644 "${REPO}/system/polkit-rules/51-msi-claw-battery-limit.rules" /etc/polkit-1/rules.d/
        install -m 0644 "${REPO}/system/udev/85-msi-claw-usb-wakeup.rules" /etc/udev/rules.d/
        install -m 0644 "${REPO}/system/modules-load/msi-wmi-platform.conf" /etc/modules-load.d/
        install -m 0644 "${REPO}/systemd/system/msi-claw-battery-limit.service" /etc/systemd/system/
        install -m 0755 "${REPO}/systemd/system-sleep/msi-claw-battery-limit.sh" /usr/lib/systemd/system-sleep/
        udevadm control --reload-rules
        /usr/local/sbin/msi-claw-usb-wakeup-sync || true
        systemctl daemon-reload
        systemctl enable --now msi-claw-battery-limit.service || true
    ' _ "${REPO_DIR}"
else
    echo "==> [2/3] Skipping privileged system files (--user-only)."
fi

echo "==> [3/3] Reloading and starting user services..."
systemctl --user daemon-reload
systemctl --user enable --now msi-claw-controller.service msi-claw-center.service
systemctl --user restart msi-claw-controller.service msi-claw-center.service

echo "==> MSI Claw Center installed successfully!"
"${HOME}/.local/bin/msi-claw-center" --status || true
