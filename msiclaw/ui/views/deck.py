"""
View 01: Deck View — Zero-scroll 2-column daily hardware controls.
TDP Power profiles, Kernel scheduler, Arc GPU power share, Dual-fan cooling,
Battery charge threshold, Display refresh/resolution, Backlight, Controller mode,
Gyro aiming, and Volatile RGB presets.
"""

import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk


def build_deck_view(win) -> Gtk.Widget:
    """Build View 01: Zero-scroll 2-column daily hardware deck."""
    grid = Gtk.Grid(column_homogeneous=True)
    grid.set_hexpand(True)
    grid.set_vexpand(True)

    left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=7)
    left.add_css_class("col-pane")
    left.add_css_class("col-divider")

    right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=7)
    right.add_css_class("col-pane")

    # --- LEFT 1: Power & RAPL TDP ---
    b_pwr = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
    b_pwr.add_css_class("ctrl-block")
    hdr, _ = win._make_block_header("POWER PROFILE (RAPL TDP)")
    b_pwr.append(hdr)
    pwr_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4, homogeneous=True)
    win.power_buttons = {}
    for prof, lbl in [
        ("power-saver", "ECO 11W"),
        ("balanced", "COOL 15/20W"),
        ("performance", "TURBO 20/25W"),
    ]:
        btn = Gtk.Button(label=lbl)
        btn.add_css_class("seg-btn")
        btn.connect("clicked", win._on_power_profile_clicked, prof)
        pwr_row.append(btn)
        win.power_buttons[prof] = btn
    b_pwr.append(pwr_row)
    left.append(b_pwr)

    # --- LEFT 2: Kernel Scheduler ---
    b_scx = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
    b_scx.add_css_class("ctrl-block")
    hdr, _ = win._make_block_header("KERNEL SCHEDULER (SCHED_EXT)")
    b_scx.append(hdr)
    scx_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4, homogeneous=True)
    win.scx_buttons = {}
    for smode, slbl in [
        ("auto", "LAVD AUTO"),
        ("gaming", "LAVD GAME"),
        ("off", "EEVDF"),
    ]:
        sbtn = Gtk.Button(label=slbl)
        sbtn.add_css_class("seg-btn")
        sbtn.connect("clicked", win._on_scx_mode_clicked, smode)
        scx_row.append(sbtn)
        win.scx_buttons[smode] = sbtn
    b_scx.append(scx_row)
    left.append(b_scx)

    # --- LEFT 3: Arc GPU Power Share ---
    b_gprio = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
    b_gprio.add_css_class("ctrl-block")
    hdr, win.gpu_cap_lbl = win._make_block_header("ARC GPU BUDGET SHARE", "CPU 100%")
    b_gprio.append(hdr)
    gp_row, win.gpu_prio_pair = win._make_bool_pair(
        "STANDARD CPU",
        "GPU PRIORITY",
        win._set_gpu_priority,
    )
    b_gprio.append(gp_row)
    left.append(b_gprio)

    # --- LEFT 4: EC Dual-Fan Cooling ---
    b_fan = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
    b_fan.add_css_class("ctrl-block")
    hdr, _ = win._make_block_header("EC DUAL-FAN COOLING")
    b_fan.append(hdr)
    cb_row, win.cooler_boost_pair = win._make_bool_pair(
        "AUTO CURVE",
        "MAX BOOST 8700",
        win._set_cooler_boost,
    )
    b_fan.append(cb_row)
    left.append(b_fan)

    # --- LEFT 5: Battery Charge Limit ---
    b_chg = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
    b_chg.add_css_class("ctrl-block-last")
    hdr, _ = win._make_block_header("BATTERY CHARGE CEILING (EC 0XD7)")
    b_chg.append(hdr)
    chg_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4, homogeneous=True)
    win.charge_limit_buttons = {}
    for pct, clbl in [
        (60, "60% DESK"),
        (80, "80% DOCK"),
        (100, "100% FULL"),
    ]:
        cbtn = Gtk.Button(label=clbl)
        cbtn.add_css_class("seg-btn")
        cbtn.connect("clicked", win._on_charge_limit_clicked, pct)
        chg_row.append(cbtn)
        win.charge_limit_buttons[pct] = cbtn
    b_chg.append(chg_row)
    left.append(b_chg)

    # --- RIGHT 1: Display Refresh & Resolution ---
    b_hz = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
    b_hz.add_css_class("ctrl-block")
    hdr, _ = win._make_block_header("DISPLAY REFRESH & RESOLUTION")
    b_hz.append(hdr)

    hz_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4, homogeneous=True)
    win.btn_60hz = Gtk.Button(label="60HZ VRR")
    win.btn_60hz.add_css_class("seg-btn")
    win.btn_60hz.connect("clicked", lambda *_: win._apply_display(60, win.current_scale, True, win.current_res))
    win.btn_120hz = Gtk.Button(label="120HZ VRR")
    win.btn_120hz.add_css_class("seg-btn")
    win.btn_120hz.connect("clicked", lambda *_: win._apply_display(120, win.current_scale, True, win.current_res))
    win.btn_fixed = Gtk.Button(label="120HZ FIXED")
    win.btn_fixed.add_css_class("seg-btn")
    win.btn_fixed.connect("clicked", lambda *_: win._apply_display(120, win.current_scale, False, win.current_res))
    hz_row.append(win.btn_60hz)
    hz_row.append(win.btn_120hz)
    hz_row.append(win.btn_fixed)
    b_hz.append(hz_row)

    res_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4, homogeneous=True)
    win.res_buttons = {}
    for rval, rlbl in [
        ("1920x1080", "1080P NATIVE"),
        ("1600x900", "900P BALANCED"),
        ("1280x720", "720P FAST"),
    ]:
        rb = Gtk.Button(label=rlbl)
        rb.add_css_class("seg-btn")
        rb.connect("clicked", lambda _b, r=rval: win._apply_display(win.current_hz, win.current_scale, win.current_vrr, r))
        res_row.append(rb)
        win.res_buttons[rval] = rb
    b_hz.append(res_row)
    right.append(b_hz)

    # --- RIGHT 2: Backlight Brightness ---
    b_bl = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
    b_bl.add_css_class("ctrl-block")
    hdr, win.bl_pct_lbl = win._make_block_header("BACKLIGHT BRIGHTNESS", "--%")
    b_bl.append(hdr)

    bl_steps = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4, homogeneous=True)
    for spct in (20, 45, 70, 100):
        sbtn = Gtk.Button(label=f"{spct}%")
        sbtn.add_css_class("seg-btn")
        sbtn.connect("clicked", lambda _b, p=spct: win.bl_scale.set_value(p))
        bl_steps.append(sbtn)
    b_bl.append(bl_steps)

    win.bl_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 1, 100, 1)
    win.bl_scale.set_draw_value(False)
    win.bl_scale.set_hexpand(True)
    win.bl_scale.connect("value-changed", win._on_brightness_changed)
    b_bl.append(win.bl_scale)
    right.append(b_bl)

    # --- RIGHT 3: Controller Mode & 6-Axis Gyro ---
    b_ctrl = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
    b_ctrl.add_css_class("ctrl-block")
    hdr, _ = win._make_block_header("CONTROLLER MODE & 6-AXIS GYRO")
    b_ctrl.append(hdr)

    cg_grid = Gtk.Grid(column_spacing=6, column_homogeneous=True)
    mode_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4, homogeneous=True)
    win.btn_mode_desktop = Gtk.Button(label="DESKTOP")
    win.btn_mode_desktop.add_css_class("seg-btn")
    win.btn_mode_desktop.connect("clicked", lambda *_: win._set_controller_mode("desktop"))
    win.btn_mode_gamepad = Gtk.Button(label="GAMEPAD")
    win.btn_mode_gamepad.add_css_class("seg-btn")
    win.btn_mode_gamepad.connect("clicked", lambda *_: win._set_controller_mode("gamepad"))
    mode_row.append(win.btn_mode_desktop)
    mode_row.append(win.btn_mode_gamepad)

    gyro_row, win.gyro_pair = win._make_bool_pair("GYRO OFF", "GYRO ON", win._set_gyro_enabled)
    cg_grid.attach(mode_row, 0, 0, 1, 1)
    cg_grid.attach(gyro_row, 1, 0, 1, 1)
    b_ctrl.append(cg_grid)
    right.append(b_ctrl)

    # --- RIGHT 4: Volatile RGB Quick Control ---
    b_rgb = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
    b_rgb.add_css_class("ctrl-block-last")
    hdr, win.rgb_pct_lbl = win._make_block_header("RGB LIGHTING (VOLATILE HID)", f"{win.rgb_brightness}%")
    b_rgb.append(hdr)

    rgb_presets_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4, homogeneous=True)
    for pname, col, br in [
        ("OFF", (0, 0, 0), 0),
        ("CYAN", (0, 170, 255), 35),
        ("RED", (255, 30, 30), 60),
        ("AMBER", (255, 145, 0), 50),
        ("WHITE", (235, 240, 255), 45),
    ]:
        pb = Gtk.Button(label=pname)
        pb.add_css_class("seg-btn")
        pb.connect("clicked", win._on_rgb_preset, col, br)
        rgb_presets_row.append(pb)
    b_rgb.append(rgb_presets_row)

    win.rgb_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
    win.rgb_scale.set_value(win.rgb_brightness)
    win.rgb_scale.set_draw_value(False)
    win.rgb_scale.set_hexpand(True)
    win.rgb_scale.connect("value-changed", win._on_rgb_brightness_changed)
    b_rgb.append(win.rgb_scale)
    right.append(b_rgb)

    grid.attach(left, 0, 0, 1, 1)
    grid.attach(right, 1, 0, 1, 1)

    scroll = Gtk.ScrolledWindow(
        hscrollbar_policy=Gtk.PolicyType.NEVER,
        vscrollbar_policy=Gtk.PolicyType.AUTOMATIC,
    )
    scroll.set_child(grid)
    return scroll
