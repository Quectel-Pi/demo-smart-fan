#!/usr/bin/env bash
set -euo pipefail

usage() {
    cat <<USAGE
Usage: $0 ANGLE [HOLD_SECONDS] [hold]

ANGLE           Software angle on the configured 0..270 degree scale.
HOLD_SECONDS    Keep the requested angle for this many seconds. Default: 1.
hold            Leave PWM enabled after the hold period.

Examples:
  $0 90 1 hold
  $0 60 1
USAGE
}

[ $# -ge 1 ] || { usage; exit 2; }
angle="$1"
hold_s="${2:-1}"
keep="${3:-}"

servo_range="${SERVO_RANGE_DEG:-270}"
min_angle="${SERVO_MIN_ANGLE:-20}"
max_angle="${SERVO_MAX_ANGLE:-250}"

read -r pulse_us hold_s < <(python3 - "$angle" "$hold_s" "$min_angle" "$max_angle" "$servo_range" <<'PY'
import sys
angle, hold_s, min_angle, max_angle, servo_range = map(float, sys.argv[1:])
if servo_range <= 0:
    raise SystemExit("servo range must be > 0")
if not (min_angle <= angle <= max_angle):
    raise SystemExit(f"angle {angle:g} outside software range {min_angle:g}..{max_angle:g}")
if hold_s < 0:
    raise SystemExit("hold seconds must be >= 0")
pulse_us = 500.0 + (angle / servo_range) * 2000.0
print(int(round(pulse_us)), f"{hold_s:g}")
PY
)

chip=""
for c in /sys/class/pwm/pwmchip*; do
    [ -e "$c" ] || continue
    if readlink -f "$c" | grep -q '/2ade3000\.pwm/'; then
        chip="$c"
        break
    fi
done

if [ -z "$chip" ]; then
    echo "PWM controller 2ade3000.pwm (GPIO2_D3 / PWM2_CH3_M2) not found." >&2
    exit 1
fi

pwm="$chip/pwm0"
if [ ! -d "$pwm" ]; then
    echo 0 > "$chip/export"
fi

echo 20000000 > "$pwm/period"
echo normal > "$pwm/polarity"
echo "$((pulse_us * 1000))" > "$pwm/duty_cycle"
echo 1 > "$pwm/enable"

echo "angle=${angle}deg range=${servo_range}deg pulse=${pulse_us}us hold=${hold_s}s chip=$chip"
sleep "$hold_s"

if [ "$keep" != "hold" ]; then
    echo 0 > "$pwm/enable"
    echo "PWM disabled."
fi
