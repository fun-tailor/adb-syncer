
# ADB 同步器 (ADB Syncer)

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT) [![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)

ADB 同步器是一个基于 Python + PyQt6 的图形化工具，通过 ADB 连接 Android 设备，管理多个文件夹同步任务（Pipeline）。专为需要频繁同步文件（如照片、文档）的开发者和高级用户设计，支持自动同步功能。

## ✨ 功能特点

- **多任务管理**：创建、编辑、删除多个同步 Pipeline，配置持久化。
- **灵活同步**：支持单向（本地→设备、设备→本地）和双向同步。
- **智能过滤**：按文件扩展名、修改时间（最近 N 天）过滤文件。
- **插件系统**：通过 Python 脚本扩展功能，例如动态日期路径、自定义冲突处理。
- **自动同步**：设备连接时自动触发指定 Pipeline（可配置间隔）。
- **安全可靠**：所有 ADB 命令异步执行，界面不卡顿；批量创建远程目录，避免重复命令。

## 📥 下载

从 [Releases](https://github.com/fun-tailor/adb-syncer/releases) 页面下载最新版本的 Windows 可执行文件。

> **注意**：本工具依赖 ADB。请确保已安装 ADB 并将其添加到系统 PATH，或将 `adb.exe` 与程序放在同一目录。

## 🚀 快速开始

1. 连接 Android 设备并开启 USB 调试。
2. 运行 `main.py` 或 `adb_syncer.exe`。
3. 点击“+ 新建 Pipeline”，填写：
   - **名称**：任务标识。
   - **本地路径**：电脑上的文件夹。
   - **设备路径**：Android 设备上的文件夹（建议以 `/sdcard/` 开头）。
   - **设备序列号**：可选，留空则使用当前连接的设备。
   - 其他选项按需设置（扩展名过滤、同步方向、同步天数等）。
4. 点击卡片上的“同步”按钮开始同步。

---

#### 软件说明 (目前版本：0.0.2)

- 新建 Pipeline 后，会在同目录下，生成 `config.json` 文件（用于保存配置）
- 检测设备的间隔是 5s；自动同步(auto sync) 的冷却时间是 30分钟

- 支持 多pipeline 自动同步（考虑到adb的稳定性，内部序列执行，耗时 depend on 文件数量）


## 🔌 插件开发（开发中）

1. 在 `plugins` 文件夹中创建 `.py` 文件。
2. 继承 `plugins.base_plugin.BasePlugin` 并实现需要的钩子方法。
3. 在 Pipeline 配置中选择该插件并提供 JSON 格式的配置参数。

**内置插件示例**：`date_interval` 可根据间隔天数自动切换日期子目录。

## 🛠️ 自行构建

需要 Python 3.8+ 和 PyQt6：

```bash
pip install pyqt6 pyinstaller
pyinstaller --onefile --noconsole --name adb_syncer --hidden-import PyQt6.sip main.py
```


### ADB 配置

#### 下载渠道

- 开发者工具 发布页面 [Android developer](https://developer.android.com/studio/releases/platform-tools) 

- cn 区域 发布页面 [Android developer](https://developer.android.google.cn/tools/releases/platform-tools)

下载解压后，可以把 `adb.exe`，`AdbWinApi.dll`，`AdbWinUsbApi.dll` 这三个复制到 本软件同目录；或者 将整个工具包文件夹的路径，写入系统路径 PATH

---

### 界面
![设置界面](assets/screenshots/screenshot_sync_edit.JPG)


