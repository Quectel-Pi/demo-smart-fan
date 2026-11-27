#!/usr/bin/env bash
set -euo pipefail

usage() {
    cat <<USAGE
Usage: $0 [FREQUENCY_HZ] [SECONDS_PER_STEP] [POLARITY]

Automatically tests the fan on 40Pin pin35 / GPIO2_C6 / PWM1_CH5_M2:
  off -> 70% -> 80% -> 90% -> 100% -> off

Defaults:
  FREQUENCY_HZ      25000
  SECONDS_PER_STEP  6

  POLARITY          normal or inversed (default: inversed)

The smart-fan service is stopped for the test and started again afterwards.
USAGE
}

if [ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ]; then
    usage
    exit 0
fi

freq_hz="${1:-25000}"
step_s="${2:-6}"
polarity="${3:-inversed}"
pwm_id="${FAN_PWM_ID:-2add5000.pwm}"

case "$freq_hz" in
    ''|*[!0-9]*) echo "frequency must be an integer" >&2; exit 2 ;;
esac
case "$step_s" in
    ''|*[!0-9]*) echo "seconds per step must be an integer" >&2; exit 2 ;;
esac
if [ "$freq_hz" -lt 1 ] || [ "$freq_hz" -gt 1000000 ]; then
    echo "frequency must be in 1..1000000 Hz" >&2
    exit 2
fi
if [ "$step_s" -lt 1 ]; then
    echo "seconds per step must be at least 1" >&2
    exit 2
fi
if [ "$polarity" != "normal" ] && [ "$polarity" != "inversed" ]; then
    echo "polarity must be normal or inversed" >&2
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
    echo "Expected 40Pin pin35 = PWM1_CH5_M2 = 2add5000.pwm." >&2
    exit 1
fi

service_was_active=0
if command -v systemctl >/dev/null 2>&1 && systemctl is-active --quiet smart-fan; then
    service_was_active=1
    echo "Stopping smart-fan service for direct PWM control..."
    systemctl stop smart-fan
fi

pwm="$chip/pwm0"
created=0
cleanup() {
    rc=$?
    if [ -d "$pwm" ]; then
        echo 0 > "$pwm/duty_cycle" 2>/dev/null || true
        if [ "$polarity" = "inversed" ]; then
            # Active-low input is off while the signal stays high.
            echo 1 > "$pwm/enable" 2>/dev/null || true
        else
            echo 0 > "$pwm/enable" 2>/dev/null || true
            if [ "$created" = "1" ]; then
                echo 0 > "$chip/unexport" 2>/dev/null || true
            fi
        fi
    fi
    if [ "$service_was_active" = "1" ]; then
        echo "Starting smart-fan service again..."
        systemctl start smart-fan 2>/dev/null || true
    fi
    exit "$rc"
}
trap cleanup EXIT INT TERM

if [ ! -d "$pwm" ]; then
    echo 0 > "$chip/export"
    created=1
fi

echo 0 > "$pwm/enable"
echo 0 > "$pwm/duty_cycle"
echo "$period_ns" > "$pwm/period"
echo "$polarity" > "$pwm/polarity"

printf 'PWM chip: %s\n' "$chip"
printf 'Pin: 40Pin pin35 / GPIO2_C6 / PWM1_CH5_M2\n'
printf 'Frequency: %s Hz, period: %s ns, polarity: %s\n\n' "$freq_hz" "$period_ns" "$polarity"

for entry in "off:0" "low:70" "medium:80" "high:90" "max:100"; do
    level="${entry%%:*}"
    percent="${entry##*:}"
    duty_ns=$(( (period_ns * percent + 50) / 100 ))

    echo 0 > "$pwm/enable"
    echo "$duty_ns" > "$pwm/duty_cycle"
    if [ "$percent" -gt 0 ] || [ "$polarity" = "inversed" ]; then
        echo 1 > "$pwm/enable"
    fi

    read_period=$(cat "$pwm/period")
    read_duty=$(cat "$pwm/duty_cycle")
    read_enable=$(cat "$pwm/enable")
    if [ "$read_period" != "$period_ns" ] || [ "$read_duty" != "$duty_ns" ]; then
        echo "PWM readback mismatch: period=$read_period duty=$read_duty enable=$read_enable" >&2
        exit 1
    fi

    printf '%-6s duty=%3s%%  duty_cycle=%s ns  enable=%s\n' \
        "$level" "$percent" "$read_duty" "$read_enable"
    sleep "$step_s"
done

echo
echo "Sweep complete; PWM set to off."
