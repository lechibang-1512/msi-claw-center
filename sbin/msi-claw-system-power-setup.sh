#!/usr/bin/env bash
# MSI Claw A1M (Meteor Lake 155H / Fedora 44) System-Level Battery & Tighter GDM OSK Optimizer
# Safely preserves Intel BE200 Wi-Fi s2idle fix (00:1c.0 / 2b:00.0), MAP1602 NVMe, and 0db0:1901 Controller.
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
    echo "Elevating via pkexec/sudo..."
    if command -v pkexec >/dev/null 2>&1 && [[ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]]; then
        exec pkexec "$0" "$@"
    else
        exec sudo "$0" "$@"
    fi
fi

SELF_REAL="$(readlink -f "$0" 2>/dev/null || echo "$0")"
DEST_REAL="$(readlink -f /usr/local/sbin/msi-claw-system-power-setup.sh 2>/dev/null || echo /usr/local/sbin/msi-claw-system-power-setup.sh)"
if [[ -f "${SELF_REAL}" && "${SELF_REAL}" != "${DEST_REAL}" ]]; then
    install -d /usr/local/sbin
    install -m 0755 "${SELF_REAL}" /usr/local/sbin/msi-claw-system-power-setup.sh
fi

TARGET_USER="${SUDO_USER:-$(logname 2>/dev/null || id -nu 1000 2>/dev/null || echo root)}"
if [[ -n "${PKEXEC_UID:-}" ]] && id -nu "${PKEXEC_UID}" >/dev/null 2>&1; then
    TARGET_USER="$(id -nu "${PKEXEC_UID}")"
elif [[ -n "${SUDO_USER:-}" && "${SUDO_USER}" != "root" ]]; then
    TARGET_USER="${SUDO_USER}"
fi
TARGET_UID="$(id -u "${TARGET_USER}" 2>/dev/null || echo 1000)"
USER_HOME="$(getent passwd "${TARGET_USER}" | cut -d: -f6)"
[[ -n "${USER_HOME}" ]] || USER_HOME="/home/${TARGET_USER}"
EXT_DIR="${USER_HOME}/.local/share/gnome-shell/extensions/claw-controls@msi-claw"

apply_fast_resume_fixes() {
    echo "[Fast-Resume] Optimizing s2idle wake latency, async Wi-Fi reload, udev PM & lockscreen auth..."
    cat > /etc/udev/rules.d/70-msi-claw-uaccess.rules << 'EOF'
# Evaluated before 73-seat-late.rules so the uaccess tag gets the active-seat ACL applied
# (no MODE=0666: world-readable keyboard evdev nodes would let any process keylog)
KERNEL=="hidraw*", SUBSYSTEM=="hidraw", ATTRS{idVendor}=="0db0", ATTRS{idProduct}=="190[1-4]", TAG+="uaccess"
KERNEL=="event*", SUBSYSTEM=="input", ATTRS{idVendor}=="0db0", ATTRS{idProduct}=="190[1-4]", TAG+="uaccess"
KERNEL=="event*", SUBSYSTEM=="input", ATTRS{name}=="AT Translated Set 2 keyboard", TAG+="uaccess"
KERNEL=="event*", SUBSYSTEM=="input", ATTRS{name}=="MSI WMI hotkeys", TAG+="uaccess"
DEVPATH=="/devices/virtual/misc/cpu_dma_latency", MODE="0660", TAG+="uaccess"
ACTION=="add|change", SUBSYSTEM=="iio", ATTR{name}=="gyro_3d", RUN+="/usr/bin/chgrp wheel /sys%p/in_anglvel_sampling_frequency /sys%p/in_anglvel_hysteresis", RUN+="/usr/bin/chmod 0664 /sys%p/in_anglvel_sampling_frequency /sys%p/in_anglvel_hysteresis"
EOF

    cat > /etc/udev/rules.d/99-iwlwifi-pci-pm.rules << 'EOF'
ACTION=="add|change", SUBSYSTEM=="pci", KERNEL=="0000:2b:00.0", ATTR{d3cold_allowed}="0", ATTR{power/control}="on"
ACTION=="add|change", SUBSYSTEM=="pci", KERNEL=="0000:00:1c.0", ATTR{d3cold_allowed}="0", ATTR{power/control}="on"
EOF

    cat > /etc/udev/rules.d/80-msi-claw-pm.rules << 'EOF'
# 1. Strictly forbid PCIe D3cold on Intel BE200 Wi-Fi & Root Port (prevents s2idle link crash)
ACTION=="add|change", SUBSYSTEM=="pci", KERNEL=="0000:00:1c.0|0000:2b:00.0", ATTR{d3cold_allowed}="0", ATTR{power/control}="on", GOTO="claw_pm_end"

# 2. Keep Touchscreen I2C0 on 'on' for instant touch response; forbid D3cold on VMD/NVMe while allowing link ASPM/APST
ACTION=="add|change", SUBSYSTEM=="pci", KERNEL=="0000:00:15.0", ATTR{power/control}="on", GOTO="claw_pm_end"
ACTION=="add|change", SUBSYSTEM=="pci", KERNEL=="0000:00:0e.0|10000:e0:06.0|10000:e0:06.1", ATTR{d3cold_allowed}="0", ATTR{power/control}="auto", GOTO="claw_pm_end"
ACTION=="add|change", SUBSYSTEM=="pci", ATTR{vendor}=="0x1d97", ATTR{device}=="0x1602", ATTR{d3cold_allowed}="0", ATTR{power/control}="on", GOTO="claw_pm_end"

# 3. Enable Runtime PM for all other eligible PCI devices (CSME 00:16.0, DTT, PMT, ISH, SRAM, GNA, NPU, Card Reader 00:1c.7/2c:00.0)
ACTION=="add|change", SUBSYSTEM=="pci", TEST=="power/control", ATTR{power/control}="auto"

# 4. Protect MSI Claw built-in Xbox360 controller (0db0:1901) & Goodix Fingerprint Reader (27c6:6092) from USB autosuspend
ACTION=="add|change", SUBSYSTEM=="usb", ATTR{idVendor}=="0db0", ATTR{idProduct}=="1901", ATTR{power/control}="on"
ACTION=="add|change", SUBSYSTEM=="usb", ATTR{idVendor}=="27c6", ATTR{idProduct}=="6092", ATTR{power/control}="on"

# 5. Eliminate per-I/O NVMe whole-disk queue stats overhead & set low-latency kyber scheduler
ACTION=="add|change", SUBSYSTEM=="block", ENV{DEVTYPE}=="disk", KERNEL=="nvme[0-9]*n[0-9]*", ATTR{queue/iostats}="0", ATTR{queue/scheduler}="kyber"

LABEL="claw_pm_end"
EOF

    udevadm control --reload-rules
    udevadm trigger --subsystem-match=pci --subsystem-match=usb --subsystem-match=hidraw --subsystem-match=input --subsystem-match=block --subsystem-match=misc --subsystem-match=iio || true
    if [[ -e /dev/cpu_dma_latency ]]; then
        chmod 0660 /dev/cpu_dma_latency 2>/dev/null || true
        setfacl -m "u:${TARGET_USER}:rw" /dev/cpu_dma_latency 2>/dev/null || true
    fi
    for iio_d in /sys/bus/iio/devices/iio:device*; do
        if [[ "$(cat "$iio_d/name" 2>/dev/null || true)" == "gyro_3d" ]]; then
            chgrp wheel "$iio_d/in_anglvel_sampling_frequency" "$iio_d/in_anglvel_hysteresis" 2>/dev/null || true
            chmod 0664 "$iio_d/in_anglvel_sampling_frequency" "$iio_d/in_anglvel_hysteresis" 2>/dev/null || true
            setfacl -m "u:${TARGET_USER}:rw" "$iio_d/in_anglvel_sampling_frequency" "$iio_d/in_anglvel_hysteresis" 2>/dev/null || true
        fi
    done
    for nv in /sys/block/nvme*n*/queue/scheduler; do
        [[ -w "$nv" ]] && echo kyber > "$nv" 2>/dev/null || true
    done
    for hd in /sys/class/hidraw/hidraw*; do
        if grep -qi "0DB0:0000190" "$hd/device/uevent" 2>/dev/null; then
            setfacl -m "u:${TARGET_USER}:rw" "/dev/$(basename "$hd")" 2>/dev/null || true
        fi
    done
    for ev in /sys/class/input/event*; do
        [[ -e "$ev/device/name" ]] || continue
        ev_name="$(cat "$ev/device/name" 2>/dev/null || true)"
        ev_uevent="$(cat "$ev/device/uevent" 2>/dev/null || true)"
        if [[ "$ev_name" == "AT Translated Set 2 keyboard" || "$ev_name" == "MSI WMI hotkeys" ]] || \
           grep -qi "0DB0/.*190" <<< "$ev_uevent"; then
            setfacl -m "u:${TARGET_USER}:rw" "/dev/input/$(basename "$ev")" 2>/dev/null || true
        fi
    done
    if [[ -d "/run/user/${TARGET_UID}" ]]; then
        # Write as the user: root must never follow symlinks planted in the user-owned runtime dir
        runuser -u "${TARGET_USER}" -- sh -c 'umask 077; printf "recheck-devices\n" > "$1.tmp.$$" && mv -f "$1.tmp.$$" "$1"' _ \
            "/run/user/${TARGET_UID}/msi-claw-cmd" 2>/dev/null || true
    fi

    # Pin s2idle (Modern Standby)
    install -d /etc/systemd/sleep.conf.d
    cat > /etc/systemd/sleep.conf.d/10-msi-claw-s2idle.conf << 'EOF'
[Sleep]
MemorySleepMode=s2idle
EOF

    # Async post-resume reload in /usr/lib/systemd/system-sleep/iwlwifi-suspend.sh:
    # - Keeps pre-suspend unload 100% synchronous so BE200 never enters s2idle bound
    # - Spawns post-resume reload in independent system.slice unit via systemd-run --no-block
    #   so user.slice (gnome-shell + eDP display) thaws ~1.05s faster instead of waiting on RF init!
    # Keep the backup OUT of system-sleep/: systemd-sleep runs every executable in that directory
    install -d -m 0755 /var/lib/msi-claw
    if [[ -f /usr/lib/systemd/system-sleep/iwlwifi-suspend.sh.orig.bak ]]; then
        mv -f /usr/lib/systemd/system-sleep/iwlwifi-suspend.sh.orig.bak /var/lib/msi-claw/iwlwifi-suspend.sh.orig
        chmod 0644 /var/lib/msi-claw/iwlwifi-suspend.sh.orig
    elif [[ -f /usr/lib/systemd/system-sleep/iwlwifi-suspend.sh && ! -f /var/lib/msi-claw/iwlwifi-suspend.sh.orig ]]; then
        install -m 0644 /usr/lib/systemd/system-sleep/iwlwifi-suspend.sh /var/lib/msi-claw/iwlwifi-suspend.sh.orig
    fi
    cat > /usr/lib/systemd/system-sleep/iwlwifi-suspend.sh << 'EOF'
#!/bin/sh
case "$1" in
  pre)
    /usr/sbin/modprobe -r iwlmld iwlwifi
    ;;
  post)
    /usr/bin/systemctl reset-failed iwlwifi-resume-reload.service >/dev/null 2>&1 || true
    /usr/bin/systemd-run --no-block --unit=iwlwifi-resume-reload \
      /bin/sh -c '/usr/sbin/modprobe iwlwifi && /usr/sbin/modprobe iwlmld' >/dev/null 2>&1 || {
      /usr/sbin/modprobe iwlwifi
      /usr/sbin/modprobe iwlmld
    }
    ;;
esac
EOF
    chmod 0755 /usr/lib/systemd/system-sleep/iwlwifi-suspend.sh

    # Keep OSK enabled & ensure Goodix MOC Fingerprint Reader (27c6:6092) stays enabled in GNOME Settings, GDM & PAM
    install -d /etc/dconf/db/local.d /etc/dconf/db/gdm.d
    cat > /etc/dconf/db/local.d/00-osk-settings << 'EOF'
[org/gnome/desktop/a11y/applications]
screen-keyboard-enabled=true

[org/gnome/login-screen]
enable-fingerprint-authentication=true
EOF
    cat > /etc/dconf/db/gdm.d/00-osk-settings << 'EOF'
[org/gnome/desktop/a11y/applications]
screen-keyboard-enabled=true

[org/gnome/login-screen]
enable-fingerprint-authentication=true
EOF
    dconf update || true

    # Ensure KDE Plasma & plasmalogin greeter use 100% full-width plasma-keyboard
    install -d /etc/xdg
    cat > /etc/xdg/plasmakeyboardrc << 'EOF'
[General]
diacriticsPopupEnabled=true
enabledLocales=en_US
keyboardNavigationEnabled=true
panelFillScreenWidth=true
EOF

    # Silence irqbalance Permission denied spam on kernel-managed VMD NVMe MSI-X & GPIO IRQs
    if [[ -f /etc/sysconfig/irqbalance ]]; then
        if ! grep -q '^IRQBALANCE_ARGS=.*--banmod=nvme' /etc/sysconfig/irqbalance 2>/dev/null; then
            sed -i '/^IRQBALANCE_ARGS=/d' /etc/sysconfig/irqbalance
            echo 'IRQBALANCE_ARGS="--banmod=nvme --banmod=vmd --banirq=138 --banirq=175"' >> /etc/sysconfig/irqbalance
            systemctl try-restart irqbalance.service 2>/dev/null || true
        fi
    fi

    if command -v authselect >/dev/null 2>&1 && ! authselect current 2>/dev/null | grep -q "with-fingerprint"; then
        authselect enable-feature with-fingerprint >/dev/null 2>&1 || true
    fi
}

apply_tuned_and_lpmd_fixes() {
    echo "[2/8] Installing MSI Claw A1M Meteor Lake TuneD Profiles (RAPL TDP + Uncore + EPP + Arc GPU SLPC)..."
    install -d /etc/tuned/profiles/powersave \
               /etc/tuned/profiles/balanced-battery \
               /etc/tuned/profiles/balanced \
               /etc/tuned/profiles/performance-battery \
               /etc/tuned/profiles/msi-claw-performance-ac

    cat > /etc/tuned/profiles/powersave/tuned.conf << 'EOF'
[main]
summary=MSI Claw A1M Cool Power Saver (11W PL1 / 14W PL2, 2.4GHz P-Core Cap)

[cpu]
governor=powersave
energy_performance_preference=power
min_perf_pct=8
max_perf_pct=50
boost=1

[uncore]
type=uncore
max_freq_khz=1400000

[sysfs]
/sys/devices/system/cpu/cpu[0-9]/cpufreq/scaling_max_freq=2400000
/sys/devices/system/cpu/cpu1[01]/cpufreq/scaling_max_freq=2400000
/sys/devices/system/cpu/cpu1[2-9]/cpufreq/scaling_max_freq=1800000
/sys/devices/system/cpu/cpu2[01]/cpufreq/scaling_max_freq=1600000
/sys/class/powercap/intel-rapl:0/constraint_0_power_limit_uw=11000000
/sys/class/powercap/intel-rapl:0/constraint_1_power_limit_uw=14000000
/sys/class/powercap/intel-rapl:0/constraint_2_power_limit_uw=35000000
/sys/class/powercap/intel-rapl-mmio:0/constraint_0_power_limit_uw=11000000
/sys/class/powercap/intel-rapl-mmio:0/constraint_1_power_limit_uw=14000000
/sys/class/powercap/intel-rapl-mmio:0/constraint_2_power_limit_uw=35000000
/sys/class/drm/card*/gt/gt0/slpc_power_profile=power_saving
/sys/class/drm/card*/gt/gt1/slpc_power_profile=power_saving
/sys/class/drm/card*/gt/gt0/rps_boost_freq_mhz=1200
/sys/class/drm/card*/gt/gt0/rps_max_freq_mhz=1400
/sys/class/drm/card*/gt/gt1/rps_boost_freq_mhz=700
/sys/class/drm/card*/device/tile0/gt0/freq0/max_freq=1400
/sys/class/drm/card*/device/tile0/gt0/freq0/power_profile=power_saving
/sys/class/drm/card*/device/tile0/gt1/freq0/max_freq=700

[sysctl]
vm.dirty_writeback_centisecs=1500
kernel.nmi_watchdog=0
EOF

    cat > /etc/tuned/profiles/balanced/tuned.conf << 'EOF'
[main]
summary=MSI Claw A1M Cool 720p AC Gaming (20W PL1 / 24W PL2, 3.1GHz P-Core Cap)

[cpu]
priority=10
governor=powersave
energy_performance_preference=balance_power
min_perf_pct=8
max_perf_pct=60
boost=1

[uncore]
type=uncore
max_freq_khz=1800000

[sysfs]
/sys/devices/system/cpu/cpu[0-9]/cpufreq/scaling_max_freq=3100000
/sys/devices/system/cpu/cpu1[01]/cpufreq/scaling_max_freq=3100000
/sys/devices/system/cpu/cpu1[2-9]/cpufreq/scaling_max_freq=2500000
/sys/devices/system/cpu/cpu2[01]/cpufreq/scaling_max_freq=2200000
/sys/class/powercap/intel-rapl:0/constraint_0_power_limit_uw=20000000
/sys/class/powercap/intel-rapl:0/constraint_1_power_limit_uw=24000000
/sys/class/powercap/intel-rapl:0/constraint_2_power_limit_uw=50000000
/sys/class/powercap/intel-rapl-mmio:0/constraint_0_power_limit_uw=20000000
/sys/class/powercap/intel-rapl-mmio:0/constraint_1_power_limit_uw=24000000
/sys/class/powercap/intel-rapl-mmio:0/constraint_2_power_limit_uw=50000000
/sys/class/drm/card*/gt/gt0/slpc_power_profile=base
/sys/class/drm/card*/gt/gt1/slpc_power_profile=power_saving
/sys/class/drm/card*/gt/gt0/rps_boost_freq_mhz=2000
/sys/class/drm/card*/gt/gt0/rps_max_freq_mhz=2150
/sys/class/drm/card*/gt/gt1/rps_boost_freq_mhz=1100
/sys/class/drm/card*/device/tile0/gt0/freq0/max_freq=2150
/sys/class/drm/card*/device/tile0/gt0/freq0/power_profile=base
/sys/class/drm/card*/device/tile0/gt1/freq0/max_freq=1100

[sysctl]
kernel.nmi_watchdog=0
EOF

    cat > /etc/tuned/profiles/balanced-battery/tuned.conf << 'EOF'
[main]
summary=MSI Claw A1M Cool 720p Battery Gaming (15W PL1 / 18W PL2, 2.9GHz P-Core Cap)

[cpu]
governor=powersave
energy_performance_preference=balance_power
min_perf_pct=8
max_perf_pct=56
boost=1

[uncore]
type=uncore
max_freq_khz=1600000

[sysfs]
/sys/devices/system/cpu/cpu[0-9]/cpufreq/scaling_max_freq=2900000
/sys/devices/system/cpu/cpu1[01]/cpufreq/scaling_max_freq=2900000
/sys/devices/system/cpu/cpu1[2-9]/cpufreq/scaling_max_freq=2400000
/sys/devices/system/cpu/cpu2[01]/cpufreq/scaling_max_freq=2000000
/sys/class/powercap/intel-rapl:0/constraint_0_power_limit_uw=15000000
/sys/class/powercap/intel-rapl:0/constraint_1_power_limit_uw=18000000
/sys/class/powercap/intel-rapl:0/constraint_2_power_limit_uw=42000000
/sys/class/powercap/intel-rapl-mmio:0/constraint_0_power_limit_uw=15000000
/sys/class/powercap/intel-rapl-mmio:0/constraint_1_power_limit_uw=18000000
/sys/class/powercap/intel-rapl-mmio:0/constraint_2_power_limit_uw=42000000
/sys/class/drm/card*/gt/gt0/slpc_power_profile=power_saving
/sys/class/drm/card*/gt/gt1/slpc_power_profile=power_saving
/sys/class/drm/card*/gt/gt0/rps_boost_freq_mhz=1850
/sys/class/drm/card*/gt/gt0/rps_max_freq_mhz=2000
/sys/class/drm/card*/gt/gt1/rps_boost_freq_mhz=1000
/sys/class/drm/card*/device/tile0/gt0/freq0/max_freq=2000
/sys/class/drm/card*/device/tile0/gt0/freq0/power_profile=power_saving
/sys/class/drm/card*/device/tile0/gt1/freq0/max_freq=1000

[sysctl]
vm.dirty_writeback_centisecs=1500
kernel.nmi_watchdog=0
EOF

    cat > /etc/tuned/profiles/performance-battery/tuned.conf << 'EOF'
[main]
summary=MSI Claw A1M Performance on Battery (20W PL1 / 24W PL2, 3.2GHz P-Core Cap)

[cpu]
governor=powersave
energy_performance_preference=balance_performance
min_perf_pct=8
max_perf_pct=62
boost=1

[uncore]
type=uncore
max_freq_khz=2400000

[sysfs]
/sys/devices/system/cpu/cpu[0-9]/cpufreq/scaling_max_freq=3200000
/sys/devices/system/cpu/cpu1[01]/cpufreq/scaling_max_freq=3200000
/sys/devices/system/cpu/cpu1[2-9]/cpufreq/scaling_max_freq=2600000
/sys/devices/system/cpu/cpu2[01]/cpufreq/scaling_max_freq=2200000
/sys/class/powercap/intel-rapl:0/constraint_0_power_limit_uw=20000000
/sys/class/powercap/intel-rapl:0/constraint_1_power_limit_uw=24000000
/sys/class/powercap/intel-rapl:0/constraint_2_power_limit_uw=50000000
/sys/class/powercap/intel-rapl-mmio:0/constraint_0_power_limit_uw=20000000
/sys/class/powercap/intel-rapl-mmio:0/constraint_1_power_limit_uw=24000000
/sys/class/powercap/intel-rapl-mmio:0/constraint_2_power_limit_uw=50000000
/sys/class/drm/card*/gt/gt0/slpc_power_profile=base
/sys/class/drm/card*/gt/gt1/slpc_power_profile=base
/sys/class/drm/card*/gt/gt0/rps_boost_freq_mhz=2150
/sys/class/drm/card*/gt/gt0/rps_max_freq_mhz=2250
/sys/class/drm/card*/gt/gt1/rps_boost_freq_mhz=1200
/sys/class/drm/card*/device/tile0/gt0/freq0/max_freq=2250
/sys/class/drm/card*/device/tile0/gt0/freq0/power_profile=base
/sys/class/drm/card*/device/tile0/gt1/freq0/max_freq=1200

[sysctl]
vm.swappiness=150
kernel.nmi_watchdog=0
EOF

    cat > /etc/tuned/profiles/msi-claw-performance-ac/tuned.conf << 'EOF'
[main]
summary=MSI Claw A1M Controlled Turbo on AC (25W PL1 / 30W PL2, 3.4GHz P-Core Cap)

[cpu]
governor=powersave
energy_performance_preference=balance_performance
min_perf_pct=10
max_perf_pct=66
boost=1

[uncore]
type=uncore
max_freq_khz=2600000

[sysfs]
/sys/devices/system/cpu/cpu[0-9]/cpufreq/scaling_max_freq=3400000
/sys/devices/system/cpu/cpu1[01]/cpufreq/scaling_max_freq=3400000
/sys/devices/system/cpu/cpu1[2-9]/cpufreq/scaling_max_freq=2800000
/sys/devices/system/cpu/cpu2[01]/cpufreq/scaling_max_freq=2400000
/sys/class/powercap/intel-rapl:0/constraint_0_power_limit_uw=25000000
/sys/class/powercap/intel-rapl:0/constraint_1_power_limit_uw=30000000
/sys/class/powercap/intel-rapl:0/constraint_2_power_limit_uw=60000000
/sys/class/powercap/intel-rapl-mmio:0/constraint_0_power_limit_uw=25000000
/sys/class/powercap/intel-rapl-mmio:0/constraint_1_power_limit_uw=30000000
/sys/class/powercap/intel-rapl-mmio:0/constraint_2_power_limit_uw=60000000
/sys/class/drm/card*/gt/gt0/slpc_power_profile=base
/sys/class/drm/card*/gt/gt1/slpc_power_profile=base
/sys/class/drm/card*/gt/gt0/rps_boost_freq_mhz=2250
/sys/class/drm/card*/gt/gt0/rps_max_freq_mhz=2250
/sys/class/drm/card*/gt/gt1/rps_boost_freq_mhz=1300
/sys/class/drm/card*/device/tile0/gt0/freq0/max_freq=2250
/sys/class/drm/card*/device/tile0/gt0/freq0/power_profile=base
/sys/class/drm/card*/device/tile0/gt1/freq0/max_freq=1300

[sysctl]
vm.swappiness=150
kernel.nmi_watchdog=0
EOF

    [[ -f /etc/tuned/ppd.conf.orig.bak ]] || { [[ ! -f /etc/tuned/ppd.conf ]] || cp -a /etc/tuned/ppd.conf /etc/tuned/ppd.conf.orig.bak; }
    cat > /etc/tuned/ppd.conf << 'EOF'
[main]
default=balanced
battery_detection=true
sysfs_acpi_monitor=true

[profiles]
power-saver=powersave
balanced=balanced
performance=msi-claw-performance-ac

[battery]
balanced=balanced-battery
performance=performance-battery
EOF

    systemctl restart tuned tuned-ppd || echo "WARN: tuned/tuned-ppd restart failed" >&2

    echo "[3/8] Configuring Intel LPMD (2000ms WLT poll, ITMT power-save & opportunistic P-core parking)..."
    if [[ -f /etc/intel_lpmd/intel_lpmd_config_F6_M170.xml ]]; then
        [[ -f /etc/intel_lpmd/intel_lpmd_config_F6_M170.xml.orig.bak ]] || \
            cp -a /etc/intel_lpmd/intel_lpmd_config_F6_M170.xml /etc/intel_lpmd/intel_lpmd_config_F6_M170.xml.orig.bak
        cat > /etc/intel_lpmd/intel_lpmd_config_F6_M170.xml << 'EOF'
<?xml version="1.0"?>
<Configuration>
    <lp_mode_cpus></lp_mode_cpus>
    <Mode>1</Mode>
    <PerformanceDef>-1</PerformanceDef>
    <BalancedDef>-1</BalancedDef>
    <PowersaverDef>0</PowersaverDef>
    <HfiLpmEnable>0</HfiLpmEnable>
    <WLTHintEnable>1</WLTHintEnable>
    <WLTProxyEnable>0</WLTProxyEnable>
    <HfiSuvEnable>0</HfiSuvEnable>
    <util_entry_threshold></util_entry_threshold>
    <util_exit_threshold></util_exit_threshold>
    <EntryDelayMS>0</EntryDelayMS>
    <ExitDelayMS>0</ExitDelayMS>
    <EntryHystMS>0</EntryHystMS>
    <ExitHystMS>0</ExitHystMS>
    <IgnoreITMT>0</IgnoreITMT>
    <States>
        <CPUFamily> 6 </CPUFamily>
        <CPUModel> 170 </CPUModel>
        <CPUConfig> * </CPUConfig>
        <State>
            <ID> 1 </ID>
            <Name> WLT_IDLE </Name>
            <WLTType> 0 </WLTType>
            <ActiveLcores>ALL</ActiveLcores>
            <ActiveEcores>ALL</ActiveEcores>
            <MinPollInterval>2000</MinPollInterval>
            <ITMTState> -1 </ITMTState>
            <IRQMigrate> 1 </IRQMigrate>
        </State>
        <State>
            <ID> 2 </ID>
            <Name> WLT_BATTERY_LIFE </Name>
            <WLTType> 1 </WLTType>
            <ActiveLcores>ALL</ActiveLcores>
            <ActiveEcores>ALL</ActiveEcores>
            <MinPollInterval>2000</MinPollInterval>
            <ITMTState> -1 </ITMTState>
            <IRQMigrate> 1 </IRQMigrate>
        </State>
        <State>
            <ID> 3 </ID>
            <Name> WLT_SUSTAINED </Name>
            <WLTType> 2 </WLTType>
            <ActivePcores>ALL</ActivePcores>
            <ActiveLcores>ALL</ActiveLcores>
            <ActiveEcores>ALL</ActiveEcores>
            <MinPollInterval>2000</MinPollInterval>
            <ITMTState> -1 </ITMTState>
            <IRQMigrate> 1 </IRQMigrate>
        </State>
        <State>
            <ID> 4 </ID>
            <Name> WLT_BURSTY </Name>
            <WLTType> 3 </WLTType>
            <ActivePcores>ALL</ActivePcores>
            <ActiveLcores>ALL</ActiveLcores>
            <ActiveEcores>ALL</ActiveEcores>
            <MinPollInterval>2000</MinPollInterval>
            <ITMTState> -1 </ITMTState>
            <IRQMigrate> 1 </IRQMigrate>
        </State>
    </States>
</Configuration>
EOF
        systemctl restart intel_lpmd.service || true
    fi

    rm -f /usr/local/bin/msi-claw-charge-limit
    modprobe -r iTCO_wdt iTCO_vendor_support 2>/dev/null || true
}

apply_memory_zram_and_scx_fixes() {
    echo "[4/8] Applying CachyOS VM/THP/dirty-bytes sysctls, live zstd zram0 & scx_lavd handheld scheduler..."
    cat > /etc/sysctl.d/99-msi-claw-power.conf << 'EOF'
vm.swappiness = 150
vm.vfs_cache_pressure = 50
vm.dirty_bytes = 268435456
vm.dirty_background_bytes = 67108864
vm.dirty_writeback_centisecs = 1500
vm.dirty_expire_centisecs = 6000
vm.page-cluster = 0
kernel.nmi_watchdog = 0
kernel.watchdog = 0
kernel.split_lock_mitigate = 0
EOF
    sysctl --system >/dev/null || true

    cat > /etc/tmpfiles.d/99-msi-claw-thp.conf << 'EOF'
w /sys/kernel/mm/transparent_hugepage/enabled - - - - always
w /sys/kernel/mm/transparent_hugepage/defrag - - - - defer+madvise
w /sys/kernel/mm/transparent_hugepage/khugepaged/max_ptes_none - - - - 409
w /sys/module/zswap/parameters/enabled - - - - N
EOF
    systemd-tmpfiles --create /etc/tmpfiles.d/99-msi-claw-thp.conf 2>/dev/null || true
    echo always > /sys/kernel/mm/transparent_hugepage/enabled 2>/dev/null || true
    echo defer+madvise > /sys/kernel/mm/transparent_hugepage/defrag 2>/dev/null || true
    echo 409 > /sys/kernel/mm/transparent_hugepage/khugepaged/max_ptes_none 2>/dev/null || true
    echo N > /sys/module/zswap/parameters/enabled 2>/dev/null || true

    cat > /etc/modprobe.d/blacklist-watchdog.conf << 'EOF'
blacklist iTCO_wdt
blacklist iTCO_vendor_support
EOF

    cat > /etc/modprobe.d/i915-power.conf << 'EOF'
options i915 enable_dc_balance=1
EOF

    cat > /etc/modprobe.d/xe-power.conf << 'EOF'
options xe enable_dc_balance=1
EOF

    cat > /etc/modprobe.d/iwlwifi-powersave.conf << 'EOF'
options iwlwifi power_save=0
options iwlmld power_scheme=1
EOF

    install -d /etc/NetworkManager/conf.d
    cat > /etc/NetworkManager/conf.d/wifi-powersave-off.conf << 'EOF'
[connection]
wifi.powersave = 2
EOF

    cat > /etc/gamemode.ini << 'EOF'
[general]
reaper_freq=5
desiredgov=powersave
defaultgov=powersave
igpu_desiredgov=powersave
igpu_power_threshold=-1
softrealtime=off
renice=5
ioprio=0
inhibit_screensaver=1
EOF

    install -d /etc/systemd/system/thermald.service.d
    cat > /etc/systemd/system/thermald.service.d/override.conf << 'EOF'
[Service]
ExecStart=
ExecStart=/usr/bin/thermald --systemd --dbus-enable
EOF

    cat > /etc/tmpfiles.d/99-msi-claw-cool.conf << 'EOF'
w /sys/devices/system/cpu/smt/control - - - - off
EOF
    if [[ -w /sys/devices/system/cpu/smt/control ]]; then
        echo off > /sys/devices/system/cpu/smt/control 2>/dev/null || true
    fi

    cat > /etc/systemd/zram-generator.conf << 'EOF'
[zram0]
zram-size = min(ram, 8192)
compression-algorithm = zstd
EOF

    # Live-switch zram0 from lzo-rle -> zstd when safe (MemAvailable > 2 GB)
    if [[ -e /sys/block/zram0/comp_algorithm ]] && ! grep -q '\[zstd\]' /sys/block/zram0/comp_algorithm 2>/dev/null; then
        mem_avail_kb="$(awk '/^MemAvailable:/ {print $2}' /proc/meminfo 2>/dev/null || echo 0)"
        if [[ "${mem_avail_kb}" -gt 2097152 ]]; then
            # Let the generator own the device: its stop step hot-removes zram0, and only a
            # daemon-reload recreates dev-zram0.device (manual zramctl --reset caused a 45s swap outage)
            systemctl daemon-reload
            systemctl restart systemd-zram-setup@zram0.service dev-zram0.swap 2>/dev/null || true
        fi
    fi

    # Install & configure sched_ext handheld scheduler (scx_lavd --autopilot via scx_loader)
    if [[ ! -x /usr/bin/scx_lavd || ! -x /usr/bin/scx_loader ]]; then
        cat > /etc/yum.repos.d/_copr:copr.fedorainfracloud.org:sirlucjan:scx-scheds-cargo.repo << 'EOF'
[copr:copr.fedorainfracloud.org:sirlucjan:scx-scheds-cargo]
name=Copr repo for scx-scheds-cargo owned by sirlucjan
baseurl=https://download.copr.fedorainfracloud.org/results/sirlucjan/scx-scheds-cargo/fedora-$releasever-$basearch/
type=rpm-md
skip_if_unavailable=True
gpgcheck=1
gpgkey=https://download.copr.fedorainfracloud.org/results/sirlucjan/scx-scheds-cargo/pubkey.gpg
repo_gpgcheck=0
enabled=1
enabled_metadata=1
EOF
        dnf install -y --setopt=install_weak_deps=False scx-scheds scx-tools || \
            dnf install -y --setopt=install_weak_deps=False scx_rusty || true
    fi

    if [[ -x /usr/bin/scx_loader && -x /usr/bin/scx_lavd ]]; then
        install -d /etc/scx_loader /etc/polkit-1/rules.d
        rm -rf /etc/systemd/system/scx_loader.service.d
        cat > /etc/scx_loader.toml << 'EOF'
default_sched = "scx_lavd"
default_mode = "Auto"
EOF
        cp -f /etc/scx_loader.toml /etc/scx_loader/config.toml
        cat > /etc/polkit-1/rules.d/50-msi-claw-scx.rules << 'EOF'
polkit.addRule(function(action, subject) {
    if (action.id == "org.scx.loader.manage-schedulers" &&
        subject.active && subject.local && subject.isInGroup("wheel")) {
        return polkit.Result.YES;
    }
});
EOF
        systemctl daemon-reload
        # A freshly installed org.scx.Loader D-Bus policy isn't active until dbus reloads its config;
        # without this, Type=dbus scx_loader times out 45s per activation attempt
        busctl call org.freedesktop.DBus /org/freedesktop/DBus org.freedesktop.DBus ReloadConfig 2>/dev/null || true
        systemctl reset-failed scx_loader.service 2>/dev/null || true
        systemctl enable --now scx_loader.service || true
        # default_sched already starts lavd; only intervene if something else is running
        if ! scxctl get 2>/dev/null | grep -qi 'lavd'; then
            scxctl switch --sched scx_lavd --mode auto 2>/dev/null || \
                scxctl start --sched scx_lavd --mode auto 2>/dev/null || true
        fi
    fi
}

if [[ "${1:-}" == "--finish-scx-thp" ]]; then
    apply_memory_zram_and_scx_fixes
    exit 0
fi

if [[ "${1:-}" == "--gpu-priority" ]]; then
    pct_file=/sys/devices/system/cpu/intel_pstate/max_perf_pct
    if [[ "${2:-}" == "on" ]]; then
        # Never raise a stricter TuneD cap (e.g. Eco 55%)
        cur_pct=$(cat "$pct_file" 2>/dev/null || echo 100)
        if (( cur_pct > 72 )); then echo 72 > "$pct_file"; fi
        touch /run/msi-claw-gpu-priority
        echo "GPU Priority enabled (CPU boost capped at <=72% / ~3.45 GHz)"
    else
        rm -f /run/msi-claw-gpu-priority
        # Re-apply the active TuneD profile so its own cap comes back instead of a blanket 100%
        prof=$(tuned-adm active 2>/dev/null | sed -n 's/^Current active profile: //p' || true)
        if [[ -n "$prof" ]] && tuned-adm profile "$prof"; then
            echo "CPU boost cap restored from TuneD profile '$prof' ($(cat "$pct_file")%)"
        else
            echo 100 > "$pct_file"
            echo "Full CPU Turbo restored (max_perf_pct=100%)"
        fi
    fi
    exit 0
fi

if [[ "${1:-}" == "--scx" ]]; then
    mode="${2:-auto}"
    if [[ "$mode" == "off" ]]; then
        if command -v scxcli >/dev/null 2>&1; then
            scxcli stop 2>/dev/null || true
        else
            scxctl stop 2>/dev/null || true
        fi
    elif command -v scxcli >/dev/null 2>&1; then
        if [[ "$mode" == "gaming" ]]; then
            scxcli run scx_lavd --performance 2>/dev/null || scxcli start scx_lavd 2>/dev/null || true
        else
            scxcli start scx_lavd 2>/dev/null || true
        fi
    elif command -v scxctl >/dev/null 2>&1; then
        scxctl switch --sched scx_lavd --mode "$mode" 2>/dev/null || \
            scxctl start --sched scx_lavd --mode "$mode" 2>/dev/null || true
    fi
    exit 0
fi

if [[ "${1:-}" == "--fast-resume" ]]; then
    apply_fast_resume_fixes
    echo "=== MSI Claw A1M Fast-Resume & Input ACL Optimization Complete! ==="
    exit 0
fi

if [[ "${1:-}" == "--fix-all-live" ]]; then
    apply_fast_resume_fixes
    apply_tuned_and_lpmd_fixes
    apply_memory_zram_and_scx_fixes
    if [[ "$(cat /sys/class/power_supply/ADP1/online 2>/dev/null || echo 1)" == "0" ]]; then
        tuned-adm profile balanced-battery 2>/dev/null || tuned-adm profile powersave 2>/dev/null || true
    else
        tuned-adm profile balanced 2>/dev/null || true
    fi
    echo "=== MSI Claw A1M Live Input ACL, TuneD, LPMD, zstd zram & scx_lavd Fixes Complete! ==="
    exit 0
fi

echo "[1/8] Hardening Wi-Fi/Controller protection, fast s2idle resume & safe PCI Runtime PM..."
apply_fast_resume_fixes
apply_tuned_and_lpmd_fixes
apply_memory_zram_and_scx_fixes

echo "[5/8] Optimizing Btrfs (/ & /home) with noatime,commit=60 and remounting live..."
[[ -f /etc/fstab.orig.bak ]] || cp -a /etc/fstab /etc/fstab.orig.bak
python3 - << 'PYEOF'
import os
from pathlib import Path
fstab = Path("/etc/fstab")
orig_txt = fstab.read_text()
lines = orig_txt.splitlines()
out = []
for line in lines:
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        out.append(line)
        continue
    parts = line.split()
    if len(parts) >= 4:
        mp, fstype, opts = parts[1], parts[2], parts[3]
        opt_list = [o for o in opts.split(",") if o != "relatime"]
        if fstype == "btrfs" and mp in ("/", "/home"):
            if "noatime" not in opt_list:
                opt_list.append("noatime")
            if not any(o.startswith("commit=") for o in opt_list):
                opt_list.append("commit=60")
            parts[3] = ",".join(opt_list)
            line = " ".join(parts)
        elif fstype == "ext4" and mp == "/boot":
            if "noatime" not in opt_list:
                opt_list.append("noatime")
            parts[3] = ",".join(opt_list)
            line = " ".join(parts)
    out.append(line)
new_txt = "\n".join(out) + "\n"
if new_txt != orig_txt:
    tmp = fstab.with_name(f".fstab.tmp.{os.getpid()}")
    tmp.write_text(new_txt)
    os.chmod(tmp, 0o644)
    os.replace(tmp, fstab)
PYEOF
systemctl daemon-reload
mount -o remount / || true
mount -o remount /home || true
mount -o remount /boot || true

echo "[6/8] Disabling unused hardware-absent, VM guest & enterprise storage daemons..."
UNUSED_UNITS=(
    ModemManager.service
    cups.service cups.socket cups.path
    pcscd.service pcscd.socket
    atd.service
    vboxservice.service vmtoolsd.service vgauthd.service qemu-guest-agent.service
    iscsi-onboot.service iscsi-starter.service
    lvm2-monitor.service mdmonitor.service raid-check.timer
    dnf-makecache.timer
    abrt-journal-core.service abrt-oops.service abrt-xorg.service abrtd.service
)
for u in "${UNUSED_UNITS[@]}"; do
    if systemctl list-unit-files "$u" >/dev/null 2>&1; then
        systemctl disable --now "$u" 2>/dev/null || true
    fi
done

echo "[7/8] Cleaning up unsupported 2-byte charge-limit helper & unloading iTCO watchdog..."
rm -f /usr/local/bin/msi-claw-charge-limit
modprobe -r iTCO_wdt iTCO_vendor_support 2>/dev/null || true

echo "[8/8] Syncing On-Screen Keyboard (KDE Plasma full-width OSK / GNOME Shell GResources if installed)..."
if rpm -q gnome-shell >/dev/null 2>&1 && [[ -f "${EXT_DIR}/us-enhanced.json" ]] && command -v glib-compile-resources >/dev/null 2>&1; then
    WORK_DIR=$(mktemp -d /tmp/claw-osk-gresource.XXXXXX)
    trap 'rm -rf "$WORK_DIR"' EXIT

    # Stage the user's extension files by reading them AS THE USER (root never opens paths in $HOME,
    # so symlinks like metadata.json -> /etc/shadow can't leak root-only files into /usr/share)
    STAGE="$WORK_DIR/stage"
    install -d -m 0700 "$STAGE"
    for ef in us-enhanced.json stylesheet.css extension.js metadata.json; do
        runuser -u "${TARGET_USER}" -- sh -c '[ -f "$1" ] && [ ! -L "$1" ] && head -c 2000000 "$1"' _ "${EXT_DIR}/$ef" \
            > "$STAGE/$ef" 2>/dev/null || rm -f "$STAGE/$ef"
    done
    [[ -s "$STAGE/us-enhanced.json" ]] || { echo "us-enhanced.json unreadable; skipping GResource sync" >&2; exit 1; }

    # Refuse to build from an unreadable/empty source: an empty list would replace the live theme/OSK gresource
    gres_list() {
        local out
        out=$(gresource list "$1") && [[ -n "$out" ]] || { echo "gresource list failed for $1" >&2; exit 1; }
        printf '%s\n' "$out"
    }

    # 8a. Recompile gnome-shell-osk-layouts.gresource with tighter us-enhanced.json
    # Only ever rebuild from the INSTALLED gnome-shell's stock file (a stale .orig.bak from an older
    # version would put old-version CSS/layouts into the new shell)
    stock_src() {
        local f="$1" want
        [[ -x /usr/local/sbin/msi-claw-shell-backup-sync ]] && /usr/local/sbin/msi-claw-shell-backup-sync >&2 || true
        want=$(rpm -qf --dump "$f" | awk -v p="$f" '$1 == p && !found {print $4; found=1}')
        for c in "$f.orig.bak" "$f"; do
            [[ -f "$c" && "$(sha256sum "$c" | cut -d' ' -f1)" == "$want" ]] && { echo "$c"; return 0; }
        done
        echo "No stock copy of $f matches $(rpm -qf "$f"); run 'dnf reinstall gnome-shell' first" >&2
        return 1
    }
    LAYOUT_SRC=$(stock_src /usr/share/gnome-shell/gnome-shell-osk-layouts.gresource)
    mkdir -p "$WORK_DIR/layouts/org/gnome/shell/osk-layouts"
    cat > "$WORK_DIR/layouts/osk.gresource.xml" << 'XMLEOF'
<?xml version="1.0" encoding="UTF-8"?>
<gresources>
  <gresource prefix="/org/gnome/shell/osk-layouts">
XMLEOF
    LAYOUT_RES=$(gres_list "$LAYOUT_SRC")  # errexit aborts here if the list fails
    for res in $LAYOUT_RES; do
        fname=$(basename "$res")
        if [[ "$fname" == "us.json" || "$fname" == "us-extended.json" ]]; then
            cp "$STAGE/us-enhanced.json" "$WORK_DIR/layouts/org/gnome/shell/osk-layouts/$fname"
        else
            gresource extract "$LAYOUT_SRC" "$res" > "$WORK_DIR/layouts/org/gnome/shell/osk-layouts/$fname"
        fi
        echo "    <file>$fname</file>" >> "$WORK_DIR/layouts/osk.gresource.xml"
    done
    cat >> "$WORK_DIR/layouts/osk.gresource.xml" << 'XMLEOF'
  </gresource>
</gresources>
XMLEOF
    glib-compile-resources --sourcedir="$WORK_DIR/layouts/org/gnome/shell/osk-layouts" \
        --target="$WORK_DIR/gnome-shell-osk-layouts.gresource" \
        "$WORK_DIR/layouts/osk.gresource.xml"
    install -m 0644 "$WORK_DIR/gnome-shell-osk-layouts.gresource" /usr/share/gnome-shell/gnome-shell-osk-layouts.gresource.tmp
    mv -f /usr/share/gnome-shell/gnome-shell-osk-layouts.gresource.tmp /usr/share/gnome-shell/gnome-shell-osk-layouts.gresource

    # 8b. Recompile gnome-shell-theme.gresource with tighter CSS
    THEME_SRC=$(stock_src /usr/share/gnome-shell/gnome-shell-theme.gresource)
    mkdir -p "$WORK_DIR/theme"
    cat > "$WORK_DIR/theme/theme.gresource.xml" << 'XMLEOF'
<?xml version="1.0" encoding="UTF-8"?>
<gresources>
  <gresource prefix="/org/gnome/shell/theme">
XMLEOF
    THEME_RES=$(gres_list "$THEME_SRC")  # errexit aborts here if the list fails
    for res in $THEME_RES; do
        rel="${res#/org/gnome/shell/theme/}"
        mkdir -p "$WORK_DIR/theme/$(dirname "$rel")"
        gresource extract "$THEME_SRC" "$res" > "$WORK_DIR/theme/$rel"
        if [[ "$rel" == "gnome-shell-dark.css" || "$rel" == "gnome-shell-light.css" ]]; then
            [[ -f "$STAGE/stylesheet.css" ]] && cat "$STAGE/stylesheet.css" >> "$WORK_DIR/theme/$rel"
        fi
        echo "    <file>$rel</file>" >> "$WORK_DIR/theme/theme.gresource.xml"
    done
    cat >> "$WORK_DIR/theme/theme.gresource.xml" << 'XMLEOF'
  </gresource>
</gresources>
XMLEOF
    glib-compile-resources --sourcedir="$WORK_DIR/theme" \
        --target="$WORK_DIR/gnome-shell-theme.gresource" \
        "$WORK_DIR/theme/theme.gresource.xml"
    install -m 0644 "$WORK_DIR/gnome-shell-theme.gresource" /usr/share/gnome-shell/gnome-shell-theme.gresource.tmp
    mv -f /usr/share/gnome-shell/gnome-shell-theme.gresource.tmp /usr/share/gnome-shell/gnome-shell-theme.gresource
    install -d /usr/share/gnome-shell/extensions/claw-controls@msi-claw
    for ef in us-enhanced.json stylesheet.css extension.js metadata.json; do
        if [[ -s "$STAGE/$ef" ]]; then
            install -m 0644 "$STAGE/$ef" "/usr/share/gnome-shell/extensions/claw-controls@msi-claw/${ef}.tmp"
            mv -f "/usr/share/gnome-shell/extensions/claw-controls@msi-claw/${ef}.tmp" "/usr/share/gnome-shell/extensions/claw-controls@msi-claw/$ef"
        fi
    done
else
    echo "  -> gnome-shell not installed; skipping GDM GResource rebuild (KDE Plasma full-width OSK configured)."
    systemctl disable --now msi-claw-shell-backup-sync.path msi-claw-shell-backup-sync.service 2>/dev/null || true
fi

# Re-apply appropriate TuneD profile based on current AC/Battery state
if [[ "$(cat /sys/class/power_supply/ADP1/online 2>/dev/null || echo 1)" == "0" ]]; then
    tuned-adm profile balanced-battery 2>/dev/null || tuned-adm profile powersave 2>/dev/null || true
else
    tuned-adm profile balanced 2>/dev/null || true
fi

echo "=== MSI Claw A1M System-Level Battery & OSK Optimization Complete! ==="
