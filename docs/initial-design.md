# 智能风扇初步设计

## 模块边界

| 模块 | 输入 | 输出 | 首版技术选择 |
| --- | --- | --- | --- |
| 采集 | UVC `/dev/video73` | RGB 帧 | V4L2 + MPP/libjpeg，复用 `vision/vendor/monitor_box` 内的代码 |
| 人体检测 | RGB 帧 | person 框、置信度 | RKNN YOLOv8s 640x640 |
| 目标稳定 | person 框 | 主目标中心、丢失时长 | 跟踪 ID + 一欧元滤波 |
| 跟随控制 | 目标中心 | 舵机角度 | 死区 + PD + 限速 |
| 执行器 | 档位、角度 | PWM/GPIO | sysfs PWM + 动态 chip 查找 |
| 语音 | 16kHz PCM | 标准化命令 | Vosk small-cn + 受限语法 |
| 状态机 | 语音/API/定时/跟随事件 | 风扇和舵机目标状态 | Python 线程安全的单一状态源 |
| 定时器 | 截止时间 | OFF 事件 | 单调时钟 |
| 调试接口 | HTTP GET/POST | JSON 状态与控制 | 本地 8080/8090 端口 |

## 风扇执行器选型

首版使用 40Pin `pin35` 的 `PWM1_CH5_M2`（`2add5000.pwm`）驱动风扇，避免修改设备树。该控制器已在本板验证 25kHz、50% 占空比。舵机继续使用 `GPIO2_D3` 的 `PWM2_CH3_M2`，两路硬件 PWM 可以同时工作。

保留 `GPIO2_D1` 时必须启用 `PWM2_CH1_M2`（`2ade1000.pwm`）并重新烧录 boot。用户态软件 PWM 只作为最后兜底：25kHz 时 CPU 调度抖动很大，低频又会造成风扇噪声，不能作为正式演示方案。

首版可以采用两个进程：

- `fan-vision`：C++，采集和 NPU 人体检测，通过 Unix Socket 输出目标中心。
- `smart-fan`：Python，语音、定时、状态机、舵机和风扇控制。

两个进程通过本地 Unix Socket 传递 10Hz 小数据包，避免 HTTP 轮询和摄像头重复打开。若演示时间紧，也可以先把目标中心发布到本地 HTTP，等闭环稳定后再收敛为 Unix Socket。

## 状态机

```text
OFF
  --打开/恢复定时--> ON
ON
  --关闭/定时到期/人为中止--> OFF
ON + FOLLOW_ON
  --检测到人--> TRACKING
TRACKING
  --目标丢失 1.5s--> HOLD
HOLD
  --目标恢复--> TRACKING
HOLD --丢失 10s--> CENTER
CENTER --丢失 30s--> OFF
```

档位 `OFF/LOW/MED/HIGH` 与跟随开关正交。`OFF` 可以保留上次档位，下一次“打开风扇”恢复到该档位。

## 主目标选择

1. 遍历置信度超过阈值的 `person` 检测。
2. 若上一帧目标仍在，优先选择 IoU 或跟踪 ID 连续的目标。
3. 否则选择框面积最大的目标，视为离设备更近。
4. 对目标中心做中值滤波去除瞬时跳点，再用一欧元滤波平滑。
5. 目标中心进入画面中心 4% 死区后不产生新的角度请求。

## 单舵机跟随控制器

```text
error = target_x_normalized - 0.5
target_rate = Kp * error + Kd * d(error)/dt
rate = clamp(target_rate, -max_rate, max_rate)
angle = clamp(angle + rate * dt, min_angle, max_angle)
```

为了防止相机安装方向相反，配置中保留 `invert`。上电时必须先回中位，不允许直接跳到上次角度。

## 语音命令解析

Vosk 只返回候选文本，业务层再做一次严格解析：

- 先去空格和标点。
- 优先匹配完整短语，若失败则匹配包含关系。
- 档位必须包含数字或明确档位词，避免“打开”错误触发。
- 同一条命令 1.5s 内去重。
- 低置信度或无法解析时播放失败提示，不改变状态。

受限语法词表包含唤醒词、动词、设备名、数字、单位、档位词和取消词，避免把开放听写结果直接当控制命令。

## 安全约束

- 舵机限位和最大速度由软件钳制，配置变更后也必须再次钳制。
- 风扇 PWM 上电默认 0，服务退出时写入 0。
- 舵机 PWM 在关闭风扇、定时停机、进入待机或服务退出时保持在当前角度并直接关闭输出，不先回中。
- 摄像头、ASR、控制循环任一崩溃，看门狗关闭风扇。
- 风扇启动占空比按实物标定，不盲目从 1% 扫描。
- 调占空比前先设置周期；按 Rockchip PWM sysfs 顺序写 period -> polarity -> duty_cycle -> enable。

## 配置草案

配置放在 `config/smart_fan.json`。所有 `pwmchip` 都保存为设备路径标识，例如 `2ade3000.pwm`，运行时再解析为当前 `/sys/class/pwm/pwmchipN`。
