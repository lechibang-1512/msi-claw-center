"""
Hardware, power, kernel lockdown, and telemetry probe helpers for MSI Claw A1M.
"""

import glob
import os
from pathlib import Path
import platform
import re
from typing import Dict, Tuple

from .constants import CLAW_PIDS


def read_sysfs(path: str, default: str = "") -> str:
    """Read a sysfs or procfs file returning stripped text or default on failure."""
    try:
        return Path(path).read_text().strip()
    except OSError:
        return default


def kernel_lockdown_mode() -> str:
    """Return active kernel lockdown state (e.g. 'integrity' under Secure Boot) or empty string."""
    txt = read_sysfs("/sys/kernel/security/lockdown", "")
    m = re.search(r"\[([a-zA-Z0-9_-]+)\]", txt)
    if m and m.group(1) != "none":
        return m.group(1)
    return ""


def gpu_priority_active() -> bool:
    """Check if GPU priority capping CPU at <=72% is currently engaged."""
    max_pct = int(read_sysfs("/sys/devices/system/cpu/intel_pstate/max_perf_pct", "100") or 100)
    return os.path.exists("/run/msi-claw-gpu-priority") and max_pct <= 72


def resolve_hwmon() -> Tuple[str, str, str]:
    """Resolve active sysfs paths for CPU temperature and dual cooling fans."""
    cpu_temp = ""
    acpitz_temp = ""
    coretemp_temp = ""
    fallback_temp = ""
    fan1 = ""
    fan2 = ""
    fallback_fan1 = ""
    fallback_fan2 = ""

    for hdir in sorted(glob.glob("/sys/class/hwmon/hwmon*")):
        name = read_sysfs(f"{hdir}/name")
        t1 = f"{hdir}/temp1_input"
        f1 = f"{hdir}/fan1_input"
        f2 = f"{hdir}/fan2_input"

        if os.path.exists(t1) and not fallback_temp:
            fallback_temp = t1

        if name == "coretemp" and os.path.exists(t1):
            coretemp_temp = t1
        elif name == "acpitz" and os.path.exists(t1):
            acpitz_temp = t1

        if name == "msi_wmi_platform":
            if os.path.exists(f1):
                fan1 = f1
            if os.path.exists(f2):
                fan2 = f2
        elif os.path.exists(f1) and not fallback_fan1:
            fallback_fan1 = f1
            if os.path.exists(f2):
                fallback_fan2 = f2

    cpu_temp = coretemp_temp or acpitz_temp or fallback_temp
    if not fan1 and fallback_fan1:
        fan1 = fallback_fan1
        fan2 = fallback_fan2

    return cpu_temp, fan1, fan2


def get_rapl_power_limits() -> Tuple[int, int]:
    """Read effective PL1 (long term) and PL2 (short term) RAPL power limits in Watts."""
    pl1_msr = float(read_sysfs("/sys/class/powercap/intel-rapl:0/constraint_0_power_limit_uw", "0") or 0) / 1e6
    pl1_mmio = float(read_sysfs("/sys/class/powercap/intel-rapl-mmio:0/constraint_0_power_limit_uw", "0") or 0) / 1e6
    pl2_msr = float(read_sysfs("/sys/class/powercap/intel-rapl:0/constraint_1_power_limit_uw", "0") or 0) / 1e6
    pl2_mmio = float(read_sysfs("/sys/class/powercap/intel-rapl-mmio:0/constraint_1_power_limit_uw", "0") or 0) / 1e6

    valid_pl1 = [v for v in (pl1_msr, pl1_mmio) if v > 0]
    eff_pl1 = int(round(min(valid_pl1))) if valid_pl1 else 0

    valid_pl2 = [v for v in (pl2_msr, pl2_mmio) if v > 0]
    eff_pl2 = int(round(min(valid_pl2))) if valid_pl2 else 0

    return eff_pl1, eff_pl2


def get_power_profile(bus=None) -> str:
    """Read active power profile from org.freedesktop.UPower.PowerProfiles D-Bus service."""
    try:
        if bus is None:
            import gi
            gi.require_version("Gio", "2.0")
            from gi.repository import Gio, GLib
            bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
        else:
            from gi.repository import GLib
        reply = bus.call_sync(
            "org.freedesktop.UPower.PowerProfiles",
            "/org/freedesktop/UPower/PowerProfiles",
            "org.freedesktop.DBus.Properties",
            "Get",
            GLib.Variant("(ss)", ("org.freedesktop.UPower.PowerProfiles", "ActiveProfile")),
            GLib.VariantType.new("(v)"),
            0,
            250,
            None,
        )
        return str(reply.unpack()[0])
    except Exception:
        return "balanced"


def set_power_profile(profile: str, bus=None) -> bool:
    """Switch active power profile (power-saver, balanced, performance) via D-Bus."""
    if profile not in ("power-saver", "balanced", "performance"):
        return False
    try:
        import gi
        gi.require_version("Gio", "2.0")
        from gi.repository import Gio, GLib
        if bus is None:
            bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
        variant = GLib.Variant(
            "(ssv)",
            ("org.freedesktop.UPower.PowerProfiles", "ActiveProfile", GLib.Variant("s", profile)),
        )
        bus.call_sync(
            "org.freedesktop.UPower.PowerProfiles",
            "/org/freedesktop/UPower/PowerProfiles",
            "org.freedesktop.DBus.Properties",
            "Set",
            variant,
            None,
            0,
            1000,
            None,
        )
        try:
            xe_prof = "power_saving" if profile == "power-saver" else "base"
            for p in glob.glob("/sys/class/drm/card*/device/tile0/gt0/freq0/power_profile"):
                Path(p).write_text(xe_prof)
        except Exception:
            pass
        return True
    except Exception:
        return False


def resolve_arc_gpu() -> Tuple[str, str]:
    """Detect Intel Arc GPU driver ('xe' vs 'i915') and sysfs card directory."""
    for cdir in sorted(glob.glob("/sys/class/drm/card[0-9]*")):
        dev_dir = f"{cdir}/device"
        if read_sysfs(f"{dev_dir}/vendor").lower() != "0x8086":
            continue
        drv = "unknown"
        drv_link = f"{dev_dir}/driver"
        if os.path.islink(drv_link):
            drv = os.path.basename(os.path.realpath(drv_link))
        if drv == "xe" or os.path.isdir(f"{dev_dir}/tile0/gt0"):
            return "xe", cdir
        if drv == "i915" or os.path.isdir(f"{cdir}/gt/gt0"):
            return "i915", cdir
    return "i915", "/sys/class/drm/card1"


def get_hardware_inventory() -> Dict[str, str]:
    """Gather live hardware and firmware inventory for the MSI Claw A1M."""
    bios_ver = read_sysfs("/sys/class/dmi/id/bios_version", "E1T41IMS.10F")
    bios_date = read_sysfs("/sys/class/dmi/id/bios_date", "")
    bios_str = f"{bios_ver} ({bios_date})" if bios_date else bios_ver

    prod_name = read_sysfs("/sys/class/dmi/id/product_name", "Claw A1M")
    prod_ver = read_sysfs("/sys/class/dmi/id/product_version", "REV:1.0")
    model_str = f"MSI {prod_name} (MS-1T41 {prod_ver})"

    mcu_str = "v1.72 (0x0172)"
    for u in glob.glob("/sys/bus/usb/devices/*"):
        try:
            vid = Path(f"{u}/idVendor").read_text().strip().lower()
            pid = Path(f"{u}/idProduct").read_text().strip().lower()
            if vid == "0db0" and pid in CLAW_PIDS:
                bcd = Path(f"{u}/bcdDevice").read_text().strip()
                mcu_str = f"v{int(bcd[:2])}.{int(bcd[2:]):02d} (0x{bcd})"
                break
        except Exception:
            pass

    drv_gpu, _ = resolve_arc_gpu()
    gpu_str = f"Intel Arc 8-Xe ({drv_gpu})"
    npu_str = "Meteor Lake VPU (/dev/accel/accel0)" if os.path.exists("/dev/accel/accel0") else "Meteor Lake VPU"
    kernel_str = f"Linux {platform.release()}"

    return {
        "model": model_str,
        "bios": bios_str,
        "cpu": "Core Ultra 7 155H (16C / 22T)",
        "gpu": gpu_str,
        "mcu": mcu_str,
        "npu": npu_str,
        "wifi": "Killer Wi-Fi 7 BE200 (iwlwifi)",
        "kernel": kernel_str,
    }
