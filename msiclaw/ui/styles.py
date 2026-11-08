"""
GTK4 / Libadwaita CSS Stylesheet for MSI Claw Center.
Strictly zero-icon styling, high-contrast typography, and compact layout rules.
"""

APP_CSS = """
window {
    background-color: #0b0d12;
    color: #e2e8f0;
    font-variant-numeric: tabular-nums;
}
image,
arrow {
    -gtk-icon-size: 0px;
    min-width: 0px;
    min-height: 0px;
    opacity: 0;
    margin: 0px;
    padding: 0px;
}
.deck-rail {
    background-color: #080a0e;
    border-right: 1px solid rgba(255, 255, 255, 0.08);
    padding: 10px 8px;
}
.rail-brand {
    font-size: 0.72em;
    font-weight: 800;
    letter-spacing: 0.12em;
    color: #94a3b8;
}
.rail-hint {
    font-size: 0.64em;
    font-weight: 600;
    letter-spacing: 0.06em;
    color: #475569;
}
.rail-nav-btn {
    min-height: 34px;
    border-radius: 4px;
    padding: 4px 10px;
    background-color: transparent;
    border: 1px solid transparent;
    border-left: 3px solid transparent;
    color: #8b9bb0;
    font-size: 0.78em;
    font-weight: 700;
    letter-spacing: 0.06em;
}
.rail-nav-btn:hover {
    background-color: #121620;
    color: #f1f5f9;
}
.rail-nav-btn.active-tab {
    background-color: #151b28;
    border-color: rgba(96, 165, 250, 0.22);
    border-left: 3px solid #3b82f6;
    color: #ffffff;
}
.rail-util-btn {
    min-height: 28px;
    border-radius: 4px;
    padding: 2px 6px;
    background-color: #11151f;
    border: 1px solid rgba(255, 255, 255, 0.09);
    color: #cbd5e1;
    font-size: 0.70em;
    font-weight: 700;
    letter-spacing: 0.05em;
}
.rail-util-btn:hover {
    background-color: #1a2030;
    color: #ffffff;
}
.close-win-btn {
    min-height: 28px;
    border-radius: 4px;
    padding: 2px 10px;
    background-color: #241218;
    border: 1px solid rgba(251, 113, 133, 0.45);
    color: #fecdd3;
    font-size: 0.72em;
    font-weight: 800;
    letter-spacing: 0.08em;
}
.close-win-btn:hover,
.close-win-btn:focus-visible {
    background-color: #e11d48;
    border-color: #fb7185;
    color: #ffffff;
}
.telemetry-strip {
    background-color: #0e1118;
    border-bottom: 1px solid rgba(255, 255, 255, 0.08);
    padding: 6px 10px;
}
.tele-cell {
    border-right: 1px solid rgba(255, 255, 255, 0.07);
    padding-right: 8px;
}
.tele-cell-last {
    padding-right: 4px;
}
.tele-key {
    font-size: 0.62em;
    font-weight: 800;
    letter-spacing: 0.08em;
    color: #64748b;
}
.tele-val {
    font-size: 0.84em;
    font-weight: 700;
    color: #f8fafc;
}
.tele-sub {
    font-size: 0.68em;
    font-weight: 500;
    color: #7da2d4;
}
.status-footer {
    background-color: #080a0e;
    border-top: 1px solid rgba(255, 255, 255, 0.07);
    padding: 4px 10px;
}
.status-feedback {
    font-size: 0.71em;
    font-weight: 600;
    color: #64748b;
}
.status-feedback-active {
    color: #60a5fa;
    font-weight: 700;
}
.status-sys {
    font-size: 0.69em;
    font-weight: 500;
    color: #64748b;
}
.col-pane {
    padding: 8px 10px;
}
.col-divider {
    border-right: 1px solid rgba(255, 255, 255, 0.06);
}
.ctrl-block {
    border-bottom: 1px solid rgba(255, 255, 255, 0.05);
    padding-bottom: 6px;
}
.ctrl-block-last {
    padding-bottom: 2px;
}
.group-hdr {
    font-size: 0.67em;
    font-weight: 800;
    letter-spacing: 0.08em;
    color: #7c8ca1;
}
.group-readout {
    font-size: 0.74em;
    font-weight: 700;
    color: #cbd5e1;
}
.seg-btn {
    min-height: 28px;
    border-radius: 4px;
    padding: 2px 7px;
    background-color: #131822;
    border: 1px solid rgba(255, 255, 255, 0.09);
    color: #cbd5e1;
    font-size: 0.74em;
    font-weight: 700;
    letter-spacing: 0.02em;
}
.seg-btn:hover {
    background-color: #1c2332;
    border-color: rgba(255, 255, 255, 0.18);
    color: #ffffff;
}
.seg-btn.active-mode {
    background-color: #1d4ed8;
    border-color: #60a5fa;
    color: #ffffff;
}
.seg-btn.eco-active {
    background-color: #047857;
    border-color: #34d399;
    color: #ffffff;
}
.seg-btn.perf-active {
    background-color: #b91c1c;
    border-color: #f87171;
    color: #ffffff;
}
.seg-btn:focus-visible,
.rail-nav-btn:focus-visible,
.rail-util-btn:focus-visible,
dropdown.select-field > button:focus-visible,
scale:focus-visible {
    outline: 2px solid #60a5fa;
    outline-offset: 1px;
}
.badge-ac {
    background-color: rgba(16, 185, 129, 0.14);
    color: #34d399;
    border: 1px solid rgba(52, 211, 153, 0.35);
    border-radius: 3px;
    padding: 2px 6px;
    font-weight: 700;
    font-size: 0.68em;
    letter-spacing: 0.04em;
}
.badge-bat {
    background-color: rgba(245, 158, 11, 0.14);
    color: #fbbf24;
    border: 1px solid rgba(251, 191, 36, 0.35);
    border-radius: 3px;
    padding: 2px 6px;
    font-weight: 700;
    font-size: 0.68em;
    letter-spacing: 0.04em;
}
scale {
    padding: 2px 0;
}
scale trough {
    min-height: 4px;
    border-radius: 2px;
    background-color: rgba(255, 255, 255, 0.14);
}
scale highlight {
    min-height: 4px;
    border-radius: 2px;
    background-color: #3b82f6;
}
scale slider {
    min-width: 18px;
    min-height: 18px;
    margin: -7px 0;
    border-radius: 4px;
    background-color: #f8fafc;
    border: 1px solid #0f172a;
}
scale slider:hover,
scale slider:active {
    background-color: #ffffff;
    box-shadow: 0 0 6px rgba(59, 130, 246, 0.6);
}
.bind-row {
    border-bottom: 1px solid rgba(255, 255, 255, 0.045);
    padding: 2px 0;
}
.key-tag {
    background-color: #151b26;
    border: 1px solid rgba(255, 255, 255, 0.12);
    border-radius: 3px;
    padding: 1px 5px;
    font-size: 0.68em;
    font-weight: 800;
    color: #cbd5e1;
}
.key-tag-accent {
    background-color: rgba(29, 78, 216, 0.22);
    border: 1px solid rgba(96, 165, 250, 0.4);
    border-radius: 3px;
    padding: 1px 5px;
    font-size: 0.68em;
    font-weight: 800;
    color: #93c5fd;
}
.key-tag-paddle {
    background-color: rgba(185, 28, 28, 0.22);
    border: 1px solid rgba(248, 113, 113, 0.4);
    border-radius: 3px;
    padding: 1px 5px;
    font-size: 0.68em;
    font-weight: 800;
    color: #fca5a5;
}
.bind-lbl {
    font-size: 0.74em;
    font-weight: 600;
    color: #94a3b8;
}
dropdown.select-field > button {
    min-height: 28px;
    border-radius: 4px;
    padding: 2px 8px;
    background-color: #07090d;
    border: 1px solid rgba(148, 163, 184, 0.22);
    border-right: 3px solid #3b82f6;
    color: #f1f5f9;
    font-size: 0.76em;
    font-weight: 600;
}
dropdown.select-field > button:hover {
    background-color: #0f131c;
    border-color: rgba(148, 163, 184, 0.4);
    border-right-color: #60a5fa;
}
dropdown.select-field popover contents {
    background-color: #0f131c;
    border: 1px solid rgba(148, 163, 184, 0.25);
    padding: 4px;
}
dropdown.select-field popover listview row {
    padding: 6px 10px;
    min-height: 28px;
    border-radius: 4px;
    font-size: 0.78em;
    color: #cbd5e1;
}
dropdown.select-field popover listview row:selected {
    background-color: #1d4ed8;
    color: #ffffff;
    font-weight: 700;
}
.spec-table {
    background-color: #0d1017;
    border: 1px solid rgba(255, 255, 255, 0.06);
    border-radius: 4px;
    padding: 4px 8px;
}
.spec-row {
    border-bottom: 1px solid rgba(255, 255, 255, 0.04);
    padding: 3px 0;
}
.spec-key {
    font-size: 0.71em;
    font-weight: 700;
    color: #64748b;
}
.spec-val {
    font-size: 0.72em;
    font-weight: 600;
    color: #e2e8f0;
}
.rgb-swatch-bar {
    min-height: 8px;
    border-radius: 3px;
    border: 1px solid rgba(255, 255, 255, 0.14);
}
"""
