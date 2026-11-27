#!/usr/bin/env bash
set -euo pipefail

usage() {
    cat <<USAGE
Usage: $0 [START_PERCENT] [END_PERCENT] [STEP_PERCENT] [SECONDS] [FREQUENCY_HZ]

Find the fan's minimum cold-start duty on 40Pin pin35 / GPIO2_C6.
Each step starts from off so the observed value is a true startup threshold.

Defaults:
  START_PERCENT    30
  END_PERCENT      70
  STEP_PERCENT     5
  SECONDS          4
  FREQUENCY_HZ     25000
USAGE
}

if [ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ]; then
    usage
    exit 0
fi

start_pct="${1:-30}"
end_pct="${2:-70}"
step_pct="${3:-5}"
hold_s="${4:-4}"
freq_hz="${5:-25000}"
pwm_id="${FAN_PWM_ID:-2add5000.pwm}"

for value in "$start_pct" "$end_pct" "$step_pct" "$hold_s" "$freq_hz"; do
    case "$value" in
        ''|*[!0-9]*) echo "all arguments must be positive integers" >&2; exit 2 ;;
    esac
done
if [ "$start_pct" -gt 100 ] || [ "$end_pct" -gt 100 ]; then
    echo "duty percentages must be in 0..100" >&2
    exit 2
fi
if [ "$start_pct" -gt "$end_pct" ] || [ "$step_pct" -lt 1 ] || [ "$hold_s" -lt 1 ] || [ "$freq_hz" -lt 1 ]; then
    echo "invalid start/end/step/seconds/frequency" >&2
    exit 2
fi

period_ns=$(( (1000000000 + freq_hz / 2) / freq_hz ))

chip=""
for c in /sys/class/pwm/pwmchip*; do
    [ -e "$c" ] || continue
    if readlink -f "$c" | grep -q "/${pwm_id}/"; then
        chip="$c"
        break
    fi
done
if [ -z "$chip" ]; then
    echo "PWM controller ${pwm_id} not found." >&2
    exit 1
fi

service_was_active=0
if command -v systemctl >/dev/null 2>&1 && systemctl is-active --quiet smart-fan; then
    service_was_active=1
    echo "Stopping smart-fan service for direct PWM control..."
    systemctl stop smart-fan
fi

pwm="$chip/pwm0"
if [ ! -d "$pwm" ]; then
    echo 0 > "$chip/export"
fi

set_off() {
    echo 0 > "$pwm/duty_cycle"
    echo 1 > "$pwm/enable"
}

cleanup() {
    rc=$?
    if [ -d "$pwm" ]; then
        set_off 2>/dev/null || true
    fi
    if [ "$service_was_active" = "1" ]; then
        echo "Starting smart-fan service again..."
        systemctl start smart-fan 2>/dev/null || true
    fi
    exit "$rc"
}
trap cleanup EXIT INT TERM

set_off
echo 0 > "$pwm/enable"
echo 0 > "$pwm/duty_cycle"
echo "$period_ns" > "$pwm/period"
echo inversed > "$pwm/polarity"
set_off

printf 'PWM chip: %s\n' "$chip"
printf 'Pin: 40Pin pin35 / GPIO2_C6 / PWM1_CH5_M2\n'
printf 'Frequency: %s Hz, polarity: inversed\n' "$freq_hz"
printf 'Each level starts from off. Watch which level first starts the fan.\n\n'

pct="$start_pct"
while [ "$pct" -le "$end_pct" ]; do
    set_off
    sleep 1
    duty_ns=$(( (period_ns * pct + 50) / 100 ))
    echo "$duty_ns" > "$pwm/duty_cycle"
    printf 'Testing %3s%%: duty_cycle=%s ns for %ss\n' "$pct" "$duty_ns" "$hold_s"
    sleep "$hold_s"
    pct=$((pct + step_pct))
done

set_off
echo
echo "Calibration complete; fan output set to off."
