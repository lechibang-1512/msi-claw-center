"""
Keybinding definitions, option lists, and hardware chord references for MSI Claw A1M.
"""

from typing import List, Tuple

STD_KEY_OPTS: List[Tuple[str, str]] = [
    ("toggle-center", "MSI Claw Center"),
    ("quick-settings", "Quick Settings"),
    ("toggle-osk", "Toggle Keyboard"),
    ("overview", "Overview / Apps"),
    ("toggle-mode", "Switch Mode"),
    ("gyro-hold", "Hold Gyro Aim"),
    ("toggle-gyro", "Toggle Gyro Aim"),
    ("screenshot", "Screenshot"),
    ("esc", "Escape (Esc)"),
    ("enter", "Enter / Return"),
    ("space", "Spacebar"),
    ("tab", "Tab"),
    ("backspace", "Backspace"),
    ("alt-tab", "Alt + Tab"),
    ("close-window", "Close (Alt+F4)"),
    ("copy", "Copy (Ctrl+C)"),
    ("paste", "Paste (Ctrl+V)"),
    ("mouse-left", "Left Click"),
    ("mouse-right", "Right Click"),
    ("mouse-middle", "Middle Click"),
    ("browser-back", "Back (Alt+Left)"),
    ("browser-forward", "Forward (Alt+Right)"),
    ("vol-up", "Volume Up"),
    ("vol-down", "Volume Down"),
    ("vol-mute", "Audio Mute"),
    ("bright-up", "Brightness Up"),
    ("bright-down", "Brightness Down"),
    ("disabled", "Disabled"),
]

MKEY_GP_OPTS: List[Tuple[str, str]] = [
    ("gyro-hold", "Hold Gyro Aim"),
    ("toggle-osk", "Toggle Keyboard"),
    ("hw:BTN_SOUTH", "Xbox A (HW MCU)"),
    ("hw:BTN_EAST", "Xbox B (HW MCU)"),
    ("hw:BTN_NORTH", "Xbox X (HW MCU)"),
    ("hw:BTN_WEST", "Xbox Y (HW MCU)"),
    ("hw:BTN_THUMBL", "Xbox L3 (HW MCU)"),
    ("hw:BTN_THUMBR", "Xbox R3 (HW MCU)"),
    ("hw:BTN_TL", "Xbox LB (HW MCU)"),
    ("hw:BTN_TR", "Xbox RB (HW MCU)"),
    ("hw:BTN_TL2", "Xbox LT (HW MCU)"),
    ("hw:BTN_TR2", "Xbox RT (HW MCU)"),
    ("hw:ABS_HAT0Y_UP", "D-Pad Up (HW MCU)"),
    ("hw:ABS_HAT0Y_DOWN", "D-Pad Down (HW MCU)"),
    ("hw:ABS_HAT0X_LEFT", "D-Pad Left (HW MCU)"),
    ("hw:ABS_HAT0X_RIGHT", "D-Pad Right (HW MCU)"),
    ("hw:BTN_SELECT", "Xbox View (HW MCU)"),
    ("hw:BTN_START", "Xbox Menu (HW MCU)"),
    ("hw:BTN_MODE", "Xbox Guide (HW MCU)"),
] + [opt for opt in STD_KEY_OPTS if opt[0] not in ("gyro-hold", "toggle-osk")]

BEZEL_BUTTON_DEFS: List[Tuple[str, str, str, str]] = [
    ("F16 TAP", "Center M", "f16_tap", "key-tag-accent"),
    ("VIEW+F16", "Center Chord", "f16_chord", "key-tag-accent"),
    ("F15 TAP", "Quick Menu", "f15_tap", "key-tag-accent"),
    ("VIEW+F15", "Quick Chord", "f15_chord", "key-tag-accent"),
    ("VIEW", "Desktop Tap", "view_desktop", "key-tag"),
    ("MENU", "Desktop Tap", "menu_desktop", "key-tag"),
    ("BTN A", "Desktop South", "a_desktop", "key-tag"),
    ("BTN B", "Desktop East", "b_desktop", "key-tag"),
    ("BTN X", "Desktop West", "x_desktop", "key-tag"),
    ("BTN Y", "Desktop North", "y_desktop", "key-tag"),
]

PADDLE_BUTTON_DEFS: List[Tuple[str, str, str, str]] = [
    ("M1 GAME", "Right Paddle", "m1_gamepad", "key-tag-paddle"),
    ("M1 DESK", "Right Desktop", "m1_desktop", "key-tag-paddle"),
    ("M2 GAME", "Left Paddle", "m2_gamepad", "key-tag-paddle"),
    ("M2 DESK", "Left Desktop", "m2_desktop", "key-tag-paddle"),
    ("VIEW+M1", "M1 Chord", "m1_chord", "key-tag-paddle"),
    ("VIEW+M2", "M2 Chord", "m2_chord", "key-tag-paddle"),
]

CHORD_REFERENCE_ROWS: List[Tuple[str, str]] = [
    ("VIEW + MENU", "Switch Desktop / Gamepad"),
    ("VIEW + DPAD U/D", "Volume Up / Down"),
    ("VIEW + DPAD L/R", "Brightness Down / Up"),
    ("VIEW + L3", "Toggle 6-Axis Gyro"),
    ("VIEW + A/B/X/Y", "Paste / Close / Copy / Shot"),
]
