#!/usr/bin/env bash
set -euo pipefail

MODEL_NAME="${MODEL_NAME:-vosk-model-small-en-us-0.15}"
MODEL_URL="${MODEL_URL:-https://alphacephei.com/vosk/models/${MODEL_NAME}.zip}"
DEST="${DEST:-/userdata/smart-fan/models}"
ADB_BIN="${ADB_BIN:-adb}"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

for tool in curl unzip "$ADB_BIN"; do
    command -v "$tool" >/dev/null || { echo "required tool missing: $tool" >&2; exit 1; }
done

"$ADB_BIN" get-state >/dev/null
echo "downloading $MODEL_NAME"
curl -L --fail --retry 2 -o "$WORK/model.zip" "$MODEL_URL"
unzip -q "$WORK/model.zip" -d "$WORK"
model_dir="$WORK/$MODEL_NAME"
[ -d "$model_dir" ] || { echo "unexpected model archive layout" >&2; exit 1; }

"$ADB_BIN" shell "mkdir -p '$DEST/$MODEL_NAME'"
"$ADB_BIN" push "$model_dir/." "$DEST/$MODEL_NAME/" >/dev/null
"$ADB_BIN" shell "test -f '$DEST/$MODEL_NAME/conf/model.conf' && test -d '$DEST/$MODEL_NAME/graph'"
"$ADB_BIN" shell "systemctl restart smart-fan.service"
echo "English voice model installed at $DEST/$MODEL_NAME"
