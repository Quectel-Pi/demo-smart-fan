#!/usr/bin/env bash
set -euo pipefail

ADB_BIN="${ADB_BIN:-adb}"

if ! "$ADB_BIN" get-state >/dev/null 2>&1; then
    echo "ADB device is not available." >&2
    exit 1
fi

"$ADB_BIN" shell 'set -e
echo "[board]"
printf "model="; tr -d "\0" </proc/device-tree/model; echo
uname -a
id
echo
echo "[camera]"
v4l2-ctl --list-devices 2>/dev/null || true
echo
echo "[audio]"
arecord -l 2>/dev/null || true
echo
echo "[pwm]"
for c in /sys/class/pwm/pwmchip*; do
    [ -e "$c" ] || continue
    printf "%s -> " "$c"
    readlink -f "$c"
    printf "npwm="
    cat "$c/npwm"
done
echo
cat /sys/kernel/debug/pwm 2>/dev/null || true
echo
echo "[fan hwmon]"
for h in /sys/class/hwmon/hwmon*; do
    [ "$(cat "$h/name" 2>/dev/null)" = pwmfan ] || continue
    echo "$h"
    cat "$h/pwm1" "$h/pwm1_enable" 2>/dev/null || true
done
echo
echo "[smart-fan resources]"
du -sh /userdata/smart-fan 2>/dev/null || true
test -r /userdata/smart-fan/vendor/vosk/libvosk.so && echo "vosk_lib=ok" || echo "vosk_lib=missing"
test -d /userdata/smart-fan/models/vosk-model-small-cn-0.22 && echo "vosk_model=ok" || echo "vosk_model=missing"
test -x /userdata/smart-fan/bin/fan_vision && echo "fan_vision=ok" || echo "fan_vision=missing"
'
