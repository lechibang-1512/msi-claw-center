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

echo "==> [1/3] Installing user binaries (symlinked to ${REPO_DIR}/bin), Python package & desktop integration..."
USER_SITE="$(python3 -c 'import site; print(site.getusersitepackages())' 2>/dev/null || echo "${HOME}/.local/lib/python3.14/site-packages")"
install -d "${HOME}/.local/bin" \
           "${USER_SITE}" \
           "${HOME}/.config/systemd/user" \
           "${HOME}/.config/systemd/user/mako.service.d" \
           "${HOME}/.local/share/applications" \
           "${HOME}/.local/share/dbus-1/services"

# Link Python package into user site-packages for direct module imports
printf '%s\n' "${REPO_DIR}" > "${USER_SITE}/msi_claw_center.pth"

for b in msi-claw-center msi-claw-controller.py msi-claw-rgb msi-claw-action.sh msi-claw-notify-daemon.sh msi-claw-osd.sh msi-claw-osk-toggle.sh msi-claw-quick-menu.sh; do
    chmod 0755 "${REPO_DIR}/bin/${b}"
    ln -sfn "${REPO_DIR}/bin/${b}" "${HOME}/.local/bin/${b}"
done

rm -f "${HOME}/.config/systemd/user/default.target.wants/msi-claw-controller.service"
install -m 0644 "${REPO_DIR}/systemd/user/msi-claw-center.service" "${HOME}/.config/systemd/user/msi-claw-center.service"
install -m 0644 "${REPO_DIR}/systemd/user/msi-claw-controller.service" "${HOME}/.config/systemd/user/msi-claw-controller.service"
printf '[Unit]\nConditionEnvironment=!KDE_FULL_SESSION\n' > "${HOME}/.config/systemd/user/mako.service.d/not-kde.conf"

sed "s|@HOME@|${HOME}|g" "${REPO_DIR}/desktop/msi-claw-center.desktop.in" > "${HOME}/.local/share/applications/msi-claw-center.desktop"
install -m 0644 "${REPO_DIR}/desktop/msi-claw-power-setup.desktop" "${HOME}/.local/share/applications/msi-claw-power-setup.desktop"
sed "s|@HOME@|${HOME}|g" "${REPO_DIR}/desktop/io.msiclaw.Center.service.in" > "${HOME}/.local/share/dbus-1/services/io.msiclaw.Center.service"
sed "s|@HOME@|${HOME}|g" "${REPO_DIR}/desktop/org.freedesktop.Notifications.service.in" > "${HOME}/.local/share/dbus-1/services/org.freedesktop.Notifications.service"

# Clean up any KWin shortcut conflict on KDE Plasma (Launch (C) = F16 stealing Center M)
# and ensure Polkit password dialogs always float above MSI Claw Center's Keep-Above layer
if command -v kwriteconfig6 >/dev/null 2>&1 && command -v kreadconfig6 >/dev/null 2>&1; then
    EXPOSE_VAL="$(kreadconfig6 --file kglobalshortcutsrc --group kwin --key ExposeAll 2>/dev/null || true)"
    if [[ "${EXPOSE_VAL}" == *"Launch (C)"* ]]; then
        CLEANED_EXPOSE="$(echo "${EXPOSE_VAL}" | sed 's/Launch (C)[[:space:]]*//g')"
        kwriteconfig6 --file kglobalshortcutsrc --group kwin --key ExposeAll "${CLEANED_EXPOSE}"
    fi
    kwriteconfig6 --file kwinrulesrc --group "Polkit Authentication Dialog" --key Description "Keep Polkit Sudo Dialog Always On Top and Focused"
    kwriteconfig6 --file kwinrulesrc --group "Polkit Authentication Dialog" --key above true
    kwriteconfig6 --file kwinrulesrc --group "Polkit Authentication Dialog" --key aboverule 3
    kwriteconfig6 --file kwinrulesrc --group "Polkit Authentication Dialog" --key fpplevel 0
    kwriteconfig6 --file kwinrulesrc --group "Polkit Authentication Dialog" --key fpplevelrule 2
    kwriteconfig6 --file kwinrulesrc --group "Polkit Authentication Dialog" --key wmclass "org.kde.polkit-kde-authentication-agent-1"
    kwriteconfig6 --file kwinrulesrc --group "Polkit Authentication Dialog" --key wmclassmatch 1
    CUR_ORDER="$(kreadconfig6 --file kwinrulesrc --group General --key Order 2>/dev/null || true)"
    if [[ "${CUR_ORDER}" != *"Polkit Authentication Dialog"* ]]; then
        NEW_ORDER="${CUR_ORDER:+${CUR_ORDER},}Polkit Authentication Dialog"
        kwriteconfig6 --file kwinrulesrc --group General --key Order "${NEW_ORDER}"
    fi
    CUR_RULES="$(kreadconfig6 --file kwinrulesrc --group General --key rules 2>/dev/null || true)"
    if [[ "${CUR_RULES}" != *"Polkit Authentication Dialog"* ]]; then
        BASE_RULES="${CUR_RULES:-${CUR_ORDER}}"
        NEW_RULES="${BASE_RULES:+${BASE_RULES},}Polkit Authentication Dialog"
        kwriteconfig6 --file kwinrulesrc --group General --key rules "${NEW_RULES}"
    fi
    if command -v qdbus-qt6 >/dev/null 2>&1; then
        DBUS_SESSION_BUS_ADDRESS="${DBUS_SESSION_BUS_ADDRESS:-unix:path=/run/user/$(id -u)/bus}" \
            qdbus-qt6 org.kde.KWin /KWin reconfigure >/dev/null 2>&1 || true
    fi
fi

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
        for s in msi-claw-battery-limit msi-claw-cooler-boost msi-claw-dnf5-snapper msi-claw-usb-wakeup-sync msi-claw-system-power-setup.sh msi-claw-shell-backup-sync; do
            install -m 0755 "${REPO}/sbin/${s}" "/usr/local/sbin/${s}"
        done
        install -m 0644 "${REPO}/system/polkit-actions/io.msiclaw.battery-limit.policy" /usr/share/polkit-1/actions/
        install -m 0644 "${REPO}/system/polkit-actions/io.msiclaw.cooler-boost.policy" /usr/share/polkit-1/actions/
        install -m 0644 "${REPO}/system/polkit-rules/51-msi-claw-battery-limit.rules" /etc/polkit-1/rules.d/
        install -m 0644 "${REPO}/system/polkit-rules/52-msi-claw-cooler-boost.rules" /etc/polkit-1/rules.d/
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
