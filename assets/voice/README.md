# 智能风扇扬声器音库

音库使用 **MeloTTS Chinese-Mix-English** 女声，语气偏向轻快、亲切的甜妹音。中文播报不带 `_en` 后缀，英文播报使用 `_en` 后缀，例如 `wake_en` 和 `fan_on_en`。所有播报在开发机上预生成，开发板只调用 `aplay` 播放 WAV，不需要安装 TTS 引擎，也不依赖网络。

中文普通播报默认 `length_scale=1.95`，中文档位提示使用更慢的 `length_scale=2.20`。英文普通播报使用 `length_scale=3.30`，英文档位提示使用 `3.45`，并提供 `3.60` 秒的最短播报时长，让英语短句更容易听清。生成器会检查每条 WAV，短句会继续拉慢语速。档位提示的峰值单独提高到 `0.78`，避免高风速时被风扇噪声盖住。数值越大语速越慢；如需微调，可重新生成单句试听，例如 `python3 tools/generate_voice.py --only fan_on_en --english-speed-length-scale 3.50`。

## 声音来源

| 项目 | 地址 | 许可 |
| --- | --- | --- |
| MeloTTS 上游开源项目 | <https://github.com/myshell-ai/MeloTTS> | MIT |
| 中文女声模型 | <https://huggingface.co/myshell-ai/MeloTTS-Chinese> | MIT |
| CPU ONNX 转换模型 | <https://huggingface.co/wolfofbackstreet/melotts_chinese_mix_english_onnx> | MIT |

模型许可全文见 [MIT-MeloTTS.txt](MIT-MeloTTS.txt)。

## 文件约定

- `manifest.json` 是播报文案和资源键的唯一来源。
- `wav/` 是开发板实际播放的音库。
- `mp3/` 是便于试听和转发的低码率副本，应用不会读取。
- WAV 格式固定为 48 kHz、16-bit、单声道 PCM。
- 每句峰值归一化到约 `-4.2 dBFS`，并添加短淡入淡出和首尾静音，避免爆音。

## 重新生成

在开发机执行：

```bash
python3 -m pip install huggingface_hub jieba onnxruntime numpy scipy lameenc
python3 tools/generate_voice.py
```

首次运行会下载约 163 MiB 的 ONNX 模型到 `/tmp/smart-fan-melotts-zh`。也可以通过 `SMART_FAN_TTS_MODEL_DIR` 或 `--model-dir` 指定缓存目录。只生成部分文案可加 `--only fan_on --only fan_off`，只生成开发板使用的 WAV 可加 `--no-mp3`。

修改 `manifest.json` 后重新生成并检查：

```bash
python3 -m unittest tests.test_audio_assets -v
```
