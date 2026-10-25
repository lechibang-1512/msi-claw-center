#!/usr/bin/env python3
"""
MSI Claw A1M Controller & Button Daemon for Fedora Linux (GNOME Wayland)
Maps all built-in controller buttons, triggers, D-pad, thumbsticks, and MSI Face Buttons
(F15 Quick Settings & F16 MSI Center M) to control the Fedora desktop, with instant
switching between Desktop Control Mode and Gamepad Mode.
"""

import ctypes
import errno
import fcntl
import glob
import json
import math
import os
import select
import signal
import socket
import struct
import subprocess
import sys
import threading
import time

try:
    from gi.repository import Gio, GLib
except Exception:
    Gio = None
    GLib = None

# Linux inotify constants (sys/inotify.h)
IN_CLOSE_WRITE = 0x08
IN_MOVED_TO = 0x80
IN_CREATE = 0x100

libc = ctypes.CDLL("libc.so.6", use_errno=True)
libc.inotify_init1.argtypes = [ctypes.c_int]
libc.inotify_init1.restype = ctypes.c_int
libc.inotify_add_watch.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_uint32]
libc.inotify_add_watch.restype = ctypes.c_int

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
KEY_ENTER = 28
KEY_LEFTCTRL = 29
KEY_LEFTSHIFT = 42
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

CLAW_PIDS = ("00001901", "00001902", "00001903", "00001904")
CLAW_READ_MODE = bytes([0x0F, 0x00, 0x00, 0x3C, 0x26]).ljust(64, b"\x00")

EVENT_STRUCT = struct.Struct("<qqHHi")


class UInputDevice:
    def __init__(self, name, product_id, ev_bits, key_bits=(), rel_bits=(), abs_axes=(), prop_bits=()):
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

    def emit(self, ev_type, code, val):
        os.write(self.fd, EVENT_STRUCT.pack(0, 0, ev_type, code, int(val)))

    def syn(self):
        self.emit(EV_SYN, SYN_REPORT, 0)

    def key(self, code, val):
        self.emit(EV_KEY, code, val)
        self.syn()

    def tap_key(self, code):
        self.emit(EV_KEY, code, 1)
        self.syn()
        time.sleep(0.015)
        self.emit(EV_KEY, code, 0)
        self.syn()

    def tap_combo(self, modifiers, key_code):
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

    def close(self):
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


class MSIClawDaemon:
    def __init__(self):
        self.running = True
        self.mode = "desktop"  # "desktop" or "gamepad"
        self.osk_open = False
        self.last_right_face_time = 0.0

        # Virtual Mouse
        self.vmouse = UInputDevice(
            name="MSI Claw Virtual Mouse",
            product_id=0x1910,
            ev_bits=[EV_KEY, EV_REL],
            key_bits=[BTN_LEFT, BTN_RIGHT, BTN_MIDDLE, BTN_SIDE, BTN_EXTRA],
            rel_bits=[REL_X, REL_Y, REL_WHEEL, REL_HWHEEL, REL_WHEEL_HI_RES, REL_HWHEEL_HI_RES],
        )

        # Virtual Keyboard (include full 1..57 range so udev input_id sets ID_INPUT_KEYBOARD=1)
        vkbd_keys = sorted(
            set(range(1, 58)).union(
                {
                    KEY_F4, KEY_SYSRQ, KEY_UP, KEY_PAGEUP, KEY_LEFT, KEY_RIGHT, KEY_DOWN,
                    KEY_PAGEDOWN, KEY_MUTE, KEY_VOLUMEDOWN, KEY_VOLUMEUP, KEY_LEFTMETA,
                    KEY_BACK, KEY_FORWARD, KEY_F15, KEY_F16, KEY_BRIGHTNESSDOWN, KEY_BRIGHTNESSUP,
                }
            )
        )
        self.vkbd = UInputDevice(
            name="MSI Claw Virtual Keyboard",
            product_id=0x1911,
            ev_bits=[EV_KEY],
            key_bits=vkbd_keys,
        )

        # Virtual Touch (for tapping TouchUp's OSK button when extension D-Bus isn't loaded)
        self.vtouch = UInputDevice(
            name="MSI Claw Virtual Touch",
            product_id=0x1912,
            ev_bits=[EV_KEY, EV_ABS],
            key_bits=[BTN_TOUCH],
            abs_axes=[
                (ABS_X, 0, 1919),
                (ABS_Y, 0, 1079),
                (ABS_MT_POSITION_X, 0, 1919),
                (ABS_MT_POSITION_Y, 0, 1079),
                (ABS_MT_SLOT, 0, 9),
                (ABS_MT_TRACKING_ID, 0, 65535),
            ],
            prop_bits=[0x01],  # INPUT_PROP_DIRECT
        )

        # Controller state
        self.ctrl_fd = None
        self.ctrl_path = None
        self.grabbed = False

        self.lx = 0
        self.ly = 0
        self.rx = 0
        self.ry = 0
        self.lt = 0
        self.rt = 0
        self.hat_x = 0
        self.hat_y = 0

        self.rem_x = 0.0
        self.rem_y = 0.0
        self.scroll_rem_x = 0.0
        self.scroll_rem_y = 0.0
        self.scroll_detent_x = 0
        self.scroll_detent_y = 0

        self.rt_clicked = False
        self.view_held = False
        self.view_pressed_at = 0.0
        self.view_used_as_chord = False
        self.menu_held = False
        self.menu_used_as_chord = False
        self.alt_tab_active = False

        # Cached session D-Bus connection (safe fallback if bus isn't ready yet)
        self.bus = None
        self._get_bus()

        # Self-pipe so SIGUSR1 / SIGUSR2 / SIGTERM / SIGINT wake select(..., None) immediately
        self.sig_r, self.sig_w = os.pipe2(os.O_NONBLOCK | os.O_CLOEXEC)
        # Wake pipe for org.freedesktop.login1.Manager PrepareForSleep (b'S' = sleep, b'W' = wake)
        self.wake_r, self.wake_w = os.pipe2(os.O_NONBLOCK | os.O_CLOEXEC)

        self.mcu_det_fds = {}   # fd -> path (0db0:1901 Interface 2 kbd/mouse, EVIOCGRAB=1)
        self.face_fds = {}      # fd -> (path, name) (event4 AT kbd & event13 MSI WMI, passive)
        self.has_atkbd_face = False
        self.denied_aux_paths = set()
        self.last_mcu_xinput_time = 0.0
        self.last_left_face_time = 0.0
        self.wake_deadlines = []
        self.wake_mcu_pending = False

        # Command file & inotify watch in XDG_RUNTIME_DIR
        runtime_dir = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
        self.cmd_file = os.path.join(runtime_dir, "msi-claw-cmd")
        self.state_file = f"/dev/shm/msi-claw-mode-{os.getuid()}"
        self.dock_state_file = f"/dev/shm/msi-claw-dock-{os.getuid()}"
        self.is_docked = None
        self.dock_label = "handheld"
        self.dock_check_deadline = 0.0
        self.uevent_sock = None
        try:
            usock = socket.socket(socket.AF_NETLINK, socket.SOCK_DGRAM | socket.SOCK_NONBLOCK | socket.SOCK_CLOEXEC, 15)
            usock.bind((0, 1))
            self.uevent_sock = usock
        except OSError:
            self.uevent_sock = None
        try:
            if os.path.exists(self.state_file):
                saved = open(self.state_file).read().strip()
                if saved in ("desktop", "gamepad"):
                    self.mode = saved
        except OSError:
            pass
        self._write_mode_state()
        self.inotify_fd = None
        self.inotify_wd = None
        ifd = libc.inotify_init1(os.O_NONBLOCK | os.O_CLOEXEC)
        if ifd >= 0:
            wd = libc.inotify_add_watch(
                ifd,
                os.fsencode(runtime_dir),
                IN_CLOSE_WRITE | IN_MOVED_TO | IN_CREATE,
            )
            if wd >= 0:
                self.inotify_fd = ifd
                self.inotify_wd = wd
            else:
                os.close(ifd)

        self._start_sleep_monitor()

    def _start_sleep_monitor(self):
        if Gio is None or GLib is None:
            return

        def _worker():
            ctx = GLib.MainContext.new()
            ctx.push_thread_default()
            try:
                sys_bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)

                def _on_prepare_for_sleep(_conn, _sender, _path, _iface, _sig, params):
                    about_to_suspend = bool(params.unpack()[0])
                    if self.wake_w is not None:
                        try:
                            os.write(self.wake_w, b"S" if about_to_suspend else b"W")
                        except OSError:
                            pass

                sys_bus.signal_subscribe(
                    "org.freedesktop.login1",
                    "org.freedesktop.login1.Manager",
                    "PrepareForSleep",
                    "/org/freedesktop/login1",
                    None,
                    Gio.DBusSignalFlags.NONE,
                    _on_prepare_for_sleep,
                )
                loop = GLib.MainLoop.new(ctx, False)
                loop.run()
            except Exception as e:
                print(f"PrepareForSleep monitor unavailable: {e}", flush=True)
            finally:
                ctx.pop_thread_default()

        t = threading.Thread(target=_worker, name="claw-sleep-monitor", daemon=True)
        t.start()

    def _find_claw_hidraw(self):
        for sys_dir in sorted(glob.glob("/sys/class/hidraw/hidraw*")):
            try:
                ue = open(os.path.join(sys_dir, "device/uevent")).read().upper()
            except OSError:
                continue
            if "0DB0:" not in ue or not any(p in ue for p in CLAW_PIDS):
                continue
            try:
                rdesc = open(os.path.join(sys_dir, "device/report_descriptor"), "rb").read(4)
                if rdesc.startswith(b"\x06\xa0\xff"):
                    return "/dev/" + os.path.basename(sys_dir)
            except OSError:
                pass
            real_dev = os.path.realpath(os.path.join(sys_dir, "device"))
            if "/INPUT1\n" in ue or ":1.1/" in real_dev or real_dev.endswith(":1.1"):
                return "/dev/" + os.path.basename(sys_dir)
        return None

    def ensure_mcu_xinput(self, force=False):
        now = time.monotonic()
        if not force and (now - self.last_mcu_xinput_time) < 1.0:
            return False
        self.last_mcu_xinput_time = now
        dev_path = self._find_claw_hidraw()
        if not dev_path or not os.access(dev_path, os.R_OK | os.W_OK):
            return False
        try:
            fd = os.open(dev_path, os.O_RDWR | os.O_NONBLOCK)
        except OSError:
            return False
        try:
            while select.select([fd], [], [], 0.002)[0]:
                if not os.read(fd, 64):
                    break
            # Query current MCU mode first (0x26 -> 0x27 ACK); ONLY switch if not already XINPUT (0x01)!
            os.write(fd, CLAW_READ_MODE)
            cur_mode = None
            mkeys_fn = 0x00
            if select.select([fd], [], [], 0.06)[0]:
                resp = os.read(fd, 64)
                if len(resp) >= 7 and resp[3] == 0x3C and resp[4] == 0x27:
                    cur_mode = resp[5]
                    mkeys_fn = resp[6] if resp[6] < 3 else 0x00
            if cur_mode == 0x01:
                return True
            pkt = bytes([0x0F, 0x00, 0x00, 0x3C, 0x24, 0x01, mkeys_fn]).ljust(64, b"\x00")
            os.write(fd, pkt)
            if select.select([fd], [], [], 0.06)[0]:
                os.read(fd, 64)
            print(f"Switched MCU from mode {cur_mode} back to XINPUT (0x01)", flush=True)
            return True
        except OSError:
            return False
        finally:
            try:
                os.close(fd)
            except OSError:
                pass

    def sync_face_keybindings(self):
        # When event4 (AT Translated Set 2 keyboard) is passively monitored in evdev,
        # unbind custom0/custom1 so gsd-media-keys neither double-fires nor fails grab.
        # Otherwise bind XF86Launch7 (KEY_F16) and XF86Launch6 (KEY_F15), which pc105+inet produces.
        left_bind = "" if self.has_atkbd_face else "XF86Launch7"
        right_bind = "" if self.has_atkbd_face else "XF86Launch6"
        if Gio is not None:
            try:
                s0 = Gio.Settings.new_with_path(
                    "org.gnome.settings-daemon.plugins.media-keys.custom-keybinding",
                    "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/custom0/",
                )
                s1 = Gio.Settings.new_with_path(
                    "org.gnome.settings-daemon.plugins.media-keys.custom-keybinding",
                    "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/custom1/",
                )
                if s0.get_string("binding") != left_bind:
                    s0.set_string("binding", left_bind)
                if s1.get_string("binding") != right_bind:
                    s1.set_string("binding", right_bind)
                Gio.Settings.sync()
                return
            except Exception:
                pass
        for idx, bind in (("custom0", left_bind), ("custom1", right_bind)):
            subprocess.run(
                [
                    "gsettings", "set",
                    f"org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/{idx}/",
                    "binding", f"'{bind}'",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

    def open_aux_devices(self):
        open_mcu_paths = set(self.mcu_det_fds.values())
        open_face_paths = {v[0] for v in self.face_fds.values()}

        for sys_path in sorted(glob.glob("/sys/class/input/event*")):
            name_file = os.path.join(sys_path, "device/name")
            if not os.path.exists(name_file):
                continue
            try:
                name = open(name_file).read().strip()
            except OSError:
                continue
            dev_path = "/dev/input/" + os.path.basename(sys_path)
            if not os.access(dev_path, os.R_OK):
                if "Xbox360 Controller for Windows" in name and dev_path not in self.denied_aux_paths:
                    self.denied_aux_paths.add(dev_path)
                    print(f"No read access to {dev_path} ({name}); check uaccess udev rule order", flush=True)
                continue

            # 0db0:1901 Interface 2 Keyboard & Mouse: grab permanently to block MCU 0x04 desktop leaks
            if "Xbox360 Controller for Windows" in name and ("Keyboard" in name or "Mouse" in name):
                if dev_path not in open_mcu_paths:
                    try:
                        fd = os.open(dev_path, os.O_RDONLY | os.O_NONBLOCK)
                        try:
                            fcntl.ioctl(fd, EVIOCGRAB, 1)
                        except OSError:
                            pass
                        self.mcu_det_fds[fd] = dev_path
                        print(f"Grabbed MCU auxiliary interface {dev_path} ({name})", flush=True)
                    except OSError:
                        pass

            # Front system buttons F15/F16 on i8042 AT keyboard & MSI WMI hotkeys (passive read, NO grab!)
            elif name in ("AT Translated Set 2 keyboard", "MSI WMI hotkeys"):
                if dev_path not in open_face_paths:
                    try:
                        fd = os.open(dev_path, os.O_RDONLY | os.O_NONBLOCK)
                        self.face_fds[fd] = (dev_path, name)
                        print(f"Monitoring front buttons passively on {dev_path} ({name})", flush=True)
                    except OSError:
                        pass

        self.has_atkbd_face = any(v[1] == "AT Translated Set 2 keyboard" for v in self.face_fds.values())
        self.sync_face_keybindings()

    def close_aux_devices(self):
        for fd in list(self.mcu_det_fds.keys()):
            try:
                fcntl.ioctl(fd, EVIOCGRAB, 0)
            except OSError:
                pass
            try:
                os.close(fd)
            except OSError:
                pass
        self.mcu_det_fds.clear()
        for fd in list(self.face_fds.keys()):
            try:
                os.close(fd)
            except OSError:
                pass
        self.face_fds.clear()
        self.has_atkbd_face = False

    def wake_display_and_lockscreen(self):
        # 1. Zero-net pointer micro-nudge resets Mutter / KWin IdleMonitor to 0ms and lifts lockscreen
        try:
            self.vmouse.emit(EV_REL, REL_X, 1)
            self.vmouse.syn()
            self.vmouse.emit(EV_REL, REL_X, -1)
            self.vmouse.syn()
        except OSError:
            pass

        # 2. KDE Plasma DPMS wake
        if os.path.exists("/usr/bin/kscreen-doctor"):
            try:
                subprocess.Popen(["kscreen-doctor", "--dpms", "on"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception:
                pass

        # 3. Ensure Mutter DPMS PowerSaveMode is ON (0) so post-suspend blanking never leaves panel dark
        if GLib is not None:
            try:
                bus = self._get_bus()
                if bus is not None:
                    bus.call_sync(
                        "org.gnome.Mutter.DisplayConfig",
                        "/org/gnome/Mutter/DisplayConfig",
                        "org.freedesktop.DBus.Properties",
                        "Set",
                        GLib.Variant(
                            "(ssv)",
                            ("org.gnome.Mutter.DisplayConfig", "PowerSaveMode", GLib.Variant("i", 0)),
                        ),
                        None,
                        Gio.DBusCallFlags.NONE,
                        400,
                        None,
                    )
            except Exception:
                pass

    def find_controller(self):
        for sys_path in sorted(glob.glob("/sys/class/input/event*")):
            name_file = os.path.join(sys_path, "device/name")
            if not os.path.exists(name_file):
                continue
            try:
                name = open(name_file).read().strip()
            except OSError:
                continue
            if "Xbox360 Controller for Windows" in name and "Keyboard" not in name and "Mouse" not in name:
                dev_path = "/dev/input/" + os.path.basename(sys_path)
                if os.access(dev_path, os.R_OK):
                    return dev_path
        return None

    def open_controller(self):
        path = self.find_controller()
        if not path:
            return False
        try:
            self.ctrl_fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
            self.ctrl_path = path
            self.update_grab()
            print(f"Connected to MSI Claw controller at {path} (mode={self.mode})", flush=True)
            return True
        except OSError as e:
            print(f"Failed to open {path}: {e}", flush=True)
            self.ctrl_fd = None
            return False

    def close_controller(self):
        if self.ctrl_fd is not None:
            if self.grabbed:
                try:
                    fcntl.ioctl(self.ctrl_fd, EVIOCGRAB, 0)
                except OSError:
                    pass
                self.grabbed = False
            try:
                os.close(self.ctrl_fd)
            except OSError:
                pass
            self.ctrl_fd = None
            self.ctrl_path = None
        self.release_all()

    def release_all(self):
        # Release every virtual button/key we may be holding and reset analog/chord state
        for btn in (BTN_LEFT, BTN_RIGHT, BTN_MIDDLE):
            self.vmouse.key(btn, 0)
        for k in (KEY_LEFT, KEY_RIGHT, KEY_UP, KEY_DOWN, KEY_BACKSPACE, KEY_LEFTALT):
            self.vkbd.key(k, 0)
        self.alt_tab_active = False
        self.rt_clicked = False
        self.lx = self.ly = self.rx = self.ry = 0
        self.lt = self.rt = 0
        self.hat_x = self.hat_y = 0

    def update_grab(self):
        if self.ctrl_fd is None:
            return
        want_grab = (self.mode == "desktop")
        if want_grab and not self.grabbed:
            try:
                fcntl.ioctl(self.ctrl_fd, EVIOCGRAB, 1)
                self.grabbed = True
            except OSError:
                pass
        elif not want_grab and self.grabbed:
            try:
                fcntl.ioctl(self.ctrl_fd, EVIOCGRAB, 0)
            except OSError:
                pass
            self.grabbed = False

    def _get_bus(self):
        if self.bus is not None and not self.bus.is_closed():
            return self.bus
        self.bus = None
        if Gio is None:
            return None
        try:
            self.bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        except Exception:
            self.bus = None
        return self.bus

    def _call_claw(self, method, params=None):
        bus = self._get_bus()
        if bus is None:
            raise RuntimeError("Session D-Bus unavailable")
        return bus.call_sync(
            "org.gnome.Shell",
            "/org/gnome/Shell/Extensions/ClawControls",
            "org.gnome.Shell.Extensions.ClawControls",
            method,
            params,
            None,
            Gio.DBusCallFlags.NONE,
            500,
            None,
        )

    def notify_user(self, title, body, icon="input-gaming-symbolic"):
        if GLib is not None:
            try:
                self._call_claw("ShowOSD", GLib.Variant("(ss)", (icon, f"{title}: {body}")))
            except Exception:
                pass
            try:
                bus = self._get_bus()
                if bus is not None:
                    bus.call_sync(
                        "org.freedesktop.Notifications",
                        "/org/freedesktop/Notifications",
                        "org.freedesktop.Notifications",
                        "Notify",
                        GLib.Variant(
                            "(susssasa{sv}i)",
                            (
                                "MSI Claw Controls",
                                0,
                                icon,
                                title,
                                body,
                                [],
                                {"x-canonical-private-synchronous": GLib.Variant("s", "msi-claw-mode")},
                                2000,
                            ),
                        ),
                        None,
                        Gio.DBusCallFlags.NONE,
                        500,
                        None,
                    )
            except Exception:
                pass

    def toggle_mode(self):
        # Release any held mouse buttons or keys before switching
        self.release_all()

        if self.mode == "desktop":
            self.mode = "gamepad"
            self.update_grab()
            self.notify_user("MSI Claw Mode", "Gamepad Mode (Xbox Controller Active)", "input-gaming-symbolic")
        else:
            self.mode = "desktop"
            self.update_grab()
            self.notify_user("MSI Claw Mode", "Desktop Control Mode (Mouse & Keyboard Active)", "input-mouse-symbolic")

        if GLib is not None:
            try:
                self._call_claw("SetControllerMode", GLib.Variant("(s)", (self.mode,)))
            except Exception:
                pass
        self._write_mode_state()
        print(f"Switched controller mode to: {self.mode}", flush=True)

    def _write_mode_state(self):
        try:
            with open(self.state_file, "w") as sf:
                sf.write(self.mode + "\n")
        except OSError:
            pass

    def toggle_osk(self):
        # 1. Try KWin VirtualKeyboard (KDE Plasma Wayland)
        bus = self._get_bus()
        if bus is not None:
            try:
                res = bus.call_sync(
                    "org.kde.KWin",
                    "/VirtualKeyboard",
                    "org.freedesktop.DBus.Properties",
                    "Get",
                    GLib.Variant("(ss)", ("org.kde.kwin.VirtualKeyboard", "visible")),
                    None,
                    Gio.DBusCallFlags.NONE,
                    200,
                    None,
                )
                is_visible = bool(res.unpack()[0])
                if is_visible:
                    bus.call_sync(
                        "org.kde.KWin",
                        "/VirtualKeyboard",
                        "org.freedesktop.DBus.Properties",
                        "Set",
                        GLib.Variant("(ssv)", ("org.kde.kwin.VirtualKeyboard", "active", GLib.Variant("b", False))),
                        None,
                        Gio.DBusCallFlags.NONE,
                        200,
                        None,
                    )
                else:
                    bus.call_sync(
                        "org.kde.KWin",
                        "/VirtualKeyboard",
                        "org.kde.kwin.VirtualKeyboard",
                        "forceActivate",
                        None,
                        None,
                        Gio.DBusCallFlags.NONE,
                        200,
                        None,
                    )
                return
            except Exception:
                pass

            # 2. Try ClawControls extension D-Bus if loaded (GNOME Shell)
            try:
                self._call_claw("ToggleOSK")
                return
            except Exception:
                pass

        # Fallback for GNOME live session: use Virtual Touch tap on TouchUp's bottom-left OSK button to open,
        # or cycle screen-keyboard-enabled to close cleanly without moving the mouse cursor
        if not self.osk_open:
            x, y = 28, 1060
            self.vtouch.emit(EV_ABS, ABS_MT_SLOT, 0)
            self.vtouch.emit(EV_ABS, ABS_MT_TRACKING_ID, 1)
            self.vtouch.emit(EV_ABS, ABS_MT_POSITION_X, x)
            self.vtouch.emit(EV_ABS, ABS_MT_POSITION_Y, y)
            self.vtouch.emit(EV_ABS, ABS_X, x)
            self.vtouch.emit(EV_ABS, ABS_Y, y)
            self.vtouch.emit(EV_KEY, BTN_TOUCH, 1)
            self.vtouch.syn()
            time.sleep(0.05)
            self.vtouch.emit(EV_ABS, ABS_MT_TRACKING_ID, -1)
            self.vtouch.emit(EV_KEY, BTN_TOUCH, 0)
            self.vtouch.syn()
            self.osk_open = True
        else:
            subprocess.run(
                ["gsettings", "set", "org.gnome.desktop.a11y.applications", "screen-keyboard-enabled", "false"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            time.sleep(0.05)
            subprocess.run(
                ["gsettings", "set", "org.gnome.desktop.a11y.applications", "screen-keyboard-enabled", "true"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self.osk_open = False

    def toggle_center(self):
        try:
            bus = self._get_bus()
            if bus is not None:
                try:
                    bus.call_sync(
                        "io.msiclaw.Center",
                        "/io/msiclaw/Center",
                        "org.gtk.Actions",
                        "Activate",
                        GLib.Variant("(sava{sv})", ("toggle", [], {})),
                        None,
                        Gio.DBusCallFlags.NONE,
                        250,
                        None,
                    )
                    return
                except Exception:
                    pass
            subprocess.Popen(
                [os.path.expanduser("~/.local/bin/msi-claw-center"), "--toggle"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except Exception as e:
            print(f"Error toggling MSI Claw Center: {e}", flush=True)

    def toggle_overview(self):
        bus = self._get_bus()
        if bus is not None:
            # 1. Try KWin Overview (KDE Plasma)
            try:
                bus.call_sync(
                    "org.kde.kglobalaccel",
                    "/component/kwin",
                    "org.kde.kglobalaccel.Component",
                    "invokeShortcut",
                    GLib.Variant("(s)", ("Overview",)),
                    None,
                    Gio.DBusCallFlags.NONE,
                    200,
                    None,
                )
                return
            except Exception:
                pass

            # 2. Try GNOME Shell Overview / App Grid
            try:
                res = bus.call_sync(
                    "org.gnome.Shell",
                    "/org/gnome/Shell",
                    "org.freedesktop.DBus.Properties",
                    "Get",
                    GLib.Variant("(ss)", ("org.gnome.Shell", "OverviewActive")),
                    None,
                    Gio.DBusCallFlags.NONE,
                    300,
                    None,
                )
                is_active = bool(res.unpack()[0])
                if is_active:
                    self._call_claw("ToggleOverview")
                    return
                self._call_claw("ShowApps")
                return
            except Exception:
                pass

        self.vkbd.tap_key(KEY_LEFTMETA)

    def toggle_quick_settings(self):
        bus = self._get_bus()
        if bus is not None:
            # 1. Try GNOME Shell ClawControls first
            try:
                self._call_claw("ToggleQuickSettings")
                return
            except Exception:
                pass

            # 2. Try KDE Plasma System Tray (Quick Settings)
            for action in ("activate widget 7", "activate widget 8"):
                try:
                    bus.call_sync(
                        "org.kde.kglobalaccel",
                        "/component/plasmashell",
                        "org.kde.kglobalaccel.Component",
                        "invokeShortcut",
                        GLib.Variant("(s)", (action,)),
                        None,
                        Gio.DBusCallFlags.NONE,
                        200,
                        None,
                    )
                    return
                except Exception:
                    pass

        # 3. Fallback: toggle MSI Claw Center overlay
        self.toggle_center()

    def _drain_inotify(self):
        saw_complete = False
        if self.inotify_fd is None:
            return saw_complete
        while True:
            try:
                data = os.read(self.inotify_fd, 4096)
                if not data:
                    break
                offset = 0
                n = len(data)
                while offset + 16 <= n:
                    _, mask, _, name_len = struct.unpack_from("<iIII", data, offset)
                    raw_name = data[offset + 16 : offset + 16 + name_len].rstrip(b"\x00")
                    if raw_name == b"msi-claw-cmd" and (mask & (IN_CLOSE_WRITE | IN_MOVED_TO)):
                        saw_complete = True
                    offset += 16 + name_len
            except OSError as e:
                if e.errno in (errno.EAGAIN, errno.EWOULDBLOCK, errno.EINTR):
                    break
                break
        return saw_complete

    def handle_external_cmd(self, unlink_empty=False):
        if not os.path.exists(self.cmd_file):
            return
        try:
            with open(self.cmd_file, "r") as f:
                cmd = f.read().strip()
            if not cmd and not unlink_empty:
                return
            # Claim by rename so a command that lands between our read and unlink isn't deleted unread
            claim = self.cmd_file + ".claimed"
            os.rename(self.cmd_file, claim)
            with open(claim, "r") as f:
                cmd = f.read().strip()
            os.unlink(claim)
        except OSError:
            return

        if cmd == "toggle" or cmd == "toggle-mode":
            self.toggle_mode()
        elif cmd == "mode-desktop":
            if self.mode != "desktop":
                self.toggle_mode()
        elif cmd == "mode-gamepad":
            if self.mode != "gamepad":
                self.toggle_mode()
        elif cmd == "toggle-osk":
            self.toggle_osk()
        elif cmd in ("center", "toggle-center", "left-face"):
            now = time.monotonic()
            if (now - self.last_left_face_time) >= 0.18:
                self.last_left_face_time = now
                self.toggle_center()
        elif cmd in ("overview", "toggle-overview"):
            now = time.monotonic()
            if (now - self.last_left_face_time) >= 0.18:
                self.last_left_face_time = now
                self.toggle_overview()
        elif cmd == "right-face" or cmd == "quick-settings":
            now = time.monotonic()
            if (now - self.last_right_face_time) >= 0.18:
                self.last_right_face_time = now
                self.toggle_quick_settings()
        elif cmd == "recheck-devices":
            self.ensure_mcu_xinput(force=True)
            self.open_aux_devices()
            self.sync_dock_state(notify=False)
        elif cmd == "sync-dock":
            self.sync_dock_state(notify=True)
        elif cmd == "wake-display":
            self.wake_display_and_lockscreen()

    def _detect_dock_state(self):
        ext_outputs = []
        for st_path in sorted(glob.glob("/sys/class/drm/card*-*/status")):
            conn_dir = os.path.basename(os.path.dirname(st_path))
            # Strip cardX- prefix -> e.g. DP-1, HDMI-A-1, eDP-1
            parts = conn_dir.split("-", 1)
            conn_name = parts[1] if len(parts) == 2 else conn_dir
            if conn_name.startswith("eDP"):
                continue
            try:
                if open(st_path).read().strip() == "connected":
                    ext_outputs.append(conn_name)
            except OSError:
                pass

        has_ext_kbd = False
        has_ext_mouse = False
        internal_vids = {"0db0", "27c6", "0603", "8087", "0000", "0001", "001f"}
        for ev_path in sorted(glob.glob("/sys/class/input/event*")):
            dev_dir = os.path.join(ev_path, "device")
            try:
                bus_id = open(os.path.join(dev_dir, "id/bustype")).read().strip().lower()
                vid = open(os.path.join(dev_dir, "id/vendor")).read().strip().lower()
                name = open(os.path.join(dev_dir, "name")).read().strip()
            except OSError:
                continue
            # Only consider external USB (0003) or Bluetooth (0005) HID peripherals
            if bus_id not in ("0003", "0005") or vid in internal_vids:
                continue
            nl = name.lower()
            if "mouse" in nl:
                has_ext_mouse = True
            elif "consumer control" not in nl and "system control" not in nl:
                try:
                    key_cap = open(os.path.join(dev_dir, "capabilities/key")).read().strip().split()
                    if key_cap and key_cap[-1] != "0":
                        has_ext_kbd = True
                except OSError:
                    pass

        docked = bool(ext_outputs) or has_ext_kbd or has_ext_mouse
        if ext_outputs:
            detail = "+".join(ext_outputs)
        elif has_ext_kbd or has_ext_mouse:
            detail = "USB"
        else:
            detail = "handheld"
        return docked, detail, has_ext_kbd

    def _apply_rgb(self, r, g, b, brightness):
        dev_path = self._find_claw_hidraw()
        if not dev_path or not os.access(dev_path, os.R_OK | os.W_OK):
            return False
        addr = 0x024A
        try:
            sys_dir = "/sys/class/hidraw/" + os.path.basename(dev_path)
            d = os.path.realpath(os.path.join(sys_dir, "device"))
            while d != "/" and not os.path.exists(os.path.join(d, "bcdDevice")):
                d = os.path.dirname(d)
            bcd_file = os.path.join(d, "bcdDevice")
            if os.path.exists(bcd_file):
                bcd = int(open(bcd_file).read().strip(), 16)
                major, minor = bcd >> 8, bcd & 0xFF
                if not ((major == 1 and minor >= 0x66) or (major == 2 and minor >= 0x17) or major >= 3):
                    addr = 0x01FA
        except Exception:
            pass
        try:
            fd = os.open(dev_path, os.O_RDWR | os.O_NONBLOCK)
        except OSError:
            return False
        try:
            while select.select([fd], [], [], 0.002)[0]:
                if not os.read(fd, 64):
                    break
            br = max(0, min(100, int(brightness)))
            rc, gc, bc = (max(0, min(255, int(v))) for v in (r, g, b))
            body = bytes([0x01, addr >> 8, addr & 0xFF, 0x24, 0x00, 1, 0x09, 0, br])
            pkt = (bytes([0x0F, 0, 0, 0x3C, 0x21]) + body + bytes([rc, gc, bc]) * 9).ljust(64, b"\x00")
            os.write(fd, pkt)
            if select.select([fd], [], [], 0.04)[0]:
                while select.select([fd], [], [], 0.002)[0]:
                    if not os.read(fd, 64):
                        break
            return True
        except OSError:
            return False
        finally:
            try:
                os.close(fd)
            except OSError:
                pass

    def _sync_dock_rgb(self, docked):
        if docked:
            self._apply_rgb(0, 0, 0, 0)
            return
        r, g, b, br = 0, 170, 255, 15
        cfg_file = os.path.expanduser("~/.config/msi-claw-rgb.json")
        if os.path.exists(cfg_file):
            try:
                cfg = json.loads(open(cfg_file).read())
                r = int(cfg.get("r", 0))
                g = int(cfg.get("g", 170))
                b = int(cfg.get("b", 255))
                br = int(cfg.get("brightness", 15))
            except Exception:
                pass
        self._apply_rgb(r, g, b, br)

    def sync_dock_state(self, notify=True, force_rgb=False):
        docked, detail, has_ext_kbd = self._detect_dock_state()
        state_str = f"docked:{detail}" if docked else "handheld"
        prev = self.is_docked
        self.is_docked = docked
        self.dock_label = state_str
        try:
            with open(self.dock_state_file, "w") as df:
                df.write(state_str + "\n")
        except OSError:
            pass

        if prev == docked:
            if force_rgb:
                self._sync_dock_rgb(docked)
            return

        # 0. Auto-toggle Controller RGB: Off (0W) when docked, restore handheld preset on undock
        self._sync_dock_rgb(docked)

        # 1. KDE Plasma Wayland: switch KWin VirtualKeyboard mode
        #    mode=0 (Touch Only) when docked so physical mouse clicks never pop up OSK on external monitor;
        #    mode=2 (Touch, Tablet & Mouse) when handheld so thumbstick clicks auto-open OSK in text fields.
        target_vk_mode = 0 if docked else 2
        bus = self._get_bus()
        if bus is not None and GLib is not None:
            try:
                if docked:
                    bus.call_sync(
                        "org.kde.KWin",
                        "/VirtualKeyboard",
                        "org.freedesktop.DBus.Properties",
                        "Set",
                        GLib.Variant("(ssv)", ("org.kde.kwin.VirtualKeyboard", "active", GLib.Variant("b", False))),
                        None,
                        Gio.DBusCallFlags.NONE,
                        200,
                        None,
                    )
                bus.call_sync(
                    "org.kde.KWin",
                    "/VirtualKeyboard",
                    "org.freedesktop.DBus.Properties",
                    "Set",
                    GLib.Variant("(ssv)", ("org.kde.kwin.VirtualKeyboard", "mode", GLib.Variant("i", target_vk_mode))),
                    None,
                    Gio.DBusCallFlags.NONE,
                    200,
                    None,
                )
            except Exception:
                pass

        if os.path.exists("/usr/bin/kwriteconfig6"):
            subprocess.Popen(
                ["/usr/bin/kwriteconfig6", "--file", "kwinrc", "--group", "Wayland", "--key", "VirtualKeyboardMode", str(target_vk_mode)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

        # 2. GNOME Shell: disable auto accessibility OSK when an external keyboard is docked; restore on undock
        if Gio is not None:
            try:
                a11y = Gio.Settings.new("org.gnome.desktop.a11y.applications")
                want_osk = not (docked and has_ext_kbd)
                if a11y.get_boolean("screen-keyboard-enabled") != want_osk:
                    a11y.set_boolean("screen-keyboard-enabled", want_osk)
            except Exception:
                pass

        print(f"Dock state -> {state_str} (KWin VirtualKeyboardMode={target_vk_mode})", flush=True)
        if notify and prev is not None:
            if docked:
                self.notify_user(
                    "Docked / Mini-PC Mode",
                    f"Connected ({detail}) · RGB off & mouse OSK suppressed",
                    "video-display-symbolic",
                )
            else:
                self.notify_user(
                    "Handheld Mode",
                    "Undocked · RGB & thumbstick auto-OSK restored",
                    "input-gaming-symbolic",
                )

    def _drain_uevents(self):
        if self.uevent_sock is None:
            return False
        relevant = False
        while True:
            try:
                pkt = self.uevent_sock.recv(8192)
                if not pkt:
                    break
                if (
                    b"SUBSYSTEM=drm" in pkt
                    or b"SUBSYSTEM=usb" in pkt
                    or b"SUBSYSTEM=input" in pkt
                    or b"SUBSYSTEM=power_supply" in pkt
                ):
                    relevant = True
            except OSError as e:
                if e.errno in (errno.EAGAIN, errno.EWOULDBLOCK, errno.EINTR):
                    break
                break
        return relevant

    def handle_event(self, ev_type, code, val):
        # Always track View + Menu chord in both Desktop and Gamepad modes
        if ev_type == EV_KEY:
            if code == BTN_SELECT:
                self.view_held = (val == 1)
                if val == 1:
                    self.view_pressed_at = time.monotonic()
                    self.view_used_as_chord = False
                    if self.menu_held:
                        self.view_used_as_chord = True
                        self.menu_used_as_chord = True
                        self.toggle_mode()
                        return
                elif val == 0:
                    if self.alt_tab_active:
                        self.vkbd.key(KEY_LEFTALT, 0)
                        self.alt_tab_active = False
                    elif not self.view_used_as_chord and self.mode == "desktop":
                        self.vkbd.tap_key(KEY_ESC)
                return

            if code == BTN_START:
                self.menu_held = (val == 1)
                if val == 1:
                    self.menu_used_as_chord = False
                    if self.view_held:
                        self.view_used_as_chord = True
                        self.menu_used_as_chord = True
                        self.toggle_mode()
                        return
                elif val == 0:
                    if not self.menu_used_as_chord and self.mode == "desktop":
                        self.vkbd.tap_combo([KEY_LEFTALT], KEY_TAB)
                return

        if self.mode != "desktop":
            return

        if ev_type == EV_ABS:
            if code == ABS_X:
                self.lx = val
            elif code == ABS_Y:
                self.ly = val
            elif code == ABS_RX:
                self.rx = val
            elif code == ABS_RY:
                self.ry = val
            elif code == ABS_Z:
                self.lt = val
            elif code == ABS_RZ:
                self.rt = val
                if val > 120 and not self.rt_clicked:
                    self.rt_clicked = True
                    self.vmouse.key(BTN_LEFT, 1)
                elif val < 80 and self.rt_clicked:
                    self.rt_clicked = False
                    self.vmouse.key(BTN_LEFT, 0)
            elif code == ABS_HAT0X:
                # Always release the previous direction first, so a View chord can't strand an arrow key
                if val != self.hat_x and self.hat_x != 0:
                    self.vkbd.key(KEY_LEFT if self.hat_x < 0 else KEY_RIGHT, 0)
                if self.view_held and val != 0:
                    self.view_used_as_chord = True
                    self.vkbd.tap_key(KEY_BRIGHTNESSUP if val > 0 else KEY_BRIGHTNESSDOWN)
                    val = 0  # chord taps hold nothing
                elif val != 0 and val != self.hat_x:
                    self.vkbd.key(KEY_LEFT if val < 0 else KEY_RIGHT, 1)
                self.hat_x = val
            elif code == ABS_HAT0Y:
                if val != self.hat_y and self.hat_y != 0:
                    self.vkbd.key(KEY_UP if self.hat_y < 0 else KEY_DOWN, 0)
                if self.view_held and val != 0:
                    self.view_used_as_chord = True
                    self.vkbd.tap_key(KEY_VOLUMEUP if val < 0 else KEY_VOLUMEDOWN)
                    val = 0
                elif val != 0 and val != self.hat_y:
                    self.vkbd.key(KEY_UP if val < 0 else KEY_DOWN, 1)
                self.hat_y = val

        elif ev_type == EV_KEY:
            if code == BTN_SOUTH:  # A -> Left Click (or View+A -> Paste)
                if val == 0:
                    self.vmouse.key(BTN_LEFT, 0)  # release unconditionally: View may have been pressed mid-click
                elif self.view_held:
                    if val == 1:
                        self.view_used_as_chord = True
                        self.vkbd.tap_combo([KEY_LEFTCTRL], KEY_V)
                else:
                    self.vmouse.key(BTN_LEFT, val)

            elif code == BTN_EAST:  # B -> Right Click (or View+B -> Alt+F4 Close Window)
                if val == 0:
                    self.vmouse.key(BTN_RIGHT, 0)
                elif self.view_held:
                    if val == 1:
                        self.view_used_as_chord = True
                        self.vkbd.tap_combo([KEY_LEFTALT], KEY_F4)
                else:
                    self.vmouse.key(BTN_RIGHT, val)

            elif code == BTN_NORTH:  # X -> Toggle OSK (or View+X -> Copy)
                if val == 1:
                    if self.view_held:
                        self.view_used_as_chord = True
                        self.vkbd.tap_combo([KEY_LEFTCTRL], KEY_C)
                    else:
                        self.toggle_osk()

            elif code == BTN_WEST:  # Y -> Overview / Apps (or View+Y -> Screenshot)
                if val == 1:
                    if self.view_held:
                        self.view_used_as_chord = True
                        self.vkbd.tap_key(KEY_SYSRQ)
                    else:
                        self.toggle_overview()

            elif code == BTN_TL:  # LB -> Back (or View+LB -> Alt+Shift+Tab)
                if val == 1:
                    if self.view_held:
                        self.view_used_as_chord = True
                        if not self.alt_tab_active:
                            self.vkbd.key(KEY_LEFTALT, 1)
                            self.alt_tab_active = True
                        self.vkbd.tap_combo([KEY_LEFTSHIFT], KEY_TAB)
                    else:
                        self.vkbd.tap_combo([KEY_LEFTALT], KEY_LEFT)

            elif code == BTN_TR:  # RB -> Forward (or View+RB -> Alt+Tab)
                if val == 1:
                    if self.view_held:
                        self.view_used_as_chord = True
                        if not self.alt_tab_active:
                            self.vkbd.key(KEY_LEFTALT, 1)
                            self.alt_tab_active = True
                        self.vkbd.tap_key(KEY_TAB)
                    else:
                        self.vkbd.tap_combo([KEY_LEFTALT], KEY_RIGHT)

            elif code == BTN_THUMBL:  # L3 -> Middle Click
                self.vmouse.key(BTN_MIDDLE, val)

            elif code == BTN_THUMBR:  # R3 -> Backspace
                self.vkbd.key(KEY_BACKSPACE, val)

            elif code == BTN_MODE:  # Guide -> Overview
                if val == 1:
                    self.toggle_overview()

    @staticmethod
    def _apply_deadzone(val, deadzone=3600, max_val=32767):
        if abs(val) <= deadzone:
            return 0.0
        sign = 1.0 if val > 0 else -1.0
        norm = (abs(val) - deadzone) / float(max_val - deadzone)
        return sign * min(1.0, norm)

    def tick_analog(self, dt):
        if self.mode != "desktop":
            return

        # Left Stick -> Mouse Cursor Movement
        nx = self._apply_deadzone(self.lx)
        ny = self._apply_deadzone(self.ly)
        if nx != 0.0 or ny != 0.0:
            mag = min(1.0, math.hypot(nx, ny))
            # Quadratic + linear curve for pixel precision at low tilt and fast travel at full tilt
            speed = (180.0 * mag + 950.0 * (mag ** 2.2))
            if self.lt > 80:  # LT held -> Precision Slow Cursor Mode (35% speed)
                speed *= 0.35

            vx = (nx / mag) * speed * dt
            vy = (ny / mag) * speed * dt

            self.rem_x += vx
            self.rem_y += vy
            dx = int(self.rem_x)
            dy = int(self.rem_y)
            if dx != 0 or dy != 0:
                self.rem_x -= dx
                self.rem_y -= dy
                if dx != 0:
                    self.vmouse.emit(EV_REL, REL_X, dx)
                if dy != 0:
                    self.vmouse.emit(EV_REL, REL_Y, dy)
                self.vmouse.syn()

        # Right Stick -> Smooth + Discrete 2D Scroll (works in Wayland, terminals/TUIs, XWayland & browsers)
        srx = self._apply_deadzone(self.rx, deadzone=3800)
        sry = self._apply_deadzone(self.ry, deadzone=3800)
        if srx != 0.0 or sry != 0.0:
            sign_y = -1.0 if sry > 0 else 1.0
            sign_x = 1.0 if srx > 0 else -1.0
            speed_y = 380.0 * abs(sry) + 1900.0 * (abs(sry) ** 1.6)
            speed_x = 380.0 * abs(srx) + 1900.0 * (abs(srx) ** 1.6)
            if self.lt > 80:
                speed_y *= 0.4
                speed_x *= 0.4
            self.scroll_rem_y += sign_y * speed_y * dt
            self.scroll_rem_x += sign_x * speed_x * dt

            hi_y = int(self.scroll_rem_y)
            hi_x = int(self.scroll_rem_x)
            emitted = False
            if abs(hi_y) >= 12:
                self.scroll_rem_y -= hi_y
                self.scroll_detent_y += hi_y
                self.vmouse.emit(EV_REL, REL_WHEEL_HI_RES, hi_y)
                if abs(self.scroll_detent_y) >= 120:
                    steps_y = int(self.scroll_detent_y / 120)
                    self.scroll_detent_y -= steps_y * 120
                    self.vmouse.emit(EV_REL, REL_WHEEL, steps_y)
                emitted = True
            if abs(hi_x) >= 12:
                self.scroll_rem_x -= hi_x
                self.scroll_detent_x += hi_x
                self.vmouse.emit(EV_REL, REL_HWHEEL_HI_RES, hi_x)
                if abs(self.scroll_detent_x) >= 120:
                    steps_x = int(self.scroll_detent_x / 120)
                    self.scroll_detent_x -= steps_x * 120
                    self.vmouse.emit(EV_REL, REL_HWHEEL, steps_x)
                emitted = True
            if emitted:
                self.vmouse.syn()
        else:
            self.scroll_detent_y = 0
            self.scroll_detent_x = 0

    def _needs_analog_tick(self):
        return (
            self.mode == "desktop"
            and (
                self._apply_deadzone(self.lx) != 0.0
                or self._apply_deadzone(self.ly) != 0.0
                or self._apply_deadzone(self.rx, deadzone=3800) != 0.0
                or self._apply_deadzone(self.ry, deadzone=3800) != 0.0
            )
        )

    def _handle_signals(self):
        while True:
            try:
                data = os.read(self.sig_r, 64)
                if not data:
                    break
                for signum in data:
                    if signum == signal.SIGUSR1:
                        self.toggle_mode()
                    elif signum == signal.SIGUSR2:
                        self.toggle_osk()
                    elif signum in (signal.SIGINT, signal.SIGTERM):
                        self.running = False
            except OSError as e:
                if e.errno in (errno.EAGAIN, errno.EWOULDBLOCK, errno.EINTR):
                    break
                break

    def _handle_wake_pipe(self):
        while True:
            try:
                data = os.read(self.wake_r, 64)
                if not data:
                    break
                for b in data:
                    if b == ord("S"):
                        # Release any held virtual buttons/modifiers cleanly prior to suspend
                        self.release_all()
                        self.view_held = self.menu_held = False
                    elif b == ord("W"):
                        # System resumed from s2idle: unblank lockscreen at +80ms & +450ms,
                        # and re-assert MCU XINPUT (0x01) at +600ms once USB 3-9 finishes resume init
                        now = time.monotonic()
                        self.wake_deadlines = [now + 0.08, now + 0.45, now + 0.65]
                        self.wake_mcu_pending = True
                        self.wake_display_and_lockscreen()
            except OSError as e:
                if e.errno in (errno.EAGAIN, errno.EWOULDBLOCK, errno.EINTR):
                    break
                break

    def _read_mcu_det_fd(self, fd):
        saw_real_activity = False
        path = self.mcu_det_fds.get(fd, "")
        is_hidraw = path.startswith("/dev/hidraw")
        while True:
            try:
                data = os.read(fd, 512)
                if not data:
                    break
                if is_hidraw:
                    # Ignore all-zero idle report 03 00 00... emitted when 0x24 0x01 resets the MCU!
                    if len(data) > 1 and any(b != 0 for b in data[1:]):
                        saw_real_activity = True
                else:
                    for offset in range(0, len(data) - (len(data) % EVENT_STRUCT.size), EVENT_STRUCT.size):
                        _, _, ev_type, _, val = EVENT_STRUCT.unpack_from(data, offset)
                        if ev_type in (EV_KEY, EV_REL) and val != 0:
                            saw_real_activity = True
            except OSError as e:
                if e.errno in (errno.EAGAIN, errno.EWOULDBLOCK, errno.EINTR):
                    break
                try:
                    os.close(fd)
                except OSError:
                    pass
                self.mcu_det_fds.pop(fd, None)
                break
        if saw_real_activity and (time.monotonic() - self.last_mcu_xinput_time) >= 0.5:
            # MCU slipped into 0x04 firmware desktop mode (e.g. holding View >= 2s or post-wake)
            self.view_held = False
            self.menu_held = False
            if self.alt_tab_active:
                self.vkbd.key(KEY_LEFTALT, 0)
                self.alt_tab_active = False
            print("Detected MCU 0x04 desktop packet; restoring XINPUT (0x01) immediately", flush=True)
            self.ensure_mcu_xinput(force=True)

    def _read_face_fd(self, fd):
        while True:
            try:
                data = os.read(fd, EVENT_STRUCT.size * 32)
                if not data:
                    break
                for offset in range(0, len(data), EVENT_STRUCT.size):
                    _, _, ev_type, code, val = EVENT_STRUCT.unpack_from(data, offset)
                    if ev_type == EV_KEY and val == 1:
                        now = time.monotonic()
                        if code == KEY_F16 and (now - self.last_left_face_time) >= 0.18:
                            self.last_left_face_time = now
                            if self.view_held:
                                self.view_used_as_chord = True
                                self.toggle_overview()
                            else:
                                self.toggle_center()
                        elif code == KEY_F15 and (now - self.last_right_face_time) >= 0.18:
                            self.last_right_face_time = now
                            self.toggle_quick_settings()
            except OSError as e:
                if e.errno in (errno.EAGAIN, errno.EWOULDBLOCK, errno.EINTR):
                    break
                try:
                    os.close(fd)
                except OSError:
                    pass
                self.face_fds.pop(fd, None)
                self.has_atkbd_face = any(v[1] == "AT Translated Set 2 keyboard" for v in self.face_fds.values())
                self.sync_face_keybindings()  # hand F15/F16 back to GNOME while we can't read them
                break

    def run(self):
        last_tick = time.monotonic()
        analog_active = False

        # Ensure MCU starts in XINPUT (0x01), open auxiliary/face devices, and sync state
        self.ensure_mcu_xinput(force=True)
        self.open_aux_devices()
        self.sync_dock_state(notify=False)
        self.handle_external_cmd(unlink_empty=True)
        self.open_controller()
        if GLib is not None:
            try:
                self._call_claw("SetControllerMode", GLib.Variant("(s)", (self.mode,)))
            except Exception:
                pass

        while self.running:
            now = time.monotonic()
            if self.dock_check_deadline and now >= self.dock_check_deadline:
                self.dock_check_deadline = 0.0
                self.sync_dock_state(notify=True)
            if self.wake_deadlines:
                due = [d for d in self.wake_deadlines if now >= d]
                if due:
                    self.wake_deadlines = [d for d in self.wake_deadlines if now < d]
                    self.wake_display_and_lockscreen()
                    if not self.wake_deadlines and self.wake_mcu_pending:
                        self.wake_mcu_pending = False
                        self.ensure_mcu_xinput(force=True)
                        self.open_aux_devices()
                        self.sync_dock_state(notify=False, force_rgb=True)
                        if self.ctrl_fd is None:
                            self.open_controller()

            watch_fds = [self.sig_r, self.wake_r]
            if self.inotify_fd is not None:
                watch_fds.append(self.inotify_fd)
            if self.uevent_sock is not None:
                watch_fds.append(self.uevent_sock)
            watch_fds.extend(self.mcu_det_fds.keys())
            watch_fds.extend(self.face_fds.keys())

            if self.ctrl_fd is None:
                if self.open_controller():
                    # Fast USB re-enumeration: re-assert XINPUT and reopen aux nodes that died with it
                    self.ensure_mcu_xinput(force=True)
                    self.open_aux_devices()
                else:
                    try:
                        rlist, _, _ = select.select(watch_fds, [], [], 1.0)
                    except InterruptedError:
                        continue
                    except OSError as e:
                        if e.errno == errno.EINTR:
                            continue
                        raise
                    if self.sig_r in rlist:
                        self._handle_signals()
                    if self.wake_r in rlist:
                        self._handle_wake_pipe()
                    if self.inotify_fd is not None and self.inotify_fd in rlist:
                        if self._drain_inotify():
                            self.handle_external_cmd(unlink_empty=True)
                    if self.uevent_sock is not None and self.uevent_sock in rlist:
                        if self._drain_uevents():
                            self.dock_check_deadline = time.monotonic() + 0.45
                    for fd in list(self.mcu_det_fds.keys()):
                        if fd in rlist:
                            self._read_mcu_det_fd(fd)
                    for fd in list(self.face_fds.keys()):
                        if fd in rlist:
                            self._read_face_fd(fd)
                    self.ensure_mcu_xinput(force=False)
                    self.open_aux_devices()
                    analog_active = False
                    continue

            watch_fds.append(self.ctrl_fd)

            timeout = None
            if self._needs_analog_tick():
                if not analog_active:
                    analog_active = True
                    last_tick = time.monotonic()
                    self.tick_analog(0.008)
                timeout = max(0.001, 0.008 - (time.monotonic() - last_tick))
            else:
                analog_active = False

            if self.wake_deadlines:
                next_wake = max(0.005, self.wake_deadlines[0] - time.monotonic())
                timeout = next_wake if timeout is None else min(timeout, next_wake)

            if self.dock_check_deadline:
                next_dock = max(0.005, self.dock_check_deadline - time.monotonic())
                timeout = next_dock if timeout is None else min(timeout, next_dock)

            try:
                rlist, _, _ = select.select(watch_fds, [], [], timeout)
            except InterruptedError:
                continue
            except OSError as e:
                if e.errno == errno.EINTR:
                    continue
                raise

            if self.sig_r in rlist:
                self._handle_signals()
                if not self.running:
                    break

            if self.wake_r in rlist:
                self._handle_wake_pipe()

            if self.inotify_fd is not None and self.inotify_fd in rlist:
                if self._drain_inotify():
                    self.handle_external_cmd(unlink_empty=True)

            if self.uevent_sock is not None and self.uevent_sock in rlist:
                if self._drain_uevents():
                    self.dock_check_deadline = time.monotonic() + 0.45

            for fd in list(self.mcu_det_fds.keys()):
                if fd in rlist:
                    self._read_mcu_det_fd(fd)

            for fd in list(self.face_fds.keys()):
                if fd in rlist:
                    self._read_face_fd(fd)

            if self.ctrl_fd is not None and self.ctrl_fd in rlist:
                while True:
                    try:
                        data = os.read(self.ctrl_fd, EVENT_STRUCT.size * 32)
                        if not data:
                            break
                        for offset in range(0, len(data), EVENT_STRUCT.size):
                            _, _, ev_type, code, val = EVENT_STRUCT.unpack_from(data, offset)
                            if ev_type != EV_SYN:
                                self.handle_event(ev_type, code, val)
                    except OSError as e:
                        if e.errno in (errno.EAGAIN, errno.EWOULDBLOCK, errno.EINTR):
                            break
                        print(f"Controller disconnected ({e}), waiting to reconnect...", flush=True)
                        self.close_controller()
                        analog_active = False
                        break

            if self._needs_analog_tick():
                now = time.monotonic()
                if not analog_active:
                    analog_active = True
                    last_tick = now
                    self.tick_analog(0.008)
                else:
                    dt = min(0.05, now - last_tick)
                    if dt >= 0.007:
                        last_tick = now
                        self.tick_analog(dt)
            else:
                analog_active = False

        self.close_controller()
        self.close_aux_devices()
        if self.uevent_sock is not None:
            try:
                self.uevent_sock.close()
            except OSError:
                pass
            self.uevent_sock = None
        if self.inotify_fd is not None:
            try:
                os.close(self.inotify_fd)
            except OSError:
                pass
            self.inotify_fd = None
        for fd_attr in ("sig_r", "sig_w", "wake_r", "wake_w"):
            fd = getattr(self, fd_attr, None)
            if fd is not None:
                try:
                    os.close(fd)
                except OSError:
                    pass
                setattr(self, fd_attr, None)
        self.vmouse.close()
        self.vkbd.close()
        self.vtouch.close()


def main():
    daemon = MSIClawDaemon()

    def sig_handler(signum, _frame):
        if signum in (signal.SIGINT, signal.SIGTERM):
            daemon.running = False
        if daemon.sig_w is not None:
            try:
                os.write(daemon.sig_w, bytes([signum]))
            except OSError:
                pass

    signal.signal(signal.SIGINT, sig_handler)
    signal.signal(signal.SIGTERM, sig_handler)
    signal.signal(signal.SIGUSR1, sig_handler)
    signal.signal(signal.SIGUSR2, sig_handler)

    daemon.run()


if __name__ == "__main__":
    main()
