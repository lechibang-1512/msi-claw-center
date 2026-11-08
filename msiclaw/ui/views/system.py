"""
View 03: System View — Fractional UI scale, handheld sleep/wake/orientation policies,
custom RGB mixer, live hardware & firmware inventory, and system maintenance actions.
"""

import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk

from ...hw import get_hardware_inventory


def build_system_view(win) -> Gtk.Widget:
    """Build View 03: UI scale, handheld locks, fine RGB channels, hardware inventory & maintenance."""
    grid = Gtk.Grid(column_homogeneous=True)
    s_left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=7)
    s_left.add_css_class("col-pane")
    s_left.add_css_class("col-divider")

    s_right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=7)
    s_right.add_css_class("col-pane")

    # --- LEFT 1: Wayland Fractional UI Scale ---
    b_scale = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
    b_scale.add_css_class("ctrl-block")
    hdr, _ = win._make_block_header("WAYLAND FRACTIONAL UI SCALE")
    b_scale.append(hdr)
    scale_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4, homogeneous=True)
    win.scale_buttons = {}
    for sc, title in [
        ("1", "1.0X"),
        ("1.25", "1.25X"),
        ("1.5", "1.5X REC"),
        ("2", "2.0X"),
    ]:
        sb = Gtk.Button(label=title)
        sb.add_css_class("seg-btn")
        sb.connect("clicked", lambda _b, s=sc: win._apply_display(win.current_hz, s, win.current_vrr, win.current_res))
        scale_row.append(sb)
        win.scale_buttons[sc] = sb
    b_scale.append(scale_row)
    s_left.append(b_scale)

    # --- LEFT 2: Idle, Wake & Orientation Policies ---
    b_pol = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
    b_pol.add_css_class("ctrl-block")
    hdr, _ = win._make_block_header("SLEEP, WAKE & ORIENTATION POLICIES")
    b_pol.append(hdr)

    idle_row, win.fast_idle_pair = win._make_bool_pair(
        "IDLE 5M / 15M",
        "FAST IDLE 2M / 5M",
        win._set_fast_idle,
    )
    wake_row, win.instant_wake_pair = win._make_bool_pair(
        "LOCK ON SLEEP",
        "INSTANT WAKE",
        win._set_instant_wake,
    )
    ori_row, win.orient_pair = win._make_bool_pair(
        "AUTO ROTATE",
        "LOCK LANDSCAPE",
        win._set_orient_lock,
    )
    b_pol.append(idle_row)
    b_pol.append(wake_row)
    b_pol.append(ori_row)
    s_left.append(b_pol)

    # --- LEFT 3: Custom RGB Channel Mixer ---
    b_mixer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
    b_mixer.add_css_class("ctrl-block-last")
    hdr, win.rgb_hex_lbl = win._make_block_header("CUSTOM RGB MIXER", "#00AAFF")
    b_mixer.append(hdr)

    win.rgb_swatch_bar = Gtk.Box()
    win.rgb_swatch_bar.add_css_class("rgb-swatch-bar")
    b_mixer.append(win.rgb_swatch_bar)

    extra_presets = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4, homogeneous=True)
    for pname, col, br in [
        ("PURPLE", (175, 50, 255), 55),
        ("EMERALD", (16, 220, 100), 50),
        ("BLUE", (30, 100, 255), 60),
        ("PINK", (255, 60, 140), 55),
    ]:
        pb = Gtk.Button(label=pname)
        pb.add_css_class("seg-btn")
        pb.connect("clicked", win._on_rgb_preset, col, br)
        extra_presets.append(pb)
    b_mixer.append(extra_presets)

    win.rgb_r_scale, win.rgb_r_lbl = win._make_rgb_channel_row(b_mixer, "R", win.rgb_color[0])
    win.rgb_g_scale, win.rgb_g_lbl = win._make_rgb_channel_row(b_mixer, "G", win.rgb_color[1])
    win.rgb_b_scale, win.rgb_b_lbl = win._make_rgb_channel_row(b_mixer, "B", win.rgb_color[2])
    s_left.append(b_mixer)

    # --- RIGHT 1: Hardware & Firmware Inventory ---
    hw_info = get_hardware_inventory()
    b_hw = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
    b_hw.add_css_class("ctrl-block")
    hdr, _ = win._make_block_header("HARDWARE & FIRMWARE INVENTORY")
    b_hw.append(hdr)

    sp_tbl = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
    sp_tbl.add_css_class("spec-table")
    for skey, sval in [
        ("MODEL", hw_info["model"]),
        ("BIOS", hw_info["bios"]),
        ("CPU", hw_info["cpu"]),
        ("GPU", hw_info["gpu"]),
        ("MCU", hw_info["mcu"]),
        ("NPU", hw_info["npu"]),
        ("WI-FI", hw_info["wifi"]),
        ("KERNEL", hw_info["kernel"]),
    ]:
        sp_tbl.append(win._make_spec_row(skey, sval))
    b_hw.append(sp_tbl)
    s_right.append(b_hw)

    # --- RIGHT 2: Firmware Verification & System Actions ---
    b_maint = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
    b_maint.add_css_class("ctrl-block-last")
    hdr, _ = win._make_block_header("MAINTENANCE & SYSTEM SETUP")
    b_maint.append(hdr)

    win.fwupd_check_btn = Gtk.Button(label="CHECK FIRMWARE UPDATES (LVFS)")
    win.fwupd_check_btn.add_css_class("seg-btn")
    win.fwupd_check_btn.connect("clicked", win._on_check_fwupd_updates)
    b_maint.append(win.fwupd_check_btn)

    win.fwupd_status_lbl = Gtk.Label(
        label="LVFS / SPI firmware verified up to date",
        xalign=0.0,
        ellipsize=3,
    )
    win.fwupd_status_lbl.add_css_class("status-sys")
    b_maint.append(win.fwupd_status_lbl)

    act_row1 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4, homogeneous=True)
    live_fix_btn = Gtk.Button(label="APPLY LIVE FIXES")
    live_fix_btn.add_css_class("seg-btn")
    live_fix_btn.add_css_class("active-mode")
    live_fix_btn.connect("clicked", win._on_apply_live_fixes)

    reapply_btn = Gtk.Button(label="FULL OSK & POWER SETUP")
    reapply_btn.add_css_class("seg-btn")
    reapply_btn.connect("clicked", win._on_reapply_system_setup)
    act_row1.append(live_fix_btn)
    act_row1.append(reapply_btn)
    b_maint.append(act_row1)

    act_row2 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4, homogeneous=True)
    fprint_btn = Gtk.Button(label="ENROLL FINGERPRINT")
    fprint_btn.add_css_class("seg-btn")
    fprint_btn.connect("clicked", win._on_enable_fingerprint)

    win.repo_btn = Gtk.Button(label=win._get_repo_button_label())
    win.repo_btn.add_css_class("seg-btn")
    win.repo_btn.connect("clicked", win._on_open_repo)
    act_row2.append(fprint_btn)
    act_row2.append(win.repo_btn)
    b_maint.append(act_row2)

    ver_lbl = Gtk.Label(label="MSI CLAW CENTER V1.3.0  |  GPL-3.0", xalign=0.0)
    ver_lbl.add_css_class("rail-hint")
    b_maint.append(ver_lbl)
    s_right.append(b_maint)

    grid.attach(s_left, 0, 0, 1, 1)
    grid.attach(s_right, 1, 0, 1, 1)

    scroll = Gtk.ScrolledWindow(
        hscrollbar_policy=Gtk.PolicyType.NEVER,
        vscrollbar_policy=Gtk.PolicyType.AUTOMATIC,
    )
    scroll.set_child(grid)
    return scroll
