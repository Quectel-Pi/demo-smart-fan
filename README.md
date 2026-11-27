# Smart Fan
[English]| [中文](README_zh.md)

## Project Overview

Smart Fan is an edge-AI appliance demo running on the Quectel Pi M2 smart single-board computer (Rockchip RK3576, Debian 13). It combines a USB camera, NPU person detection, a pan servo, an offline Chinese/English voice assistant, a hardware-PWM fan and a bilingual local web console into one self-contained device:

- Detect people in the camera stream with YOLOv8s on the RK3576 NPU
- Turn the fan toward the detected person with a 270° pan servo
- Accept hands-free Chinese and English voice commands
- Switch between four fan levels and set a timed shutdown
- Enter standby when nobody is present for a while
- Everything runs locally; no network or cloud service is required

## Key Features

### Core Functions
- **NPU person detection**: a C++17 process captures UVC video, runs the YOLOv8s RKNN model and publishes person boxes as JSON
- **Stable person following**: people are grouped by horizontal direction, the largest group wins, and continuity checks avoid abrupt direction changes
- **Smooth servo control**: deadband, PD control, speed limiting and soft start drive the pan servo
- **Offline bilingual voice control**: Vosk `small-cn` and `small-en-us` recognize restricted Chinese and English grammars, with no network needed
- **Spoken feedback**: pre-generated MeloTTS Chinese and English WAV prompts are played through the onboard ES8389 codec
- **Four-speed PWM fan**: 70%, 80%, 90% and 100% duty levels, active-low fan input supported
- **Timer and power management**: 10-minute, 30-minute and 1-hour timers, plus automatic standby
- **Bilingual web console**: camera preview, person boxes, device state, a Chinese/English language switch and the same commands as voice

## Project Architecture

```
Smart Fan
├── Project Root
│   ├── README.md                 # English documentation
│   ├── README_zh.md              # Chinese documentation
│   ├── Makefile                  # Build, test and deploy entry points
│   ├── app/smart_fan/            # Python application
│   │   ├── main.py               # Application process and lifecycle
│   │   ├── controller.py         # Fan, follow, timer and behavior state machine
│   │   ├── follower.py           # Servo follow controller
│   │   ├── target.py             # Multi-person target selection
│   │   ├── vision.py             # fan_vision process and JSON reader
│   │   ├── voice.py              # Offline Vosk command recognizer
│   │   ├── audio.py              # Asynchronous WAV playback
│   │   ├── hardware.py           # PWM servo/fan output
│   │   └── web.py                # Web console, MJPEG stream and API
│   ├── vision/                   # C++ vision process and vendored capture/inference sources
│   ├── config/smart_fan.json     # Board configuration
│   ├── models/                   # YOLOv8s RKNN model and labels
│   ├── assets/voice/             # Pre-generated voice prompts
│   ├── scripts/                  # install.sh and smart-fan.service
│   ├── tools/                    # PWM, servo, audio and board probe tools
│   ├── tests/                    # Host-side unit tests
│   ├── prebuilds/sysroot/        # Bundled cross-build sysroot
│   └── toolchains/               # Bundled AArch64 toolchain entry points
```

## Hardware Connection

| Function | Default connection | Configuration |
| --- | --- | --- |
| Servo signal | `GPIO2_D3` / `PWM2_CH3_M2` / `2ade3000.pwm` | 50 Hz; 500–2500 µs maps to 0–270° |
| Fan control | 40Pin `pin35` / `GPIO2_C6` / `PWM1_CH5_M2` / `2add5000.pwm` | 25 kHz, 70/80/90/100% duty |
| Camera | USB UVC camera | Default `/dev/video73` |
| Audio | ES8389 codec | `plughw:CARD=rockchipes8389,DEV=0` |

> **Warning**: never connect a fan directly to a GPIO or PWM pin. Use a MOSFET or fan driver rated for the fan current, tie its ground to the board ground, and keep motor current away from the board.

## Installation Dependencies

### Bundled Resources

The project ships everything the cross-build needs and resolves all build paths inside its own directory:

```
prebuilds/sysroot/
toolchains/m2-debian-rootfs-toolchain/
third_party/rknn/include/
tools/cmake/aarch64-m2-debian-toolchain.cmake
vision/vendor/monitor_box/
models/yolov8s-640-640.rknn
```

Host requirements are CMake 3.16+ and `qemu-aarch64` binfmt support. Verify the bundle before building:

```bash
make check-deps
```

### Board Environment

- `librknnrt`, RGA, Rockchip MPP and JPEG runtime libraries
- Python 3
- ALSA utilities providing `arecord`, `aplay` and `amixer`
- Vosk C library and the Chinese `vosk-model-small-cn-0.22` model
- ADB access from the development host

## Model Preparation

### Person Detection Model

The YOLOv8s RKNN model and COCO labels are included in `models/`:

- `models/yolov8s-640-640.rknn`
- `models/coco_80_labels_list.txt`

> **Note**: the RKNN runtime on the board and the model conversion tool must be compatible. Keep the same RKNN runtime version across build and target.

### Offline Speech Models

The shared Vosk library and Chinese model are required. The English model is optional; without it, the app continues with Chinese speech only.

```
/userdata/smart-fan/vendor/vosk/libvosk.so
/userdata/smart-fan/models/vosk-model-small-cn-0.22/
/userdata/smart-fan/models/vosk-model-small-en-us-0.15/
```

Install or update the English model with:

```bash
tools/install_english_voice_model.sh
```

> **Note**: if the Vosk library or Chinese model is missing, voice recognition is disabled. If only the English model is missing, Chinese speech remains available.

### Voice Announcements

The WAV prompt library is included under `assets/voice/`, generated with the MIT-licensed MeloTTS Chinese model. See [`assets/voice/README.md`](assets/voice/README.md) for the source and regeneration steps. The board only needs `aplay`.

## Build and Deploy

### Build and Test on the Host

```bash
make vision     # cross-compile the fan_vision process
make test       # run the host-side unit tests
make run-dry    # run without hardware, camera or voice
```

In dry-run mode the fan and servo are mocked and the web console is available at `http://127.0.0.1:8090/`.

### Deploy to the Board

```bash
adb devices
make deploy
```

`make deploy` copies `fan_vision` (building it first if it is missing), the application, configuration, model, voice assets and service unit to the board, installs and starts `smart-fan.service`, and forwards port 8090 to the host.

Useful service commands:

```bash
adb shell systemctl status smart-fan --no-pager
adb shell journalctl -u smart-fan -f
adb shell systemctl stop smart-fan
adb shell systemctl start smart-fan
```

ADB port forwards are lost when the host USB session or ADB server restarts. Restore the web console with:

```bash
make web
```

Then open `http://127.0.0.1:8090/`. The web console works while the fan is off; only the camera area shows a standby placeholder until the fan is turned on.

## Usage Instructions

### Web Console

Open the forwarded address:

```
http://127.0.0.1:8090/
```

The console shows the live camera preview, person boxes, device state and performance. The default `api.listen` is `127.0.0.1`; change it to `0.0.0.0` in `config/smart_fan.json` for direct LAN access.

Available endpoints:

```
GET  /                  Web console
GET  /api/status        Device, vision, voice and behavior state
POST /api/command       JSON command: {"command":"fan_on"}
GET  /stream.mjpg       MJPEG camera preview
GET  /snapshot.jpg      Latest JPEG snapshot
```

### Voice Control

Say the wake word **"小风小风"**, then issue a command within five seconds.

| Chinese command | Action |
| --- | --- |
| 小风小风，打开风扇 | Turn the fan on at the last level |
| 小风小风，关闭风扇 | Turn off the fan; camera output pauses and the servo is de-energized at its current angle |
| 小风小风，一档 / 二档 / 三档 / 四档 | Select 70% / 80% / 90% / 100% duty |
| 小风小风，开启跟随 / 停止跟随 | Enable person following; stopping keeps the servo at its current angle |
| 小风小风，定时十分钟 / 半小时 / 一小时后关闭 | Set a timed shutdown |
| 小风小风，取消定时 | Cancel the timer |
| 小风小风，开启自动关机 / 打开自动关机 | Enable automatic shutdown when nobody is present |
| 小风小风，关闭自动关机 / 停止自动关机 | Disable automatic shutdown while continuing to search for a person |

While the fan is off, level and follow commands plus the ten-minute, half-hour and one-hour shutdown timers from voice or the web buttons do not change their settings. The speaker instead asks the user to turn the fan on first. Direct API calls can still pre-select a level or store a timer unless `require_fan_on` is set.

The automatic-shutdown setting can be changed by voice or from the web console while the fan is on or off. Both controls update the same runtime state. Disabling it only prevents the long absence timeout from shutting down the fan; manual shutdown and explicit timers still take effect. The startup default is controlled by `behavior.auto_off_enabled` in `config/smart_fan.json`.

#### English voice control

The Chinese and English recognizers run in parallel. English accepts complete wake phrases including **"Hey Fan"**, **"Hi Fan"**, **"Hello Fan"**, **"Okay Fan"**, plus "Hey Fans" and "Hey Smart Fan". Issue a command within ten seconds, or use a full command such as "Hey Fan, turn on the fan". A standalone "Hey" is still rejected to avoid wake-ups from ambient speech.

English wake-up now plays "I'm listening." by default so the successful trigger is audible. Wait for the acknowledgement before speaking the command, or use a single wake-plus-command sentence. The web console also shows an awake state, the remaining window and the most recent recognized command. Set `voice.announce_wake_en` to `false` to make English wake-up silent.

English announcements are generated at a slower pace than Chinese, with still slower level announcements. To make a phrase even slower, regenerate it with a larger scale, for example `python3 tools/generate_voice.py --only fan_on_en --english-speed-length-scale 3.50`.

| English command | Action |
| --- | --- |
| Hey Fan, turn on the fan / start the fan / fan on | Turn the fan on |
| Hey Fan, turn off the fan / shut off the fan / fan off | Turn the fan off |
| Hey Fan, level one / fan speed two / max speed | Select the fan level |
| Hey Fan, follow me / start tracking / stop following | Enable or disable person following |
| Hey Fan, timer ten minutes / set a timer for half an hour | Set a timed shutdown |
| Hey Fan, turn off the fan in one hour / shut the fan off after an hour | Set a timed shutdown with natural wording |
| Hey Fan, cancel timer / cancel the timer / clear the timer | Cancel the timer |
| Hey Fan, enable automatic shutdown / disable auto shutdown | Enable or disable long-absence shutdown |

Natural alternatives such as "power on", "power off", "track me", "turn tracking off" and "turn automatic shutdown on" are also accepted. Timer phrases using "in ten minutes", "after half an hour" or "for one hour" all set the same timed shutdown. If the fan is off, the assistant asks the user to turn it on first instead of storing a timer. English capture uses separate `voice.min_input_peak_en`, `voice.min_speech_sec_en` and wake thresholds so quieter speech is not discarded by the Chinese settings. Adjust `voice.capture_volume` first if the microphone level is still low.

Selecting **中文** or **EN** in the web console switches both the interface and the language used for web-triggered and subsequent status announcements. A recognized voice command switches the announcement language to that voice language. The web choice is stored in the browser.

### API Commands

```
fan_on  fan_off
level_low  level_medium  level_high  level_max
follow_on  follow_off
timer_10m  timer_half_hour  timer_1h  timer_cancel
auto_off_on  auto_off_off
```

## Deployment Recommendations

### Camera and Servo Placement
- Mount the camera and fan on the same rotating axis, so the camera looks where the fan blows.
- Keep the camera level and avoid reflective glass or a moving grille in front of the lens.
- Calibrate the mechanical servo limits before enabling automatic following. The default 20°–250° range is a software limit, not a guarantee for every enclosure.

### Fan and Electrical Safety
- Use a separate driver stage and verify the logic-level threshold of its control input.
- Confirm the required polarity; the tested setup uses an active-low, `inversed` fan input.
- Start with the fan disconnected and check the PWM signal with a meter or oscilloscope before attaching the load.
- Confirm that every level starts reliably from the off state.

### Audio
- Keep the microphone away from the fan airflow and speaker port to reduce false wake-ups.
- Lower `voice.capture_volume` first if ambient noise triggers commands often.
- Validate the first voice deployment with headphones or a small test speaker to avoid acoustic feedback.

## Behavior Explanation

### Behavior States
- **Off**: fan off and camera paused; the servo keeps its current angle and PWM output is disabled
- **Manual**: fan on with following disabled
- **Follow**: a person is present and the servo follows the selected target
- **Search**: nobody confirmed for 5 seconds; the servo sweeps slowly between 60° and 220°
- **Standby**: nobody present for 60 seconds; the fan turns off, the camera pauses, and the servo is de-energized at its current angle while voice and web stay online. Automatic shutdown can be disabled from the web console or with `behavior.auto_off_enabled`.

### Person Following
- Person boxes are filtered by confidence, minimum image height and aspect ratio.
- Remaining boxes are grouped by horizontal direction; the direction with more people wins, and within it the nearest convincing person is preferred.
- Only a target outside the horizontal deadband produces servo movement; a PD controller with rate and step limits computes the angle.
- `servo.invert` corrects the mounting direction.
- Explicitly stopping person following keeps the servo at its current angle instead of returning it to center.

### Timer Behavior
- Timers store a monotonic deadline, so changing the system clock does not shift the shutdown time.
- Timer state is kept in memory and is cleared when the service restarts.

## Common Issues

### Q1: Camera Cannot Be Opened
**Solution:**
- Check the video node with `v4l2-ctl --list-devices`
- Confirm no other process owns the UVC camera
- Update `vision.device` if the board assigned a different node
- Check the USB cable and power quality; 640×480 MJPG should be stable at 30 fps

### Q2: Vision Process Fails to Start
**Solution:**
- Re-run `make vision` and check the first lines of `journalctl -u smart-fan -f`
- Confirm the model exists under `/userdata/smart-fan/models/`
- Make sure the RKNN runtime version matches the converted model
- Verify RGA, MPP, JPEG and RKNN libraries exist in the board image

### Q3: Servo Moves the Wrong Way or Hits the Enclosure
**Solution:**
- Stop the service first
- Change `servo.invert` for direction, and adjust `servo.min_angle`, `servo.max_angle` and `servo.center_angle`
- Use `tools/servo_calibrate.py` to find safe limits

### Q4: Fan Does Not Change Speed
**Solution:**
- Confirm the control wire is on 40Pin `pin35`, not the legacy `GPIO2_D1` signal
- Confirm `2add5000.pwm` exists under `/sys/class/pwm`
- Check `fan.polarity`; the tested setup requires `inversed`
- Test the PWM with the service stopped before reconnecting the fan

### Q5: Web Console Cannot Be Reached
**Solution:**
- Use the ADB forward printed by `make deploy`, or set `api.listen` to `0.0.0.0`
- Verify the service is running and port 8090 is free
- Try `adb shell curl http://127.0.0.1:8090/api/status` to isolate network problems

### Q6: Voice Recognition Is Unavailable
**Solution:**
- Verify the `libvosk.so` and model paths in `config/smart_fan.json`
- Check that `arecord -D plughw:CARD=rockchipes8389,DEV=0` records audio
- Review `voice.last_error`, `input_peak` and `input_rms` in `/api/status`

## Debugging Tools

| Tool | Purpose |
| --- | --- |
| `tools/probe_board.sh` | Report board, camera, ALSA, PWM and runtime status |
| `tools/servo_test.sh` | Move the servo to one angle and hold it |
| `tools/servo_calibrate.py` | Interactively find safe servo limits |
| `tools/fan_pwm_test.sh` | Test one fan PWM duty cycle and frequency |
| `tools/fan_pwm_sweep.sh` | Step through all configured fan levels |
| `tools/fan_pwm_calibrate.sh` | Find the minimum reliable cold-start duty |
| `tools/voice_probe.py` | Inspect microphone input and Vosk recognition |

## Reporting Issues

If you encounter any problems during use, please submit technical inquiries on the [Quectel Official Forum](https://forumschinese.quectel.com/c/quectel-pi/58). Our technical support team will respond promptly.

Issues and Pull Requests are also welcome to report problems or contribute improvements.
