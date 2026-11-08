#!/usr/bin/env bash
# Zero-RAM-when-closed Handheld Quick Settings Menu (F15) for labwc on MSI Claw A1M
set -u

if [[ -z "${WAYLAND_DISPLAY:-}" ]]; then
  for sock in "${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"/wayland-*; do
    if [[ -S "${sock}" ]]; then
      export WAYLAND_DISPLAY="$(basename "${sock}")"
      break
    fi
  done
fi

# Act as a true toggle when F15 is pressed a second time
if pkill -x fuzzel 2>/dev/null; then
  exit 0
fi

OSD_HELPER="${HOME}/.local/bin/msi-claw-osd.sh"
OSK_HELPER="${HOME}/.local/bin/msi-claw-osk-toggle.sh"
ACTION_HELPER="${HOME}/.local/bin/msi-claw-action.sh"
STATE_FILE="${HOME}/.config/labwc/display-state.env"

# Gather live status in <15ms
vol_raw=$(wpctl get-volume @DEFAULT_AUDIO_SINK@ 2>/dev/null || echo "Volume: 0.50")
vol_pct=$(awk '{printf "%d", $2 * 100}' <<< "${vol_raw}")
[[ "${vol_raw}" == *"[MUTED]"* ]] && vol_lbl="Muted (${vol_pct}%)" || vol_lbl="${vol_pct}%"

cur_b=$(cat /sys/class/backlight/intel_backlight/brightness 2>/dev/null || echo 19200)
max_b=$(cat /sys/class/backlight/intel_backlight/max_brightness 2>/dev/null || echo 192000)
br_pct=$(( (cur_b * 100 + max_b / 2) / max_b ))

bat_cap=$(cat /sys/class/power_supply/BAT1/capacity 2>/dev/null || cat /sys/class/power_supply/BAT0/capacity 2>/dev/null || echo "--")
bat_st=$(cat /sys/class/power_supply/BAT1/status 2>/dev/null || echo "")

wifi_radio=$(nmcli radio wifi 2>/dev/null || echo "enabled")
if [[ "${wifi_radio}" == "enabled" ]]; then
  wifi_ssid=$(nmcli -t -f active,ssid dev wifi 2>/dev/null | awk -F: '$1=="yes"{print $2; exit}')
  wifi_lbl="${wifi_ssid:-Disconnected}"
else
  wifi_lbl="Off"
fi

bt_pow=$(bluetoothctl show 2>/dev/null | awk '/Powered:/{print $2; exit}')
[[ "${bt_pow}" == "yes" ]] && bt_lbl="On" || bt_lbl="Off"

ctrl_mode=$(cat "/dev/shm/msi-claw-mode-$(id -u)" 2>/dev/null || echo "desktop")
ppd_prof=$(gdbus call --system --dest org.freedesktop.UPower.PowerProfiles --object-path /org/freedesktop/UPower/PowerProfiles --method org.freedesktop.DBus.Properties.Get "org.freedesktop.UPower.PowerProfiles" "ActiveProfile" 2>/dev/null | sed -n "s/.*'\([^']*\)'.*/\1/p")
if [[ -z "${ppd_prof}" ]]; then
  ppd_prof=$(gdbus call --system --dest net.hadess.PowerProfiles --object-path /net/hadess/PowerProfiles --method org.freedesktop.DBus.Properties.Get "net.hadess.PowerProfiles" "ActiveProfile" 2>/dev/null | sed -n "s/.*'\([^']*\)'.*/\1/p")
fi

CLAW_HZ="120"
CLAW_SCALE="1.5"
CLAW_VRR="enabled"
[[ -f "${STATE_FILE}" ]] && source "${STATE_FILE}"

wifi_submenu() {
  local choice
  choice=$(
    {
      if [[ "${wifi_radio}" == "enabled" ]]; then
        echo "[OFF]  Turn Wi-Fi Off"
        echo "[SCAN] Rescan & List Networks"
        nmcli -t -f IN-USE,SIGNAL,SECURITY,SSID dev wifi list --rescan no 2>/dev/null | \
          awk -F: 'NF>=4 && $4!="" { mark=($1=="*" ? "* " : "  "); printf "%s[%3s%%] %s (%s)\n", mark, $2, $4, ($3==""?"Open":$3) }'
      else
        echo "[ON]   Turn Wi-Fi On"
      fi
      echo "[BACK] Cancel"
    } | fuzzel --no-icons --dmenu --prompt="Wi-Fi > " --width=48 --lines=11
  )
  case "${choice}" in
    ""|*"[BACK]"*) return ;;
    *"Turn Wi-Fi Off"*) nmcli radio wifi off ;;
    *"Turn Wi-Fi On"*) nmcli radio wifi on ;;
    *"Rescan"*) nmcli dev wifi rescan >/dev/null 2>&1 || true; exec "$0" ;;
    *)
      ssid=$(sed -E 's/^..\[[ 0-9]+%\] (.*) \([^)]*\)$/\1/' <<< "${choice}")
      if [[ -n "${ssid}" ]]; then
        if ! nmcli dev wifi connect "${ssid}" >/dev/null 2>&1; then
          # Show OSK on overlay layer above fuzzel password prompt
          "${OSK_HELPER}" --show >/dev/null 2>&1 || true
          pass=$(fuzzel --no-icons --dmenu --password --prompt="Password (${ssid}) > " --width=46 --lines=0)
          "${OSK_HELPER}" --hide >/dev/null 2>&1 || true
          [[ -n "${pass}" ]] && nmcli dev wifi connect "${ssid}" password "${pass}" >/dev/null 2>&1 || true
        fi
      fi
      ;;
  esac
}

bt_submenu() {
  local choice
  choice=$(
    {
      if [[ "${bt_pow}" == "yes" ]]; then
        echo "[OFF]  Turn Bluetooth Off"
        bluetoothctl devices Paired 2>/dev/null | while read -r _ mac name; do
          [[ -z "${mac}" ]] && continue
          info=$(bluetoothctl info "${mac}" 2>/dev/null)
          [[ "${info}" == *"Connected: yes"* ]] && st="Connected" || st="Paired"
          echo "[DEV]  ${name} [${st}] (${mac})"
        done
      else
        echo "[ON]   Turn Bluetooth On"
      fi
      echo "[BACK] Cancel"
    } | fuzzel --no-icons --dmenu --prompt="Bluetooth > " --width=48 --lines=9
  )
  case "${choice}" in
    ""|*"[BACK]"*) return ;;
    *"Turn Bluetooth Off"*) bluetoothctl power off >/dev/null 2>&1 ;;
    *"Turn Bluetooth On"*) bluetoothctl power on >/dev/null 2>&1 ;;
    *"("*)
      mac=$(sed -n 's/.*(\([0-9A-F:]*\))$/\1/p' <<< "${choice}")
      if [[ "${choice}" == *"[Connected]"* ]]; then
        bluetoothctl disconnect "${mac}" >/dev/null 2>&1 &
      else
        bluetoothctl connect "${mac}" >/dev/null 2>&1 &
      fi
      ;;
  esac
}

selection=$(
  cat << EOF | fuzzel --no-icons --dmenu --prompt="CLAW (${bat_cap}% ${bat_st}) > " --width=48 --lines=13
[DECK]    MSI Claw Center (TDP / Display / RGB)
[MODE]    Controller Mode: ${ctrl_mode^^} (Tap to Switch)
[POWER]   Power Profile: ${ppd_prof:-balanced} (Switch Mode)
[DISPLAY] Display: ${CLAW_HZ}Hz | ${CLAW_SCALE}x | VRR ${CLAW_VRR}
[OSK]     Toggle On-Screen Keyboard (wvkbd)
[WIFI]    Wi-Fi: ${wifi_lbl}
[BT]      Bluetooth: ${bt_lbl}
[AUDIO]   Volume: ${vol_lbl}
[LIGHT]   Brightness: ${br_pct}%
[SHOT]    Screenshot (Fullscreen / Region)
[SLEEP]   Sleep (Suspend s2idle)
[SESSION] Session & Power (Log Out / Reboot / Shut Down)
[EXIT]    Close Menu
EOF
)

case "${selection}" in
  ""|*"[EXIT]"*) exit 0 ;;
  *"MSI Claw Center"*) ~/.local/bin/msi-claw-center --toggle >/dev/null 2>&1 & ;;
  *"Controller Mode"*) "${ACTION_HELPER}" toggle-mode ;;
  *"Power Profile:"*)
    pprof=$(printf "Performance (Max TDP)\nBalanced (Auto TDP)\nPower Saver (Battery Saver)\n[BACK] Cancel\n" | fuzzel --no-icons --dmenu --prompt="Power Profile > " --width=36 --lines=4)
    case "${pprof}" in
      *Performance*) "${OSD_HELPER}" power-profile performance ;;
      *Balanced*)    "${OSD_HELPER}" power-profile balanced ;;
      *"Power Saver"*) "${OSD_HELPER}" power-profile power-saver ;;
    esac
    ;;
  *"Display:"*)
    dchoice=$(printf "120Hz Smooth + VRR (1.5x Handheld)\n60Hz Battery Saver + VRR (1.5x Handheld)\n120Hz Compact (1.25x Scale)\n120Hz Large Touch (1.75x Scale)\n[BACK] Cancel\n" | fuzzel --no-icons --dmenu --prompt="Display > " --width=44 --lines=5)
    case "${dchoice}" in
      *"120Hz Smooth"*)
        printf 'CLAW_RES="1920x1080"\nCLAW_HZ="120"\nCLAW_SCALE="1.5"\nCLAW_VRR="enabled"\n' > "${STATE_FILE}"
        "${OSD_HELPER}" display-hz 120
        ;;
      *"60Hz Battery"*)
        printf 'CLAW_RES="1920x1080"\nCLAW_HZ="60"\nCLAW_SCALE="1.5"\nCLAW_VRR="enabled"\n' > "${STATE_FILE}"
        "${OSD_HELPER}" display-hz 60
        ;;
      *"1.25x"*)
        printf 'CLAW_RES="1920x1080"\nCLAW_HZ="120"\nCLAW_SCALE="1.25"\nCLAW_VRR="enabled"\n' > "${STATE_FILE}"
        "${OSD_HELPER}" display-hz 120
        ;;
      *"1.75x"*)
        printf 'CLAW_RES="1920x1080"\nCLAW_HZ="120"\nCLAW_SCALE="1.75"\nCLAW_VRR="enabled"\n' > "${STATE_FILE}"
        "${OSD_HELPER}" display-hz 120
        ;;
    esac
    ;;
  *"On-Screen Keyboard"*) "${OSK_HELPER}" ;;
  *"Wi-Fi:"*) wifi_submenu ;;
  *"Bluetooth:"*) bt_submenu ;;
  *"Volume:"*)
    vchoice=$(printf "Volume 100%%\nVolume 75%%\nVolume 50%%\nVolume 25%%\nToggle Mute\n[BACK] Cancel\n" | fuzzel --no-icons --dmenu --prompt="Volume > " --width=32 --lines=6)
    case "${vchoice}" in
      *100%*) wpctl set-mute @DEFAULT_AUDIO_SINK@ 0; wpctl set-volume @DEFAULT_AUDIO_SINK@ 1.0 ;;
      *75%*)  wpctl set-mute @DEFAULT_AUDIO_SINK@ 0; wpctl set-volume @DEFAULT_AUDIO_SINK@ 0.75 ;;
      *50%*)  wpctl set-mute @DEFAULT_AUDIO_SINK@ 0; wpctl set-volume @DEFAULT_AUDIO_SINK@ 0.50 ;;
      *25%*)  wpctl set-mute @DEFAULT_AUDIO_SINK@ 0; wpctl set-volume @DEFAULT_AUDIO_SINK@ 0.25 ;;
      *Mute*) "${OSD_HELPER}" vol-mute ;;
    esac
    ;;
  *"Brightness:"*)
    bchoice=$(printf "100%%\n75%%\n50%%\n25%%\n10%%\n[BACK] Cancel\n" | fuzzel --no-icons --dmenu --prompt="Brightness > " --width=30 --lines=6)
    if [[ "${bchoice}" != *"[BACK]"* ]]; then
      bpct=$( grep -oE '[0-9]+' <<< "${bchoice}" || true )
      if [[ -n "${bpct}" ]]; then
        max_b=$(cat /sys/class/backlight/intel_backlight/max_brightness 2>/dev/null || echo 192000)
        raw=$(( (bpct * max_b + 50) / 100 ))
        gdbus call --system --dest org.freedesktop.login1 --object-path /org/freedesktop/login1/session/auto --method org.freedesktop.login1.Session.SetBrightness "backlight" "intel_backlight" "${raw}" >/dev/null 2>&1 || true
      fi
    fi
    ;;
  *"Screenshot"*)
    schoice=$(printf "Capture Full Screen (Clipboard + Pictures)\nSelect Region (Clipboard + Pictures)\n[BACK] Cancel\n" | fuzzel --no-icons --dmenu --prompt="Screenshot > " --width=44 --lines=3)
    case "${schoice}" in
      *"Full Screen"*) sleep 0.18 && "${OSD_HELPER}" screenshot & ;;
      *"Select Region"*) sleep 0.18 && "${OSD_HELPER}" screenshot-region & ;;
    esac
    ;;
  *"Sleep"*) systemctl suspend ;;
  *"Session & Power"*)
    pchoice=$(printf "Log Out of labwc (Back to Session Picker)\nReboot MSI Claw\nShut Down MSI Claw\nCancel\n" | fuzzel --no-icons --dmenu --prompt="Session & Power > " --width=44 --lines=4)
    case "${pchoice}" in
      *"Log Out"*) labwc --exit ;;
      *"Reboot"*) systemctl reboot ;;
      *"Shut Down"*) systemctl poweroff ;;
    esac
    ;;
esac
