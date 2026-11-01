#!/usr/bin/env bash
# Session-aware org.freedesktop.Notifications D-Bus activation wrapper
# Dispatches to mako in labwc/wlroots sessions and KDE Plasma's notification server in Plasma.
case "${XDG_CURRENT_DESKTOP:-}:${DESKTOP_SESSION:-}" in
    *labwc*|*wlroots*|*sway*)
        exec /usr/bin/mako
        ;;
esac

if pgrep -u "${UID:-$(id -u)}" -x labwc >/dev/null 2>&1 && \
   ! pgrep -u "${UID:-$(id -u)}" -x plasmashell >/dev/null 2>&1; then
    exec /usr/bin/mako
fi

exec /usr/bin/plasma_waitforname org.freedesktop.Notifications
