# MSI Claw Center (`io.msiclaw.Center`)

Native **GTK4 / Libadwaita** handheld & docked Mini-PC control center, hardware button/controller daemon, and Meteor Lake power & Embedded Controller (EC) suite for the **MSI Claw A1M** (`MS-1T41`, Intel Core Ultra 7 155H) on Linux Wayland (**KDE Plasma 6** & **GNOME Shell**).

---

## Features

- **Zero-Idle-CPU Overlay GUI (`msi-claw-center`)**
  - Single-instance D-Bus activated GTK4 / Libadwaita overlay (`io.msiclaw.Center`) toggled instantly via the physical **MSI Center M** button (`F16`) or `msi-claw-center --toggle`.
  - Uses `0.0%` CPU when hidden/unmapped; polls telemetry every 2s only while visible.
- **Hardware EC Battery Charge Limit (`60% / 80% / 100%`)**
  - Talks directly to the MSI Embedded Controller (`EC 0xD7`) via the upstream Linux `msi_wmi_platform` driver (`get_data` / `set_data` 32-byte WMI frames) with true **AC passthrough (`0.0W` battery current)** once the target threshold is reached.
  - Persists across reboots and `s2idle` sleep via `msi-claw-battery-limit.service`, with passwordless Polkit integration for `wheel` users.
- **Automatic Dock / Mini-PC ↔ Handheld Switching (`msi-claw-controller.py`)**
  - Event-driven kernel hotplug listener (`NETLINK_KOBJECT_UEVENT`, `0.0%` idle CPU):
    - **When Docked (e.g. Ugreen / Thunderbolt 4 / USB-C DP Alt-Mode):** Suppresses mouse-triggered on-screen keyboard popups (`KWin VirtualKeyboard mode=0`), turns off controller thumbstick/ABXY RGB LEDs (`0W`), and displays live external monitor refresh rate + `AC Bypass` badge.
    - **When Undocked (Handheld):** Automatically restores thumbstick + touch virtual keyboard auto-popup (`KWin VirtualKeyboard mode=2`) and restores your saved handheld RGB color & brightness (`~/.config/msi-claw-rgb.json`).
- **Smart External USB Keyboard `s2idle` Wakeup**
  - `msi-claw-usb-wakeup-sync` + `85-msi-claw-usb-wakeup.rules` dynamically enables `power/wakeup` along the exact USB hub ancestry leading to an external USB keyboard while keeping mice, Ethernet adapters, and unused root hubs `wakeup=disabled` to prevent spurious wakes.
- **Built-in Controller (`0db0:1901`) & Front Hardware Buttons**
  - **View + Menu:** Instant toggle between **Desktop Control Mode** (thumbstick cursor, 2D smooth scroll, trigger/ABXY clicks, `View` chord shortcuts) and native **Xbox Gamepad Mode**.
  - **MSI Center M (`F16`):** Toggles MSI Claw Center overlay (`View + F16` opens Overview / App Grid).
  - **Quick Settings (`F15`):** Opens KDE Plasma System Tray Quick Settings or GNOME Quick Settings.
- **Zero-Flash-Wear RGB Studio (`msi-claw-rgb`)**
  - Streams HID `WRITE_PROFILE_DATA (0x21)` directly to the controller MCU without `SYNC_TO_ROM (0x22)` flash wear.
- **Meteor Lake 155H Power, Scheduler & Wi-Fi 7 `s2idle` Tuning**
  - RAPL PL1/PL2 + Uncore + Intel Arc SLPC TuneD profiles (`11W Eco`, `18W/28W Balanced`, `25W/35W Turbo`), `scx_lavd` scheduler switching, GPU Priority CPU boost cap, and Intel Killer BE200 (`0000:2b:00.0`) D3cold / `s2idle` crash prevention.

---

## Repository Layout

```text
msi-claw-center/
├── bin/
│   ├── msi-claw-center                # GTK4 / Libadwaita GUI & CLI daemon
│   ├── msi-claw-controller.py         # Controller, face buttons & dock hotplug daemon
│   ├── msi-claw-rgb                   # Standalone HID RGB CLI
│   └── msi-claw-action.sh             # Runtime command helper
├── sbin/
│   ├── msi-claw-battery-limit         # EC 0xD7 battery charge threshold controller
│   ├── msi-claw-usb-wakeup-sync       # USB keyboard hub wakeup chain manager
│   ├── msi-claw-system-power-setup.sh # System TuneD, LPMD, scx_lavd & BE200 s2idle setup
│   └── msi-claw-shell-backup-sync     # GNOME Shell GResource backup helper
├── systemd/                           # User & system systemd units + post-sleep hook
├── system/                            # Polkit policy/rules, udev rules, modules-load
├── desktop/                           # .desktop launchers & D-Bus activation service
├── gnome-extension/                   # claw-controls@msi-claw GNOME Shell extension & 5-row OSK
└── install.sh                         # Full or --user-only installer
```

---

## Installation

### Dependencies (Fedora 44+)
```bash
sudo dnf install -y python3 python3-gobject gtk4 libadwaita tuned tuned-ppd polkit
```

### Install Everything (User + System EC / Wakeup Rules)
```bash
git clone https://github.com/<your-username>/msi-claw-center.git ~/msi-claw-center
cd ~/msi-claw-center
./install.sh
```

*(Optional)* To apply full Meteor Lake RAPL TuneD profiles, Intel LPMD, `zstd` zram, `scx_lavd`, and Intel BE200 Wi-Fi 7 `s2idle` fixes:
```bash
sudo /usr/local/sbin/msi-claw-system-power-setup.sh --fix-all-live
```

---

## CLI Usage

```bash
msi-claw-center --toggle               # Show / hide the MSI Claw Center overlay
msi-claw-center --status               # Print JSON telemetry (battery, EC limit, dock, temps, RPM)
msi-claw-rgb off                       # Turn off controller RGB LEDs (0W)
msi-claw-rgb 0 170 255 25              # Custom RGB (R G B Brightness%)
pkexec /usr/local/sbin/msi-claw-battery-limit set 80   # Set EC 0xD7 battery cap (50..100%)
```

---

## License

Licensed under the **GNU General Public License v3.0 or later** (`GPL-3.0-or-later`). See [LICENSE](LICENSE).
