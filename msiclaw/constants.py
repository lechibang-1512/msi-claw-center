"""
Global constants, hardware identifiers, and default configurations for MSI Claw A1M.
"""

import os
from pathlib import Path

# Controller USB product IDs
CLAW_PIDS = ("00001901", "00001902", "00001903", "00001904")

# Controller HID read command
CLAW_READ_MODE = bytes([0x0F, 0x00, 0x00, 0x3C, 0x26]).ljust(64, b"\x00")

# Inter-process synchronization paths in /dev/shm
def get_overlay_shm_path(uid: int = None) -> Path:
    if uid is None:
        uid = os.getuid()
    return Path(f"/dev/shm/msi-claw-overlay-{uid}")

OVERLAY_SHM_PATH = get_overlay_shm_path()

# User configuration paths in ~/.config
CONFIG_DIR = Path.home() / ".config"
RGB_CONFIG_PATH = CONFIG_DIR / "msi-claw-rgb.json"
GYRO_CONFIG_PATH = CONFIG_DIR / "msi-claw-gyro.json"
KEYS_CONFIG_PATH = CONFIG_DIR / "msi-claw-keys.json"

# MSI Claw MCU M1/M2 macro software intercept scan codes on event5
MCU_M1_SW_CODE = 0x59
MCU_M2_SW_CODE = 0x58

# Hardware MCU macro key codes
HW_MKEY_CODES = {
    "hw:ABS_HAT0Y_UP": 0x01,
    "hw:ABS_HAT0Y_DOWN": 0x02,
    "hw:ABS_HAT0X_LEFT": 0x03,
    "hw:ABS_HAT0X_RIGHT": 0x04,
    "hw:BTN_TL": 0x05,
    "hw:BTN_TR": 0x06,
    "hw:BTN_THUMBL": 0x07,
    "hw:BTN_THUMBR": 0x08,
    "hw:BTN_SOUTH": 0x09,
    "hw:BTN_EAST": 0x0A,
    "hw:BTN_NORTH": 0x0B,
    "hw:BTN_WEST": 0x0C,
    "hw:BTN_MODE": 0x0D,
    "hw:BTN_SELECT": 0x0E,
    "hw:BTN_START": 0x0F,
    "hw:BTN_TL2": 0x13,
    "hw:BTN_TR2": 0x14,
}

# Factory default key bindings
DEFAULT_KEY_BINDINGS = {
    "view_desktop": "esc",
    "menu_desktop": "alt-tab",
    "f16_tap": "toggle-center",
    "f16_chord": "overview",
    "f15_tap": "quick-settings",
    "f15_chord": "toggle-osk",
    "m1_desktop": "toggle-osk",
    "m2_desktop": "enter",
    "m1_gamepad": "gyro-hold",
    "m2_gamepad": "toggle-osk",
    "m1_chord": "screenshot",
    "m2_chord": "toggle-gyro",
    "a_desktop": "mouse-left",
    "b_desktop": "mouse-right",
    "x_desktop": "toggle-osk",
    "y_desktop": "overview",
}
