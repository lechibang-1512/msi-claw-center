"""
MSI Claw A1M Controller RGB Power Control (Zero-Flash-Wear HID Protocol).
Based on open-source MSI Claw HID research from hhd-dev/hhd & Christo262/claw-ambient.
Uses WRITE_PROFILE_DATA (0x21) without SYNC_TO_ROM (0x22) to avoid MCU flash wear.
"""

import glob
import os
from pathlib import Path
import re
import select
from typing import Optional, Tuple

from .constants import CLAW_PIDS
from .hw import read_sysfs


class ClawRGBController:
    """Direct zero-flash-wear MSI Claw RGB HID controller."""

    def __init__(self):
        self.sys_dir, self.dev_path = self._find()
        self.addr = self._get_addr(self.sys_dir) if self.sys_dir else 0x024A

    @staticmethod
    def _find() -> Tuple[Optional[str], Optional[str]]:
        for sdir in sorted(glob.glob("/sys/class/hidraw/hidraw*")):
            ue = read_sysfs(f"{sdir}/device/uevent").upper()
            if "0DB0:" in ue and any(p in ue for p in CLAW_PIDS):
                try:
                    rdesc = Path(f"{sdir}/device/report_descriptor").read_bytes()
                    if rdesc.startswith(b"\x06\xa0\xff"):
                        return sdir, "/dev/" + os.path.basename(sdir)
                    continue
                except OSError:
                    pass
                real_dev = os.path.realpath(f"{sdir}/device")
                if re.search(r"/INPUT1(?:\r?\n|$)", ue) or ":1.1/" in real_dev or real_dev.endswith(":1.1"):
                    return sdir, "/dev/" + os.path.basename(sdir)
        return None, None

    @staticmethod
    def _get_addr(sdir: str) -> int:
        d = os.path.realpath(f"{sdir}/device")
        while d != "/" and not os.path.exists(f"{d}/bcdDevice"):
            d = os.path.dirname(d)
        bcd_txt = read_sysfs(f"{d}/bcdDevice")
        if bcd_txt:
            try:
                bcd = int(bcd_txt, 16)
                major, minor = bcd >> 8, bcd & 0xFF
                if (major == 1 and minor >= 0x66) or (major == 2 and minor >= 0x17) or major >= 3:
                    return 0x024A
                return 0x01FA
            except ValueError:
                pass
        return 0x024A

    def apply(self, r: int, g: int, b: int, brightness: int) -> Tuple[bool, str]:
        if (
            not self.dev_path
            or not os.path.exists(self.dev_path)
            or not self.sys_dir
            or "0DB0:" not in read_sysfs(f"{self.sys_dir}/device/uevent").upper()
        ):
            self.sys_dir, self.dev_path = self._find()
            if self.sys_dir:
                self.addr = self._get_addr(self.sys_dir)
        if not self.dev_path:
            return False, "MSI Claw RGB hidraw device not detected"
        try:
            fd = os.open(self.dev_path, os.O_RDWR | os.O_NONBLOCK)
        except PermissionError:
            return False, f"Permission denied on {self.dev_path} (run Live Fixes)"
        except OSError as e:
            self.dev_path = None
            return False, f"Device open failed: {e.strerror}"

        try:
            try:
                while os.read(fd, 64):
                    pass
            except BlockingIOError:
                pass
            br = max(0, min(100, int(brightness)))
            rc, gc, bc = (max(0, min(255, int(v))) for v in (r, g, b))
            body = bytes([0x01, self.addr >> 8, self.addr & 0xFF, 0x24, 0x00, 1, 0x09, 0, br])
            pkt = (bytes([0x0F, 0, 0, 0x3C, 0x21]) + body + bytes([rc, gc, bc]) * 9).ljust(64, b"\x00")
            os.write(fd, pkt)
            rlist, _, _ = select.select([fd], [], [], 0.04)
            if rlist:
                try:
                    while os.read(fd, 64):
                        pass
                except BlockingIOError:
                    pass
            return True, "OK"
        except OSError as e:
            return False, f"HID write error: {e.strerror}"
        finally:
            os.close(fd)


_global_rgb_controller = None

def get_rgb_controller() -> ClawRGBController:
    global _global_rgb_controller
    if _global_rgb_controller is None:
        _global_rgb_controller = ClawRGBController()
    return _global_rgb_controller


def set_rgb(r: int, g: int, b: int, brightness: int = 100) -> int:
    """Set RGB colors (0-255) and brightness (0-100) returning 0 on success."""
    ctrl = get_rgb_controller()
    ok, _msg = ctrl.apply(r, g, b, brightness)
    return 0 if ok else 1


def main() -> None:
    """CLI entrypoint for msi-claw-rgb command."""
    import sys
    args = sys.argv[1:]
    cmd = args[0].lower() if args else "help"
    if cmd == "off":
        sys.exit(set_rgb(0, 0, 0, 0))
    elif cmd == "dim":
        sys.exit(set_rgb(0, 150, 255, 15))
    elif cmd in ("on", "full"):
        sys.exit(set_rgb(255, 35, 35, 75))
    elif len(args) >= 3:
        br = int(args[3]) if len(args) >= 4 else 60
        sys.exit(set_rgb(int(args[0]), int(args[1]), int(args[2]), br))
    else:
        print(
            "MSI Claw A1M Controller RGB Power Control\n"
            "Usage:\n"
            "  msi-claw-rgb off                  # Turn off all 9 controller RGB LEDs\n"
            "  msi-claw-rgb dim                  # Subtle 15% cyan-blue glow\n"
            "  msi-claw-rgb on                   # 75% MSI red glow\n"
            "  msi-claw-rgb <r> <g> <b> [0-100]  # Custom RGB (0-255) & brightness (0-100)"
        )
        sys.exit(0)
