# VoiceNote

低启动成本的电脑端语音记录工具 —— **想到什么直接说，后台自动记录并实时转成文字。**

不做语音输入法：那个场景微信输入法、豆包输入法已经足够好。这个工具只解决一件事 ——
把脑子里一闪而过的念头随手说出来，剩下的交给它。

## 它是怎么工作的

```
麦克风 ──▶ VAD 分段 ──▶ 语音识别 ──▶ 按日期落盘
           (本地 CPU)     (本地 GPU)     文本 + 音频
```

- **启动即监听，不需要点任何东西。** 托盘图标常驻，看到绿色就说明在听。
- **不说话时几乎零开销。** 本地 VAD 判断有没有人在说话，静音时的音频**直接丢弃** ——
  不占 GPU、不出文本、也不上传到任何地方。
- **停顿约 0.7 秒即出字。** 说一句、停一下，这句话就会出现在当天的记录里。
- **默认完全离线。** 语音不出本机，断网照常工作，没有调用成本；也可以选配
  OpenAI 兼容的云端识别引擎（见下文「界面与设置」）。

## 环境要求

只支持 64 位 Windows + NVIDIA 显卡。用安装包的话不需要装 Python；
从源码运行需要 Python 3.13。本项目开发与验证所用的机器：

| | |
|---|---|
| GPU | NVIDIA RTX 4060 Laptop（8GB） |
| CPU | i9-13900HX |
| 内存 | 16GB |

> **必须用 NVIDIA GPU。** 实测 `large-v3-turbo` 在 CUDA 上 RTF 为 **0.18**（约 5.5 倍实时），
> 而同一台机器的 CPU 上 RTF 高达 **1.77** —— 也就是说 20 秒的话要花 35 秒识别，
> 队列只会越堆越长。CPU 不是"慢一点"，是**跑不动**。
> 如果哪天 CUDA 用不了，正确做法是把 `asr.model` 换成更小的模型（如 `small`），而不是改用 CPU。

## 安装

### 方式一：安装包（推荐）

到 [Releases](https://github.com/Johnwatson1234/VoiceNote/releases) 下载
`VoiceNote-Setup-<版本>.exe`，双击即可。

- 装到用户目录，**不需要管理员权限，全程不弹 UAC**
- 可选创建桌面快捷方式和开机自启（也可以之后右键托盘图标切换）
- 控制面板里能正常卸载

### 方式二：免安装便携版

下载 `VoiceNote-Portable-<版本>.zip`，解压到任意目录，双击里面的 `VoiceNote.exe`。
不写注册表、不需要安装。

### 首次启动要下载模型

程序本身不含识别模型（1.6GB，超过 GitHub Releases 的单文件上限）。**第一次启动**会联网
下载，托盘图标显示**黄色**表示正在准备，**变绿**就说明可以开始说话了。

| | |
|---|---|
| 程序本体 | 约 2.3 GB |
| 识别模型 | 约 1.6 GB |
| **合计占盘** | **约 4 GB** |

默认走国内镜像 `hf-mirror.com`。想换回官方源，把 `config.toml` 里的
`general.hf_endpoint` 改成空字符串。

> 程序没有代码签名证书，Windows 可能弹 SmartScreen 警告。点「更多信息」→「仍要运行」即可。

## 从源码运行（开发用）

```bash
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
```

脚本会建虚拟环境、装依赖、生成 `config.toml` 并做一次环境体检。然后启动：

```bash
.venv\Scripts\pythonw.exe -m voicenote
```

`pythonw.exe` 不带控制台，启动时不会闪黑窗。想开机自启，右键托盘图标勾选「开机自启」即可。

如需使用 NVIDIA Parakeet V3，再安装可选的 NeMo 依赖（会额外安装 PyTorch 等，体积较大；
当前官方安装包未内置 NeMo，需从源码安装或自行打包）：

```bash
uv pip install --python .venv\Scripts\python.exe -e ".[parakeet]"
```

### 自己打包

```bash
powershell -ExecutionPolicy Bypass -File scripts\build.ps1
```

产物在 `dist\`：便携版目录、便携版 ZIP、以及安装器（需先 `winget install JRSoftware.InnoSetup`，
没装也不影响便携版）。构建脚本会自动对打好的 exe 跑一次自检，**跑不过就直接失败**，
不会产出看起来正常但 GPU 用不了的坏包。

## 界面与设置

单击托盘图标打开主窗口。**关闭窗口默认只是隐藏到托盘，录音不中断**；想让它直接退出，
把 `general.close_action` 改成 `"exit"`。左侧四个页面：

| 页面 | 能做什么 |
|---|---|
| 记录 | 按日期翻看记录，点 ▶ 回放当时那段音频、复制文本、用系统程序打开当天文件 |
| 本地模型 | 查看 `tiny` / `base` / `small` / `large-v3-turbo` / `parakeet-tdt-0.6b-v3` 的缓存状态，下载 / 重试 / 一键切换（切换后自动热加载，不用重启） |
| API 配置 | 使用 OpenAI 兼容的云端识别：内置 OpenAI / 硅基流动 / Groq 模板，可一键测连通性 |
| 录音与系统 | 麦克风、VAD 参数、识别提示词、数据目录、开机自启、关闭窗口行为 |

托盘右键菜单提供同样的入口：打开主界面、选项设置、API 配置、暂停/恢复监听、开机自启、
打开数据目录、退出。

**API Key 不存在 `config.toml` 里**，而是保存在 `<data_dir>/state/secrets.json`
（当前为明文，仅供本机使用；加密存储留待后续版本）。这样把 `config.toml` 分享出去
或提交到仓库时不会带出密钥。厂商私有协议（如 DashScope 原生接口）列表里可见，
但标注为暂不支持，需要走其 OpenAI 兼容模式或自建网关。

## 记录存在哪

默认在 `%USERPROFILE%\VoiceNote`，想换盘就改 `config.toml` 里的 `general.data_dir`。

```
VoiceNote/
├── transcripts/2026-10-05.md          # 文本，一天一个文件
├── audio/2026-10-05/100211-838.flac   # 音频，按天分目录
├── models/silero_vad.onnx
├── state/secrets.json                 # 云端 API 的 Key（有则会有，不进版本库）
└── logs/voicenote.log
```

记录长这样，点 ▶ 可以直接回放当时那段话：

```markdown
# 2026-10-05

- `09:42:13` 今天下午要把 VAD 阈值调一下，far-field 的时候老是断错。 [▶](../audio/2026-10-05/094213-123.flac)
```

音频用 FLAC 无损压缩，约 60MB/小时。不想要音频就把 `config.toml` 里的
`audio.enabled` 改成 `false`。

## 常用配置

完整说明见 `config.example.toml`。几个最可能想调的：

| 配置项 | 什么时候改它 |
|---|---|
| `vad.speech_threshold` | 环境吵、老是误触发 → 调高（如 0.6）；说话轻、老是漏 → 调低（如 0.35） |
| `vad.min_silence_ms` | 觉得断句太碎 → 调高（如 1000）；觉得出字太慢 → 调低（如 500） |
| `audio.device` | 想指定麦克风。先跑 `python -m voicenote --check` 看设备列表，填名字的一部分即可 |
| `asr.initial_prompt` | 人名、项目名、专业术语老识别错 → 写进去当提示词 |
| `asr.language` | 默认留空自动检测，中英混说体验最好。若输出繁体，可试填 `zh` |
| `asr.engine` | 默认 `faster_whisper`（本地 Whisper）；英文极速可用 `parakeet`（需装 `nemo_toolkit[asr]`）；想用云端识别改成 `api` |
| `general.close_action` | 关窗口想直接退出就填 `"exit"`；默认 `"minimize_to_tray"`（隐藏到托盘，继续录音） |
| `general.data_dir` | 想把记录放到别的盘 |

## 验证与自检

```bash
# 单元测试：分段逻辑、配置兼容性、API 请求/响应解析、模型下载与热切换、界面接线
# （界面测试用 Qt offscreen 平台，没装 PySide6 会自动跳过）
.venv\Scripts\python.exe -m pytest tests\ -q

# 环境体检：打印配置、音频设备、CUDA DLL 情况、云端 API 是否已配置 Key
.venv\Scripts\python.exe -m voicenote --check

# 端到端自检：用一段公开语音跑完整链路，不需要麦克风
# 打包版也能跑：VoiceNote.exe --selftest
.venv\Scripts\python.exe -m voicenote --selftest

# GPU 性能基线
.venv\Scripts\python.exe scripts\smoke_test.py
```

`--selftest` 会输出 RTF。**RTF 大于等于 1 就说明慢于实时**，通常意味着 CUDA DLL
没被正确加载、GPU 悄悄回落到了 CPU —— 这是打包版最容易出的问题，所以构建脚本
把它设为强制检查项。

## 已知限制

- **不是字级实时上屏。** 说完整句、停顿之后才出字。要做到边说边出字需要流式模型，
  第一版没做。
- **强制切分不对齐低能量点。** 连续说超过 20 秒会硬切，切点可能落在词中间。
  20 秒一段的情况下很少见，暂不为它增加复杂度。
- **音频会持续累积**，约 60MB/小时。目前没有自动清理。
- **记录页没有全文搜索**，只按日期浏览。记录是纯 markdown，复杂查询用任何编辑器或 `grep`。
- **本地模型支持 faster-whisper 系列**（tiny/base/small/large-v3-turbo）和
  **NVIDIA Parakeet TDT V3**（需自行 `pip install "nemo_toolkit[asr]"`，首次切换时
  NeMo 会自动下载约 2.5GB 权重；支持 25 种欧洲语言，不支持中文，也不接受
  `initial_prompt` / 自定义词表）。SenseVoiceSmall 的本地 ONNX 推理还没做，
  想用它可以在「API 配置」里接硅基流动的对应模型。
- **API Key 目前明文存放**在 `state/secrets.json`（仅本机用户目录）。加密存储留待后续版本。

## 后续可能的方向

如果这个基础功能确实用得上，再基于攒下来的音频和文本做搜索、整理、总结、知识库。
ASR 引擎也已经做成可替换的接口，可以用 `scripts/ab_compare.py` 拿自己的录音
对比 faster-whisper 和 Qwen3-ASR（中文 CER 更低），用数据决定要不要换。

## 许可证

[MIT](LICENSE)
