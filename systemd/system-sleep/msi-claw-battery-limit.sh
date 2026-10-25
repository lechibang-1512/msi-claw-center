#!/bin/sh
case "$1" in
  post)
    /usr/local/sbin/msi-claw-battery-limit restore >/dev/null 2>&1 || true
    ;;
esac
