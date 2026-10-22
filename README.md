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
├── audio_engine.py               # Platform-independent audio engine
├── tests/                         # Automated tests
├── .github/workflows/ci.yml      # CI workflow
├── build.spec                    # PyInstaller 打包配置
├── pyproject.toml                # Project metadata and dependency groups
├── uv.lock                       # Locked dependency versions
├── requirements.txt              # Exported compatibility dependency list
├── rule.example.json             # 示例规则映射配置文件
├── run.bat                       # Windows 快速启动脚本
├── README.md                     # README 文件
└── LICENSE                       # 许可证文件
```

> **注意**：程序首次运行或保存配置时，会自动生成默认音效包文件夹以保存你的自定义设置。源码运行时，该文件夹位于 `audio_engine.py` 旁；打包运行时，它位于可执行文件旁。默认音效包为空；导入或添加音频后才能播放音效。

## 环境要求

- **Python**: 3.10–3.12 (for source development)
- **Runtime support**: The native keyboard input path uses Win32 and the desktop runtime is currently Windows-only. macOS CI checks the platform-independent audio engine and validates app packaging; starting the native app and global keyboard input on macOS are not supported yet.

## 快速开始

### 运行发布版本（EXE）
下载最新版本的 `.exe` 和音效包压缩包，解压音效包后把文件夹和 `.exe` 放到同目录下双击运行主程序即可。

### 从源码运行

**方法一**：
On Windows, run [`run.bat`](run.bat) from the project directory. It installs the locked dependencies with `uv` and starts the application.

**方法二（手动纯命令行操作）**：

1. Clone the project and enter its directory:
   
   ```bash
   git clone https://github.com/JoeyTeng/SoundKeyboard.git
   cd SoundKeyboard
   ```
   
2. Install the locked dependencies (install [uv](https://docs.astral.sh/uv/) first):

   ```bash
   uv sync --locked
   ```

3. Start the application on Windows:

   ```bash
   uv run --locked main.py
   ```

## 音效包与规则配置指南

本软件使用“音效包”文件夹的形式来管理音效。一个标准的音效包文件夹内包含你所需要的音频文件，并在根目录包含一个 `rule.json` 文件：

- 你可以在软件的“音效自定义”界面中点击 **+添加**，双击捕获按键并选择本地音频文件。
- 点击 **保存** 后，程序会自动生成或更新当前挂载的音效包的 `rule.json`。
- 点击设置面板的 **导入音效包** 选择其他文件夹，即可无缝切换不同的一套配置及音效。

## 构建可执行文件

Install the build dependency group and create the Windows executable or macOS packaging artifact:

```bash
uv sync --locked --no-default-groups --group build
uv run --locked --no-sync pyinstaller --clean --noconfirm build.spec
```

The build output is written to `dist/`. The macOS `.app` produced by this command is currently packaging validation only; native macOS startup and keyboard input are planned for a separate follow-up change. In a frozen build, the default sound pack is stored next to the executable.

## Development and CI

The project targets Python 3.10–3.12. `pyproject.toml` defines project dependencies and development tools, while `uv.lock` records the exact resolved versions. `requirements.txt` is an exported compatibility artifact; use `uv` and the lockfile for project development.

Install development dependencies and run the checks locally:

```bash
uv sync --locked --group dev
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked pytest
```

CI runs lint checks and the test suite on Windows and macOS with Python 3.10 and 3.12. It builds on both operating systems with Python 3.12, runs a Windows executable smoke test, and packages the macOS `.app`. The stable `CI required` status gates lint, all test matrix jobs, and both builds. The Windows-only `--smoke-test` mode uses SDL's dummy audio driver and a temporary sound pack, installs no global keyboard hook, and exits after 200 ms. The macOS checks exercise the extracted platform-independent `audio_engine.py` and app packaging; they do not establish native macOS application startup or global keyboard input support.

## 依赖库

| 依赖包 | 用途 |
|--------|------|
| PyQt5 | GUI 桌面界面与设置面板的构建交互 |
| pygame | 高性能的音频混音器与按键音效播放引擎 |
| numpy | 用于底层音频数据的矩阵处理、变调计算及倒放生成 |
| keyboard | 全局键盘事件的底层捕获与注入回调 |

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
