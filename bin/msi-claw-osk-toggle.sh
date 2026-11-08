#!/usr/bin/env bash
# Toggle ultra-lightweight wvkbd-mobintl Wayland On-Screen Keyboard (~8 MB RSS)
# Features:
#  - Full-width QWERTY layout (full,special,emoji,nav) across 100% of the 7" panel for accurate thumb typing,
#    plus top Esc / Tab / Ctrl / Alt / Super / Arrow strip
#  - Automatic popup on Wayland text-input focus (--auto via zwp_input_method_v2) in Handheld Mode,
#    and --daemon-manual when docked with a physical keyboard
#  - Overlay Wayland layer so OSK appears above fuzzel password prompts & fullscreen apps
set -u

WVKBD_BIN="${HOME}/.local/bin/wvkbd-mobintl"
[[ -x "${WVKBD_BIN}" ]] || WVKBD_BIN="$(command -v wvkbd-mobintl 2>/dev/null || true)"
[[ -n "${WVKBD_BIN}" ]] || exit 1

if [[ -z "${WAYLAND_DISPLAY:-}" ]]; then
  for sock in "${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"/wayland-*; do
    if [[ -S "${sock}" ]]; then
      export WAYLAND_DISPLAY="$(basename "${sock}")"
      break
    fi
  done
fi

WVKBD_COMMON_ARGS=(
  --wayland-layer overlay
  -L 290
  -H 290
  -l landscape,landscapespecial,emoji,nav
  --landscape-layers landscape,landscapespecial,emoji,nav
  --fn "Sans Bold 16"
  --bg 10131ce8
  --fg 1f2536f0
  --fg-sp 171c2af0
  --press 00d2fffa
  --press-sp 00d2fffa
  --swipe 00a8ccfa
  --swipe-sp 00a8ccfa
  --text f2f5faff
  --text-sp 98a4bcff
  --text-press 0b0e14ff
  -R 6
)

case "${1:-toggle}" in
  --daemon)
    pkill -x wvkbd-mobintl 2>/dev/null || true
    exec "${WVKBD_BIN}" --hidden --auto "${WVKBD_COMMON_ARGS[@]}"
    ;;
  --daemon-manual)
    pkill -x wvkbd-mobintl 2>/dev/null || true
    exec "${WVKBD_BIN}" --hidden "${WVKBD_COMMON_ARGS[@]}"
    ;;
  --show)
    if pkill -USR2 -x wvkbd-mobintl 2>/dev/null; then
      exit 0
    fi
    nohup "${WVKBD_BIN}" --auto "${WVKBD_COMMON_ARGS[@]}" >/dev/null 2>&1 &
    ;;
  --hide)
    pkill -USR1 -x wvkbd-mobintl 2>/dev/null || true
    ;;
  *)
    if pkill -RTMIN -x wvkbd-mobintl 2>/dev/null; then
      exit 0
    fi
    nohup "${WVKBD_BIN}" --auto "${WVKBD_COMMON_ARGS[@]}" >/dev/null 2>&1 &
    ;;
esac
