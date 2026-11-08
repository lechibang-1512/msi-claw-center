# MSI Claw Center (`io.msiclaw.Center`)

[![Platform](https://img.shields.io/badge/Platform-MSI%20Claw%20A1M-red.svg)](https://www.msi.com)
[![OS](https://img.shields.io/badge/OS-Fedora%20Linux%20Wayland-blue.svg)](https://getfedora.org)
[![Desktop](https://img.shields.io/badge/Desktop-KDE%20Plasma%206%20%7C%20GNOME%2050-teal.svg)](https://kde.org)
[![UI Toolkit](https://img.shields.io/badge/UI-GTK4%20%2F%20Libadwaita-green.svg)](https://gtk.org)
[![License](https://img.shields.io/badge/License-GPL--3.0--or--later-orange.svg)](LICENSE)

Native **GTK4 / Libadwaita** handheld performance HUD, controller daemon, and hardware optimization suite designed specifically for the **MSI Claw A1M** (`MS-1T41`, Intel Core Ultra 7 155H Meteor Lake) running Linux Wayland (**KDE Plasma 6** and **GNOME Shell 50**).

---

## Highlights

- **Zero-Idle-CPU Overlay HUD (`msi-claw-center`)**
  - Single-instance D-Bus activated overlay (`io.msiclaw.Center`) toggled instantly via the physical **MSI Center M** button (`F16`) or gamepad shortcut.
  - Consumes **0.0% CPU when hidden**; runs a 2-second telemetry loop only while visible on screen; trims GTK/GLib heap memory on hide.
  - High-density, **100% zero-icon and zero-emoji monochrome engineering design** with monospace tabular figures for maximum readability and zero clutter.
- **Mid-Game Gamepad & Keyboard Navigation**
  - Seamlessly navigate the entire overlay mid-game using the controller:
    - **`LB` / `RB`**: Switch between HUD views (`01 DECK`, `02 KEYMAP`, `03 SYSTEM`).
    - **D-Pad / Analog Sticks**: Navigate items and controls.
    - **`A` / Enter**: Activate, toggle, or open drop-down menus.
    - **`B` / Escape**: Go back, dismiss menus, or hide the overlay.
  - Dedicated top-right **`EXIT`** button and titlebar controls accessible via touch, mouse cursor, or controller.
- **Unobstructed Polkit Privilege Elevation**
  - Root actions (RAPL TDP, fan Cooler Boost, EC battery threshold, system tuning) invoke Polkit dialogs configured with KDE KWin layer-3 keep-above rules (`aboverule=3`, `fpplevelrule=2`).
  - Overlay automatically steps down or minimizes during authentication to prevent credential dialog occlusion, and seamlessly restores itself once authorization is completed.
- **Hardware EC Battery Charge Limit (`60% / 80% / 100%`)**
  - Communicates directly with the MSI Embedded Controller (`EC 0xD7`) via the upstream Linux `msi_wmi_platform` driver (`get_data` / `set_data` 32-byte WMI frames).
  - Enables true **AC passthrough (`0.0W` battery current)** once the target charge threshold is reached, dramatically extending battery lifespan.
  - Automatically re-applies post-`s2idle` suspend and across system reboots via `msi-claw-battery-limit.service`.
- **Automatic Dock (Mini-PC) ↔ Handheld Switching**
  - Event-driven kernel hotplug daemon (`NETLINK_KOBJECT_UEVENT`, 0.0% idle CPU):
    - **Docked Mode (Thunderbolt 4 / USB-C DP Alt-Mode):** Suppresses virtual keyboard popups when clicking with an external mouse (`KWin VirtualKeyboard mode=0`), switches off controller LEDs (`0W`), and displays external monitor refresh rate and `AC Bypass` telemetry.
    - **Handheld Mode:** Automatically restores touch & thumbstick virtual keyboard auto-popup (`KWin VirtualKeyboard mode=2`) and reloads saved handheld RGB profiles.
- **Zero-Flash-Wear RGB Controller (`msi-claw-rgb`)**
  - Streams volatile HID `WRITE_PROFILE_DATA (0x21)` packets directly to the controller MCU RAM without triggering `SYNC_TO_ROM (0x22)`, eliminating EEPROM flash wear.
- **Dual Compositor & Display Integration**
  - Native display switching: toggles between **1920x1080 @ 120Hz with Adaptive-Sync VRR** and 60Hz power-save mode via `kscreen-doctor` on KDE Plasma and `gdctl` on GNOME.
  - Seamless backlight brightness adjustment integrating with `org.kde.Solid.PowerManagement` on KDE and Mutter Backlight on GNOME.
- **Meteor Lake 155H Power & System Hardening**
  - Intel RAPL PL1/PL2 power profiles (`Eco 11W`, `Balanced 18W/28W`, `Turbo 25W/35W`).
  - `scx_lavd` extensible BPF gaming scheduler integration.
  - GPU Priority CPU boost capping.
  - Complete Intel Killer Wi-Fi 7 BE200 (`0000:2b:00.0`) PCIe D3cold and `s2idle` suspend/resume crash prevention.
  - Smart external USB keyboard wakeup tree management (`msi-claw-usb-wakeup-sync`).

---

## 3-View Zero-Icon HUD Architecture

The HUD is divided into three focused, high-density views switched via the top rail or gamepad bumpers (`LB`/`RB`):

```text
┌──────────────────────────────────────────────────────────────────────────────┐
│ [01 DECK]   [02 KEYMAP]   [03 SYSTEM]        [SYNC] [EXIT]                   │
├──────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  01 DECK                                                                     │
│  ─────────────────────────────────────────────────────────────────────────   │
│  • RAPL TDP Profile       : [ECO 11W] [BALANCED 18W] [TURBO 35W]             │
│  • CPU Scheduler          : [DEFAULT] [SCX_LAVD]                             │
│  • GPU Priority           : [OFF] [ON (CAP BOOST)]                           │
│  • Fan Cooling Mode       : [AUTO CURVE] [COOLER BOOST 100%]                 │
│  • EC Battery Limit       : [60%] [80%] [100%]                               │
│  • Display Refresh Rate   : [60 HZ] [120 HZ VRR]                             │
│  • Backlight Brightness   : ───────────●─────────── 70%                      │
│  • Controller Input Mode  : [DESKTOP] [GAMEPAD]                              │
│  • Gyro Sensor Emulation  : [OFF] [MOUSE (JOYSTICK)]                         │
│  • Quick RGB Lighting     : [OFF] [CYAN] [ORANGE] [WHITE]                    │
│                                                                              │
│  02 KEYMAP                                                                   │
│  ─────────────────────────────────────────────────────────────────────────   │
│  • Keymap Profile         : [DEFAULT] [RTS/DESKTOP] [FPS/GAME]               │
│  • Gyro Axis Sensitivity  : ──────●──────────────── 1.0x                     │
│  • 16 Bezel & Macro Remaps: M1 Paddle, M2 Paddle, View, Menu, D-Pad, etc.    │
│  • Hardware Chord Table   : View + D-Pad, View + Face Buttons, Mode Toggles  │
│                                                                              │
│  03 SYSTEM                                                                   │
│  ─────────────────────────────────────────────────────────────────────────   │
│  • UI Scaling Density     : [100% COMPACT] [125% BALANCED] [150% LARGE]      │
│  • System Power Policies  : Sleep / Wake / Rotation Lock toggles             │
│  • Custom RGB Studio      : R/G/B/Brightness sliders + live CSS swatch       │
│  • Hardware Inventory     : CPU, iGPU, RAM, Battery, Firmware, Drivers       │
│  • LVFS Firmware Check    : Check fwupd for MSI BIOS / Controller updates    │
│  • System Power Setup     : Run Meteor Lake TuneD / s2idle hardening script  │
│                                                                              │
├──────────────────────────────────────────────────────────────────────────────┤
│ BAT: 82% 21.4W (AC) | EC: 80% | FAN: 3450 RPM | CPU: 52°C | GPU: 48°C       │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

## Codebase Structure

The project has been reorganized into a clean, modular Python package (`msiclaw`) paired with dedicated system services and privileged helpers:

```text
msi-claw-center/
├── msiclaw/                           # Core Python package
│   ├── __init__.py                    # Version (__version__ = "1.3.0") & package root
│   ├── constants.py                   # USB PIDs, HID endpoints, scan codes, chord maps, defaults
│   ├── hw.py                          # Sysfs reader, hwmon discovery, Arc GPU detection, hardware inventory
│   ├── rgb.py                         # Zero-flash-wear HID profile writer & RGB CLI engine
│   ├── keymap.py                      # Bezel/paddle button definitions & chord references
│   ├── input/
│   │   ├── __init__.py                # Input module exports
│   │   └── uinput.py                  # Linux uinput virtual device wrapper, ioctls & EV/KEY constants
│   └── ui/
│       ├── __init__.py                # UI module exports
│       ├── styles.py                  # High-contrast zero-icon CSS stylesheet (APP_CSS)
│       ├── views/
│       │   ├── __init__.py            # View builder exports
│       │   ├── deck.py                # View 01: Deck (RAPL, scheduler, cooling, battery, display)
│       │   ├── keymap.py              # View 02: Keymap (gyro, button selectors, chord table)
│       │   └── system.py              # View 03: System (scale, custom RGB, inventory, firmware)
│       ├── window.py                  # Overlay window, rail navigation, telemetry, Polkit elevation
│       └── app.py                     # GtkApplication, D-Bus service, CLI --status, memory trimming
├── bin/                               # User-space entrypoints (installed to ~/.local/bin)
│   ├── msi-claw-center                # Lightweight launcher executing msiclaw.ui.app
│   ├── msi-claw-controller.py         # Controller event listener, virtual mouse/kbd, dock hotplug
│   ├── msi-claw-rgb                   # Standalone RGB CLI tool executing msiclaw.rgb
│   ├── msi-claw-action.sh             # Desktop action and shortcut runner
│   ├── msi-claw-notify-daemon.sh      # Minimal fallback notification daemon
│   ├── msi-claw-osd.sh                # Handheld on-screen display notifier
│   ├── msi-claw-osk-toggle.sh         # Dual-desktop virtual keyboard toggle
│   └── msi-claw-quick-menu.sh         # Compact Quick Settings dialog
├── sbin/                              # Privileged system helpers (installed to /usr/local/sbin)
│   ├── msi-claw-battery-limit         # EC 0xD7 charge threshold controller (WMI 32-byte frames)
│   ├── msi-claw-cooler-boost          # EC 100% fan Cooler Boost toggle
│   ├── msi-claw-system-power-setup.sh # Full Meteor Lake TuneD, LPMD, scx_lavd & BE200 s2idle setup
│   ├── msi-claw-usb-wakeup-sync       # Smart external USB keyboard wakeup chain manager
│   ├── msi-claw-dnf5-snapper          # DNF5 pre/post Btrfs snapshot hook
│   └── msi-claw-shell-backup-sync     # GNOME Shell GResource backup helper
├── system/                            # Privileged system configurations
│   ├── polkit-actions/                # PolicyKit action definitions (battery-limit, cooler-boost)
│   ├── polkit-rules/                  # Passwordless elevation rules for wheel group users
│   ├── udev/                          # 85-msi-claw-usb-wakeup.rules (dynamic hub wakeup)
│   └── modules-load/                  # msi-wmi-platform.conf
├── systemd/                           # Systemd unit configurations
│   ├── user/                          # msi-claw-center.service, msi-claw-controller.service
│   ├── system/                        # msi-claw-battery-limit.service
│   └── system-sleep/                  # Post-suspend EC battery limit restoration hook
├── desktop/                           # .desktop application launchers & D-Bus service manifests
├── gnome-extension/                   # claw-controls@msi-claw GNOME extension & 5-row OSK
├── pyproject.toml                     # Standard PEP 518 / PEP 621 Python package configuration
├── install.sh                         # Master installation & deployment script
└── LICENSE                            # GNU General Public License v3.0 or later
```

---

## Hardware Controller Buttons & Shortcut Chords

The built-in controller (`Micro Star International Xbox360 Controller for Windows`, `0db0:1901`) features front bezel buttons and rear macro paddles:

### Front Bezel Buttons
| Button | Linux Event | Function in Desktop Mode | Function in Gamepad Mode |
|:---|:---|:---|:---|
| **MSI Center M** (Bottom-Left) | `KEY_F16` | Toggles **MSI Claw Center** HUD | Toggles **MSI Claw Center** HUD |
| **Quick Settings** (Bottom-Right) | `KEY_F15` | Toggles KDE / GNOME Quick Settings | Toggles KDE / GNOME Quick Settings |
| **View** (Top-Left) | `BTN_SELECT` | Tap: `Escape`; Hold: Chord modifier | Native Xbox Back / View |
| **Menu** (Top-Right) | `BTN_START` | Tap: `Alt + Tab` (Switch Windows) | Native Xbox Menu / Start |

### Rear Macro Paddles
| Paddle | Linux Event | Default Function |
|:---|:---|:---|
| **M1 Paddle** (Rear Left) | `KEY_MACRO1` (`0x29`) | Configurable via View 02 Keymap (Default: `Left Super / Windows Key`) |
| **M2 Paddle** (Rear Right) | `KEY_MACRO2` (`0x2a`) | Configurable via View 02 Keymap (Default: `Virtual Keyboard Toggle`) |

### Hardware Chord Shortcuts
Hold **`View`** (`BTN_SELECT`) and press any of the following:

| Shortcut Chord | Action |
|:---|:---|
| **`View` + `Menu`** | **Toggle Controller Mode** (Desktop Control Mode ↔ Native Gamepad Mode) |
| **`View` + `D-Pad Up`** | Volume Up (`+5%`) |
| **`View` + `D-Pad Down`** | Volume Down (`-5%`) |
| **`View` + `D-Pad Right`** | Panel Backlight Brightness Up (`+10%`) |
| **`View` + `D-Pad Left`** | Panel Backlight Brightness Down (`-10%`) |
| **`View` + `A`** | Quick Paste (`Ctrl + V` or `Ctrl + Shift + V` in terminal) |
| **`View` + `B`** | Close Current Window (`Alt + F4`) |
| **`View` + `X`** | Quick Copy (`Ctrl + C` or `Ctrl + Shift + C` in terminal) |
| **`View` + `Y`** | Fullscreen Screenshot |
| **`View` + `MSI Center M`** | Toggle Desktop Application Grid / Overview |

---

## Installation & Setup

### Prerequisites
On Fedora Linux 44+:
```bash
sudo dnf install -y python3 python3-gobject gtk4 libadwaita tuned tuned-ppd polkit fwupd
```

### Full Installation
Run the installer as your regular desktop user (it will prompt for Polkit/sudo elevation only for `/usr/local/sbin` and system rules):
```bash
git clone https://github.com/lechibang/msi-claw-center.git ~/Documents/projects/msi-claw-center
cd ~/Documents/projects/msi-claw-center
./install.sh
```

### User-Only Installation (No Root Elevation)
If you only want to install or update the user-space Python package, GUI HUD, controller daemon, and user systemd units:
```bash
./install.sh --user-only
```

### Full Meteor Lake System & Power Hardening (Recommended)
To apply the complete Meteor Lake RAPL power profiles, Intel LPMD tuning, `scx_lavd` scheduler support, and Intel BE200 Wi-Fi 7 `s2idle` crash fixes:
```bash
sudo /usr/local/sbin/msi-claw-system-power-setup.sh --fix-all-live
```

---

## Command Line Interface (CLI) Reference

### Overlay HUD (`msi-claw-center`)
```bash
# Toggle HUD overlay visibility
msi-claw-center --toggle

# Explicitly show or hide the overlay
msi-claw-center --show
msi-claw-center --hide

# Switch to a specific HUD tab (1=DECK, 2=KEYMAP, 3=SYSTEM)
msi-claw-center --tab 1

# Print real-time system and hardware telemetry as structured JSON
msi-claw-center --status
```

#### Example `--status` JSON Output:
```json
{
  "docked": false,
  "battery_pct": 84,
  "battery_status": "Discharging",
  "battery_power_w": 18.25,
  "battery_limit_pct": 80,
  "cpu_temp_c": 51.0,
  "gpu_temp_c": 47.0,
  "fan_rpm": 3200,
  "cpu_freq_mhz": 2400.0,
  "rapl_profile": "balanced",
  "cooler_boost": false,
  "gpu_priority": false,
  "refresh_hz": 120,
  "backlight_pct": 70,
  "controller_mode": "desktop",
  "gyro_enabled": false,
  "compositor": "kde"
}
```

### Controller RGB Tool (`msi-claw-rgb`)
```bash
# Turn off controller thumbstick & button RGB LEDs (0W)
msi-claw-rgb off

# Set quick color preset (cyan, orange, white, red, green, blue, purple)
msi-claw-rgb cyan
msi-claw-rgb orange 50

# Set custom RGB with brightness: msi-claw-rgb <R> <G> <B> [Brightness%]
msi-claw-rgb 0 170 255 30

# Print active RGB controller status
msi-claw-rgb status
```

### Privileged EC Battery Cap (`msi-claw-battery-limit`)
```bash
# Query active hardware EC charge limit
/usr/local/sbin/msi-claw-battery-limit get

# Set hardware EC battery charge limit (60%, 80%, or 100%)
pkexec /usr/local/sbin/msi-claw-battery-limit set 80
```

### Privileged Fan Cooler Boost (`msi-claw-cooler-boost`)
```bash
# Query active Cooler Boost status
/usr/local/sbin/msi-claw-cooler-boost status

# Toggle or set Cooler Boost (100% max fan speed)
pkexec /usr/local/sbin/msi-claw-cooler-boost toggle
pkexec /usr/local/sbin/msi-claw-cooler-boost on
pkexec /usr/local/sbin/msi-claw-cooler-boost off
```

---

## D-Bus Interface Specification

`msi-claw-center` exports the `io.msiclaw.Center` service on the user session bus:

- **Bus Name:** `io.msiclaw.Center`
- **Object Path:** `/io/msiclaw/Center`
- **Interface:** `io.msiclaw.Center`

### Methods:
- `Toggle()`: Toggles the overlay window visibility.
- `Show()`: Presents and focuses the overlay window.
- `Hide()`: Minimizes and hides the overlay window, immediately triggering memory cleanup.
- `SetTab(tab_index: i)`: Switches the active rail tab (`0` = Deck, `1` = Keymap, `2` = System).
- `GetStatus() -> s`: Returns the full JSON telemetry dictionary.

---

## Verifications & Testing

You can run automated syntax and rule verification across the entire project at any time:

```bash
# Verify Python compilation across all modules and scripts
python3 -m py_compile $(git ls-files "*.py" "bin/msi-claw-center" "bin/msi-claw-rgb" "sbin/msi-claw-battery-limit" "sbin/msi-claw-cooler-boost")

# Verify zero-icon rule across all UI components
python3 -c '
import os, sys
os.environ["WAYLAND_DISPLAY"] = os.environ.get("WAYLAND_DISPLAY", "wayland-1")
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw
from msiclaw.ui.app import MSIClawCenterApp

app = MSIClawCenterApp()
app.register(None)
win = app.get_or_create_window()

def walk(w):
    acc = [w]
    child = w.get_first_child()
    while child:
        acc.extend(walk(child))
        child = child.get_next_sibling()
    return acc

widgets = walk(win)
images = [w for w in widgets if isinstance(w, Gtk.Image)]
non_search = [w for w in images if w.get_icon_name() not in ("system-search-symbolic", "edit-clear-symbolic")]
assert len(non_search) == 0, f"Found unexpected icons: {non_search}"
print(f"VERIFIED: {len(widgets)} widgets verified with 100% zero-icon enforcement!")
'
```

---

## License

This project is licensed under the **GNU General Public License v3.0 or later** (`GPL-3.0-or-later`). See the [LICENSE](LICENSE) file for complete details.
