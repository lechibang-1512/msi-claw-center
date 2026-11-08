#!/usr/bin/env bash
# Lightweight Hardware OSD, Display/Power Preset & Screenshot helper for labwc / wlroots on MSI Claw A1M
set -u

send_osd() {
  local title="$1"
  local body="$2"
  local icon="${3:-preferences-system-symbolic}"
  local val="${4:-}"
  local hints="{'x-canonical-private-synchronous': <'msi-claw-osd'>}"
  if [[ -n "${val}" ]]; then
    hints="{'x-canonical-private-synchronous': <'msi-claw-osd'>, 'value': <int32 ${val}>}"
  fi
  gdbus call --session \
    --dest org.freedesktop.Notifications \
    --object-path /org/freedesktop/Notifications \
    --method org.freedesktop.Notifications.Notify \
    "MSI Claw OSD" 0 "${icon}" "${title}" "${body}" \
    "[]" "${hints}" 1600 >/dev/null 2>&1 || true
}

set_logind_brightness_pct() {
  local target_pct="$1"
  (( target_pct < 2 )) && target_pct=2
  (( target_pct > 100 )) && target_pct=100
  local max_b
  max_b=$(cat /sys/class/backlight/intel_backlight/max_brightness 2>/dev/null || echo 192000)
  local raw=$(( (target_pct * max_b + 50) / 100 ))
  (( raw < 100 )) && raw=100
  if command -v brightnessctl >/dev/null 2>&1 && [[ -w /sys/class/backlight/intel_backlight/brightness ]]; then
    brightnessctl -q -d intel_backlight set "${target_pct}%" >/dev/null 2>&1 || true
  else
    gdbus call --system \
      --dest org.freedesktop.login1 \
      --object-path /org/freedesktop/login1/session/auto \
      --method org.freedesktop.login1.Session.SetBrightness \
      "backlight" "intel_backlight" "${raw}" >/dev/null 2>&1 || \
      brightnessctl -q -d intel_backlight set "${target_pct}%" >/dev/null 2>&1 || true
  fi
  echo "${target_pct}"
}

get_brightness_pct() {
  local cur max_b
  cur=$(cat /sys/class/backlight/intel_backlight/brightness 2>/dev/null || echo 19200)
  max_b=$(cat /sys/class/backlight/intel_backlight/max_brightness 2>/dev/null || echo 192000)
  echo $(( (cur * 100 + max_b / 2) / max_b ))
}

case "${1:-}" in
  vol-up)
    wpctl set-mute @DEFAULT_AUDIO_SINK@ 0 >/dev/null 2>&1 || true
    wpctl set-volume -l 1.0 @DEFAULT_AUDIO_SINK@ 5%+ >/dev/null 2>&1 || true
    vol_raw=$(wpctl get-volume @DEFAULT_AUDIO_SINK@ 2>/dev/null || echo "Volume: 0.50")
    pct=$(awk '{printf "%d", $2 * 100}' <<< "${vol_raw}")
    send_osd "Volume" "${pct}%" "audio-volume-high-symbolic" "${pct}"
    ;;
  vol-down)
    wpctl set-volume @DEFAULT_AUDIO_SINK@ 5%- >/dev/null 2>&1 || true
    vol_raw=$(wpctl get-volume @DEFAULT_AUDIO_SINK@ 2>/dev/null || echo "Volume: 0.50")
    pct=$(awk '{printf "%d", $2 * 100}' <<< "${vol_raw}")
    send_osd "Volume" "${pct}%" "audio-volume-medium-symbolic" "${pct}"
    ;;
  vol-mute)
    wpctl set-mute @DEFAULT_AUDIO_SINK@ toggle >/dev/null 2>&1 || true
    vol_raw=$(wpctl get-volume @DEFAULT_AUDIO_SINK@ 2>/dev/null || echo "")
    if [[ "${vol_raw}" == *"[MUTED]"* ]]; then
      send_osd "Audio" "Muted" "audio-volume-muted-symbolic" "0"
    else
      pct=$(awk '{printf "%d", $2 * 100}' <<< "${vol_raw}")
      send_osd "Volume" "Unmuted (${pct}%)" "audio-volume-high-symbolic" "${pct}"
    fi
    ;;
  bright-up)
    cur=$(get_brightness_pct)
    npct=$(set_logind_brightness_pct $(( cur + 5 )))
    send_osd "Brightness" "${npct}%" "display-brightness-symbolic" "${npct}"
    ;;
  bright-down)
    cur=$(get_brightness_pct)
    npct=$(set_logind_brightness_pct $(( cur - 5 )))
    send_osd "Brightness" "${npct}%" "display-brightness-symbolic" "${npct}"
    ;;
  screenshot)
    shot_dir="${HOME}/Pictures/Screenshots"
    mkdir -p "${shot_dir}"
    shot_file="${shot_dir}/Claw_$(date +%Y%m%d_%H%M%S).png"
    if grim "${shot_file}"; then
      wl-copy < "${shot_file}" 2>/dev/null || true
      send_osd "Screenshot Saved" "$(basename "${shot_file}") (copied to clipboard)" "camera-photo-symbolic"
    fi
    ;;
  screenshot-region)
    shot_dir="${HOME}/Pictures/Screenshots"
    mkdir -p "${shot_dir}"
    shot_file="${shot_dir}/Claw_Region_$(date +%Y%m%d_%H%M%S).png"
    geom=$(slurp 2>/dev/null || true)
    if [[ -n "${geom}" ]] && grim -g "${geom}" "${shot_file}"; then
      wl-copy < "${shot_file}" 2>/dev/null || true
      send_osd "Region Screenshot Saved" "$(basename "${shot_file}") (copied to clipboard)" "camera-photo-symbolic"
    fi
    ;;
  display-hz)
    state_file="${HOME}/.config/labwc/display-state.env"
    CLAW_RES="1920x1080"
    CLAW_HZ="120"
    CLAW_SCALE="1.5"
    CLAW_VRR="enabled"
    [[ -f "${state_file}" ]] && source "${state_file}"
    target_hz="${2:-toggle}"
    if [[ "${target_hz}" == "toggle" ]]; then
      [[ "${CLAW_HZ}" == "120" ]] && target_hz="60" || target_hz="120"
    fi
    cat > "${state_file}" <<EOF
CLAW_RES="${CLAW_RES}"
CLAW_HZ="${target_hz}"
CLAW_SCALE="${CLAW_SCALE}"
CLAW_VRR="${CLAW_VRR}"
EOF
    "${HOME}/.config/labwc/display-init.sh" >/dev/null 2>&1 || true
    send_osd "Display Refresh Rate" "${CLAW_RES} @ ${target_hz}Hz (${CLAW_SCALE}x · VRR ${CLAW_VRR})" "video-display-symbolic"
    ;;
  power-profile)
    cur_prof=$(
      gdbus call --system --dest org.freedesktop.UPower.PowerProfiles --object-path /org/freedesktop/UPower/PowerProfiles --method org.freedesktop.DBus.Properties.Get "org.freedesktop.UPower.PowerProfiles" "ActiveProfile" 2>/dev/null | sed -n "s/.*'\([^']*\)'.*/\1/p"
    )
    if [[ -z "${cur_prof}" ]]; then
      cur_prof=$(
        gdbus call --system --dest net.hadess.PowerProfiles --object-path /net/hadess/PowerProfiles --method org.freedesktop.DBus.Properties.Get "net.hadess.PowerProfiles" "ActiveProfile" 2>/dev/null | sed -n "s/.*'\([^']*\)'.*/\1/p"
      )
    fi
    target_prof="${2:-cycle}"
    if [[ "${target_prof}" == "cycle" ]]; then
      case "${cur_prof}" in
        power-saver) target_prof="balanced" ;;
        balanced)    target_prof="performance" ;;
        *)           target_prof="power-saver" ;;
      esac
    fi
    gdbus call --system \
      --dest org.freedesktop.UPower.PowerProfiles \
      --object-path /org/freedesktop/UPower/PowerProfiles \
      --method org.freedesktop.DBus.Properties.Set \
      "org.freedesktop.UPower.PowerProfiles" "ActiveProfile" "<'${target_prof}'>" >/dev/null 2>&1 || \
    gdbus call --system \
      --dest net.hadess.PowerProfiles \
      --object-path /net/hadess/PowerProfiles \
      --method org.freedesktop.DBus.Properties.Set \
      "net.hadess.PowerProfiles" "ActiveProfile" "<'${target_prof}'>" >/dev/null 2>&1 || true
    send_osd "Power Profile" "${target_prof^}" "power-profile-${target_prof}-symbolic"
    ;;
esac
