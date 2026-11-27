# 智能风扇
[中文]| [English](README.md)

## 项目概述

智能风扇是运行在 Quectel Pi M2 智能主控板（Rockchip RK3576，Debian 13）上的边缘 AI 家电 Demo，将 USB 摄像头、NPU 人体检测、水平舵机、离线中英文语音助手、硬件 PWM 风扇和双语本地网页控制台集成在一个独立设备中，能够：

- 在摄像头画面中检测人体并驱动风扇转向
- 通过 270° 水平舵机让风扇朝向检测到的人
- 支持离线中文和英文语音免提控制
- 切换四档风量并设置定时关闭
- 长时间无人时自动进入待机
- 全部功能本地运行，不依赖网络或云服务

## 主要特性

### 核心功能
- **NPU 人体检测**：C++17 视觉进程采集 UVC 视频，在 RK3576 NPU 上运行 YOLOv8s RKNN 模型，以 JSON 输出人体框
- **稳定的人体跟随**：按画面横向方向对人员分组，优先人数更多的方向，并通过连续性判断避免镜头突然甩动
- **平滑舵机控制**：死区、PD 控制、限速和软启动共同驱动水平舵机
- **离线双语语音控制**：Vosk `small-cn` 和 `small-en-us` 分别使用受限中英文语法识别命令，运行过程中不需要网络
- **自然语音播报**：预生成的 MeloTTS 中英文 WAV 通过板载 ES8389 播放
- **四档 PWM 风扇**：70%、80%、90%、100% 四档占空比，支持低电平有效驱动
- **定时与状态管理**：10 分钟、30 分钟、1 小时定时关闭，并支持自动待机
- **双语本地网页控制台**：摄像头预览、人体框、设备状态、中英文界面切换、无人自动关机开关，以及和语音相同的控制命令

## 项目架构

```
智能风扇
├── 项目根目录
│   ├── README.md                 # 英文文档
│   ├── README_zh.md              # 中文文档
│   ├── Makefile                  # 编译、测试和部署入口
│   ├── app/smart_fan/            # Python 应用
│   │   ├── main.py               # 应用进程和生命周期
│   │   ├── controller.py         # 风扇、跟随、定时和行为状态机
│   │   ├── follower.py           # 舵机跟随控制器
│   │   ├── target.py             # 多人主目标选择
│   │   ├── vision.py             # fan_vision 子进程和 JSON 读取
│   │   ├── voice.py              # 离线 Vosk 命令识别
│   │   ├── audio.py              # 异步 WAV 播报
│   │   ├── hardware.py           # 舵机和风扇 PWM 输出
│   │   └── web.py                # 网页控制台、MJPEG 和 API
│   ├── vision/                   # C++ 视觉程序和内置的采集/推理源码
│   ├── config/smart_fan.json     # 板端配置
│   ├── models/                   # YOLOv8s RKNN 模型和标签
│   ├── assets/voice/             # 预生成语音音库
│   ├── scripts/                  # install.sh 和 smart-fan.service
│   ├── tools/                    # PWM、舵机、音频和板端探测工具
│   ├── tests/                    # 宿主机单元测试
│   ├── prebuilds/sysroot/        # 项目内交叉编译 sysroot
│   └── toolchains/               # 项目内 AArch64 工具链入口
```

## 硬件连接

| 功能 | 默认连接 | 配置 |
| --- | --- | --- |
| 舵机信号 | `GPIO2_D3` / `PWM2_CH3_M2` / `2ade3000.pwm` | 50 Hz；500–2500 µs 对应 0–270° |
| 风扇控制 | 40Pin `pin35` / `GPIO2_C6` / `PWM1_CH5_M2` / `2add5000.pwm` | 25 kHz，70/80/90/100% 占空比 |
| 摄像头 | USB UVC 设备 | 默认 `/dev/video73` |
| 音频 | ES8389 codec | `plughw:CARD=rockchipes8389,DEV=0` |

> **注意**：不要让 GPIO 或 PWM 引脚直接承担风扇电流。应使用额定电流足够的 MOSFET 或风扇驱动板，并将其地与开发板共地，电机电流不能经过开发板。

## 安装依赖

### 项目内依赖

编译所需的一切都在本目录内，所有编译路径都只指向项目自身：

```
prebuilds/sysroot/
toolchains/m2-debian-rootfs-toolchain/
third_party/rknn/include/
tools/cmake/aarch64-m2-debian-toolchain.cmake
vision/vendor/monitor_box/
models/yolov8s-640-640.rknn
```

宿主机需要 CMake 3.16+ 和支持 `qemu-aarch64` 的 binfmt。编译前先校验依赖完整性：

```bash
make check-deps
```

### 板端环境

- `librknnrt`、RGA、Rockchip MPP 和 JPEG 运行库
- Python 3
- 提供 `arecord`、`aplay` 和 `amixer` 的 ALSA 工具
- Vosk C 库和中文 `vosk-model-small-cn-0.22` 模型
- 宿主机到开发板的 ADB 连接

## 模型准备

### 人体检测模型

YOLOv8s RKNN 模型和 COCO 标签已随项目发布，位于 `models/`：

- `models/yolov8s-640-640.rknn`
- `models/coco_80_labels_list.txt`

> **注意**：板端 RKNN 运行时和模型转换工具必须版本兼容，建议编译环境与运行环境使用相同的 RKNN 运行时版本。

### 离线语音模型

Vosk 动态库和中文模型是必需资源，英文模型可选。英文模型缺失时，应用仍会正常启动，只保留中文语音识别。

```
/userdata/smart-fan/vendor/vosk/libvosk.so
/userdata/smart-fan/models/vosk-model-small-cn-0.22/
/userdata/smart-fan/models/vosk-model-small-en-us-0.15/
```

可通过以下脚本下载并安装英文模型：

```bash
tools/install_english_voice_model.sh
```

> **注意**：Vosk 动态库或中文模型缺失时，语音识别会关闭；只有英文模型缺失时，中文语音仍可正常使用。

### 语音播报音库

预生成的 WAV 音库位于 `assets/voice/`，使用 MIT 许可的 MeloTTS 中文模型生成。音源和重新生成方法见 [`assets/voice/README.md`](assets/voice/README.md)。开发板只需要 `aplay`。

## 编译与部署

### 宿主机编译与测试

```bash
make vision     # 交叉编译 fan_vision 视觉程序
make test       # 运行宿主机单元测试
make run-dry    # 无硬件、摄像头和语音时运行
```

dry-run 模式使用模拟风扇和舵机，网页控制台仍可通过 `http://127.0.0.1:8090/` 访问。

### 部署到开发板

```bash
adb devices
make deploy
```

`make deploy` 会复制 `fan_vision`（缺失时先自动编译），以及应用、配置、模型、语音资源和服务文件到开发板，安装并启动 `smart-fan.service`，并把板端 8090 端口转发到宿主机。

常用服务命令：

```bash
adb shell systemctl status smart-fan --no-pager
adb shell journalctl -u smart-fan -f
adb shell systemctl stop smart-fan
adb shell systemctl start smart-fan
```

宿主机重启、重新插拔 USB 或 ADB 服务重启后，ADB 端口转发会丢失，需要重新建立：

```bash
make web
```

随后打开 `http://127.0.0.1:8090/`。风扇关闭时网页控制台仍应正常显示，只有摄像头区域会显示待机占位图。

## 使用方法

### 网页控制台

打开转发后的地址：

```
http://127.0.0.1:8090/
```

控制台可查看实时摄像头画面、人体框、设备状态和性能指标。默认 `api.listen` 为 `127.0.0.1`；如需局域网直接访问，请将 `config/smart_fan.json` 中的 `api.listen` 改为 `0.0.0.0`。

提供的接口：

```
GET  /                  网页控制台
GET  /api/status        设备、视觉、语音和行为状态
POST /api/command       JSON 命令：{"command":"fan_on"}
GET  /stream.mjpg       MJPEG 摄像头预览
GET  /snapshot.jpg      最新 JPEG 快照
```

### 语音控制

先说唤醒词 **“小风小风”**，然后在 5 秒内说出命令。

| 语音命令 | 动作 |
| --- | --- |
| 小风小风，打开风扇 | 按上次档位打开风扇 |
| 小风小风，关闭风扇 | 关闭风扇，摄像头和舵机输出进入待机；舵机停在当前角度并断电 |
| 小风小风，一档 / 二档 / 三档 / 四档 | 设置 70% / 80% / 90% / 100% 占空比 |
| 小风小风，开启跟随 / 停止跟随 | 开启人体跟随；停止时舵机保持在当前角度 |
| 小风小风，定时十分钟 / 半小时 / 一小时后关闭 | 设置定时关闭 |
| 小风小风，取消定时 | 取消定时 |
| 小风小风，开启自动关机 / 打开自动关机 | 开启长时间无人自动关机 |
| 小风小风，关闭自动关机 / 停止自动关机 | 关闭长时间无人自动关机，并继续巡视寻找人员 |

自动关机开关可在风扇开启或关闭时通过语音和网页修改，两种操作控制同一份运行状态。关闭后只停止“长时间无人自动关机”，手动关闭和显式设置的定时关机仍会正常执行。启动时的默认状态由 `config/smart_fan.json` 中的 `behavior.auto_off_enabled` 决定。

风扇关闭时，通过语音或网页按钮执行档位、开启/停止跟随以及十分钟/半小时/一小时定时关闭都不会修改设置，而是提示“请先打开风扇”。直接调用 API 时默认仍可预选档位或保存定时任务；如需与语音和网页一致，可在请求中加入 `require_fan_on: true`。

#### 英文语音控制

中文和英文识别器会并行工作。英文唤醒接受完整的 **“Hey Fan”**、**“Hi Fan”**、**“Hello Fan”**、**“Okay Fan”** 等常用说法，也可以用 “Hey Fans” 或 “Hey Smart Fan”。唤醒后 10 秒内说出命令；也可以直接说完整命令，例如 “Hey Fan, turn on the fan”。单独的 “Hey” 仍不作为有效唤醒词，以免被环境声误触发。

英文唤醒默认播放 “I'm listening.”，让用户知道识别已经成功。收到唤醒后请等提示音结束再说命令；也可以把唤醒词和命令放在同一句里。网页状态栏会同步显示“已唤醒 · English”和剩余时间，识别到命令后会显示命令名称。若不需要语音应答，将 `voice.announce_wake_en` 设为 `false`。

英文播报已单独放慢到更清晰的语速，档位播报会再慢一些。若现场仍觉得快，可重新生成英文音库：`python3 tools/generate_voice.py --only fan_on_en --english-speed-length-scale 3.50`。

| 英文命令 | 动作 |
| --- | --- |
| Hey Fan, turn on the fan / start the fan / fan on | 打开风扇 |
| Hey Fan, turn off the fan / shut off the fan / fan off | 关闭风扇 |
| Hey Fan, level one / fan speed two / max speed | 切换风力档位 |
| Hey Fan, follow me / start tracking / stop following | 开启或停止人体跟随 |
| Hey Fan, timer ten minutes / set a timer for half an hour | 设置定时关闭 |
| Hey Fan, turn off the fan in one hour / shut the fan off after an hour | 使用自然句式设置定时关闭 |
| Hey Fan, cancel timer / cancel the timer / clear the timer | 取消定时 |
| Hey Fan, enable automatic shutdown / disable auto shutdown | 开启或关闭长时间无人自动关机 |

也支持 “power on”“power off”“track me”“turn tracking off”“turn automatic shutdown on” 等自然说法。英文定时命令可使用 “in ten minutes”“after half an hour”“for one hour” 等句式；风扇关闭时会提示先打开风扇，不会保存失效的定时任务。英文使用独立的 `voice.min_input_peak_en`、`voice.min_speech_sec_en` 和唤醒阈值，避免较轻的英文语音被中文设置直接丢弃；如果麦克风输入仍然偏小，可优先提高 `voice.capture_volume`。

网页右上角选择 **中文 / EN** 时，界面、网页触发的播报以及后续巡视/待机等状态播报都会同步切换语言。识别到语音命令时，播报语言会跟随该条语音的语言；网页选择结果会保存在浏览器中。

### API 命令

```
fan_on  fan_off
level_low  level_medium  level_high  level_max
follow_on  follow_off
timer_10m  timer_half_hour  timer_1h  timer_cancel
auto_off_on  auto_off_off
```

## 部署建议

### 摄像头与舵机安装
- 摄像头和风扇应安装在同一旋转轴上，使镜头朝向与出风方向一致。
- 保持摄像头水平，避免镜头前出现反光玻璃或运动网罩。
- 启用自动跟随前先标定舵机机械限位。默认 20°–250° 只是软件限位，不代表所有外壳都能安全使用。

### 风扇与电气安全
- 风扇必须经过独立驱动级控制，并确认控制输入的逻辑电平。
- 确认实际所需极性；当前实测方案使用低电平有效，配置为 `inversed`。
- 首次测试 PWM 时先断开风扇，用万用表或示波器确认波形，再连接负载。
- 确认每个档位都能从关闭状态可靠启动。

### 音频
- 麦克风应远离风扇气流和扬声器，减少误唤醒。
- 环境噪声导致频繁误识别时，优先降低 `voice.capture_volume`。
- 首次语音部署建议使用耳机或小音量扬声器，避免扬声器回采。

## 工作原理说明

### 行为状态
- **Off**：风扇关闭，摄像头暂停；舵机停在当前角度并关闭 PWM 输出
- **Manual**：风扇运行，但人体跟随已关闭
- **Follow**：画面中有人，舵机跟随选中的主目标
- **Search**：连续 5 秒没有确认的人体时，舵机在 60°–220° 之间缓慢巡视
- **Standby**：连续 60 秒无人后，风扇关闭，摄像头暂停，舵机停在当前角度并断电，语音和网页服务保持在线。该自动关机行为可通过网页或语音关闭，也可通过 `behavior.auto_off_enabled` 设置启动默认值

### 人体跟随
- 视觉程序先按置信度、最小画面高度和高宽比过滤人体框。
- 目标选择器按横向位置对剩余人体框分组，优先人数更多的一组，再选择该组中更近、更可靠的目标。
- 只有目标超出水平死区时，控制器才产生新的舵机角度；PD 控制器结合角速度和步长限制计算角度。
- `servo.invert` 用于修正实际安装方向。
- 显式停止跟随时，舵机保持在停止时的角度，不会自动复位到中心。

### 定时行为
- 定时器保存单调时钟绝对截止时间，修改系统时间不会改变关闭时间。
- 定时状态只保存在内存中，服务重启后会清除。

## 常见问题

### Q1: 摄像头无法打开
**解决方案：**
- 使用 `v4l2-ctl --list-devices` 检查视频节点
- 确认没有其他进程占用同一个 USB 摄像头
- 如果板端分配了不同节点，请修改 `vision.device`
- 检查 USB 线和供电质量；640×480 MJPG 应在 30 fps 下稳定取流

### Q2: 视觉程序启动失败
**解决方案：**
- 重新执行 `make vision`，并通过 `journalctl -u smart-fan -f` 查看日志开头
- 确认模型已部署到 `/userdata/smart-fan/models/`
- 确认 RKNN 运行时版本与模型转换版本一致
- 检查目标镜像中是否存在 RGA、MPP、JPEG 和 RKNN 动态库

### Q3: 舵机方向错误或碰到外壳
**解决方案：**
- 测试前先停止服务
- 通过 `servo.invert` 调整方向，通过 `servo.min_angle`、`servo.max_angle` 和 `servo.center_angle` 调整机械安全范围
- 使用 `tools/servo_calibrate.py` 交互校准安全限位

### Q4: 风扇无法调速
**解决方案：**
- 确认控制线接在 40Pin `pin35`，而不是原来的 `GPIO2_D1` 风扇信号
- 确认 `/sys/class/pwm` 下存在 `2add5000.pwm`
- 检查 `fan.polarity`；当前实测驱动需要 `inversed`
- 停止服务并使用 PWM 工具测量控制信号，确认无误后再连接风扇

### Q5: 网页控制台无法访问
**解决方案：**
- 使用 `make deploy` 输出的 ADB 转发地址，或将 `api.listen` 改为 `0.0.0.0`
- 确认服务正在运行，且 8090 端口没有被其他程序占用
- 在板端执行 `adb shell curl http://127.0.0.1:8090/api/status`，区分板端服务问题与网络访问问题

### Q6: 语音识别不可用
**解决方案：**
- 检查 `config/smart_fan.json` 中的 `libvosk.so` 和模型目录
- 确认 `arecord -D plughw:CARD=rockchipes8389,DEV=0` 能正常录音
- 在 `/api/status` 中查看 `voice.last_error`、`input_peak` 和 `input_rms`

## 调试工具

| 工具 | 用途 |
| --- | --- |
| `tools/probe_board.sh` | 检查开发板、摄像头、ALSA、PWM 和运行资源 |
| `tools/servo_test.sh` | 让舵机转到指定角度并保持一段时间 |
| `tools/servo_calibrate.py` | 交互式标定舵机安全限位和中心角 |
| `tools/fan_pwm_test.sh` | 测试单个风扇 PWM 占空比和频率 |
| `tools/fan_pwm_sweep.sh` | 依次测试所有风扇档位 |
| `tools/fan_pwm_calibrate.sh` | 测量风扇能够可靠冷启动的最低占空比 |
| `tools/voice_probe.py` | 检查麦克风输入和 Vosk 识别结果 |

## 报告问题

如在使用过程中遇到问题，欢迎在[移远官方论坛](https://forumschinese.quectel.com/c/quectel-pi/58) 提交技术咨询，我们的技术支持团队将及时为您解答。

欢迎提交 Issue 反馈问题或 Pull Request 贡献代码改进！
