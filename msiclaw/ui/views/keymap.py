"""
View 02: Keymap View — Compact recessed selector table for all 16 buttons,
gyro sensitivity, back-paddle presets, and built-in chord reference.
"""

import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk

from ...keymap import (
    STD_KEY_OPTS,
    MKEY_GP_OPTS,
    BEZEL_BUTTON_DEFS,
    PADDLE_BUTTON_DEFS,
    CHORD_REFERENCE_ROWS,
)


def build_keymap_view(win) -> Gtk.Widget:
    """Build View 02: Compact 2-column recessed selector table for all 16 bindings + gyro sens."""
    win._std_key_opts = STD_KEY_OPTS
    win._mkey_gp_opts = MKEY_GP_OPTS

    vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)

    # Top Preset & Gyro Sensitivity Strip
    top_bar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
    top_bar.add_css_class("col-pane")
    top_bar.add_css_class("ctrl-block")

    preset_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4, homogeneous=True)
    for plbl, pmode in [
        ("DEFAULT KEYS", "default"),
        ("M1/M2: XBOX A / B", "ab_paddles"),
        ("M1/M2: XBOX R3 / L3", "r3l3_paddles"),
        ("M1/M2: COPY / PASTE", "desk_productivity"),
    ]:
        pbtn = Gtk.Button(label=plbl)
        pbtn.add_css_class("seg-btn")
        pbtn.connect("clicked", win._on_key_preset_clicked, pmode)
        preset_row.append(pbtn)
    top_bar.append(preset_row)

    gsens_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
    gsens_lbl = Gtk.Label(label="GYRO SENSITIVITY (LT / M1 HOLD)", xalign=0.0)
    gsens_lbl.add_css_class("group-hdr")
    win.gyro_scale_ui = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 1.0, 10.0, 0.5)
    win.gyro_scale_ui.set_value(win.gyro_sens)
    win.gyro_scale_ui.set_draw_value(False)
    win.gyro_scale_ui.set_hexpand(True)
    win.gyro_sens_lbl = Gtk.Label(label=f"{win.gyro_sens:.1f}x", width_chars=5, xalign=1.0)
    win.gyro_sens_lbl.add_css_class("group-readout")
    win.gyro_scale_ui.connect("value-changed", win._on_gyro_sens_changed)
    gsens_row.append(gsens_lbl)
    gsens_row.append(win.gyro_scale_ui)
    gsens_row.append(win.gyro_sens_lbl)
    top_bar.append(gsens_row)
    vbox.append(top_bar)

    # 2-Column Compact Selector Matrix
    cols = Gtk.Grid(column_homogeneous=True)
    k_left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
    k_left.add_css_class("col-pane")
    k_left.add_css_class("col-divider")

    k_right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
    k_right.add_css_class("col-pane")

    lhdr, _ = win._make_block_header("FRONT BEZEL & DESKTOP ABXY")
    k_left.append(lhdr)
    for tag_t, desc_t, ckey, tcls in BEZEL_BUTTON_DEFS:
        k_left.append(win._make_bind_row(tag_t, desc_t, ckey, STD_KEY_OPTS, tcls))

    rhdr, _ = win._make_block_header("REAR PADDLES M1 / M2 (0MS MCU)")
    k_right.append(rhdr)
    for tag_t, desc_t, ckey, tcls in PADDLE_BUTTON_DEFS:
        opts = MKEY_GP_OPTS if "gamepad" in ckey else STD_KEY_OPTS
        k_right.append(win._make_bind_row(tag_t, desc_t, ckey, opts, tcls))

    chdr, _ = win._make_block_header("BUILT-IN GLOBAL VIEW CHORDS")
    chdr.set_margin_top(6)
    k_right.append(chdr)
    chord_tbl = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
    chord_tbl.add_css_class("spec-table")
    for ck, cv in CHORD_REFERENCE_ROWS:
        chord_tbl.append(win._make_spec_row(ck, cv))
    k_right.append(chord_tbl)

    cols.attach(k_left, 0, 0, 1, 1)
    cols.attach(k_right, 1, 0, 1, 1)
    vbox.append(cols)

    scroll = Gtk.ScrolledWindow(
        hscrollbar_policy=Gtk.PolicyType.NEVER,
        vscrollbar_policy=Gtk.PolicyType.AUTOMATIC,
    )
    scroll.set_child(vbox)
    return scroll
