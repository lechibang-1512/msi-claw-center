"""
Main Application Window for MSI Claw Center (MSIClawCenterWindow).
Asymmetric Left Command Rail (152px) + Right Instrument Stage layout.
Supports single-instance overlay toggling, mid-game gamepad navigation,
passwordless D-Bus hardware controls, and unobstructed Polkit sudo prompts.
"""

import glob
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import time

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk

from ..constants import (
    DEFAULT_KEY_BINDINGS,
    GYRO_CONFIG_PATH,
    KEYS_CONFIG_PATH,
    OVERLAY_SHM_PATH,
    RGB_CONFIG_PATH,
)
from ..hw import (
    get_hardware_inventory,
    get_rapl_power_limits,
    gpu_priority_active,
    kernel_lockdown_mode,
    read_sysfs,
    resolve_arc_gpu,
    resolve_hwmon,
)
from ..rgb import ClawRGBController
from .views.deck import build_deck_view
from .views.keymap import build_keymap_view
from .views.system import build_system_view


class MSIClawCenterWindow(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="MSI Claw Center")
        self.set_default_size(820, 470)
        self.set_size_request(680, 410)

        self.sys_bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
        self.ses_bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        self.cpu_temp_path, self.fan1_path, self.fan2_path = resolve_hwmon()
        self.gpu_drv, self.gpu_card_dir = resolve_arc_gpu()
        self.rgb_ctrl = ClawRGBController()
        self.rgb_color = (0, 170, 255)
        self.rgb_brightness = 15
        self.rgb_cfg_path = RGB_CONFIG_PATH
        if self.rgb_cfg_path.exists():
            try:
                rcfg = json.loads(self.rgb_cfg_path.read_text())
                self.rgb_color = (int(rcfg.get("r", 0)), int(rcfg.get("g", 170)), int(rcfg.get("b", 255)))
                self.rgb_brightness = int(rcfg.get("brightness", 15))
            except Exception:
                pass

        self._rgb_swatch_css = Gtk.CssProvider()
        disp = Gdk.Display.get_default()
        if disp is not None:
            Gtk.StyleContext.add_provider_for_display(
                disp,
                self._rgb_swatch_css,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1,
            )

        self.gyro_cfg_path = GYRO_CONFIG_PATH
        self.gyro_enabled = True
        self.gyro_sens = 4.0
        self.gyro_mode = "lt_hold"
        self.gyro_invert_x = False
        self.gyro_invert_y = False
        if self.gyro_cfg_path.exists():
            try:
                gcfg = json.loads(self.gyro_cfg_path.read_text())
                self.gyro_enabled = bool(gcfg.get("enabled", True))
                self.gyro_sens = max(1.0, min(10.0, float(gcfg.get("sensitivity", 4.0))))
                self.gyro_mode = str(gcfg.get("mode", "lt_hold"))
                self.gyro_invert_x = bool(gcfg.get("invert_x", False))
                self.gyro_invert_y = bool(gcfg.get("invert_y", False))
            except Exception:
                pass
        self._gyro_debounce_id = 0
        self._updating_gyro_ui = False

        self.keys_cfg_path = KEYS_CONFIG_PATH
        self.default_key_cfg = dict(DEFAULT_KEY_BINDINGS)
        self.key_cfg = dict(self.default_key_cfg)
        self._load_key_bindings()
        self._updating_keys_ui = False
        self.key_dropdowns = {}

        self.current_output = "eDP-1"
        self.current_res = "1920x1080"
        self.current_scale = "1.5"
        self.current_hz = 120
        self.current_vrr = True
        self._kscreen_modes = {}
        self.bl_serial = 0
        self.bl_min = 1920
        self.bl_max = 192000
        self.kde_bl_max = 10000
        self._cached_is_plasma = None
        self._cached_is_wlroots = None
        self._bl_updating = False
        self._bl_debounce_id = 0
        self._rgb_debounce_id = 0
        self._updating_rgb_ui = False

        self._fast_idle_state = False
        self._orient_locked_state = False
        self._instant_wake_state = False

        self._last_rc6_ms = None
        self._last_rc6_ts = None
        self._timer_id = 0
        self._feedback_timer_id = 0
        self._focus_loss_timer_id = 0
        self._pkexec_proc = None
        self._pkexec_hide_timer_id = 0
        self._restore_after_pkexec = False
        self._tab_order = ["deck", "keymap", "system"]

        self._build_ui()
        self._connect_lifecycle()
        self._sync_initial_controls()
        self._refresh_telemetry()

    # -----------------------------------------------------------------
    # Compact Zero-Icon Widget Builders
    # -----------------------------------------------------------------
    def _make_tele_cell(self, key_txt, is_last=False):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        box.add_css_class("tele-cell-last" if is_last else "tele-cell")
        box.set_hexpand(True)
        klbl = Gtk.Label(label=key_txt, xalign=0.0)
        klbl.add_css_class("tele-key")
        vlbl = Gtk.Label(label="--", xalign=0.0, ellipsize=3)
        vlbl.add_css_class("tele-val")
        slbl = Gtk.Label(label="--", xalign=0.0, ellipsize=3)
        slbl.add_css_class("tele-sub")
        box.append(klbl)
        box.append(vlbl)
        box.append(slbl)
        return box, vlbl, slbl

    def _make_block_header(self, title_txt, readout_txt=None):
        hdr = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        tlbl = Gtk.Label(label=title_txt, xalign=0.0)
        tlbl.add_css_class("group-hdr")
        tlbl.set_hexpand(True)
        hdr.append(tlbl)
        rlbl = None
        if readout_txt is not None:
            rlbl = Gtk.Label(label=readout_txt, xalign=1.0)
            rlbl.add_css_class("group-readout")
            hdr.append(rlbl)
        return hdr, rlbl

    def _make_bool_pair(self, off_lbl, on_lbl, callback):
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4, homogeneous=True)
        btn_off = Gtk.Button(label=off_lbl)
        btn_off.add_css_class("seg-btn")
        btn_on = Gtk.Button(label=on_lbl)
        btn_on.add_css_class("seg-btn")
        btn_off.connect("clicked", lambda *_: callback(False))
        btn_on.connect("clicked", lambda *_: callback(True))
        row.append(btn_off)
        row.append(btn_on)
        return row, (btn_off, btn_on)

    @staticmethod
    def _set_bool_pair(pair, state, on_cls="active-mode", off_cls="active-mode"):
        btn_off, btn_on = pair
        for b in (btn_off, btn_on):
            b.remove_css_class("active-mode")
            b.remove_css_class("eco-active")
            b.remove_css_class("perf-active")
        if state:
            btn_on.add_css_class(on_cls)
        elif off_cls:
            btn_off.add_css_class(off_cls)

    def _make_bind_row(self, tag_txt, label_txt, cfg_key, opt_list, tag_cls="key-tag"):
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        row.add_css_class("bind-row")

        tag = Gtk.Label(label=tag_txt, xalign=0.5, width_chars=8)
        tag.add_css_class(tag_cls)

        lbl = Gtk.Label(label=label_txt, xalign=0.0, ellipsize=3)
        lbl.add_css_class("bind-lbl")
        lbl.set_hexpand(True)

        str_list = Gtk.StringList.new([o[1] for o in opt_list])
        if not hasattr(self, "_dd_factory"):
            fac = Gtk.SignalListItemFactory()
            fac.connect("setup", lambda _f, li: li.set_child(Gtk.Label(xalign=0.0, ellipsize=3)))
            fac.connect("bind", lambda _f, li: li.get_child().set_label(li.get_item().get_string()))
            self._dd_factory = fac
        dd = Gtk.DropDown(model=str_list, factory=self._dd_factory, list_factory=self._dd_factory)
        dd.add_css_class("select-field")
        dd.set_size_request(148, -1)

        cur_val = self.key_cfg.get(cfg_key, self.default_key_cfg.get(cfg_key, ""))
        sel_i = 0
        for oi, (oval, _) in enumerate(opt_list):
            if oval == cur_val:
                sel_i = oi
                break
        dd.set_selected(sel_i)
        dd.connect("notify::selected", self._on_key_dropdown_changed, cfg_key, opt_list)
        self.key_dropdowns[cfg_key] = (dd, opt_list)

        row.append(tag)
        row.append(lbl)
        row.append(dd)
        return row

    def _make_spec_row(self, key_text, val_text):
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        row.add_css_class("spec-row")
        klbl = Gtk.Label(label=key_text, xalign=0.0)
        klbl.add_css_class("spec-key")
        vlbl = Gtk.Label(label=val_text, xalign=1.0, ellipsize=3)
        vlbl.add_css_class("spec-val")
        vlbl.set_hexpand(True)
        row.append(klbl)
        row.append(vlbl)
        return row

    def _switch_tab(self, tab_name):
        if tab_name not in self._tab_order:
            return
        self.view_stack.set_visible_child_name(tab_name)
        for tname, tbtn in self.nav_tab_buttons.items():
            if tname == tab_name:
                tbtn.add_css_class("active-tab")
            else:
                tbtn.remove_css_class("active-tab")

    def _cycle_tab(self, delta):
        cur = self.view_stack.get_visible_child_name() or "deck"
        idx = self._tab_order.index(cur) if cur in self._tab_order else 0
        nxt = self._tab_order[(idx + delta) % len(self._tab_order)]
        self._switch_tab(nxt)

    def _toggle_controller_mode_quick(self):
        cur = read_sysfs(f"/dev/shm/msi-claw-mode-{os.getuid()}", "desktop")
        self._set_controller_mode("gamepad" if cur == "desktop" else "desktop")

    # -----------------------------------------------------------------
    # Main Asymmetric 3-View Zero-Icon Split Deck
    # -----------------------------------------------------------------
    def _build_ui(self):
        root_hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)

        # =============================================================
        # ZONE A: Left Command Rail (152px Fixed)
        # =============================================================
        self.left_rail = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.left_rail.add_css_class("deck-rail")
        self.left_rail.set_size_request(152, -1)

        rail_drag = Gtk.WindowHandle()
        brand_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        brand_lbl = Gtk.Label(label="MSI CLAW A1M", xalign=0.0)
        brand_lbl.add_css_class("rail-brand")
        self.power_badge = Gtk.Label(label="AC BYPASS", xalign=0.0, ellipsize=3)
        self.power_badge.add_css_class("badge-ac")
        brand_box.append(brand_lbl)
        brand_box.append(self.power_badge)
        rail_drag.set_child(brand_box)
        self.left_rail.append(rail_drag)

        nav_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        nav_box.set_margin_top(4)
        self.nav_tab_buttons = {}
        for tname, tlabel in [
            ("deck", "01  DECK"),
            ("keymap", "02  KEYMAP"),
            ("system", "03  SYSTEM"),
        ]:
            tbtn = Gtk.Button()
            lbl = Gtk.Label(label=tlabel, xalign=0.0)
            tbtn.set_child(lbl)
            tbtn.add_css_class("rail-nav-btn")
            tbtn.connect("clicked", lambda _b, n=tname: self._switch_tab(n))
            nav_box.append(tbtn)
            self.nav_tab_buttons[tname] = tbtn
        self.left_rail.append(nav_box)

        hint_lbl = Gtk.Label(label="LB / RB  SWITCH VIEW\nB / ESC / EXIT  CLOSE", xalign=0.0)
        hint_lbl.add_css_class("rail-hint")
        hint_lbl.set_margin_top(2)
        self.left_rail.append(hint_lbl)

        spacer = Gtk.Box()
        spacer.set_vexpand(True)
        self.left_rail.append(spacer)

        # Bottom Rail Quick Actions
        rail_dock = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.hdr_mode_btn = Gtk.Button(label="MODE: DESKTOP")
        self.hdr_mode_btn.add_css_class("seg-btn")
        self.hdr_mode_btn.connect("clicked", lambda *_: self._toggle_controller_mode_quick())
        rail_dock.append(self.hdr_mode_btn)

        util_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4, homogeneous=True)
        osk_btn = Gtk.Button(label="OSK")
        osk_btn.add_css_class("rail-util-btn")
        osk_btn.connect("clicked", lambda *_: self._send_claw_cmd("toggle-osk"))
        close_btn = Gtk.Button(label="CLOSE")
        close_btn.add_css_class("close-win-btn")
        close_btn.connect("clicked", lambda *_: self.close())
        util_row.append(osk_btn)
        util_row.append(close_btn)
        rail_dock.append(util_row)
        self.left_rail.append(rail_dock)

        root_hbox.append(self.left_rail)

        # =============================================================
        # ZONE B: Right Instrument Stage
        # =============================================================
        stage_vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        stage_vbox.set_hexpand(True)
        stage_vbox.set_vexpand(True)

        # Draggable Tabular Telemetry Strip
        tele_drag = Gtk.WindowHandle()
        tele_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        tele_bar.add_css_class("telemetry-strip")

        c_bat, self.bat_val, self.bat_sub = self._make_tele_cell("BATTERY")
        c_cpu, self.cpu_val, self.cpu_sub = self._make_tele_cell("CPU / RAPL")
        c_gpu, self.gpu_val, self.gpu_sub = self._make_tele_cell("ARC GPU")
        c_fan, self.fan_val, self.fan_sub = self._make_tele_cell("FANS / OUT", is_last=True)

        hdr_actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4, valign=Gtk.Align.CENTER)
        refresh_btn = Gtk.Button(label="SYNC")
        refresh_btn.add_css_class("rail-util-btn")
        refresh_btn.connect("clicked", lambda *_: self._refresh_telemetry())

        exit_btn = Gtk.Button(label="EXIT")
        exit_btn.add_css_class("close-win-btn")
        exit_btn.connect("clicked", lambda *_: self.close())

        hdr_actions.append(refresh_btn)
        hdr_actions.append(exit_btn)

        tele_bar.append(c_bat)
        tele_bar.append(c_cpu)
        tele_bar.append(c_gpu)
        tele_bar.append(c_fan)
        tele_bar.append(hdr_actions)
        tele_drag.set_child(tele_bar)
        stage_vbox.append(tele_drag)

        # 3-View Stack (Instant/90ms Crossfade, Zero Lag)
        self.view_stack = Gtk.Stack(
            transition_type=Gtk.StackTransitionType.CROSSFADE,
            transition_duration=80,
        )
        self.view_stack.set_vexpand(True)
        self.view_stack.set_hexpand(True)

        self.view_stack.add_named(build_deck_view(self), "deck")
        self.view_stack.add_named(build_keymap_view(self), "keymap")
        self.view_stack.add_named(build_system_view(self), "system")
        stage_vbox.append(self.view_stack)

        # Inline Bottom Status & Feedback Strip
        footer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        footer.add_css_class("status-footer")
        self.status_feedback_lbl = Gtk.Label(
            label="READY  |  F16 OVERLAY  |  EXIT / ESC CLOSE  |  1-3 VIEWS",
            xalign=0.0,
            ellipsize=3,
        )
        self.status_feedback_lbl.add_css_class("status-feedback")
        self.status_feedback_lbl.set_hexpand(True)

        self.sys_status_lbl = Gtk.Label(label="--", xalign=1.0, ellipsize=3)
        self.sys_status_lbl.add_css_class("status-sys")

        footer.append(self.status_feedback_lbl)
        footer.append(self.sys_status_lbl)
        stage_vbox.append(footer)

        root_hbox.append(stage_vbox)
        self.set_content(root_hbox)

        self._switch_tab("deck")

        key_ctrl = Gtk.EventControllerKey()
        key_ctrl.connect("key-pressed", self._on_key_pressed)
        self.add_controller(key_ctrl)

    def _make_rgb_channel_row(self, parent_box, ch_name, init_val):
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        clbl = Gtk.Label(label=ch_name, width_chars=2, xalign=0.0)
        clbl.add_css_class("group-hdr")
        scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 255, 1)
        scale.set_value(init_val)
        scale.set_draw_value(False)
        scale.set_hexpand(True)
        vlbl = Gtk.Label(label=str(init_val), width_chars=4, xalign=1.0)
        vlbl.add_css_class("group-readout")
        scale.connect("value-changed", self._on_rgb_channel_changed)
        row.append(clbl)
        row.append(scale)
        row.append(vlbl)
        parent_box.append(row)
        return scale, vlbl

    # -----------------------------------------------------------------
    # Keyboard, Gamepad Navigation & Lifecycle
    # -----------------------------------------------------------------
    def _on_key_pressed(self, _controller, keyval, _keycode, state):
        mods = state & Gtk.accelerator_get_default_mod_mask()
        if keyval == Gdk.KEY_Escape:
            self.close()
            return True
        if keyval in (Gdk.KEY_q, Gdk.KEY_Q) and (mods == 0 or mods == Gdk.ModifierType.CONTROL_MASK):
            self.close()
            return True
        if keyval in (Gdk.KEY_w, Gdk.KEY_W) and mods == Gdk.ModifierType.CONTROL_MASK:
            self.close()
            return True
        if keyval == Gdk.KEY_Page_Up and mods == Gdk.ModifierType.CONTROL_MASK:
            self._cycle_tab(-1)
            return True
        if keyval == Gdk.KEY_Page_Down and mods == Gdk.ModifierType.CONTROL_MASK:
            self._cycle_tab(1)
            return True
        if mods & (Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.ALT_MASK | Gdk.ModifierType.SUPER_MASK):
            return False
        if keyval in (Gdk.KEY_1, Gdk.KEY_F1):
            self._switch_tab("deck")
            return True
        if keyval in (Gdk.KEY_2, Gdk.KEY_F2):
            self._switch_tab("keymap")
            return True
        if keyval in (Gdk.KEY_3, Gdk.KEY_F3):
            self._switch_tab("system")
            return True
        if keyval in (Gdk.KEY_F7, Gdk.KEY_bracketleft):
            self._cycle_tab(-1)
            return True
        if keyval in (Gdk.KEY_F8, Gdk.KEY_bracketright):
            self._cycle_tab(1)
            return True
        return False

    def _toast(self, msg):
        self.status_feedback_lbl.set_label(str(msg))
        self.status_feedback_lbl.add_css_class("status-feedback-active")
        if self._feedback_timer_id:
            GLib.source_remove(self._feedback_timer_id)
        self._feedback_timer_id = GLib.timeout_add(2600, self._reset_feedback_label)

    def _reset_feedback_label(self):
        self._feedback_timer_id = 0
        self.status_feedback_lbl.remove_css_class("status-feedback-active")
        self.status_feedback_lbl.set_label("READY  |  F16 OVERLAY  |  EXIT / ESC CLOSE  |  1-3 VIEWS")
        return GLib.SOURCE_REMOVE

    def _set_overlay_active_flag(self, active):
        try:
            if active:
                tmp = OVERLAY_SHM_PATH.with_suffix(f".{os.getpid()}")
                tmp.write_text(f"{os.getpid()}\n")
                tmp.replace(OVERLAY_SHM_PATH)
            else:
                OVERLAY_SHM_PATH.unlink(missing_ok=True)
        except OSError:
            pass
        self._send_claw_cmd("overlay-sync")

    def _connect_lifecycle(self):
        self.connect("map", lambda *_: self._on_mapped())
        self.connect("unmap", lambda *_: self._on_unmapped())
        self.connect("notify::is-active", self._on_active_changed)
        self.connect("close-request", self._on_close_request)

    def _on_active_changed(self, *_args):
        if not self.get_mapped():
            return
        if self.is_active():
            self._set_overlay_active_flag(True)

    def _on_mapped(self):
        if self._focus_loss_timer_id:
            GLib.source_remove(self._focus_loss_timer_id)
            self._focus_loss_timer_id = 0
        self._set_overlay_active_flag(True)
        self._start_polling()
        if self.get_focus() is None:
            btn = self.power_buttons.get("balanced")
            if btn is not None:
                btn.grab_focus()

    def _on_unmapped(self):
        if self._focus_loss_timer_id:
            GLib.source_remove(self._focus_loss_timer_id)
            self._focus_loss_timer_id = 0
        self._set_overlay_active_flag(False)
        self._stop_polling()

    def _on_close_request(self, _win):
        if self._focus_loss_timer_id:
            GLib.source_remove(self._focus_loss_timer_id)
            self._focus_loss_timer_id = 0
        self._set_overlay_active_flag(False)
        self._stop_polling()
        self.set_visible(False)
        return True

    def _start_polling(self):
        try:
            self.repo_btn.set_label(self._get_repo_button_label())
        except Exception:
            pass
        self._load_key_bindings()
        self._sync_key_dropdowns_ui()
        if self._timer_id == 0:
            self._refresh_telemetry()
            self._timer_id = GLib.timeout_add(2000, self._on_timer_tick)

    def _stop_polling(self):
        if self._timer_id != 0:
            GLib.source_remove(self._timer_id)
            self._timer_id = 0

    def _on_timer_tick(self):
        if not self.get_mapped():
            self._timer_id = 0
            return GLib.SOURCE_REMOVE
        self._refresh_telemetry()
        return GLib.SOURCE_CONTINUE

    # -----------------------------------------------------------------
    # Hardware & Desktop Environment Sync
    # -----------------------------------------------------------------
    def _sync_initial_controls(self):
        self._sync_key_dropdowns_ui()
        self._sync_rgb_widgets()
        self._set_bool_pair(self.gyro_pair, self.gyro_enabled, on_cls="active-mode", off_cls="active-mode")
        try:
            if self._is_plasma():
                pd_txt = read_sysfs(str(Path.home() / ".config" / "powerdevilrc"), "")
                idle_ok = False
                for blk in re.split(r"(?m)^(?=\[)", pd_txt):
                    if blk.startswith("[Battery][SuspendAndShutdown]"):
                        m_to = re.search(r"(?m)^AutoSuspendIdleTimeoutSec=(\d+)", blk)
                        if m_to:
                            idle_ok = int(m_to.group(1)) <= 300
                        break
                self._fast_idle_state = idle_ok
                ksl_txt = read_sysfs(str(Path.home() / ".config" / "kscreenlockerrc"), "")
                self._instant_wake_state = "LockOnResume=false" in ksl_txt
            else:
                src = Gio.SettingsSchemaSource.get_default()
                if src and src.lookup("org.gnome.desktop.session", True) and src.lookup("org.gnome.settings-daemon.plugins.power", True):
                    sess = Gio.Settings.new("org.gnome.desktop.session")
                    pwr = Gio.Settings.new("org.gnome.settings-daemon.plugins.power")
                    self._fast_idle_state = sess.get_uint("idle-delay") <= 120 and pwr.get_int("sleep-inactive-battery-timeout") <= 300
                if src and src.lookup("org.gnome.settings-daemon.peripherals.touchscreen", True):
                    ts = Gio.Settings.new("org.gnome.settings-daemon.peripherals.touchscreen")
                    self._orient_locked_state = ts.get_boolean("orientation-lock")
                if src and src.lookup("org.gnome.desktop.screensaver", True):
                    ss = Gio.Settings.new("org.gnome.desktop.screensaver")
                    self._instant_wake_state = not ss.get_boolean("lock-enabled")
        except Exception:
            pass
        self._set_bool_pair(self.fast_idle_pair, self._fast_idle_state, on_cls="eco-active", off_cls="active-mode")
        self._set_bool_pair(self.instant_wake_pair, self._instant_wake_state, on_cls="active-mode", off_cls="active-mode")
        self._set_bool_pair(self.orient_pair, self._orient_locked_state, on_cls="eco-active", off_cls="active-mode")
        self._sync_backlight()
        self._sync_display()

    def _is_plasma(self):
        if self._cached_is_plasma is not None:
            return self._cached_is_plasma
        de = os.environ.get("XDG_CURRENT_DESKTOP", "").lower()
        sess = os.environ.get("DESKTOP_SESSION", "").lower()
        if "kde" in de or "plasma" in sess:
            self._cached_is_plasma = True
        elif de or sess:
            self._cached_is_plasma = False
        else:
            self._cached_is_plasma = (
                subprocess.call(["pgrep", "-x", "kwin_wayland"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0
            )
        return self._cached_is_plasma

    def _is_wlroots(self):
        if self._cached_is_wlroots is not None:
            return self._cached_is_wlroots
        de = os.environ.get("XDG_CURRENT_DESKTOP", "").lower()
        sess = os.environ.get("DESKTOP_SESSION", "").lower()
        if any(k in de or k in sess for k in ("labwc", "wlroots", "sway", "river", "dwl")):
            self._cached_is_wlroots = True
        elif de or sess or self._is_plasma():
            self._cached_is_wlroots = False
        else:
            self._cached_is_wlroots = (
                subprocess.call(["pgrep", "-x", "labwc"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0
            )
        return self._cached_is_wlroots

    def _finish_dbus_call(self, bus, res, fallback_cmd=None):
        try:
            if bus is not None:
                bus.call_finish(res)
        except Exception:
            if fallback_cmd:
                self._send_claw_cmd(fallback_cmd)

    def _sync_backlight(self):
        if self._is_plasma():
            try:
                res = self.ses_bus.call_sync(
                    "org.kde.Solid.PowerManagement",
                    "/org/kde/Solid/PowerManagement/Actions/BrightnessControl",
                    "org.kde.Solid.PowerManagement.Actions.BrightnessControl",
                    "brightness",
                    None,
                    None,
                    Gio.DBusCallFlags.NONE,
                    250,
                    None,
                )
                val = int(res.unpack()[0])
                res_max = self.ses_bus.call_sync(
                    "org.kde.Solid.PowerManagement",
                    "/org/kde/Solid/PowerManagement/Actions/BrightnessControl",
                    "org.kde.Solid.PowerManagement.Actions.BrightnessControl",
                    "brightnessMax",
                    None,
                    None,
                    Gio.DBusCallFlags.NONE,
                    250,
                    None,
                )
                mx = int(res_max.unpack()[0])
                if mx > 0:
                    self.kde_bl_max = mx
                pct = max(1, min(100, round(val * 100 / max(1, mx))))
                self._bl_updating = True
                self.bl_scale.set_value(pct)
                self.bl_pct_lbl.set_label(f"{pct}%")
                self._bl_updating = False
                return
            except Exception:
                pass

        if not self._is_plasma() and not self._is_wlroots():
            try:
                res = self.ses_bus.call_sync(
                    "org.gnome.Mutter.DisplayConfig",
                    "/org/gnome/Mutter/DisplayConfig",
                    "org.freedesktop.DBus.Properties",
                    "Get",
                    GLib.Variant("(ss)", ("org.gnome.Mutter.DisplayConfig", "Backlight")),
                    GLib.VariantType.new("(v)"),
                    Gio.DBusCallFlags.NONE,
                    250,
                    None,
                )
                serial, items = res.unpack()[0]
                self.bl_serial = serial
                for item in items:
                    if item.get("connector") == "eDP-1":
                        self.bl_min = int(item.get("min", 1920))
                        self.bl_max = int(item.get("max", 192000))
                        val = int(item.get("value", 9600))
                        pct = round(((val - self.bl_min) / max(1, self.bl_max - self.bl_min)) * 99 + 1)
                        pct = max(1, min(100, pct))
                        self._bl_updating = True
                        self.bl_scale.set_value(pct)
                        self.bl_pct_lbl.set_label(f"{pct}%")
                        self._bl_updating = False
                        return
            except Exception:
                pass

        raw = int(read_sysfs("/sys/class/backlight/intel_backlight/brightness", "9600") or 9600)
        mx = int(read_sysfs("/sys/class/backlight/intel_backlight/max_brightness", "192000") or 192000)
        pct = max(1, min(100, round(raw * 100 / max(1, mx))))
        self._bl_updating = True
        self.bl_scale.set_value(pct)
        self.bl_pct_lbl.set_label(f"{pct}%")
        self._bl_updating = False

    def _on_brightness_changed(self, scale):
        if self._bl_updating:
            return
        pct = int(round(scale.get_value()))
        self.bl_pct_lbl.set_label(f"{pct}%")
        if self._bl_debounce_id:
            GLib.source_remove(self._bl_debounce_id)
        self._bl_debounce_id = GLib.timeout_add(30, self._commit_brightness, pct)

    def _commit_brightness(self, pct):
        self._bl_debounce_id = 0

        if self._is_plasma():
            try:
                raw_kde = max(1, min(self.kde_bl_max, int(round(pct * self.kde_bl_max / 100.0))))
                self.ses_bus.call(
                    "org.kde.Solid.PowerManagement",
                    "/org/kde/Solid/PowerManagement/Actions/BrightnessControl",
                    "org.kde.Solid.PowerManagement.Actions.BrightnessControl",
                    "setBrightnessSilent",
                    GLib.Variant("(i)", (raw_kde,)),
                    None,
                    Gio.DBusCallFlags.NONE,
                    250,
                    None,
                    lambda b, r: self._finish_dbus_call(b, r),
                )
                return GLib.SOURCE_REMOVE
            except Exception:
                pass

        if self._is_wlroots():
            try:
                mx = int(read_sysfs("/sys/class/backlight/intel_backlight/max_brightness", "192000") or 192000)
                raw_bl = max(100, min(mx, int(round(pct * mx / 100.0))))
                self.sys_bus.call(
                    "org.freedesktop.login1",
                    "/org/freedesktop/login1/session/auto",
                    "org.freedesktop.login1.Session",
                    "SetBrightness",
                    GLib.Variant("(ssu)", ("backlight", "intel_backlight", raw_bl)),
                    None,
                    Gio.DBusCallFlags.NONE,
                    300,
                    None,
                    lambda b, r: self._finish_dbus_call(b, r),
                )
                return GLib.SOURCE_REMOVE
            except Exception:
                pass

        raw = int(round(self.bl_min + ((pct - 1) / 99.0) * (self.bl_max - self.bl_min)))
        raw = max(self.bl_min, min(self.bl_max, raw))

        def on_got_serial(bus, res):
            try:
                reply = bus.call_finish(res)
                serial = reply.unpack()[0][0]
                self.bl_serial = serial
                self.ses_bus.call(
                    "org.gnome.Mutter.DisplayConfig",
                    "/org/gnome/Mutter/DisplayConfig",
                    "org.gnome.Mutter.DisplayConfig",
                    "SetBacklight",
                    GLib.Variant("(usi)", (self.bl_serial, "eDP-1", raw)),
                    None,
                    Gio.DBusCallFlags.NONE,
                    300,
                    None,
                    lambda _b, r: self._finish_dbus_call(bus, r),
                )
            except Exception:
                pass

        try:
            self.ses_bus.call(
                "org.gnome.Mutter.DisplayConfig",
                "/org/gnome/Mutter/DisplayConfig",
                "org.freedesktop.DBus.Properties",
                "Get",
                GLib.Variant("(ss)", ("org.gnome.Mutter.DisplayConfig", "Backlight")),
                GLib.VariantType.new("(v)"),
                Gio.DBusCallFlags.NONE,
                300,
                None,
                on_got_serial,
            )
        except Exception:
            pass
        return GLib.SOURCE_REMOVE

    def _sync_display(self):
        if self._is_plasma():
            self._sync_display_from_kscreen()
        elif self._is_wlroots():
            self._sync_display_from_wlr_randr()
        else:
            self._sync_display_from_gdctl()

    def _sync_display_from_wlr_randr(self):
        try:
            proc = Gio.Subprocess.new(
                ["wlr-randr"],
                Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_SILENCE,
            )
            proc.communicate_utf8_async(None, None, self._on_wlr_randr_show_done)
        except Exception:
            pass

    def _on_wlr_randr_show_done(self, proc, res):
        try:
            ok, stdout, _ = proc.communicate_utf8_finish(res)
            if not stdout:
                return
            sc_m = re.search(r"Scale:\s*([0-9.]+)", stdout)
            if sc_m:
                sc_val = sc_m.group(1).rstrip("0").rstrip(".") if "." in sc_m.group(1) else sc_m.group(1)
                self.current_scale = sc_val

            cur_m = re.search(r"([0-9]+x[0-9]+)\s+px,\s*([0-9.]+)\s*Hz[^\n]*current", stdout)
            if cur_m:
                self.current_res = cur_m.group(1)
                hz_f = float(cur_m.group(2))
                self.current_hz = 60 if hz_f < 90 else 120

            vrr_m = re.search(r"Adaptive Sync:\s*(\w+)", stdout, re.IGNORECASE)
            if vrr_m:
                self.current_vrr = vrr_m.group(1).lower() == "enabled"

            vrr_txt = "+VRR" if self.current_vrr else "Fixed"
            self.fan_sub.set_label(f"{self.current_res}@{self.current_hz} {vrr_txt} {self.current_scale}x")
            self._update_display_highlights()
        except Exception:
            pass

    def _sync_display_from_kscreen(self):
        try:
            proc = Gio.Subprocess.new(
                ["kscreen-doctor", "-j"],
                Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_SILENCE,
            )
            proc.communicate_utf8_async(None, None, self._on_kscreen_show_done)
        except Exception:
            pass

    def _on_kscreen_show_done(self, proc, res):
        try:
            ok, stdout, _ = proc.communicate_utf8_finish(res)
            if not stdout:
                return
            data = json.loads(stdout)
            outputs = data.get("outputs", [])
            if not outputs:
                return
            enabled_outs = [o for o in outputs if o.get("enabled")]
            edp_out = next((o for o in outputs if str(o.get("name", "")).startswith("eDP")), None)
            out = next((o for o in enabled_outs if not str(o.get("name", "")).startswith("eDP")), None) or (
                enabled_outs[0] if enabled_outs else outputs[0]
            )
            if edp_out:
                locked = int(edp_out.get("autoRotatePolicy", 1)) == 0
                if self._orient_locked_state != locked:
                    self._orient_locked_state = locked
                    self._set_bool_pair(self.orient_pair, locked, on_cls="eco-active", off_cls="active-mode")

            modes_map = {}
            modes_err = {}
            for m in out.get("modes", []):
                mw = m.get("size", {}).get("width")
                mh = m.get("size", {}).get("height")
                mrate = float(m.get("refreshRate", 0) or 0)
                mid = m.get("id")
                if mw and mh and mid is not None and mrate > 0:
                    bucket_hz = 60 if mrate < 90 else 120
                    key = (f"{mw}x{mh}", bucket_hz)
                    err = abs(mrate - bucket_hz)
                    if key not in modes_err or err < modes_err[key]:
                        modes_err[key] = err
                        modes_map[key] = str(mid)
            self._kscreen_modes = modes_map

            conn_name = str(out.get("name", "eDP-1"))
            self.current_output = conn_name
            try:
                self.current_scale = f"{float(out.get('scale', 1.5)):g}"
            except (TypeError, ValueError):
                self.current_scale = "1.5"
            cur_id = str(out.get("currentModeId"))
            exact_hz = 120
            for m in out.get("modes", []):
                if str(m.get("id")) == cur_id:
                    w = m.get("size", {}).get("width", 1920)
                    h = m.get("size", {}).get("height", 1080)
                    exact_hz = round(m.get("refreshRate", 120))
                    self.current_res = f"{w}x{h}"
                    self.current_hz = 60 if exact_hz < 90 else 120
                    break
            vrr_policy = out.get("vrrPolicy", 0)
            vrr_capable = (out.get("capabilities", 0) & 2) != 0 if isinstance(out.get("capabilities"), int) else True
            self.current_vrr = (vrr_policy != 0) and vrr_capable
            if not conn_name.startswith("eDP"):
                edp_state = "eDP Off" if (edp_out and not edp_out.get("enabled")) else "Dual"
                self.fan_sub.set_label(f"{conn_name}: {self.current_res}@{exact_hz} {edp_state}")
            else:
                vrr_txt = "+VRR" if self.current_vrr else "Fixed"
                self.fan_sub.set_label(f"{self.current_res}@{exact_hz} {vrr_txt} {self.current_scale}x")
            self._update_display_highlights()
        except Exception:
            pass

    def _sync_display_from_gdctl(self):
        try:
            proc = Gio.Subprocess.new(
                ["gdctl", "show"],
                Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_SILENCE,
            )
            proc.communicate_utf8_async(None, None, self._on_gdctl_show_done)
        except Exception:
            pass

    def _on_gdctl_show_done(self, proc, res):
        try:
            ok, stdout, _ = proc.communicate_utf8_finish(res)
            if not stdout:
                return
            sc_m = re.search(r"Scale:\s*([0-9.]+)", stdout)
            if sc_m:
                sc_val = sc_m.group(1).rstrip("0").rstrip(".") if "." in sc_m.group(1) else sc_m.group(1)
                self.current_scale = sc_val

            hz_m = re.search(r"Current mode[\s\S]*?([0-9]+x[0-9]+)@([0-9.]+)", stdout) or re.search(
                r"([0-9]+x[0-9]+)@([0-9.]+)", stdout
            )
            res_txt = self.current_res
            if hz_m:
                res_txt = hz_m.group(1)
                self.current_res = res_txt
                hz_f = float(hz_m.group(2))
                self.current_hz = 60 if hz_f < 90 else 120

            self.current_vrr = "variable" in stdout.lower() or "+vrr" in stdout.lower()
            vrr_txt = "+VRR" if self.current_vrr else "Fixed"
            self.fan_sub.set_label(f"{res_txt}@{self.current_hz} {vrr_txt} {self.current_scale}x")
            self._update_display_highlights()
        except Exception:
            pass

    def _update_display_highlights(self):
        if self.current_hz == 60:
            self.btn_60hz.add_css_class("eco-active")
            self.btn_120hz.remove_css_class("active-mode")
            self.btn_fixed.remove_css_class("active-mode")
        elif self.current_vrr:
            self.btn_60hz.remove_css_class("eco-active")
            self.btn_120hz.add_css_class("active-mode")
            self.btn_fixed.remove_css_class("active-mode")
        else:
            self.btn_60hz.remove_css_class("eco-active")
            self.btn_120hz.remove_css_class("active-mode")
            self.btn_fixed.add_css_class("active-mode")

        for rval, btn in self.res_buttons.items():
            if rval == self.current_res:
                btn.add_css_class("active-mode")
            else:
                btn.remove_css_class("active-mode")

        for sc, btn in self.scale_buttons.items():
            if sc == self.current_scale:
                btn.add_css_class("active-mode")
            else:
                btn.remove_css_class("active-mode")

    def _apply_display(self, hz, scale, vrr=True, res_override=None):
        self.current_hz = hz
        self.current_scale = str(scale)
        self.current_vrr = vrr
        if res_override:
            self.current_res = res_override
        res_txt = self.current_res or "1920x1080"
        self._update_display_highlights()

        if self._is_plasma():
            out_name = self.current_output or "eDP-1"
            vrr_pol = "automatic" if vrr else "never"
            mode_spec = self._kscreen_modes.get((res_txt, hz)) or f"{res_txt}@{hz}"
            cmd = [
                "kscreen-doctor",
                f"output.{out_name}.mode.{mode_spec}",
                f"output.{out_name}.scale.{scale}",
                f"output.{out_name}.vrrpolicy.{vrr_pol}",
            ]
            try:
                proc = Gio.Subprocess.new(
                    cmd,
                    Gio.SubprocessFlags.STDOUT_SILENCE | Gio.SubprocessFlags.STDERR_SILENCE,
                )
                proc.wait_check_async(
                    None,
                    lambda p, r: (
                        self._toast(
                            f"Applied {res_txt} @ {hz}Hz {'+VRR' if vrr else 'Fixed'} ({scale}x)"
                            if self._finish_ok(p, r)
                            else f"Display mode {res_txt}@{hz} rejected by KScreen"
                        ),
                        self._sync_display(),
                    ),
                )
            except Exception as e:
                self._toast(f"Display error: {e}")
            return

        if self._is_wlroots():
            vrr_val = "enabled" if vrr else "disabled"
            state_path = Path.home() / ".config" / "labwc" / "display-state.env"
            init_script = Path.home() / ".config" / "labwc" / "display-init.sh"
            try:
                state_path.parent.mkdir(parents=True, exist_ok=True)
                state_path.write_text(
                    f'CLAW_RES="{res_txt}"\nCLAW_HZ="{hz}"\nCLAW_SCALE="{scale}"\nCLAW_VRR="{vrr_val}"\n'
                )
                proc = Gio.Subprocess.new(
                    [str(init_script)],
                    Gio.SubprocessFlags.STDOUT_SILENCE | Gio.SubprocessFlags.STDERR_SILENCE,
                )
                proc.wait_check_async(
                    None,
                    lambda p, r: (
                        self._toast(
                            f"Applied {res_txt} @ {hz}Hz {'+VRR' if vrr else 'Fixed'} ({scale}x)"
                            if self._finish_ok(p, r)
                            else f"Display mode {res_txt}@{hz} rejected by wlr-randr"
                        ),
                        self._sync_display(),
                    ),
                )
            except Exception as e:
                self._toast(f"Display error: {e}")
            return

        suffix = "+vrr" if vrr else ""
        if res_txt == "1600x900":
            mode = f"1600x900@{59.946 if hz == 60 else 119.948}{suffix}"
        elif res_txt == "1280x720":
            mode = f"1280x720@{59.855 if hz == 60 else 119.858}{suffix}"
        else:
            mode = f"1920x1080@{60.004 if hz == 60 else 120.003}{suffix}"

        try:
            proc = Gio.Subprocess.new(
                [
                    "gdctl",
                    "set",
                    "--persistent",
                    "--logical-monitor",
                    "--primary",
                    "--scale",
                    str(scale),
                    "--monitor",
                    "eDP-1",
                    "--mode",
                    mode,
                ],
                Gio.SubprocessFlags.STDOUT_SILENCE | Gio.SubprocessFlags.STDERR_SILENCE,
            )
            proc.wait_check_async(
                None,
                lambda p, r: (
                    self._toast(
                        f"Applied {res_txt} @ {hz}Hz {'+VRR' if vrr else 'Fixed'} ({scale}x)"
                        if self._finish_ok(p, r)
                        else f"Display mode {mode} @ {scale}x rejected by Mutter"
                    ),
                    self._sync_display(),
                ),
            )
        except Exception as e:
            self._toast(f"Display error: {e}")

    # -----------------------------------------------------------------
    # Power, Cooling, Controller & RGB Actions
    # -----------------------------------------------------------------
    def _on_power_profile_clicked(self, _btn, profile):
        try:
            variant = GLib.Variant(
                "(ssv)",
                ("org.freedesktop.UPower.PowerProfiles", "ActiveProfile", GLib.Variant("s", profile)),
            )

            def on_profile_set(bus, res):
                try:
                    bus.call_finish(res)
                    self._toast(f"Power profile: {profile}")
                except Exception as e:
                    self._toast(f"Profile switch failed: {e}")
                GLib.timeout_add(350, lambda: (self._refresh_telemetry(), GLib.SOURCE_REMOVE)[1])

            self.sys_bus.call(
                "org.freedesktop.UPower.PowerProfiles",
                "/org/freedesktop/UPower/PowerProfiles",
                "org.freedesktop.DBus.Properties",
                "Set",
                variant,
                None,
                Gio.DBusCallFlags.NONE,
                1000,
                None,
                on_profile_set,
            )
            self._update_power_highlights(profile)
            try:
                xe_prof = "power_saving" if profile == "power-saver" else "base"
                for p in glob.glob("/sys/class/drm/card*/device/tile0/gt0/freq0/power_profile"):
                    Path(p).write_text(xe_prof)
            except Exception:
                pass
        except Exception as e:
            self._toast(f"Profile switch failed: {e}")

    def _update_power_highlights(self, active):
        for prof, btn in self.power_buttons.items():
            btn.remove_css_class("eco-active")
            btn.remove_css_class("active-mode")
            btn.remove_css_class("perf-active")
            if prof == active:
                if prof == "power-saver":
                    btn.add_css_class("eco-active")
                elif prof == "performance":
                    btn.add_css_class("perf-active")
                else:
                    btn.add_css_class("active-mode")

    def _send_claw_cmd(self, cmd):
        rdir = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
        tmp_path = f"{rdir}/.msi-claw-cmd.{os.getpid()}"
        dst_path = f"{rdir}/msi-claw-cmd"
        try:
            Path(tmp_path).write_text(f"{cmd}\n")
            os.replace(tmp_path, dst_path)
        except OSError:
            pass

    def _set_controller_mode(self, target):
        self._send_claw_cmd(f"mode-{target}")
        self._toast(f"Controller mode: {'Desktop Mouse/Kbd' if target == 'desktop' else 'Xbox Gamepad'}")
        GLib.timeout_add(250, lambda: (self._refresh_controller_mode(), GLib.SOURCE_REMOVE)[1])

    def _refresh_controller_mode(self):
        mode = read_sysfs(f"/dev/shm/msi-claw-mode-{os.getuid()}", "desktop")
        if mode == "gamepad":
            self.btn_mode_gamepad.add_css_class("perf-active")
            self.btn_mode_desktop.remove_css_class("active-mode")
            self.hdr_mode_btn.set_label("MODE: GAMEPAD")
            self.hdr_mode_btn.add_css_class("perf-active")
            self.hdr_mode_btn.remove_css_class("active-mode")
        else:
            self.btn_mode_desktop.add_css_class("active-mode")
            self.btn_mode_gamepad.remove_css_class("perf-active")
            self.hdr_mode_btn.set_label("MODE: DESKTOP")
            self.hdr_mode_btn.add_css_class("active-mode")
            self.hdr_mode_btn.remove_css_class("perf-active")

    def _save_handheld_rgb_pref(self, color, brightness):
        dock_raw = read_sysfs(f"/dev/shm/msi-claw-dock-{os.getuid()}", "handheld")
        if brightness > 0 or not dock_raw.startswith("docked"):
            try:
                self.rgb_cfg_path.parent.mkdir(parents=True, exist_ok=True)
                self.rgb_cfg_path.write_text(
                    json.dumps({"r": color[0], "g": color[1], "b": color[2], "brightness": brightness}) + "\n"
                )
            except OSError:
                pass

    def _update_rgb_swatch_css(self):
        r, g, b = self.rgb_color
        br = self.rgb_brightness
        hex_code = f"#{r:02X}{g:02X}{b:02X}"
        if br <= 0 or (r == 0 and g == 0 and b == 0):
            bg = "#11151d"
            self.rgb_hex_lbl.set_label("OFF (0.0W)")
        else:
            bg = f"rgb({r},{g},{b})"
            self.rgb_hex_lbl.set_label(f"{hex_code}  |  {br}%")
        self._rgb_swatch_css.load_from_string(f".rgb-swatch-bar {{ background-color: {bg}; }}")

    def _sync_rgb_widgets(self):
        self._updating_rgb_ui = True
        try:
            r, g, b = self.rgb_color
            br = self.rgb_brightness
            self.rgb_scale.set_value(br)
            self.rgb_pct_lbl.set_label(f"{br}%")
            self.rgb_r_scale.set_value(r)
            self.rgb_g_scale.set_value(g)
            self.rgb_b_scale.set_value(b)
            self.rgb_r_lbl.set_label(str(r))
            self.rgb_g_lbl.set_label(str(g))
            self.rgb_b_lbl.set_label(str(b))
            self._update_rgb_swatch_css()
        finally:
            self._updating_rgb_ui = False

    def _on_rgb_preset(self, _btn, color, brightness):
        self.rgb_color = color
        self.rgb_brightness = brightness
        self._save_handheld_rgb_pref(color, brightness)
        self._sync_rgb_widgets()
        ok, msg = self.rgb_ctrl.apply(color[0], color[1], color[2], brightness)
        if not ok:
            self._toast(msg)
        elif brightness == 0:
            self._toast("RGB Off (0.0W)")
        else:
            self._toast("RGB lighting updated")

    def _on_rgb_channel_changed(self, _scale):
        if self._updating_rgb_ui:
            return
        r = int(round(self.rgb_r_scale.get_value()))
        g = int(round(self.rgb_g_scale.get_value()))
        b = int(round(self.rgb_b_scale.get_value()))
        self.rgb_color = (r, g, b)
        self.rgb_r_lbl.set_label(str(r))
        self.rgb_g_lbl.set_label(str(g))
        self.rgb_b_lbl.set_label(str(b))
        if self.rgb_brightness == 0 and (r > 0 or g > 0 or b > 0):
            self._updating_rgb_ui = True
            self.rgb_brightness = 45
            self.rgb_scale.set_value(45)
            self.rgb_pct_lbl.set_label("45%")
            self._updating_rgb_ui = False
        self._update_rgb_swatch_css()
        self._schedule_rgb_apply()

    def _on_rgb_brightness_changed(self, scale):
        if self._updating_rgb_ui:
            return
        br = int(round(scale.get_value()))
        self.rgb_brightness = br
        self.rgb_pct_lbl.set_label(f"{br}%")
        if br > 0 and self.rgb_color == (0, 0, 0):
            self._updating_rgb_ui = True
            self.rgb_color = (0, 170, 255)
            self.rgb_r_scale.set_value(0)
            self.rgb_g_scale.set_value(170)
            self.rgb_b_scale.set_value(255)
            self.rgb_r_lbl.set_label("0")
            self.rgb_g_lbl.set_label("170")
            self.rgb_b_lbl.set_label("255")
            self._updating_rgb_ui = False
        self._update_rgb_swatch_css()
        self._schedule_rgb_apply()

    def _schedule_rgb_apply(self):
        if self._rgb_debounce_id:
            GLib.source_remove(self._rgb_debounce_id)
        self._rgb_debounce_id = GLib.timeout_add(35, self._commit_rgb)

    def _commit_rgb(self):
        self._rgb_debounce_id = 0
        r, g, b = self.rgb_color
        self._save_handheld_rgb_pref(self.rgb_color, self.rgb_brightness)
        self.rgb_ctrl.apply(r, g, b, self.rgb_brightness)
        return GLib.SOURCE_REMOVE

    @staticmethod
    def _finish_ok(proc, res):
        try:
            return proc.wait_check_finish(res)
        except Exception:
            return False

    def _set_fast_idle(self, state):
        self._fast_idle_state = bool(state)
        self._set_bool_pair(self.fast_idle_pair, self._fast_idle_state, on_cls="eco-active", off_cls="active-mode")
        if self._is_plasma():
            bat_blank = 120 if state else 300
            bat_sleep = 300 if state else 900
            for grp, key, val in [
                (("AC", "SuspendAndShutdown"), "AutoSuspendAction", "0"),
                (("AC", "Display"), "TurnOffDisplayIdleTimeoutSec", "600"),
                (("Battery", "Display"), "TurnOffDisplayIdleTimeoutSec", str(bat_blank)),
                (("Battery", "SuspendAndShutdown"), "AutoSuspendAction", "1"),
                (("Battery", "SuspendAndShutdown"), "AutoSuspendIdleTimeoutSec", str(bat_sleep)),
            ]:
                cmd = ["kwriteconfig6", "--file", "powerdevilrc"]
                for g in grp:
                    cmd.extend(["--group", g])
                cmd.extend(["--key", key, val])
                subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                self.ses_bus.call_sync(
                    "org.kde.Solid.PowerManagement",
                    "/org/kde/Solid/PowerManagement",
                    "org.kde.Solid.PowerManagement",
                    "reparseConfiguration",
                    None,
                    None,
                    Gio.DBusCallFlags.NONE,
                    250,
                    None,
                )
            except Exception:
                pass
            self._toast("Battery idle: 2m blank / 5m sleep" if state else "Battery idle: 5m blank / 15m sleep")
            return
        try:
            src = Gio.SettingsSchemaSource.get_default()
            if src and src.lookup("org.gnome.desktop.session", True) and src.lookup("org.gnome.settings-daemon.plugins.power", True):
                sess = Gio.Settings.new("org.gnome.desktop.session")
                pwr = Gio.Settings.new("org.gnome.settings-daemon.plugins.power")
                pwr.set_string("sleep-inactive-ac-type", "nothing")
                if state:
                    sess.set_uint("idle-delay", 120)
                    pwr.set_int("sleep-inactive-battery-timeout", 300)
                    self._toast("Battery idle: 2m blank / 5m sleep")
                else:
                    sess.set_uint("idle-delay", 300)
                    pwr.set_int("sleep-inactive-battery-timeout", 900)
                    self._toast("Battery idle: 5m blank / 15m sleep")
        except Exception:
            pass

    def _set_orient_lock(self, state):
        self._orient_locked_state = bool(state)
        self._set_bool_pair(self.orient_pair, self._orient_locked_state, on_cls="eco-active", off_cls="active-mode")
        if self._is_plasma() and os.path.exists("/usr/bin/kscreen-doctor"):
            try:
                cmd = (
                    ["/usr/bin/kscreen-doctor", "output.eDP-1.rotation.none", "output.eDP-1.autoRotatePolicy.never"]
                    if state
                    else ["/usr/bin/kscreen-doctor", "output.eDP-1.autoRotatePolicy.inTabletMode"]
                )
                subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                self._toast("Landscape orientation locked" if state else "Auto-rotation enabled")
            except Exception:
                pass
            return
        try:
            src = Gio.SettingsSchemaSource.get_default()
            if src and src.lookup("org.gnome.settings-daemon.peripherals.touchscreen", True):
                ts = Gio.Settings.new("org.gnome.settings-daemon.peripherals.touchscreen")
                ts.set_boolean("orientation-lock", bool(state))
                self._toast("Landscape orientation locked" if state else "Auto-rotation enabled")
        except Exception:
            pass

    def _set_instant_wake(self, state):
        self._instant_wake_state = bool(state)
        self._set_bool_pair(self.instant_wake_pair, self._instant_wake_state, on_cls="active-mode", off_cls="active-mode")
        if self._is_plasma() and os.path.exists("/usr/bin/kwriteconfig6"):
            try:
                val = "false" if state else "true"
                for key in ("LockOnResume", "Autolock"):
                    subprocess.run(
                        ["/usr/bin/kwriteconfig6", "--file", "kscreenlockerrc", "--group", "Daemon", "--key", key, val],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                subprocess.Popen(
                    ["qdbus-qt6", "org.freedesktop.ScreenSaver", "/ScreenSaver", "configure"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                self._toast("Instant wake enabled" if state else "Lock on sleep enabled")
            except Exception:
                pass
            return
        try:
            src = Gio.SettingsSchemaSource.get_default()
            if src and src.lookup("org.gnome.desktop.screensaver", True):
                ss = Gio.Settings.new("org.gnome.desktop.screensaver")
                ss.set_boolean("lock-enabled", not bool(state))
                self._toast("Instant wake enabled" if state else "Lock on sleep enabled")
        except Exception:
            pass

    def _resolve_repo_info(self):
        repo_dir = Path.home() / "msi-claw-center"
        try:
            script_real = Path(__file__).resolve()
            for cand in (script_real.parent.parent.parent, script_real.parent.parent):
                if (cand / ".git").exists():
                    repo_dir = cand
                    break
        except Exception:
            pass
        remote_url = ""
        if (repo_dir / ".git").exists():
            try:
                out = subprocess.check_output(
                    ["git", "-C", str(repo_dir), "remote", "get-url", "origin"],
                    stderr=subprocess.DEVNULL,
                    text=True,
                    timeout=0.5,
                ).strip()
                if out.startswith("git@github.com:"):
                    out = "https://github.com/" + out[len("git@github.com:") :]
                if out.endswith(".git"):
                    out = out[:-4]
                if out.startswith("http://") or out.startswith("https://"):
                    remote_url = out
            except Exception:
                pass
        return repo_dir, remote_url

    def _get_repo_button_label(self):
        _repo_dir, remote_url = self._resolve_repo_info()
        return "OPEN GITHUB REPO" if remote_url else "OPEN SOURCE DIR"

    def _on_open_repo(self, _btn):
        repo_dir, remote_url = self._resolve_repo_info()
        target_uri = remote_url if remote_url else repo_dir.as_uri()
        try:
            Gio.AppInfo.launch_default_for_uri(target_uri, None)
            self._toast("Opening repository..." if remote_url else f"Opened {repo_dir}")
        except Exception as e:
            self._toast(f"Could not open repository: {e}")

    def _on_check_fwupd_updates(self, _btn):
        if getattr(self, "_fwupd_running", False):
            return
        self._fwupd_running = True
        self.fwupd_check_btn.set_sensitive(False)
        self.fwupd_status_lbl.set_label("Checking LVFS / fwupd updates...")

        def _worker():
            try:
                res = subprocess.run(
                    ["fwupdmgr", "get-updates", "--no-unreported-check"],
                    capture_output=True,
                    text=True,
                    timeout=15,
                )
                out = res.stdout.strip()
                if "No updates available" in out or res.returncode == 2:
                    msg = "All firmware up to date (BIOS 10F / SysFW 271)"
                elif res.returncode == 0 and "Upgrade" in out:
                    msg = "Firmware updates available via fwupdmgr"
                else:
                    msg = out.splitlines()[-1] if out else "Firmware check completed"
            except subprocess.TimeoutExpired:
                msg = "Firmware update check timed out"
            except Exception as e:
                msg = f"Check failed: {e}"

            def _update_ui():
                self._fwupd_running = False
                self.fwupd_check_btn.set_sensitive(True)
                self.fwupd_status_lbl.set_label(msg)
                self._toast(msg)
                return False

            GLib.idle_add(_update_ui)

        threading.Thread(target=_worker, daemon=True).start()

    def _on_enable_fingerprint(self, _btn):
        try:
            cmd = (
                ["systemsettings", "kcm_users"]
                if self._is_plasma() and os.path.exists("/usr/bin/systemsettings")
                else ["gnome-control-center", "system", "users"]
            )
            Gio.Subprocess.new(
                cmd,
                Gio.SubprocessFlags.STDOUT_SILENCE | Gio.SubprocessFlags.STDERR_SILENCE,
            )
            self._toast("Opened Users settings for Goodix fingerprint enrollment")
        except Exception as e:
            self._toast(f"Error opening Users settings: {e}")

    def _power_setup_script(self):
        sys_script = "/usr/local/sbin/msi-claw-system-power-setup.sh"
        if os.path.isfile(sys_script) and os.access(sys_script, os.X_OK):
            return sys_script
        repo_dir, _ = self._resolve_repo_info()
        repo_script = str(repo_dir / "sbin" / "msi-claw-system-power-setup.sh")
        if os.path.isfile(repo_script) and os.access(repo_script, os.X_OK):
            return repo_script
        return sys_script

    def _ensure_polkit_agent(self):
        """Ensure a GUI Polkit Authentication Agent is running before invoking pkexec."""
        if not self._is_plasma() and not self._is_wlroots():
            return
        agent_pat = "polkit-kde-authentication-agent-1|lxpolkit|polkit-gnome-authentication-agent-1|hyprpolkitagent|xfce-polkit"
        if subprocess.call(["pgrep", "-f", agent_pat], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0:
            return
        for cand in (
            "/usr/libexec/kf6/polkit-kde-authentication-agent-1",
            "/usr/libexec/lxpolkit",
            "/usr/libexec/polkit-gnome-authentication-agent-1",
        ):
            if os.path.isfile(cand) and os.access(cand, os.X_OK):
                try:
                    subprocess.Popen(
                        [cand],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        start_new_session=True,
                    )
                    time.sleep(0.15)
                except Exception:
                    pass
                break

    def _focus_polkit_dialog_plasma(self):
        """Raise and focus KWin's Polkit authentication window above normal windows."""
        if not self._is_plasma():
            return
        rdir = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}"))
        js_path = rdir / "msi-claw-polkit-raise.js"
        try:
            js_path.write_text(
                "const wins = workspace.windowList();\n"
                "for (let i = 0; i < wins.length; i++) {\n"
                "  const w = wins[i];\n"
                "  const cls = String(w.resourceClass || '').toLowerCase();\n"
                "  if (cls.indexOf('polkit') !== -1) {\n"
                "    w.minimized = false;\n"
                "    w.keepAbove = true;\n"
                "    workspace.activeWindow = w;\n"
                "  }\n"
                "}\n"
            )
            res = self.ses_bus.call_sync(
                "org.kde.KWin",
                "/Scripting",
                "org.kde.kwin.Scripting",
                "loadScript",
                GLib.Variant("(ss)", (str(js_path), "msiclawpolkitraise")),
                GLib.VariantType.new("(i)"),
                Gio.DBusCallFlags.NONE,
                300,
                None,
            )
            sid = res.unpack()[0]
            self.ses_bus.call_sync(
                "org.kde.KWin",
                f"/Scripting/Script{sid}",
                "org.kde.kwin.Script",
                "run",
                None,
                None,
                Gio.DBusCallFlags.NONE,
                300,
                None,
            )
            self.ses_bus.call_sync(
                "org.kde.KWin",
                "/Scripting",
                "org.kde.kwin.Scripting",
                "unloadScript",
                GLib.Variant("(s)", ("msiclawpolkitraise",)),
                None,
                Gio.DBusCallFlags.NONE,
                300,
                None,
            )
        except Exception:
            pass

    def _suspend_window_for_auth(self):
        """Temporarily yield the always-on-top overlay while Polkit prompts for a sudo password."""
        self._pkexec_hide_timer_id = 0
        if self._pkexec_proc is None:
            return GLib.SOURCE_REMOVE
        if self.get_visible():
            self._restore_after_pkexec = True
            self._set_overlay_active_flag(False)
            self._stop_polling()
            self.set_visible(False)
        self._focus_polkit_dialog_plasma()
        GLib.timeout_add(160, lambda: (self._focus_polkit_dialog_plasma(), GLib.SOURCE_REMOVE)[1])
        return GLib.SOURCE_REMOVE

    def _run_pkexec(self, args_after_pkexec, on_done_cb):
        """Run a pkexec command safely without occluding or queuing behind Polkit password dialogs."""
        if self._pkexec_proc is not None:
            self._toast("Authentication prompt already active")
            self._suspend_window_for_auth()
            return
        self._ensure_polkit_agent()
        try:
            proc = Gio.Subprocess.new(
                ["pkexec", *args_after_pkexec],
                Gio.SubprocessFlags.STDOUT_SILENCE | Gio.SubprocessFlags.STDERR_SILENCE,
            )
        except Exception as e:
            self._toast(f"Privilege elevation error: {e}")
            return

        self._pkexec_proc = proc
        self._restore_after_pkexec = False
        if self._pkexec_hide_timer_id:
            GLib.source_remove(self._pkexec_hide_timer_id)
        self._pkexec_hide_timer_id = GLib.timeout_add(45, self._suspend_window_for_auth)

        def _finished(p, res):
            if self._pkexec_hide_timer_id:
                GLib.source_remove(self._pkexec_hide_timer_id)
                self._pkexec_hide_timer_id = 0
            self._pkexec_proc = None
            ok = self._finish_ok(p, res)
            if self._restore_after_pkexec:
                self._restore_after_pkexec = False
                self.set_visible(True)
                self.unminimize()
                self.present()
            on_done_cb(ok)

        proc.wait_check_async(None, _finished)

    def _on_scx_mode_clicked(self, _btn, mode):
        script = self._power_setup_script()

        def _done(ok):
            self._toast(
                f"Scheduler: {'EEVDF' if mode == 'off' else f'scx_lavd ({mode})'}"
                if ok
                else "Scheduler switch canceled or failed"
            )
            GLib.timeout_add(300, lambda: (self._refresh_telemetry(), GLib.SOURCE_REMOVE)[1])

        try:
            if os.path.exists("/usr/bin/scxcli"):
                if mode == "off":
                    self._run_pkexec(["/usr/bin/scxcli", "stop"], _done)
                elif mode == "gaming":
                    self._run_pkexec(["/usr/bin/scxcli", "run", "scx_lavd", "--performance"], _done)
                else:
                    self._run_pkexec(["/usr/bin/scxcli", "start", "scx_lavd"], _done)
                return
            if os.path.exists("/usr/bin/scxctl"):
                if mode == "off":
                    cmd = ["scxctl", "stop"]
                else:
                    scx_state = read_sysfs("/sys/kernel/sched_ext/state", "disabled")
                    sub = "switch" if scx_state == "enabled" else "start"
                    cmd = ["scxctl", sub, "--sched", "scx_lavd", "--mode", mode]
                proc = Gio.Subprocess.new(
                    cmd,
                    Gio.SubprocessFlags.STDOUT_SILENCE | Gio.SubprocessFlags.STDERR_SILENCE,
                )
                proc.wait_check_async(None, lambda p, r: _done(self._finish_ok(p, r)))
                return
            self._run_pkexec([script, "--scx", mode], _done)
        except Exception as e:
            self._toast(f"Scheduler error: {e}")

    def _set_gpu_priority(self, want_on):
        cur_on = gpu_priority_active()
        if bool(want_on) == cur_on:
            return
        target = "on" if want_on else "off"
        script = self._power_setup_script()

        def on_done(ok):
            if not ok:
                self._toast("GPU priority change canceled")
            elif target == "on":
                self._toast("GPU Priority ON (CPU capped ~3.45 GHz)")
            else:
                restored_pct = read_sysfs("/sys/devices/system/cpu/intel_pstate/max_perf_pct", "100")
                self._toast(f"GPU Priority OFF (CPU max {restored_pct}%)")
            self._refresh_telemetry()

        self._run_pkexec([script, "--gpu-priority", target], on_done)

    def _on_apply_live_fixes(self, _btn):
        script = self._power_setup_script()
        self._run_pkexec(
            [script, "--fix-all-live"],
            lambda ok: (
                self._toast("Live TuneD, LPMD, zram & scx_lavd applied" if ok else "Live fix canceled"),
                self._refresh_telemetry(),
            ),
        )

    def _on_reapply_system_setup(self, _btn):
        script = self._power_setup_script()
        self._run_pkexec(
            [script],
            lambda ok: (
                self._toast("System power & OSK setup applied" if ok else "Setup canceled"),
                self._refresh_telemetry(),
            ),
        )

    def _on_charge_limit_clicked(self, _btn, pct):
        helper = "/usr/local/sbin/msi-claw-battery-limit"

        def on_done(ok):
            if ok:
                self._update_charge_limit_highlights(pct)
                self._toast(f"Battery Charge Limit set to {pct}% (EC 0xD7)")
            else:
                lk = kernel_lockdown_mode()
                if lk:
                    self._toast(f"Blocked by Secure Boot Lockdown ({lk})")
                else:
                    self._toast(f"Failed to set {pct}% charge limit")
            GLib.timeout_add(400, lambda: (self._refresh_telemetry(), GLib.SOURCE_REMOVE)[1])

        self._run_pkexec([helper, "set", str(pct)], on_done)

    def _update_charge_limit_highlights(self, active_pct):
        for pct, btn in self.charge_limit_buttons.items():
            btn.remove_css_class("eco-active")
            btn.remove_css_class("active-mode")
            btn.remove_css_class("perf-active")
            if pct == active_pct:
                if pct <= 60:
                    btn.add_css_class("eco-active")
                else:
                    btn.add_css_class("active-mode")

    def _set_cooler_boost(self, state):
        cb_cur = read_sysfs("/run/msi-claw-cooler-boost", "off") == "on"
        if bool(state) == cb_cur:
            return
        helper = "/usr/local/sbin/msi-claw-cooler-boost"
        target = "on" if state else "off"
        self._set_bool_pair(self.cooler_boost_pair, state, on_cls="perf-active", off_cls="active-mode")

        def on_done(ok):
            if ok:
                self._toast("EC Cooler Boost ON (~8,700 RPM)" if state else "EC Cooler Boost OFF (Auto Curve)")
            else:
                self._set_bool_pair(self.cooler_boost_pair, cb_cur, on_cls="perf-active", off_cls="active-mode")
                lk = kernel_lockdown_mode()
                if lk:
                    self._toast(f"Blocked by Secure Boot Lockdown ({lk})")
                else:
                    self._toast("Cooler Boost toggle failed")
            GLib.timeout_add(350, lambda: (self._refresh_telemetry(), GLib.SOURCE_REMOVE)[1])

        self._run_pkexec([helper, target], on_done)

    def _set_gyro_enabled(self, state):
        if self._updating_gyro_ui:
            return
        self.gyro_enabled = bool(state)
        self._set_bool_pair(self.gyro_pair, self.gyro_enabled, on_cls="active-mode", off_cls="active-mode")
        self._commit_gyro_config(show_toast=True)

    def _on_gyro_sens_changed(self, scale):
        if self._updating_gyro_ui:
            return
        val = round(scale.get_value() * 2.0) / 2.0
        self.gyro_sens = max(1.0, min(10.0, val))
        self.gyro_sens_lbl.set_label(f"{self.gyro_sens:.1f}x")
        if self._gyro_debounce_id:
            GLib.source_remove(self._gyro_debounce_id)
        self._gyro_debounce_id = GLib.timeout_add(60, self._on_gyro_debounce_fire)

    def _on_gyro_debounce_fire(self):
        self._gyro_debounce_id = 0
        self._commit_gyro_config(show_toast=False)
        return GLib.SOURCE_REMOVE

    def _commit_gyro_config(self, show_toast=False):
        try:
            self.gyro_cfg_path.parent.mkdir(parents=True, exist_ok=True)
            self.gyro_cfg_path.write_text(
                json.dumps(
                    {
                        "enabled": self.gyro_enabled,
                        "sensitivity": round(self.gyro_sens, 2),
                        "mode": self.gyro_mode,
                        "invert_x": self.gyro_invert_x,
                        "invert_y": self.gyro_invert_y,
                    },
                    indent=2,
                )
                + "\n"
            )
        except OSError:
            pass
        try:
            self.ses_bus.call(
                "io.msiclaw.Controller",
                "/io/msiclaw/Controller",
                "io.msiclaw.Controller",
                "SetGyroConfig",
                GLib.Variant("(bds)", (self.gyro_enabled, float(self.gyro_sens), str(self.gyro_mode))),
                None,
                Gio.DBusCallFlags.NONE,
                250,
                None,
                lambda b, r: self._finish_dbus_call(b, r, "reload-gyro"),
            )
        except Exception:
            self._send_claw_cmd("reload-gyro")
        if show_toast:
            self._toast(f"Gyro Aim ON (Hold LT / {self.gyro_sens:.1f}x)" if self.gyro_enabled else "Gyro Aim OFF")

    def _load_key_bindings(self):
        cfg = dict(self.default_key_cfg)
        if self.keys_cfg_path.exists():
            try:
                loaded = json.loads(self.keys_cfg_path.read_text())
                if isinstance(loaded, dict):
                    for k in self.default_key_cfg:
                        val = str(loaded.get(k, "")).strip()
                        if val:
                            cfg[k] = val
            except Exception:
                pass
        self.key_cfg = cfg

    def _save_and_apply_key_bindings(self, toast_msg=None):
        try:
            self.keys_cfg_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.keys_cfg_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.key_cfg, indent=2) + "\n")
            tmp.replace(self.keys_cfg_path)
        except OSError:
            pass
        try:
            self.ses_bus.call(
                "io.msiclaw.Controller",
                "/io/msiclaw/Controller",
                "io.msiclaw.Controller",
                "ReloadKeyBindings",
                None,
                None,
                Gio.DBusCallFlags.NONE,
                250,
                None,
                lambda b, r: self._finish_dbus_call(b, r, "reload-keys"),
            )
        except Exception:
            self._send_claw_cmd("reload-keys")
        if toast_msg:
            self._toast(toast_msg)

    def _sync_key_dropdowns_ui(self):
        self._updating_keys_ui = True
        try:
            for cfg_key, (dd, opt_list) in self.key_dropdowns.items():
                cur_val = self.key_cfg.get(cfg_key, self.default_key_cfg.get(cfg_key, ""))
                sel_i = 0
                for oi, (oval, _) in enumerate(opt_list):
                    if oval == cur_val:
                        sel_i = oi
                        break
                dd.set_selected(sel_i)
        finally:
            self._updating_keys_ui = False

    def _on_key_dropdown_changed(self, dd, _pspec, cfg_key, opt_list):
        if self._updating_keys_ui:
            return
        idx = int(dd.get_selected())
        if 0 <= idx < len(opt_list):
            act_val, act_lbl = opt_list[idx]
            if self.key_cfg.get(cfg_key) != act_val:
                self.key_cfg[cfg_key] = act_val
                self._save_and_apply_key_bindings(f"Bound {cfg_key} -> {act_lbl}")

    def _on_key_preset_clicked(self, _btn, preset_name):
        if preset_name == "default":
            self.key_cfg = dict(self.default_key_cfg)
            msg = "Restored default 4-key & M1/M2 bindings"
        elif preset_name == "ab_paddles":
            self.key_cfg["m1_gamepad"] = "hw:BTN_SOUTH"
            self.key_cfg["m2_gamepad"] = "hw:BTN_EAST"
            msg = "Mapped Gamepad M1=Xbox A, M2=Xbox B (MCU)"
        elif preset_name == "r3l3_paddles":
            self.key_cfg["m1_gamepad"] = "hw:BTN_THUMBR"
            self.key_cfg["m2_gamepad"] = "hw:BTN_THUMBL"
            msg = "Mapped Gamepad M1=Xbox R3, M2=Xbox L3 (MCU)"
        elif preset_name == "desk_productivity":
            self.key_cfg["m1_desktop"] = "copy"
            self.key_cfg["m2_desktop"] = "paste"
            msg = "Mapped Desktop M1=Copy, M2=Paste"
        else:
            return
        self._sync_key_dropdowns_ui()
        self._save_and_apply_key_bindings(msg)

    # -----------------------------------------------------------------
    # Live Telemetry Loop (2s Interval When Mapped, 0% Idle When Hidden)
    # -----------------------------------------------------------------
    def _refresh_telemetry(self):
        ac_online = read_sysfs("/sys/class/power_supply/ADP1/online", "1") == "1"
        bat = "/sys/class/power_supply/BAT1"
        cap = read_sysfs(f"{bat}/capacity", "--")
        status = read_sysfs(f"{bat}/status", "Unknown")
        dock_raw = read_sysfs(f"/dev/shm/msi-claw-dock-{os.getuid()}", "handheld")
        is_docked = dock_raw.startswith("docked")
        run_chg_txt = read_sysfs("/run/msi-claw-charge-limit", "")
        if run_chg_txt:
            chg_limit_txt = run_chg_txt
        elif kernel_lockdown_mode():
            chg_limit_txt = "0"
        else:
            chg_limit_txt = read_sysfs("/var/lib/msi-claw/charge-limit", "100")
        try:
            chg_limit = int(chg_limit_txt)
        except ValueError:
            chg_limit = 100
        self._update_charge_limit_highlights(chg_limit)

        if ac_online:
            if is_docked:
                dock_conn = dock_raw.split(":", 1)[1] if ":" in dock_raw else "DOCK"
                if status in ("Not charging", "Full"):
                    self.power_badge.set_label(f"DOCK {dock_conn} BYPASS")
                else:
                    self.power_badge.set_label(f"DOCK {dock_conn} CHG")
            else:
                self.power_badge.set_label("AC CHARGING" if status == "Charging" else "AC BYPASS")
            self.power_badge.remove_css_class("badge-bat")
            self.power_badge.add_css_class("badge-ac")
        else:
            self.power_badge.set_label("ON BATTERY")
            self.power_badge.remove_css_class("badge-ac")
            self.power_badge.add_css_class("badge-bat")

        cur_ua = abs(float(read_sysfs(f"{bat}/current_now", "0") or 0))
        volt_uv = float(read_sysfs(f"{bat}/voltage_now", "0") or 0)
        pwr_uw = read_sysfs(f"{bat}/power_now", "")
        chg_now = float(read_sysfs(f"{bat}/charge_now", "0") or 0)
        chg_full = float(read_sysfs(f"{bat}/charge_full", "4707000") or 4707000)
        chg_des = float(read_sysfs(f"{bat}/charge_full_design", "4550000") or 4550000)

        watts = (abs(float(pwr_uw)) / 1e6) if pwr_uw else ((cur_ua * volt_uv) / 1e12)
        eta_str = ""
        if cur_ua > 50000 and status in ("Charging", "Discharging"):
            target_chg = chg_full * (chg_limit / 100.0) if status == "Charging" else 0.0
            hrs = (max(0.0, target_chg - chg_now) / cur_ua) if status == "Charging" else (chg_now / cur_ua)
            if 0 < hrs < 30:
                eta_str = f"{int(hrs)}h{int((hrs % 1) * 60):02d}m | "
        health = min(100, round((chg_full / max(1.0, chg_des)) * 100))

        if ac_online and status in ("Not charging", "Full") and watts < 0.2:
            self.bat_val.set_label(f"{cap}%  Bypass 0.0W")
        else:
            self.bat_val.set_label(f"{cap}%  {status} {watts:.1f}W")
        self.bat_sub.set_label(f"{eta_str}Cap {chg_limit}% | Hlth {health}%")

        # CPU, RAPL TDP & Uncore
        t_mc = float(read_sysfs(self.cpu_temp_path, "0") or 0)
        eff_pl1, eff_pl2 = get_rapl_power_limits()
        uncore_ghz = float(read_sysfs("/sys/devices/system/cpu/intel_uncore_frequency/package_00_die_00/max_freq_khz", "2800000") or 0) / 1e6
        epp = read_sysfs("/sys/devices/system/cpu/cpu0/cpufreq/energy_performance_preference", "balance")
        max_pct = int(read_sysfs("/sys/devices/system/cpu/intel_pstate/max_perf_pct", "100") or 100)

        self.cpu_val.set_label(f"{t_mc / 1000.0:.0f}°C  {eff_pl1}W / {eff_pl2}W")
        self.cpu_sub.set_label(f"Unc {uncore_ghz:.1f}G | {max_pct}% | {epp[:7]}")

        gp_active = gpu_priority_active()
        self._set_bool_pair(self.gpu_prio_pair, gp_active, on_cls="eco-active", off_cls="active-mode")
        self.gpu_cap_lbl.set_label(f"CPU CAP {max_pct}%")

        # sched_ext & Live System Status Footer
        scx_state = read_sysfs("/sys/kernel/sched_ext/state", "disabled")
        scx_ops = read_sysfs("/sys/kernel/sched_ext/root/ops", "") if scx_state == "enabled" else ""
        clean_ops = re.sub(r"^scx_", "", scx_ops.strip())
        base_ops = re.split(r"[\s_-]+", clean_ops)[0] if clean_ops else ""
        sched_lbl = f"scx_{base_ops}" if base_ops else "EEVDF"

        def apply_scx_highlight(mode_idx):
            for smode, sbtn in self.scx_buttons.items():
                sbtn.remove_css_class("active-mode")
                sbtn.remove_css_class("perf-active")
                if scx_state != "enabled" and smode == "off":
                    sbtn.add_css_class("active-mode")
                elif scx_state == "enabled":
                    if smode == "gaming" and mode_idx == 1:
                        sbtn.add_css_class("perf-active")
                    elif smode == "auto" and mode_idx != 1:
                        sbtn.add_css_class("active-mode")

        def _detect_scx_perf():
            pid = getattr(self, "_scx_pid", 0)
            if pid > 0:
                cmd_raw = read_sysfs(f"/proc/{pid}/cmdline", "")
                if "scx_lavd" in cmd_raw:
                    return 1 if "--performance" in cmd_raw else 0
                self._scx_pid = 0
            for cp in glob.glob("/proc/[0-9]*/comm"):
                if read_sysfs(cp, "") == "scx_lavd":
                    try:
                        self._scx_pid = int(cp.split("/")[2])
                        cmd_raw = read_sysfs(f"/proc/{self._scx_pid}/cmdline", "")
                        return 1 if "--performance" in cmd_raw else 0
                    except ValueError:
                        pass
            return 0

        def on_got_scx_mode(bus, res):
            try:
                apply_scx_highlight(int(bus.call_finish(res).unpack()[0]))
            except Exception:
                apply_scx_highlight(_detect_scx_perf())

        if scx_state == "enabled":
            try:
                self.sys_bus.call(
                    "org.scx.Loader",
                    "/org/scx/Loader",
                    "org.freedesktop.DBus.Properties",
                    "Get",
                    GLib.Variant("(ss)", ("org.scx.Loader", "SchedulerMode")),
                    GLib.VariantType.new("(v)"),
                    Gio.DBusCallFlags.NONE,
                    200,
                    None,
                    on_got_scx_mode,
                )
            except Exception:
                apply_scx_highlight(_detect_scx_perf())
        else:
            self._scx_pid = 0
            apply_scx_highlight(0)

        zram_raw = read_sysfs("/sys/block/zram0/comp_algorithm", "[lzo-rle]")
        zram_m = re.search(r"\[([^\]]+)\]", zram_raw)
        zram_alg = zram_m.group(1) if zram_m else zram_raw
        nvme_raw = read_sysfs("/sys/block/nvme0n1/queue/scheduler", "[none]")
        nvme_m = re.search(r"\[([^\]]+)\]", nvme_raw)
        nvme_sched = nvme_m.group(1) if nvme_m else nvme_raw
        d3c = read_sysfs("/sys/bus/pci/devices/0000:2b:00.0/d3cold_allowed", "0")
        new_status = f"{sched_lbl} | zram:{zram_alg} | nvme:{nvme_sched} | D3cold={d3c}"
        if getattr(self, "_last_sys_status", None) != new_status:
            self._last_sys_status = new_status
            self.sys_status_lbl.set_label(new_status)

        # Active PPD Profile highlight (throttled to every 3rd tick)
        self._telemetry_tick_count = getattr(self, "_telemetry_tick_count", 0) + 1
        if self._telemetry_tick_count % 3 == 1:
            def on_got_profile(bus, res):
                try:
                    reply = bus.call_finish(res)
                    active_prof = reply.unpack()[0]
                    self._update_power_highlights(active_prof)
                except Exception:
                    pass

            try:
                self.sys_bus.call(
                    "org.freedesktop.UPower.PowerProfiles",
                    "/org/freedesktop/UPower/PowerProfiles",
                    "org.freedesktop.DBus.Properties",
                    "Get",
                    GLib.Variant("(ss)", ("org.freedesktop.UPower.PowerProfiles", "ActiveProfile")),
                    GLib.VariantType.new("(v)"),
                    Gio.DBusCallFlags.NONE,
                    300,
                    None,
                    on_got_profile,
                )
            except Exception:
                pass

        # Intel Arc GPU (xe GuC PC & i915 SLPC)
        now_ts = time.monotonic()
        self.gpu_drv, self.gpu_card_dir = resolve_arc_gpu()
        if self.gpu_drv == "xe":
            gt0_dir = f"{self.gpu_card_dir}/device/tile0/gt0"
            rc6_ms = float(read_sysfs(f"{gt0_dir}/gtidle/idle_residency_ms", "0") or 0)
            max_mhz = read_sysfs(f"{gt0_dir}/freq0/max_freq", "--")
            act_mhz = read_sysfs(f"{gt0_dir}/freq0/act_freq", "") or read_sysfs(f"{gt0_dir}/freq0/cur_freq", "--")
            rc6_str = "C6 --%"
            if self._last_rc6_ms is not None and self._last_rc6_ts is not None:
                dt_ms = (now_ts - self._last_rc6_ts) * 1000.0
                if dt_ms > 100:
                    pct = max(0.0, min(100.0, ((rc6_ms - self._last_rc6_ms) / dt_ms) * 100.0))
                    rc6_str = f"C6 {pct:.0f}%"
            self._last_rc6_ms = rc6_ms
            self._last_rc6_ts = now_ts
            self.gpu_val.set_label(f"{rc6_str}  {max_mhz}M")
            self.gpu_sub.set_label(f"xe GuC | Act {act_mhz}M")
        else:
            gt0_dir = f"{self.gpu_card_dir}/gt/gt0"
            rc6_ms = float(read_sysfs(f"{gt0_dir}/rc6_residency_ms", "0") or 0)
            rc6_str = "RC6 --%"
            if self._last_rc6_ms is not None and self._last_rc6_ts is not None:
                dt_ms = (now_ts - self._last_rc6_ts) * 1000.0
                if dt_ms > 100:
                    pct = max(0.0, min(100.0, ((rc6_ms - self._last_rc6_ms) / dt_ms) * 100.0))
                    rc6_str = f"RC6 {pct:.0f}%"
            self._last_rc6_ms = rc6_ms
            self._last_rc6_ts = now_ts

            slpc_raw = read_sysfs(f"{gt0_dir}/slpc_power_profile", "[base]")
            slpc_m = re.search(r"\[([^\]]+)\]", slpc_raw)
            slpc = slpc_m.group(1) if slpc_m else slpc_raw
            boost_mhz = read_sysfs(f"{gt0_dir}/rps_boost_freq_mhz", "--")
            self.gpu_val.set_label(f"{rc6_str}  {boost_mhz}M")
            self.gpu_sub.set_label(f"i915 | SLPC {slpc}")

        # Cooling Fans, EC Cooler Boost, Gyro Aim & Controller Mode
        f1 = read_sysfs(self.fan1_path, "0")
        f2 = read_sysfs(self.fan2_path, "0")
        if (not f1 or f1 == "0") and (not f2 or f2 == "0"):
            # If fans unreadable, re-probe hwmon in case module loaded late
            _, new_f1, new_f2 = resolve_hwmon()
            if new_f1 and new_f1 != self.fan1_path:
                self.fan1_path, self.fan2_path = new_f1, new_f2
                f1 = read_sysfs(self.fan1_path, "0")
                f2 = read_sysfs(self.fan2_path, "0")
        cb_active = read_sysfs("/run/msi-claw-cooler-boost", "off") == "on"
        if not cb_active:
            try:
                if int(f1 or 0) > 7500 and int(f2 or 0) > 7500:
                    cb_active = True
            except ValueError:
                pass
        self._set_bool_pair(self.cooler_boost_pair, cb_active, on_cls="perf-active", off_cls="active-mode")
        fan_suffix = " BOOST" if cb_active else ""
        self.fan_val.set_label(f"{f1}/{f2} RPM{fan_suffix}")

        gyro_shm = read_sysfs(f"/dev/shm/msi-claw-gyro-{os.getuid()}", "")
        if gyro_shm and not self._gyro_debounce_id:
            gparts = gyro_shm.split("\t")
            if len(gparts) >= 2:
                g_en = gparts[0] == "1"
                try:
                    g_sens = max(1.0, min(10.0, float(gparts[1])))
                except ValueError:
                    g_sens = self.gyro_sens
                g_mode = gparts[2].strip() if len(gparts) >= 3 and gparts[2].strip() in ("lt_hold", "always") else self.gyro_mode
                self.gyro_mode = g_mode
                if g_en != self.gyro_enabled or abs(g_sens - self.gyro_sens) >= 0.1:
                    self.gyro_enabled = g_en
                    self.gyro_sens = g_sens
                    self._updating_gyro_ui = True
                    self._set_bool_pair(self.gyro_pair, g_en, on_cls="active-mode", off_cls="active-mode")
                    self.gyro_scale_ui.set_value(g_sens)
                    self.gyro_sens_lbl.set_label(f"{g_sens:.1f}x")
                    self._updating_gyro_ui = False

        self._refresh_controller_mode()
