#!/usr/bin/env bash
set -euo pipefail

usage() {
    cat <<USAGE
Usage: $0 DUTY_PERCENT [FREQUENCY_HZ] [HOLD_SECONDS] [hold]

DUTY_PERCENT   0..100
FREQUENCY_HZ   Default: 25000
HOLD_SECONDS   Default: 2
hold           Leave PWM enabled after the hold period

Set FAN_PWM_POLARITY=normal or inversed (default: inversed).

Hardware:
  40Pin pin35 / GPIO2_C6 / PWM1_CH5_M2 / 2add5000.pwm

Examples:
  $0 50 25000 3
  $0 35 25000 5 hold
  $0 100 25000 2 hold
USAGE
}

[ $# -ge 1 ] || { usage; exit 2; }

duty_pct="$1"
freq_hz="${2:-25000}"
hold_s="${3:-2}"
keep="${4:-}"
pwm_id="${FAN_PWM_ID:-2add5000.pwm}"
polarity="${FAN_PWM_POLARITY:-inversed}"

read -r period_ns duty_ns < <(python3 - "$duty_pct" "$freq_hz" <<'PY'
import sys
duty=float(sys.argv[1]); freq=float(sys.argv[2])
if not 0 <= duty <= 100:
    raise SystemExit("duty must be in 0..100")
if not 1 <= freq <= 1_000_000:
    raise SystemExit("frequency must be in 1..1000000 Hz")
period=int(round(1_000_000_000.0/freq))
duty_ns=int(round(period*duty/100.0))
print(period, duty_ns)
PY
)

chip=""
for c in /sys/class/pwm/pwmchip*; do
    [ -e "$c" ] || continue
    if readlink -f "$c" | grep -q "/${pwm_id}/"; then
        chip="$c"
        break
    fi
done

if [ "$polarity" != "normal" ] && [ "$polarity" != "inversed" ]; then
    echo "FAN_PWM_POLARITY must be normal or inversed" >&2
    exit 2
fi

if [ -z "$chip" ]; then
    echo "PWM controller ${pwm_id} not found." >&2
    echo "Expected 40Pin pin35 = PWM1_CH5_M2 = 2add5000.pwm." >&2
    exit 1
fi

pwm="$chip/pwm0"
created=0
if [ ! -d "$pwm" ]; then
    echo 0 > "$chip/export"
    created=1
fi

cleanup() {
    rc=$?
    if [ -d "$pwm" ]; then
        echo 0 > "$pwm/duty_cycle" 2>/dev/null || true
        if [ "$polarity" = "inversed" ]; then
            echo 1 > "$pwm/enable" 2>/dev/null || true
        else
            echo 0 > "$pwm/enable" 2>/dev/null || true
        fi
        if [ "$keep" != "hold" ] && [ "$created" = "1" ] && [ "$polarity" != "inversed" ]; then
            echo 0 > "$chip/unexport" 2>/dev/null || true
        fi
    fi
    exit "$rc"
}
trap cleanup EXIT

echo 0 > "$pwm/enable"
echo 0 > "$pwm/duty_cycle"
echo "$period_ns" > "$pwm/period"
echo "$polarity" > "$pwm/polarity"
echo "$duty_ns" > "$pwm/duty_cycle"
echo 1 > "$pwm/enable"

printf 'fan pwm: duty=%s%% freq=%sHz period=%sns active=%sns polarity=%s pin=40Pin-35 chip=%s\n' \
    "$duty_pct" "$freq_hz" "$period_ns" "$duty_ns" "$polarity" "$chip"
sleep "$hold_s"

if [ "$keep" = "hold" ]; then
    trap - EXIT
    echo "PWM remains enabled."
fi
