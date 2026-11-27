#!/usr/bin/env bash
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
DEST="${DEST:-/userdata/smart-fan}"
ADB_BIN="${ADB_BIN:-adb}"
START=0
BUILD_VISION="${BUILD_VISION:-0}"
for arg in "$@"; do
    case "$arg" in
        --start) START=1 ;;
        *) echo "unknown option: $arg" >&2; exit 2 ;;
    esac
done

"$ADB_BIN" get-state >/dev/null

BINARY="$ROOT/prebuilt/aarch64/fan_vision"
if [ "$BUILD_VISION" = "1" ]; then
    make -C "$ROOT" vision
    BINARY="$ROOT/build/vision/fan_vision"
elif [ ! -x "$BINARY" ]; then
    echo "prebuilt vision binary missing; building from source..."
    make -C "$ROOT" vision
    BINARY="$ROOT/build/vision/fan_vision"
fi

"$ADB_BIN" shell "mkdir -p '$DEST/app/smart_fan' '$DEST/bin' '$DEST/config' '$DEST/models' '$DEST/state' '$DEST/tools' '$DEST/voice'"
"$ADB_BIN" push "$ROOT/app/smart_fan/." "$DEST/app/smart_fan/" >/dev/null
"$ADB_BIN" push "$BINARY" "$DEST/bin/fan_vision" >/dev/null
"$ADB_BIN" push "$ROOT/config/smart_fan.json" "$DEST/config/smart_fan.json" >/dev/null
"$ADB_BIN" push "$ROOT/assets/voice/wav/." "$DEST/voice/" >/dev/null
"$ADB_BIN" push "$ROOT/assets/voice/manifest.json" "$DEST/voice/manifest.json" >/dev/null
"$ADB_BIN" push "$ROOT/tools/servo_calibrate.py" "$DEST/tools/servo_calibrate.py" >/dev/null
"$ADB_BIN" push "$ROOT/tools/voice_probe.py" "$DEST/tools/voice_probe.py" >/dev/null
"$ADB_BIN" push "$ROOT/models/yolov8s-640-640.rknn" "$DEST/models/yolov8s-640-640.rknn" >/dev/null
"$ADB_BIN" push "$ROOT/models/coco_80_labels_list.txt" "$DEST/models/coco_80_labels_list.txt" >/dev/null
"$ADB_BIN" push "$ROOT/scripts/smart-fan.service" /tmp/smart-fan.service >/dev/null
"$ADB_BIN" shell "chmod +x '$DEST/bin/fan_vision' '$DEST/tools/servo_calibrate.py' '$DEST/tools/voice_probe.py'; install -m 0644 /tmp/smart-fan.service /etc/systemd/system/smart-fan.service; systemctl daemon-reload"

if [ "$START" = "1" ]; then
    "$ADB_BIN" shell "systemctl enable smart-fan.service >/dev/null; systemctl restart smart-fan.service; sleep 2; systemctl --no-pager --full status smart-fan.service | sed -n '1,24p'"
    "$ADB_BIN" forward tcp:8090 tcp:8090 >/dev/null
    echo "Web UI through ADB: http://127.0.0.1:8090/"
else
    echo "Installed. Start with: adb shell systemctl start smart-fan.service"
fi
