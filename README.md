# OCR 图像识别操作工具

使用DeepSeekV4Pro制作的工具demo
基于 OpenCV 模板匹配 + PyAutoGUI 键鼠操作的自动化工具，参考 [MAA](https://github.com/MaaAssistantArknights/MaaAssistantArknights) 设计思路。

支持两种识别模式：
- **模板匹配** — 截取屏幕图像作为模板，匹配成功后执行操作
- **颜色匹配** — 检测屏幕上出现的特定颜色（如红点提示、高亮边框），匹配后点击或执行操作

搭配分支逻辑、循环重试、流程编排，无需编程即可创建自动化流程。

## 快速开始

### 前置要求

- **Python 3.9+**（需勾选"Add Python to PATH"）
- Windows 10/11

> Python 下载: [https://www.python.org/downloads/](https://www.python.org/downloads/)

### 启动方式（二选一）

**方式一：直接运行源码**

```bash
# 1. 克隆项目
git clone <your-repo-url>
cd ocr-tool

# 2. 安装依赖
pip install -r requirements.txt

# 3. 启动
python main.py
```

**方式二：使用打包好的 exe**

从 [Releases](<your-releases-url>) 下载 `release.zip`，解压后得到：

```
release/
  OCR识别操作工具.exe
  templates/          ← 存放模板截图
  flows/              ← 存放流程文件
```

双击 `OCR识别操作工具.exe` 即可运行，无需安装 Python。

## 使用指南

### 基本概念

```
截取模板图片 → 设置匹配步骤 → 编排操作流程 → 运行自动化
```

每个**步骤**包含：
- **模板图片** — 要在屏幕上查找的图像
- **匹配条件** — 置信度阈值、搜索区域、超时时间
- **匹配成功时** — 执行什么操作、跳转到哪个步骤
- **匹配失败时** — 执行什么操作、跳转到哪个步骤

### 第一步：截取模板

1. 点击工具栏 **"截取模板"**
2. 屏幕变暗后，鼠标框选要识别的目标区域
3. 松开鼠标自动保存到 `templates/` 目录

### 第二步：创建流程

1. 点击 **"添加步骤"**，设置步骤名称
2. 点击模板图片旁的 **"浏览"** 或 **"截取"** 选择模板
3. 调整匹配阈值（默认 0.8，越高越严格）
4. 在 **"匹配成功时"** 区域点 `+` 添加操作：
   - **click** — 鼠标点击（支持绝对坐标 / 相对匹配点偏移）
   - **wait** — 等待 N 秒
   - **keypress** — 模拟按键（如 `enter`、`ctrl+c`）
   - **typewrite** — 输入文本
   - **scroll** — 滚轮滚动
   - **drag** — 鼠标拖拽
5. 设置"跳转到步骤"决定下一步走向
6. 同样配置 **"匹配失败时"** 的分支

### 第三步：设置入口步骤

在左侧下拉框中选择流程的起始步骤。

### 第四步：运行

点击 **"▶ 运行"** 或按 `F5` 开始执行，按 `Esc` 停止。

运行日志显示在底部面板。

### 快捷键

| 快捷键 | 功能 |
|--------|------|
| `Ctrl+N` | 新建流程 |
| `Ctrl+O` | 打开流程 |
| `Ctrl+S` | 保存流程 |
| `F5` | 运行流程 |
| `Esc` | 停止运行 |

### 操作示例：匹配主界面按钮并点击

```
步骤: "检测主界面"
  匹配模式: 模板匹配
  模板: templates/main_button.png
  阈值: 0.8

  匹配成功:
    1. click (x=0, y=0, 相对匹配点)  ← 点击匹配到的按钮
    2. wait 2秒
    → 跳转到: "下一步骤"

  匹配失败:
    1. wait 3秒
    → 跳转到: "检测主界面"  ← 循环等待出现
```

### 颜色匹配：检测动态提示并点击

适合场景：页面上出现红点、高亮色块等动态提示，需要检测到后点击。

```
步骤: "检测红点提示"
  匹配模式: 颜色匹配
  目标颜色: #FF0000（红色）
  颜色容差: 20（±20 以内的红色都算匹配）
  搜索区域: 800, 0, 400, 200（只检测右上角区域）

  匹配成功:
    1. click (x=0, y=0, 相对匹配点)  ← 直接点击红点位置
    → 跳转到: "处理通知"

  匹配失败:
    → 跳转到: "下一步骤"  ← 没红点就跳过
```

## 流程 JSON 格式

流程文件保存在 `flows/` 目录，可直接编辑 JSON：

```json
{
  "entry_step": "step_1",
  "steps": [
    {
      "id": "step_1",
      "name": "检测主界面",
      "template": "templates/main.png",
      "threshold": 0.8,
      "region": [],
      "timeout": 30.0,
      "interval": 1.0,
      "on_match": {
        "actions": [
          { "type": "click", "x": 0, "y": 0, "relative": "match_center" },
          { "type": "wait", "duration": 2.0 }
        ],
        "goto": "step_2"
      },
      "on_no_match": {
        "actions": [],
        "goto": "step_1"
      }
    }
  ]
}
```

### 操作类型参考

| type | 参数 | 说明 |
|------|------|------|
| `click` | x, y, button, clicks, relative | 鼠标点击 |
| `wait` | duration | 等待（秒） |
| `keypress` | keys | 按键，组合键用 `+` 连接 |
| `typewrite` | text | 输入文本 |
| `scroll` | scroll | 滚轮（正=上，负=下） |
| `drag` | x, y, x2, y2, duration | 拖拽 |

`relative` 取值：
- `"absolute"` — 绝对屏幕坐标
- `"match_center"` — 以匹配区域中心为原点偏移（x/y 可填负数）

## 打包为 exe

```bash
python build_exe.py
```

打包完成后，`release/` 目录包含可直接分发的完整包：

```
release/
  OCR识别操作工具.exe
  templates/
  flows/
```

将整个 `release/` 文件夹压缩即可分享给未安装 Python 的用户。

## 项目结构

```
ocr-tool/
  main.py              # 主程序（GUI + 引擎）
  build_exe.py          # 打包脚本
  requirements.txt      # Python 依赖
  test_engine.py        # 核心引擎测试
  启动工具.bat           # Windows 一键启动
  一键打包.bat           # Windows 一键打包
  templates/            # 模板图片目录
  flows/                # 流程 JSON 目录
  dist/                 # 打包产物
  release/              # 发布目录
```

## 依赖

| 包 | 用途 |
|----|------|
| opencv-python | 模板匹配 |
| pyautogui | 键鼠操作 |
| pillow | 图像处理 |
| mss | 快速截屏（可选） |
| pyinstaller | 打包为 exe |

## 常见问题

### 双击 `.bat` 提示 "未找到 Python"

Python 可能未添加到系统 PATH。有 3 种解决方法：

1. **重新运行 Python 安装程序**，选择 `Modify`，勾选 `Add Python to PATH` 后安装
2. **手动添加 PATH**：将 `C:\Users\<用户名>\AppData\Local\Programs\Python\Python3xx` 添加到系统环境变量
3. **直接用命令行启动**：打开 cmd 或 PowerShell 进入项目目录，输入 `python main.py`

`.bat` 脚本会自动扫描常见安装路径，如果以上方法都无效，请确认 Python 已正确安装。

### 运行报错 `No module named 'cv2'`

依赖未安装，在项目目录下执行：

```bash
pip install -r requirements.txt
```

双击 `启动工具.bat` 也会自动检测并安装依赖。

### 杀毒软件误报

打包后的 exe 可能被部分杀毒软件误报（PyAutoGUI 模拟键鼠操作的特征）。可将其加入白名单，或直接用源码运行。

## License

MIT

## 项目截图
<img width="1002" height="752" alt="ScreenShot_2026-05-13_101709_079" src="https://github.com/user-attachments/assets/6368739a-97f9-46ee-89ba-843c58e108ed" />
<img width="1002" height="752" alt="ScreenShot_2026-05-13_104358_623" src="https://github.com/user-attachments/assets/653e468d-6b72-412d-9fcf-2b77e87fbce2" />

