# 音效键盘 (SoundKeyboard)

## 作者：[@依然匹萨吧](https://space.bilibili.com/6297797)

## 功能介绍

**[介绍视频](https://www.bilibili.com/video/BV1ArQZBwE27)**

**音效键盘** 是一款基于 PyQt5 开发的桌面按键音效反馈工具。它可以为你在敲击键盘时播放自定义的音频，支持丰富的按键映射规则，并自带多种趣味音效变调功能，让你的每一次打字都充满乐趣。

### 1. 基础功能
- **自定义按键音效**：支持为每一个按键独立绑定音频文件，按下按键时自动播放对应音效，兼容 mp3、ogg、wav、flac 等常见格式。
- **预设包支持**：支持一键导入和自定义音效包(包含音频文件和规则集文件的文件夹)，快速应用成套的音效配置。

### 2. 特色音效模式
- **水牛音（低八度）**：按下 `CapsLock`（大小写锁定键），可开启音频的低八度变调效果。
- **倒放音效**：按下 `Shift` 键，可开启按键音效的倒放效果。
- **演奏模式**：开启该模式后，通过按下特定的按键（如 A, S, D, F 等），可像弹钢琴一样触发不同音高的音效（需当前音效包内提供对应的 `key.mp3/wav/ogg/flac` 音频文件）。

### 3. 可视化界面与自定义
- **界面外观设置**：支持自由修改主题色（橙色、绿色、蓝色）、界面尺寸缩放（20%~70%）以及窗口不透明度。
- **可视化规则编辑**：内置按键捕获机制，双击即可轻松绑定按键与音频文件，无需手动编写配置文件。
- **系统托盘驻留**：支持最小化至系统托盘，不占用任务栏空间，随时可以唤出设置或进行隐藏。

## 文件说明

```text
├── main.py                       # 主程序入口
├── audio_engine.py               # 音频加载与变调
├── build.spec                    # PyInstaller 打包配置
├── pyproject.toml                # Python project and tooling configuration
├── uv.lock                       # Locked Python dependencies
├── rule.example.json             # 示例规则映射配置文件
├── run.command                   # macOS quick launch script
├── run.bat                       # Windows quick launch script
├── README.md                     # README 文件
└── LICENSE                       # 许可证文件
```

> **注意**：默认音效包初始为空，不包含音频文件。导入音效包或添加音频并配置规则后，才会播放按键音效。

## 环境要求

- **Windows**: Windows 10 or later is recommended.
- **macOS**: A recent macOS version. Global keyboard capture and input control require user-granted **Input Monitoring** and **Accessibility** permissions.
- **Python (source runs)**: Python 3.10–3.12, managed with [uv](https://docs.astral.sh/uv/). The project defaults to Python 3.12.

On macOS, open **System Settings → Privacy & Security** and grant SoundKeyboard access under **Input Monitoring** and **Accessibility**. Depending on how you launch it, the listed item may be Terminal (or another terminal host) for a source run, or SoundKeyboard for the packaged app. After changing permissions, quit and reopen the launcher or app, then retry. macOS controls these permissions; SoundKeyboard does not grant them silently and does not require `sudo`.

See Apple's guides for [Input Monitoring](https://support.apple.com/en-ie/guide/mac-help/mchl4cedafb6/27/mac/27) and [Accessibility access](https://support.apple.com/en-ie/guide/mac-help/mh43185/27/mac/27).

Password and other secure input fields may suppress global keystroke monitoring. macOS and applications also reserve some system shortcuts, so those shortcuts may not be captured or remapped reliably. Physical key positions use ANSI keyboard mapping. Option and Command are shown using the canonical `alt` and `win` key names for compatibility with existing rules.

## 快速开始

### Run a release build

On Windows, download and run the `.exe`. On macOS, download and open the `.app` archive. The macOS app is not Developer ID signed or notarized, so macOS may require you to approve opening it in Privacy & Security.

The default pack is created automatically when needed. Source runs store it in the `default_pack` directory beside `main.py`, regardless of the current working directory. Packaged macOS app data is stored at `~/Library/Application Support/SoundKeyboard/default_pack`; on Windows, it remains next to the executable. You can import another sound pack from the settings panel.

### 从源码运行

Install [uv](https://docs.astral.sh/uv/getting-started/installation/), which manages the project's Python 3.12 environment, then use the launcher for your platform:

- macOS: double-click [`run.command`](run.command). If macOS blocks the script, open Terminal in the project directory and run `./run.command`.
- Windows: double-click [`run.bat`](run.bat).

For a manual setup from a terminal:

1. Clone or download the project:
   
   ```bash
   git clone https://github.com/JoeyTeng/SoundKeyboard.git
   cd SoundKeyboard
   ```
   
2. Install the locked runtime and development dependencies:

   ```bash
   uv sync --locked --group dev
   ```

3. Run the application:

   ```bash
   uv run --locked main.py
   ```

The smoke check briefly shows the GUI, uses a temporary data directory and a silent audio driver, and exits automatically without capturing global input:

```bash
uv run --locked main.py --smoke-test
```

On macOS, complete the permissions setup above before expecting global keyboard features to work.

## 音效包与规则配置指南

本软件使用“音效包”文件夹的形式来管理音效。一个标准的音效包文件夹内包含你所需要的音频文件，并在根目录包含一个 `rule.json` 文件：

- 你可以在软件的“音效自定义”界面中点击 **+添加**，双击捕获按键并选择本地音频文件。
- 点击 **保存** 后，程序会自动生成或更新当前挂载的音效包的 `rule.json`。
- 点击设置面板的 **导入音效包** 选择其他文件夹，即可无缝切换不同的一套配置及音效。

## Lint, format, test, and build

Run the same checks used by CI:

```bash
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked pytest
```

To build, install only the locked build dependencies, then package for the current operating system:

```bash
uv sync --locked --no-default-groups --group build
uv run --locked --no-sync pyinstaller --clean --noconfirm build.spec
```

The build output is written under `dist/`. The stable CI workflow required for changes runs lint, formatting, and tests on Python 3.10 and 3.12 on Windows and macOS, and builds the Windows `.exe` plus a macOS `.app` archive. The macOS workflow also runs a packaged silent startup smoke check. The macOS app is not Developer ID signed or notarized. CI does not validate physical keyboard behavior, audio playback, or macOS TCC permission setup; those still require manual checks on the target machine.

## 依赖库

| 依赖包 | 用途 |
|--------|------|
| PyQt5 | GUI 桌面界面与设置面板的构建交互 |
| pygame | 高性能的音频混音器与按键音效播放引擎 |
| numpy | 用于底层音频数据的矩阵处理、变调计算及倒放生成 |
| keyboard / Quartz and AppKit | Platform-specific global keyboard capture and input handling |

## 声明与开源许可证

**声明：本软件免费且非官方，禁止商用贩卖，使用代表同意自行承担所有后果。**

本项目采用 **[知识共享 署名 - 非商业性使用 - 相同方式共享 4.0 国际许可证 (CC BY-NC-SA 4.0)](LICENSE)** 授权。

### 核心条款说明

1. **允许的行为**：你可以自由复制、修改、分发本项目的代码 / 程序，前提是满足以下条件；
2. **禁止的行为**：严禁将本项目（包括修改后的衍生版本）用于任何商业目的（如出售、付费分发、商业运营等）；
3. **必须遵守**：
   - **署名**：必须保留原作者信息（[@依然匹萨吧](https://space.bilibili.com/6297797)）；
   - **相同方式共享**：若你修改 / 衍生本项目，必须采用与本协议相同的许可证发布。

请查看官方协议全文：https://creativecommons.org/licenses/by-nc-sa/4.0/legalcode.zh-hans

本项目仅供学习交流使用，禁止商用或贩卖。
