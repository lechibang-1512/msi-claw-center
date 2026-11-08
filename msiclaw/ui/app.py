"""
MSI Claw Center Application Daemon & CLI interface (MSIClawCenterApp).
Handles single-instance overlay toggles, D-Bus actions, and JSON telemetry status.
"""

import atexit
import ctypes
import gc
import json
import os
import signal
import sys

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, Gtk

from ..constants import OVERLAY_SHM_PATH
from ..hw import (
    get_power_profile,
    get_rapl_power_limits,
    kernel_lockdown_mode,
    read_sysfs,
    resolve_arc_gpu,
    resolve_hwmon,
    set_power_profile,
)
from .styles import APP_CSS
from .window import MSIClawCenterWindow


def _cleanup_overlay_shm():
    try:
        OVERLAY_SHM_PATH.unlink(missing_ok=True)
    except OSError:
        pass


atexit.register(_cleanup_overlay_shm)
try:
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    signal.signal(signal.SIGINT, lambda *_: sys.exit(0))
except Exception:
    pass


class MSIClawCenterApp(Adw.Application):
    def __init__(self):
        super().__init__(
            application_id="io.msiclaw.Center",
            flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE,
        )

    def do_startup(self):
        try:
            Gtk.init()
            gtk_settings = Gtk.Settings.get_default()
            if gtk_settings is not None:
                gtk_settings.set_property("gtk-application-prefer-dark-theme", False)
        except Exception:
            pass
        Adw.Application.do_startup(self)
        self.hold()  # Keep daemon alive when window is unmapped / hidden
        Adw.StyleManager.get_default().set_color_scheme(Adw.ColorScheme.FORCE_DARK)
        provider = Gtk.CssProvider()
        provider.load_from_string(APP_CSS)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(),
            provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )

        # Register application actions
        toggle_action = Gio.SimpleAction.new("toggle", None)
        toggle_action.connect("activate", lambda *_: self.toggle_window())
        self.add_action(toggle_action)

        hide_action = Gio.SimpleAction.new("hide", None)
        hide_action.connect("activate", lambda *_: self.hide_window())
        self.add_action(hide_action)

        show_action = Gio.SimpleAction.new("show", None)
        show_action.connect("activate", lambda *_: self.show_window())
        self.add_action(show_action)

        quit_action = Gio.SimpleAction.new("quit", None)
        quit_action.connect("activate", lambda *_: self._on_quit_action())
        self.add_action(quit_action)

    def _on_quit_action(self):
        _cleanup_overlay_shm()
        windows = self.get_windows()
        if windows:
            windows[0]._send_claw_cmd("overlay-sync")
        try:
            while self.get_hold_count() > 0:
                self.release()
        except Exception:
            pass
        self.quit()

    def get_or_create_window(self):
        windows = self.get_windows()
        if windows:
            return windows[0]
        return MSIClawCenterWindow(self)

    def show_window(self):
        win = self.get_or_create_window()
        win.set_visible(True)
        win.unminimize()
        win.present()
        return win

    def hide_window(self):
        windows = self.get_windows()
        if windows:
            windows[0]._set_overlay_active_flag(False)
            windows[0]._stop_polling()
            windows[0].set_visible(False)
            try:
                gc.collect()
                ctypes.CDLL("libc.so.6").malloc_trim(0)
            except Exception:
                pass

    def toggle_window(self):
        windows = self.get_windows()
        if not windows:
            self.show_window()
            return
        win = windows[0]
        if win.get_visible() and win.is_active():
            win._set_overlay_active_flag(False)
            win._stop_polling()
            win.set_visible(False)
            try:
                gc.collect()
                ctypes.CDLL("libc.so.6").malloc_trim(0)
            except Exception:
                pass
        else:
            win.set_visible(True)
            win.unminimize()
            win.present()

    def do_activate(self):
        self.show_window()

    def do_command_line(self, command_line):
        args = command_line.get_arguments()[1:]
        if "--toggle" in args or "-t" in args:
            self.toggle_window()
        elif "--hide" in args:
            self.hide_window()
        elif "--show" in args or "--present" in args:
            self.show_window()
        elif "--background" in args or "--daemon" in args:
            # Idle background mode: keep D-Bus active without inflating full window heap
            pass
        elif "--quit" in args or "-q" in args:
            self._on_quit_action()
        elif "--status" in args:
            cpu_t, f1, f2 = resolve_hwmon()
            gdrv, _ = resolve_arc_gpu()
            eff_pl1, eff_pl2 = get_rapl_power_limits()
            active_prof = get_power_profile()
            bat_cap = read_sysfs("/sys/class/power_supply/BAT1/capacity", "--")
            bat_status = read_sysfs("/sys/class/power_supply/BAT1/status", "Unknown")
            run_chg = read_sysfs("/run/msi-claw-charge-limit", "")
            lk_mode = kernel_lockdown_mode()
            if run_chg:
                chg_lim_disp = f"{run_chg}%"
            elif lk_mode:
                saved_chg = read_sysfs("/var/lib/msi-claw/charge-limit", "")
                chg_lim_disp = f"locked (Secure Boot {lk_mode}; saved {saved_chg}%)" if saved_chg else f"locked (Secure Boot {lk_mode})"
            else:
                chg_lim_disp = f"{read_sysfs('/var/lib/msi-claw/charge-limit', '100')}%"
            cb_state = read_sysfs("/run/msi-claw-cooler-boost", "off")
            ctrl_mode = read_sysfs(f"/dev/shm/msi-claw-mode-{os.getuid()}", "desktop")
            dock_mode = read_sysfs(f"/dev/shm/msi-claw-dock-{os.getuid()}", "handheld")
            gyro_shm = read_sysfs(f"/dev/shm/msi-claw-gyro-{os.getuid()}", "1\t4.00\tlt_hold").split("\t")
            gyro_summary = (
                f"{'on' if gyro_shm[0] == '1' else 'off'} ({float(gyro_shm[1]):.1f}x, {gyro_shm[2]})"
                if len(gyro_shm) >= 3
                else "on"
            )
            status_obj = {
                "power_profile": active_prof,
                "rapl_pl1_pl2": f"{eff_pl1}W/{eff_pl2}W" if (eff_pl1 and eff_pl2) else "--",
                "battery": f"{bat_cap}% ({bat_status})",
                "charge_limit": chg_lim_disp,
                "dock_state": dock_mode,
                "cpu_temp": f"{float(read_sysfs(cpu_t, '0') or 0)/1000:.1f}°C" if cpu_t else "--",
                "gpu_driver": gdrv,
                "fans_rpm": f"{read_sysfs(f1, '0')}/{read_sysfs(f2, '0')}" if (f1 and f2) else "--",
                "cooler_boost": cb_state,
                "controller_mode": ctrl_mode,
                "gyro_aim": gyro_summary,
            }
            command_line.print_literal(json.dumps(status_obj, indent=2) + "\n")
        elif "--power-profile" in args:
            idx = args.index("--power-profile")
            if idx + 1 < len(args):
                prof = args[idx + 1].strip().lower()
                ok = set_power_profile(prof)
                if ok:
                    command_line.print_literal(f"Power profile set to: {prof}\n")
                else:
                    command_line.print_literal(f"Error: Invalid profile '{prof}'. Valid: power-saver, balanced, performance\n")
            else:
                cur = get_power_profile()
                command_line.print_literal(f"Current power profile: {cur}\n")
        elif "--help" in args or "-h" in args:
            help_txt = (
                "MSI Claw Center\n"
                "Usage:\n"
                "  msi-claw-center [OPTION...]\n\n"
                "Options:\n"
                "  -t, --toggle                 Toggle MSI Claw Center window overlay (show/hide)\n"
                "  --show                       Present MSI Claw Center window\n"
                "  --hide                       Hide MSI Claw Center window\n"
                "  --background                 Start daemon in background with hidden window\n"
                "  -q, --quit                   Quit MSI Claw Center\n"
                "  --status                     Print quick handheld telemetry summary (JSON)\n"
                "  --power-profile [PROFILE]    Get or set power profile (power-saver, balanced, performance)\n"
                "  -h, --help                   Show this help message\n"
            )
            command_line.print_literal(help_txt)
        else:
            self.show_window()
        return 0


def main():
    app = MSIClawCenterApp()
    sys.exit(app.run(sys.argv))
