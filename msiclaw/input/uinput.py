"""
Linux uinput userspace virtual device driver for MSI Claw A1M.
Creates virtual mouse, virtual keyboard, and virtual touch interfaces via /dev/uinput.
"""

import fcntl
import os
import struct
import time
from typing import Sequence, Tuple

# Linux input / uinput constants
UI_SET_EVBIT = 0x40045564
UI_SET_KEYBIT = 0x40045565
UI_SET_RELBIT = 0x40045566
UI_SET_ABSBIT = 0x40045567
UI_SET_PROPBIT = 0x4004556E
UI_DEV_SETUP = 0x405C5503
UI_ABS_SETUP = 0x401C5504
UI_DEV_CREATE = 0x5501
UI_DEV_DESTROY = 0x5502
EVIOCGRAB = 0x40044590

EV_SYN = 0x00
EV_KEY = 0x01
EV_REL = 0x02
EV_ABS = 0x03

SYN_REPORT = 0x00

# Relative axes
REL_X = 0x00
REL_Y = 0x01
REL_HWHEEL = 0x06
REL_WHEEL = 0x08
REL_WHEEL_HI_RES = 0x0B
REL_HWHEEL_HI_RES = 0x0C

# Absolute axes (Gamepad & Touch)
ABS_X = 0x00
ABS_Y = 0x01
ABS_Z = 0x02     # LT (0..255)
ABS_RX = 0x03
ABS_RY = 0x04
ABS_RZ = 0x05    # RT (0..255)
ABS_HAT0X = 0x10 # D-Pad X (-1, 0, 1)
ABS_HAT0Y = 0x11 # D-Pad Y (-1, 0, 1)

ABS_MT_SLOT = 0x2F
ABS_MT_POSITION_X = 0x35
ABS_MT_POSITION_Y = 0x36
ABS_MT_TRACKING_ID = 0x39

# Mouse & Touch buttons
BTN_LEFT = 0x110
BTN_RIGHT = 0x111
BTN_MIDDLE = 0x112
BTN_SIDE = 0x113
BTN_EXTRA = 0x114
BTN_TOUCH = 0x14A

# Gamepad buttons (Xbox 360 layout on MSI Claw A1M 0db0:1901)
BTN_SOUTH = 0x130  # A
BTN_EAST = 0x131   # B
BTN_NORTH = 0x133  # X
BTN_WEST = 0x134   # Y
BTN_TL = 0x136     # LB
BTN_TR = 0x137     # RB
BTN_SELECT = 0x13A # View
BTN_START = 0x13B  # Menu
BTN_MODE = 0x13C   # Guide
BTN_THUMBL = 0x13D # L3
BTN_THUMBR = 0x13E # R3

# Keyboard keys
KEY_ESC = 1
KEY_BACKSPACE = 14
KEY_TAB = 15
KEY_LEFTBRACE = 26
KEY_RIGHTBRACE = 27
KEY_ENTER = 28
KEY_LEFTCTRL = 29
KEY_A = 30
KEY_LEFTSHIFT = 42
KEY_Z = 44
KEY_X = 45
KEY_C = 46
KEY_V = 47
KEY_LEFTALT = 56
KEY_SPACE = 57
KEY_F4 = 62
KEY_SYSRQ = 99
KEY_UP = 103
KEY_PAGEUP = 104
KEY_LEFT = 105
KEY_RIGHT = 106
KEY_DOWN = 108
KEY_PAGEDOWN = 109
KEY_INSERT = 110
KEY_DELETE = 111
KEY_MUTE = 113
KEY_VOLUMEDOWN = 114
KEY_VOLUMEUP = 115
KEY_LEFTMETA = 125
KEY_BACK = 158
KEY_FORWARD = 159
KEY_F15 = 185
KEY_F16 = 186
KEY_BRIGHTNESSDOWN = 224
KEY_BRIGHTNESSUP = 225

EVENT_STRUCT = struct.Struct("<qqHHi")


class UInputDevice:
    """Wrapper around /dev/uinput ioctls to emit Linux input events."""

    def __init__(
        self,
        name: str,
        product_id: int,
        ev_bits: Sequence[int],
        key_bits: Sequence[int] = (),
        rel_bits: Sequence[int] = (),
        abs_axes: Sequence[Tuple[int, int, int]] = (),
        prop_bits: Sequence[int] = (),
    ):
        for attempt in range(20):
            try:
                self.fd = os.open("/dev/uinput", os.O_WRONLY | os.O_NONBLOCK)
                break
            except (PermissionError, FileNotFoundError):
                if attempt == 19:
                    raise
                time.sleep(0.5)

        for ev in ev_bits:
            fcntl.ioctl(self.fd, UI_SET_EVBIT, ev)
        for k in key_bits:
            fcntl.ioctl(self.fd, UI_SET_KEYBIT, k)
        for r in rel_bits:
            fcntl.ioctl(self.fd, UI_SET_RELBIT, r)
        for p in prop_bits:
            fcntl.ioctl(self.fd, UI_SET_PROPBIT, p)
        for axis, min_v, max_v in abs_axes:
            fcntl.ioctl(self.fd, UI_SET_ABSBIT, axis)
            abs_setup = struct.pack("<Hxxiiiiii", axis, 0, min_v, max_v, 0, 0, 0)
            fcntl.ioctl(self.fd, UI_ABS_SETUP, abs_setup)

        setup = struct.pack("<HHHH80sI", 0x03, 0x0DB0, product_id, 1, name.encode("utf-8"), 0)
        fcntl.ioctl(self.fd, UI_DEV_SETUP, setup)
        fcntl.ioctl(self.fd, UI_DEV_CREATE)

    def emit(self, ev_type: int, code: int, val: int) -> None:
        os.write(self.fd, EVENT_STRUCT.pack(0, 0, ev_type, code, int(val)))

    def syn(self) -> None:
        self.emit(EV_SYN, SYN_REPORT, 0)

    def key(self, code: int, val: int) -> None:
        self.emit(EV_KEY, code, val)
        self.syn()

    def tap_key(self, code: int) -> None:
        self.emit(EV_KEY, code, 1)
        self.syn()
        time.sleep(0.015)
        self.emit(EV_KEY, code, 0)
        self.syn()

    def tap_combo(self, modifiers: Sequence[int], key_code: int) -> None:
        for m in modifiers:
            self.emit(EV_KEY, m, 1)
        self.syn()
        time.sleep(0.015)
        self.emit(EV_KEY, key_code, 1)
        self.syn()
        time.sleep(0.02)
        self.emit(EV_KEY, key_code, 0)
        for m in reversed(modifiers):
            self.emit(EV_KEY, m, 0)
        self.syn()

    def close(self) -> None:
        if self.fd is not None:
            try:
                fcntl.ioctl(self.fd, UI_DEV_DESTROY)
            except OSError:
                pass
            try:
                os.close(self.fd)
            except OSError:
                pass
            self.fd = None
