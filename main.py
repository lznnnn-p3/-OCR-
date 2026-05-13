"""
OCR图像识别操作工具 - 基于模板匹配的自动化工具
参考 MAA 设计思路，支持图像匹配 → 键鼠操作 → 分支流程
"""
import json
import os
import sys
import time
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

import cv2
import numpy as np
import pyautogui
from PIL import Image, ImageTk, ImageGrab

pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.1

if getattr(sys, 'frozen', False):
    BASE_DIR = Path(sys.executable).parent
else:
    BASE_DIR = Path(__file__).parent
FLOWS_DIR = BASE_DIR / "flows"
TEMPLATES_DIR = BASE_DIR / "templates"
FLOWS_DIR.mkdir(exist_ok=True)
TEMPLATES_DIR.mkdir(exist_ok=True)


# ─── Data Structures ──────────────────────────────────────────────

@dataclass
class Action:
    """单个操作"""
    type: str = "click"          # click, wait, keypress, typewrite, scroll, drag
    x: int = 0
    y: int = 0
    button: str = "left"         # left, right, middle
    clicks: int = 1
    keys: str = ""               # e.g. "enter", "ctrl+c"
    text: str = ""
    duration: float = 0.5        # seconds
    scroll: int = 0
    x2: int = 0
    y2: int = 0
    relative: str = "absolute"   # absolute, match_center


@dataclass
class Branch:
    """匹配分支"""
    actions: list = field(default_factory=list)
    goto: str = ""


@dataclass
class Step:
    """流程步骤"""
    id: str = ""
    name: str = "新步骤"
    match_mode: str = "template" # template / color
    template: str = ""           # 模板图片路径 (match_mode=template)
    threshold: float = 0.8       # 匹配置信度 0-1
    target_color: str = ""       # 目标颜色 hex, 如 "#FF0000" (match_mode=color)
    color_tolerance: int = 10    # 颜色容差 0-255
    region: tuple = ()           # 搜索区域 (x,y,w,h)，空为全屏
    timeout: float = 10.0        # 超时秒数
    interval: float = 0.5        # 重试间隔秒数
    on_match: Branch = field(default_factory=Branch)
    on_no_match: Branch = field(default_factory=Branch)


# ─── Core Engine ──────────────────────────────────────────────────

class MatchEngine:
    """图像匹配引擎"""

    @staticmethod
    def capture_screen(region=None) -> np.ndarray:
        """截取屏幕，返回 BGR 格式的 numpy 数组"""
        img = ImageGrab.grab(bbox=region, all_screens=True)
        return cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)

    @staticmethod
    def match_template(screenshot: np.ndarray, template_path: str,
                       threshold: float, region=None) -> Optional[tuple]:
        """
        在截图中匹配模板，返回 (center_x, center_y, confidence) 或 None
        """
        template = cv2.imread(template_path)
        if template is None:
            return None

        if region:
            x, y, w, h = region
            search_area = screenshot[y:y + h, x:x + w]
            offset_x, offset_y = x, y
        else:
            search_area = screenshot
            offset_x, offset_y = 0, 0

        if search_area.shape[0] < template.shape[0] or search_area.shape[1] < template.shape[1]:
            return None

        result = cv2.matchTemplate(search_area, template, cv2.TM_CCOEFF_NORMED)
        min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)

        if max_val >= threshold:
            center_x = offset_x + max_loc[0] + template.shape[1] // 2
            center_y = offset_y + max_loc[1] + template.shape[0] // 2
            return (center_x, center_y, float(max_val))

        return None

    @staticmethod
    def match_all(screenshot: np.ndarray, template_path: str,
                  threshold: float, region=None) -> list:
        """匹配所有满足阈值的位置，返回 [(cx, cy, conf), ...]"""
        template = cv2.imread(template_path)
        if template is None:
            return []

        if region:
            x, y, w, h = region
            search_area = screenshot[y:y + h, x:x + w]
            offset_x, offset_y = x, y
        else:
            search_area = screenshot
            offset_x, offset_y = 0, 0

        if search_area.shape[0] < template.shape[0] or search_area.shape[1] < template.shape[1]:
            return []

        result = cv2.matchTemplate(search_area, template, cv2.TM_CCOEFF_NORMED)
        locations = np.where(result >= threshold)
        matches = []
        tw, th = template.shape[1], template.shape[0]
        for pt in zip(*locations[::-1]):
            cx = offset_x + pt[0] + tw // 2
            cy = offset_y + pt[1] + th // 2
            conf = float(result[pt[1], pt[0]])
            matches.append((cx, cy, conf))
        return matches

    @staticmethod
    def parse_hex_color(hex_str: str) -> tuple:
        """hex 颜色字符串转 BGR tuple，如 '#FF0000' → (0, 0, 255)"""
        h = hex_str.lstrip("#").strip()
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        return (b, g, r)  # OpenCV 用 BGR

    @staticmethod
    def match_color(screenshot: np.ndarray, target_color: str,
                    tolerance: int, region=None) -> Optional[tuple]:
        """
        在截图中匹配颜色，返回第一个匹配点的 (x, y, 1.0) 或 None。
        target_color: '#FF0000' 格式
        tolerance: 每个通道的容差 (0-255)
        """
        try:
            target = MatchEngine.parse_hex_color(target_color)
        except (ValueError, IndexError):
            return None

        if region:
            x, y, w, h = region
            search_area = screenshot[y:y + h, x:x + w]
            offset_x, offset_y = x, y
        else:
            search_area = screenshot
            offset_x, offset_y = 0, 0

        lower = np.array([max(0, c - tolerance) for c in target], dtype=np.uint8)
        upper = np.array([min(255, c + tolerance) for c in target], dtype=np.uint8)

        mask = cv2.inRange(search_area, lower, upper)
        points = cv2.findNonZero(mask)
        if points is not None and len(points) > 0:
            pt = points[0][0]
            return (offset_x + int(pt[0]), offset_y + int(pt[1]), 1.0)

        return None


class ActionExecutor:
    """操作执行器"""

    @staticmethod
    def execute(action: Action, match_pos: Optional[tuple] = None):
        """执行单个操作。match_pos 为匹配中心点 (cx, cy)，用于相对定位"""
        x, y = action.x, action.y
        if action.relative == "match_center" and match_pos:
            x = match_pos[0] + action.x
            y = match_pos[1] + action.y

        if action.type == "click":
            pyautogui.click(x, y, clicks=action.clicks, button=action.button)
        elif action.type == "wait":
            time.sleep(action.duration)
        elif action.type == "keypress":
            pyautogui.hotkey(*action.keys.split("+"))
        elif action.type == "typewrite":
            pyautogui.typewrite(action.text, interval=0.05)
        elif action.type == "scroll":
            pyautogui.scroll(action.scroll, x=x, y=y)
        elif action.type == "drag":
            pyautogui.moveTo(x, y)
            pyautogui.drag(action.x2 - x, action.y2 - y, duration=action.duration)
        else:
            print(f"[WARN] 未知操作类型: {action.type}")


class FlowEngine:
    """流程执行引擎"""

    def __init__(self, log_callback=None):
        self.steps: dict[str, Step] = {}
        self.entry_step_id: str = ""
        self.running = False
        self.paused = False
        self.current_step_id: str = ""
        self.log = log_callback or print

    def load_flow(self, path: str):
        """从 JSON 文件加载流程"""
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.steps.clear()
        for sdata in data.get("steps", []):
            step = Step()
            step.id = sdata["id"]
            step.name = sdata.get("name", step.id)
            step.match_mode = sdata.get("match_mode", "template")
            step.template = sdata.get("template", "")
            step.threshold = sdata.get("threshold", 0.8)
            step.target_color = sdata.get("target_color", "")
            step.color_tolerance = sdata.get("color_tolerance", 10)
            step.region = tuple(sdata.get("region", [])) or ()
            step.timeout = sdata.get("timeout", 10.0)
            step.interval = sdata.get("interval", 0.5)
            om = sdata.get("on_match", {})
            step.on_match = Branch(
                actions=[Action(**a) for a in om.get("actions", [])],
                goto=om.get("goto", "")
            )
            onm = sdata.get("on_no_match", {})
            step.on_no_match = Branch(
                actions=[Action(**a) for a in onm.get("actions", [])],
                goto=onm.get("goto", "")
            )
            self.steps[step.id] = step
        self.entry_step_id = data.get("entry_step", "")
        self.log(f"流程已加载: {len(self.steps)} 个步骤")

    def save_flow(self, path: str):
        """保存流程为 JSON 文件"""
        data = {
            "entry_step": self.entry_step_id,
            "steps": []
        }
        for step in self.steps.values():
            sdata = {
                "id": step.id,
                "name": step.name,
                "match_mode": step.match_mode,
                "template": step.template,
                "threshold": step.threshold,
                "target_color": step.target_color,
                "color_tolerance": step.color_tolerance,
                "region": list(step.region) if step.region else [],
                "timeout": step.timeout,
                "interval": step.interval,
                "on_match": {
                    "actions": [a.__dict__ for a in step.on_match.actions],
                    "goto": step.on_match.goto
                },
                "on_no_match": {
                    "actions": [a.__dict__ for a in step.on_no_match.actions],
                    "goto": step.on_no_match.goto
                }
            }
            data["steps"].append(sdata)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        self.log(f"流程已保存: {path}")

    def _run_branch(self, branch: Branch, match_pos: Optional[tuple]):
        """执行分支中的操作序列"""
        for action in branch.actions:
            if not self.running:
                return
            self.log(f"  执行: {action.type} {action.keys or f'({action.x},{action.y})'}")
            ActionExecutor.execute(action, match_pos)

    def _execute_step(self, step: Step):
        """执行单步骤的匹配循环"""
        if step.match_mode == "color":
            if not step.target_color:
                self.log(f"[ERROR] 未设置目标颜色")
                return step.on_no_match.goto if not self._is_branch_empty(step.on_no_match) else ""
        else:
            if not step.template or not os.path.isfile(step.template):
                self.log(f"[ERROR] 模板文件不存在: {step.template}")
                return step.on_no_match.goto if not self._is_branch_empty(step.on_no_match) else ""

        region = step.region if step.region else None
        deadline = time.time() + step.timeout

        if step.match_mode == "color":
            self.log(f"→ 步骤 [{step.name}] 颜色匹配 (目标={step.target_color}, 容差={step.color_tolerance}, 超时={step.timeout}s)")
        else:
            self.log(f"→ 步骤 [{step.name}] 模板匹配 (阈值={step.threshold}, 超时={step.timeout}s)")

        while self.running and time.time() < deadline:
            screenshot = MatchEngine.capture_screen()

            if step.match_mode == "color":
                result = MatchEngine.match_color(screenshot, step.target_color,
                                                 step.color_tolerance, region)
            else:
                result = MatchEngine.match_template(screenshot, step.template,
                                                    step.threshold, region)

            if result:
                cx, cy, conf = result
                self.log(f"  ✓ 匹配成功! 位置=({cx},{cy}), 置信度={conf:.3f}")
                self._run_branch(step.on_match, (cx, cy))
                return step.on_match.goto
            else:
                time.sleep(step.interval)

        self.log(f"  ✗ 匹配超时 ({step.timeout}s)")
        self._run_branch(step.on_no_match, None)
        return step.on_no_match.goto

    @staticmethod
    def _is_branch_empty(branch: Branch) -> bool:
        return len(branch.actions) == 0 and not branch.goto

    def run(self):
        """执行流程主循环"""
        if not self.entry_step_id or self.entry_step_id not in self.steps:
            self.log("[ERROR] 未设置入口步骤或入口步骤不存在")
            return

        self.running = True
        self.current_step_id = self.entry_step_id
        visited = set()
        max_steps = 1000
        step_count = 0

        self.log("══════════ 开始执行流程 ══════════")

        while self.running and self.current_step_id and step_count < max_steps:
            step_count += 1
            if self.current_step_id in visited:
                self.log(f"[WARN] 检测到循环，返回步骤 [{self.current_step_id}]")
            visited.add(self.current_step_id)

            step = self.steps.get(self.current_step_id)
            if not step:
                self.log(f"[ERROR] 步骤不存在: {self.current_step_id}")
                break

            next_id = self._execute_step(step)
            self.current_step_id = next_id

        self.running = False
        self.log(f"══════════ 流程结束 (执行 {step_count} 步) ══════════")

    def stop(self):
        """停止执行"""
        self.running = False
        self.log("■ 用户停止流程")


# ─── GUI Application ──────────────────────────────────────────────

class StepDialog(tk.Toplevel):
    """步骤编辑对话框 — 使用 Tab 分页"""

    def __init__(self, parent, step: Step, all_step_ids: list):
        super().__init__(parent)
        self.step = step
        self.all_step_ids = all_step_ids
        self.result = None

        self.title(f"编辑步骤 - {step.name}")
        # 动态计算窗口高度，确保能完整显示
        screen_h = self.winfo_screenheight()
        win_h = min(580, screen_h - 120)
        self.geometry(f"720x{win_h}")
        self.minsize(600, 450)
        self.resizable(True, True)
        self.transient(parent)
        self.grab_set()

        self._build_ui()
        self._load_step()
        self.wait_window()

    def _build_ui(self):
        # 底部按钮先创建，固定在窗口底部
        btn_row = ttk.Frame(self, padding=(10, 5))
        btn_row.pack(side=tk.BOTTOM, fill=tk.X)
        ttk.Button(btn_row, text="保存", command=self._on_save, width=10).pack(side=tk.RIGHT, padx=5)
        ttk.Button(btn_row, text="取消", command=self.destroy, width=10).pack(side=tk.RIGHT, padx=5)

        # Tab 分页
        notebook = ttk.Notebook(self, padding=5)
        notebook.pack(fill=tk.BOTH, expand=True, padx=5, pady=(5, 0))

        # --- Tab 1: 基本设置 ---
        tab_settings = ttk.Frame(notebook, padding=10)
        notebook.add(tab_settings, text="基本设置")

        basic = ttk.LabelFrame(tab_settings, text="步骤信息", padding=10)
        basic.pack(fill=tk.X)

        ttk.Label(basic, text="名称:").grid(row=0, column=0, sticky=tk.W, padx=(0, 5))
        self.name_var = tk.StringVar()
        ttk.Entry(basic, textvariable=self.name_var, width=30).grid(row=0, column=1, sticky=tk.W)

        ttk.Label(basic, text="ID:").grid(row=0, column=2, sticky=tk.W, padx=(10, 5))
        self.id_var = tk.StringVar()
        ttk.Entry(basic, textvariable=self.id_var, width=20).grid(row=0, column=3, sticky=tk.W)

        # 匹配模式
        mode_frame = ttk.LabelFrame(tab_settings, text="匹配模式", padding=10)
        mode_frame.pack(fill=tk.X, pady=(10, 0))
        self.match_mode_var = tk.StringVar(value="template")
        ttk.Radiobutton(mode_frame, text="模板匹配 — 使用截图与模板图片比对",
                        variable=self.match_mode_var, value="template",
                        command=self._on_mode_change).grid(row=0, column=0, sticky=tk.W)
        ttk.Radiobutton(mode_frame, text="颜色匹配 — 检测屏幕上出现的特定颜色",
                        variable=self.match_mode_var, value="color",
                        command=self._on_mode_change).grid(row=1, column=0, sticky=tk.W, pady=(5, 0))

        # 匹配参数容器
        self.match_params = ttk.Frame(tab_settings, padding=(0, 10, 0, 0))
        self.match_params.pack(fill=tk.X)

        # 通用设置（超时、间隔、搜索区域）
        common_frame = ttk.LabelFrame(tab_settings, text="重试设置", padding=10)
        common_frame.pack(fill=tk.X, pady=(10, 0))

        ttk.Label(common_frame, text="超时(秒):").grid(row=0, column=0, sticky=tk.W, padx=(0, 5))
        self.timeout_var = tk.DoubleVar(value=10.0)
        ttk.Spinbox(common_frame, textvariable=self.timeout_var, from_=0.5, to=300, increment=1, width=8).grid(
            row=0, column=1, sticky=tk.W)

        ttk.Label(common_frame, text="重试间隔(秒):").grid(row=0, column=2, sticky=tk.W, padx=(10, 5))
        self.interval_var = tk.DoubleVar(value=0.5)
        ttk.Spinbox(common_frame, textvariable=self.interval_var, from_=0.1, to=10, increment=0.1, width=8).grid(
            row=0, column=3, sticky=tk.W)

        region_row = ttk.Frame(common_frame)
        region_row.grid(row=1, column=0, columnspan=4, sticky=tk.EW, pady=(10, 0))
        ttk.Label(region_row, text="搜索区域 (x,y,w,h 留空=全屏):").pack(side=tk.LEFT)
        self.region_x = tk.StringVar(value="")
        self.region_y = tk.StringVar(value="")
        self.region_w = tk.StringVar(value="")
        self.region_h = tk.StringVar(value="")
        for sv, label in [(self.region_x, "x"), (self.region_y, "y"), (self.region_w, "w"), (self.region_h, "h")]:
            ttk.Label(region_row, text=label).pack(side=tk.LEFT, padx=(5, 0))
            ttk.Entry(region_row, textvariable=sv, width=6).pack(side=tk.LEFT, padx=1)

        self._build_template_params()
        self._build_color_params()

        # --- Tab 2: 匹配成功 ---
        tab_match = ttk.Frame(notebook, padding=10)
        notebook.add(tab_match, text="✓ 匹配成功时")
        self._build_branch_ui(tab_match, "on_match")

        # --- Tab 3: 匹配失败 ---
        tab_nomatch = ttk.Frame(notebook, padding=10)
        notebook.add(tab_nomatch, text="✗ 匹配失败时")
        self._build_branch_ui(tab_nomatch, "on_no_match")

    def _build_branch_ui(self, parent, branch_name):
        """构建分支的动作列表 + 跳转"""
        frame = ttk.Frame(parent)
        frame.pack(fill=tk.BOTH, expand=True)

        # 动作列表
        cols = ("类型", "参数", "说明")
        tree = ttk.Treeview(frame, columns=cols, show="headings", height=4)
        tree.heading("类型", text="类型")
        tree.heading("参数", text="参数")
        tree.heading("说明", text="说明")
        tree.column("类型", width=80)
        tree.column("参数", width=200)
        tree.column("说明", width=200)
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        scrollbar = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=tree.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        tree.configure(yscrollcommand=scrollbar.set)

        setattr(self, f"{branch_name}_tree", tree)

        btn_frame = ttk.Frame(frame)
        btn_frame.pack(side=tk.RIGHT, padx=(5, 0))
        ttk.Button(btn_frame, text="+", width=2,
                   command=lambda: self._add_action(branch_name)).pack(pady=1)
        ttk.Button(btn_frame, text="-", width=2,
                   command=lambda: self._remove_action(branch_name)).pack(pady=1)
        ttk.Button(btn_frame, text="↑", width=2,
                   command=lambda: self._move_action(branch_name, -1)).pack(pady=1)
        ttk.Button(btn_frame, text="↓", width=2,
                   command=lambda: self._move_action(branch_name, 1)).pack(pady=1)

        # 跳转设置
        goto_frame = ttk.Frame(parent)
        goto_frame.pack(fill=tk.X, pady=(5, 0))
        ttk.Label(goto_frame, text="跳转到步骤:").pack(side=tk.LEFT)
        goto_var = tk.StringVar()
        goto_cb = ttk.Combobox(goto_frame, textvariable=goto_var, values=[""] + self.all_step_ids, width=25)
        goto_cb.pack(side=tk.LEFT, padx=5)
        setattr(self, f"{branch_name}_goto_var", goto_var)
        setattr(self, f"{branch_name}_goto_cb", goto_cb)

    def _add_action(self, branch_name):
        """弹出添加动作的小对话框"""
        dialog = ActionDialog(self)
        if dialog.result:
            action = dialog.result
            tree = getattr(self, f"{branch_name}_tree")
            desc = self._action_desc(action)
            tree.insert("", tk.END, values=(action.type,
                       f"{action.keys or f'({action.x},{action.y})'}", desc),
                        tags=(json.dumps(action.__dict__, ensure_ascii=False),))

    def _remove_action(self, branch_name):
        tree = getattr(self, f"{branch_name}_tree")
        sel = tree.selection()
        for item in sel:
            tree.delete(item)

    def _move_action(self, branch_name, direction):
        tree = getattr(self, f"{branch_name}_tree")
        sel = tree.selection()
        if not sel:
            return
        items = tree.get_children()
        idx = items.index(sel[0])
        new_idx = idx + direction
        if 0 <= new_idx < len(items):
            tree.move(sel[0], "", new_idx)

    def _action_desc(self, action: Action) -> str:
        if action.type == "click":
            pos = f"相对匹配点({action.x},{action.y})" if action.relative == "match_center" else f"({action.x},{action.y})"
            return f"点击 {pos} {action.button}键 x{action.clicks}"
        elif action.type == "wait":
            return f"等待 {action.duration}秒"
        elif action.type == "keypress":
            return f"按键 {action.keys}"
        elif action.type == "typewrite":
            return f"输入文本: {action.text}"
        elif action.type == "scroll":
            return f"滚动 {action.scroll}"
        elif action.type == "drag":
            return f"拖拽 ({action.x},{action.y})→({action.x2},{action.y2})"
        return action.type

    def _browse_template(self):
        path = filedialog.askopenfilename(
            title="选择模板图片",
            filetypes=[("图片文件", "*.png *.jpg *.jpeg *.bmp"), ("所有文件", "*.*")],
            initialdir=TEMPLATES_DIR
        )
        if path:
            self.template_var.set(path)

    def _capture_template(self):
        """截取屏幕区域作为模板"""
        self.withdraw()
        self.update()
        time.sleep(0.3)

        # 先截取屏幕，再在截图上叠加遮罩，保证能看到屏幕内容
        screen_img = ImageGrab.grab(all_screens=True)
        darkened = screen_img.copy()
        darken = Image.new("RGB", darkened.size, (0, 0, 0))
        darkened = Image.blend(darkened, darken, 0.5)

        cancelled = [False]

        overlay = tk.Toplevel()
        overlay.attributes("-fullscreen", True)
        overlay.attributes("-topmost", True)
        overlay.overrideredirect(True)

        tk_img = ImageTk.PhotoImage(darkened)
        canvas = tk.Canvas(overlay, cursor="cross", highlightthickness=0,
                           width=darkened.width, height=darkened.height)
        canvas.pack(fill=tk.BOTH, expand=True)
        canvas.create_image(0, 0, anchor=tk.NW, image=tk_img, tag="bg")

        rect = [0, 0, 0, 0]
        dragging = [False]

        def on_mouse_down(e):
            dragging[0] = True
            rect[0], rect[1] = e.x, e.y
            rect[2], rect[3] = e.x, e.y

        def on_mouse_move(e):
            if not dragging[0]:
                return
            rect[2], rect[3] = e.x, e.y
            canvas.delete("sel")
            x1, y1 = min(rect[0], rect[2]), min(rect[1], rect[3])
            x2, y2 = max(rect[0], rect[2]), max(rect[1], rect[3])
            canvas.create_rectangle(x1, y1, x2, y2, outline="red", width=2, tag="sel")

        def on_mouse_up(e):
            dragging[0] = False
            overlay.destroy()

        def on_cancel(e):
            cancelled[0] = True
            overlay.destroy()

        canvas.bind("<ButtonPress-1>", on_mouse_down)
        canvas.bind("<B1-Motion>", on_mouse_move)
        canvas.bind("<ButtonRelease-1>", on_mouse_up)
        canvas.bind("<Button-3>", on_cancel)
        canvas.bind("<Escape>", on_cancel)

        overlay.focus_force()
        overlay.grab_set()
        overlay.wait_window()

        self.deiconify()
        self.lift()
        self.focus_force()

        x1, y1, x2, y2 = min(rect[0], rect[2]), min(rect[1], rect[3]), max(rect[0], rect[2]), max(rect[1], rect[3])
        if cancelled[0] or x2 - x1 < 5 or y2 - y1 < 5:
            return

        img = screen_img.crop((x1, y1, x2, y2))
        ts = int(time.time())
        save_path = TEMPLATES_DIR / f"capture_{ts}.png"
        img.save(str(save_path))
        self.template_var.set(str(save_path))

    def _build_template_params(self):
        """构建模板匹配的参数 UI"""
        frame = ttk.LabelFrame(self.match_params, text="模板匹配参数", padding=10)
        self.template_param_frame = frame

        ttk.Label(frame, text="模板图片:").grid(row=0, column=0, sticky=tk.W, padx=(0, 5))
        tmpl_row = ttk.Frame(frame)
        tmpl_row.grid(row=0, column=1, columnspan=2, sticky=tk.EW)
        self.template_var = tk.StringVar()
        ttk.Entry(tmpl_row, textvariable=self.template_var, width=30).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(tmpl_row, text="浏览", command=self._browse_template, width=6).pack(side=tk.LEFT, padx=2)
        ttk.Button(tmpl_row, text="截取", command=self._capture_template, width=6).pack(side=tk.LEFT)

        ttk.Label(frame, text="匹配阈值:").grid(row=1, column=0, sticky=tk.W, padx=(0, 5), pady=(10, 0))
        self.threshold_var = tk.DoubleVar(value=0.8)
        ttk.Scale(frame, from_=0.5, to=1.0, variable=self.threshold_var,
                  orient=tk.HORIZONTAL, length=200).grid(row=1, column=1, sticky=tk.W, pady=(10, 0))
        self.thresh_label = ttk.Label(frame, text="0.80")
        self.thresh_label.grid(row=1, column=2, sticky=tk.W, pady=(10, 0))
        self.threshold_var.trace_add("write", lambda *a: self.thresh_label.configure(
            text=f"{self.threshold_var.get():.2f}"))

    def _build_color_params(self):
        """构建颜色匹配的参数 UI"""
        frame = ttk.LabelFrame(self.match_params, text="颜色匹配参数", padding=10)
        self.color_param_frame = frame

        ttk.Label(frame, text="目标颜色:").grid(row=0, column=0, sticky=tk.W, padx=(0, 5))
        color_row = ttk.Frame(frame)
        color_row.grid(row=0, column=1, columnspan=2, sticky=tk.EW)
        self.color_var = tk.StringVar(value="#FF0000")
        self.color_entry = ttk.Entry(color_row, textvariable=self.color_var, width=12)
        self.color_entry.pack(side=tk.LEFT)
        # 颜色预览色块
        self.color_preview = tk.Canvas(color_row, width=24, height=24, bg="#FF0000",
                                       highlightthickness=1, highlightbackground="#888")
        self.color_preview.pack(side=tk.LEFT, padx=8)
        ttk.Button(color_row, text="取色", command=self._pick_color, width=6).pack(side=tk.LEFT)
        ttk.Label(frame, text="支持格式: #FF0000", foreground="#888",
                  font=("", 8)).grid(row=0, column=3, sticky=tk.W, padx=5)
        self.color_var.trace_add("write", lambda *a: self._update_color_preview())

        ttk.Label(frame, text="颜色容差:").grid(row=1, column=0, sticky=tk.W, padx=(0, 5), pady=(10, 0))
        self.tolerance_var = tk.IntVar(value=10)
        ttk.Scale(frame, from_=0, to=80, variable=self.tolerance_var,
                  orient=tk.HORIZONTAL, length=200).grid(row=1, column=1, sticky=tk.W, pady=(10, 0))
        self.tolerance_label = ttk.Label(frame, text="10")
        self.tolerance_label.grid(row=1, column=2, sticky=tk.W, pady=(10, 0))
        self.tolerance_var.trace_add("write", lambda *a: self.tolerance_label.configure(
            text=str(self.tolerance_var.get())))

    def _update_color_preview(self):
        try:
            hex_str = self.color_var.get().strip()
            if hex_str.startswith("#") and len(hex_str) >= 7:
                self.color_preview.configure(bg=hex_str[:7])
            else:
                self.color_preview.configure(bg="#CCCCCC")
        except Exception:
            self.color_preview.configure(bg="#CCCCCC")

    def _pick_color(self):
        """屏幕取色 — 点击屏幕上任意位置获取颜色"""
        self.withdraw()
        self.update()
        time.sleep(0.3)

        # 先截取屏幕，显示原图让用户看到真实颜色
        screen_img = ImageGrab.grab(all_screens=True)

        overlay = tk.Toplevel()
        overlay.attributes("-fullscreen", True)
        overlay.attributes("-topmost", True)
        overlay.overrideredirect(True)

        tk_img = ImageTk.PhotoImage(screen_img)
        canvas = tk.Canvas(overlay, cursor="crosshair", highlightthickness=0,
                           width=screen_img.width, height=screen_img.height)
        canvas.pack(fill=tk.BOTH, expand=True)
        canvas.create_image(0, 0, anchor=tk.NW, image=tk_img, tag="bg")

        picked = [None]
        click_pos = [None]

        def on_down(e):
            click_pos[0] = (e.x, e.y)

        def on_up(e):
            if click_pos[0]:
                overlay.destroy()

        def on_cancel(e):
            overlay.destroy()

        canvas.bind("<ButtonPress-1>", on_down)
        canvas.bind("<ButtonRelease-1>", on_up)
        canvas.bind("<Button-3>", on_cancel)
        canvas.bind("<Escape>", on_cancel)

        overlay.focus_force()
        overlay.grab_set()
        overlay.wait_window()

        if click_pos[0]:
            rgb = screen_img.getpixel(click_pos[0])
            picked[0] = f"#{rgb[0]:02X}{rgb[1]:02X}{rgb[2]:02X}"

        self.deiconify()
        self.lift()
        self.focus_force()

        if picked[0]:
            self.color_var.set(picked[0])

    def _on_mode_change(self):
        mode = self.match_mode_var.get()
        if mode == "color":
            self.template_param_frame.pack_forget()
            self.color_param_frame.pack(fill=tk.X)
        else:
            self.color_param_frame.pack_forget()
            self.template_param_frame.pack(fill=tk.X)

    def _load_step(self):
        """加载步骤数据到界面"""
        s = self.step
        self.name_var.set(s.name)
        self.id_var.set(s.id)
        self.match_mode_var.set(s.match_mode)
        self.template_var.set(s.template)
        self.threshold_var.set(s.threshold)
        self.color_var.set(s.target_color or "#FF0000")
        self.tolerance_var.set(s.color_tolerance)
        self.timeout_var.set(s.timeout)
        self.interval_var.set(s.interval)
        if s.region and len(s.region) == 4:
            self.region_x.set(str(s.region[0]))
            self.region_y.set(str(s.region[1]))
            self.region_w.set(str(s.region[2]))
            self.region_h.set(str(s.region[3]))

        self._on_mode_change()

        for branch_name, branch in [("on_match", s.on_match), ("on_no_match", s.on_no_match)]:
            tree = getattr(self, f"{branch_name}_tree")
            for action in branch.actions:
                desc = self._action_desc(action)
                tree.insert("", tk.END, values=(action.type,
                           f"{action.keys or f'({action.x},{action.y})'}", desc),
                            tags=(json.dumps(action.__dict__, ensure_ascii=False),))
            getattr(self, f"{branch_name}_goto_var").set(branch.goto)

    def _on_save(self):
        """保存步骤数据"""
        s = self.step
        s.name = self.name_var.get().strip() or "未命名"
        s.id = self.id_var.get().strip() or s.name
        s.match_mode = self.match_mode_var.get()
        s.template = self.template_var.get()
        s.threshold = self.threshold_var.get()
        s.target_color = self.color_var.get().strip()
        s.color_tolerance = self.tolerance_var.get()
        s.timeout = self.timeout_var.get()
        s.interval = self.interval_var.get()

        rx = self.region_x.get().strip()
        ry = self.region_y.get().strip()
        rw = self.region_w.get().strip()
        rh = self.region_h.get().strip()
        if rx and ry and rw and rh:
            s.region = (int(rx), int(ry), int(rw), int(rh))
        else:
            s.region = ()

        for branch_name in ["on_match", "on_no_match"]:
            tree = getattr(self, f"{branch_name}_tree")
            actions = []
            for item in tree.get_children():
                tags = tree.item(item, "tags")
                if tags:
                    adata = json.loads(tags[0])
                    actions.append(Action(**adata))
            branch = getattr(s, branch_name)
            branch.actions = actions
            branch.goto = getattr(self, f"{branch_name}_goto_var").get()

        self.result = True
        self.destroy()


class ActionDialog(tk.Toplevel):
    """添加/编辑单个操作"""

    def __init__(self, parent):
        super().__init__(parent)
        self.title("添加操作")
        self.geometry("420x380")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()
        self.result = None
        self._build_ui()
        self.wait_window()

    def _build_ui(self):
        main = ttk.Frame(self, padding=10)
        main.pack(fill=tk.BOTH, expand=True)

        ttk.Label(main, text="操作类型:").grid(row=0, column=0, sticky=tk.W)
        self.type_var = tk.StringVar(value="click")
        type_cb = ttk.Combobox(main, textvariable=self.type_var,
                               values=["click", "wait", "keypress", "typewrite", "scroll", "drag"],
                               state="readonly", width=15)
        type_cb.grid(row=0, column=1, sticky=tk.W, padx=5)
        type_cb.bind("<<ComboboxSelected>>", self._on_type_change)

        # 动态参数区域
        self.params_frame = ttk.Frame(main)
        self.params_frame.grid(row=1, column=0, columnspan=2, sticky=tk.NSEW, pady=10)
        main.rowconfigure(1, weight=1)

        self._param_widgets = {}
        self._build_click_params()

        # 按钮
        btn_row = ttk.Frame(main)
        btn_row.grid(row=2, column=0, columnspan=2, pady=(10, 0))
        ttk.Button(btn_row, text="确定", command=self._ok).pack(side=tk.RIGHT, padx=5)
        ttk.Button(btn_row, text="取消", command=self.destroy).pack(side=tk.RIGHT, padx=5)

    def _clear_params(self):
        for w in self.params_frame.winfo_children():
            w.destroy()
        self._param_widgets.clear()

    def _add_param_row(self, row, label, widget, var_name=None):
        ttk.Label(self.params_frame, text=label).grid(row=row, column=0, sticky=tk.W, pady=2)
        widget.grid(row=row, column=1, sticky=tk.EW, padx=5, pady=2)
        if var_name:
            self._param_widgets[var_name] = widget

    def _build_click_params(self):
        self._clear_params()
        row = 0
        ttk.Label(self.params_frame, text="点击坐标 (相对匹配点偏移时可填正负数):",
                  font=("", 9)).grid(row=row, column=0, columnspan=2, sticky=tk.W, pady=(0, 5))
        row += 1

        x_var = tk.IntVar(value=0)
        self._add_param_row(row, "X:", ttk.Entry(self.params_frame, textvariable=x_var, width=15), "x")
        setattr(self, "_x_var", x_var)
        row += 1

        y_var = tk.IntVar(value=0)
        self._add_param_row(row, "Y:", ttk.Entry(self.params_frame, textvariable=y_var, width=15), "y")
        setattr(self, "_y_var", y_var)
        row += 1

        self._add_param_row(row, "按钮:", ttk.Combobox(self.params_frame,
                            textvariable=(btn_var := tk.StringVar(value="left")),
                            values=["left", "right", "middle"], state="readonly", width=13), "button")
        setattr(self, "_btn_var", btn_var)
        row += 1

        clicks_var = tk.IntVar(value=1)
        self._add_param_row(row, "点击次数:", ttk.Spinbox(self.params_frame,
                            textvariable=clicks_var, from_=1, to=10, width=15), "clicks")
        setattr(self, "_clicks_var", clicks_var)
        row += 1

        rel_var = tk.StringVar(value="absolute")
        self._add_param_row(row, "定位方式:", ttk.Combobox(self.params_frame,
                            textvariable=rel_var, values=["absolute", "match_center"],
                            state="readonly", width=13), "relative")
        setattr(self, "_rel_var", rel_var)

    def _build_wait_params(self):
        self._clear_params()
        dur_var = tk.DoubleVar(value=1.0)
        self._add_param_row(0, "等待时长(秒):",
                            ttk.Spinbox(self.params_frame, textvariable=dur_var, from_=0.1, to=300, increment=0.5, width=15))
        setattr(self, "_dur_var", dur_var)

    def _build_keypress_params(self):
        self._clear_params()
        ttk.Label(self.params_frame, text="组合键用 + 连接 (例: ctrl+c, alt+f4, enter):",
                  font=("", 9)).grid(row=0, column=0, columnspan=2, sticky=tk.W, pady=(0, 5))
        keys_var = tk.StringVar(value="")
        self._add_param_row(1, "按键:", ttk.Entry(self.params_frame, textvariable=keys_var, width=20))
        setattr(self, "_keys_var", keys_var)

    def _build_typewrite_params(self):
        self._clear_params()
        text_var = tk.StringVar(value="")
        self._add_param_row(0, "输入文本:", ttk.Entry(self.params_frame, textvariable=text_var, width=30))
        setattr(self, "_text_var", text_var)

    def _build_scroll_params(self):
        self._clear_params()
        scroll_var = tk.IntVar(value=-3)
        self._add_param_row(0, "滚动量 (+上/-下):",
                            ttk.Spinbox(self.params_frame, textvariable=scroll_var, from_=-100, to=100, width=15))
        setattr(self, "_scroll_var", scroll_var)

    def _build_drag_params(self):
        self._clear_params()
        for r, (label, var_name) in enumerate([("起点X:", "x1"), ("起点Y:", "y1"), ("终点X:", "x2"), ("终点Y:", "y2")]):
            v = tk.IntVar(value=0)
            self._add_param_row(r, label, ttk.Entry(self.params_frame, textvariable=v, width=15), var_name)
            setattr(self, f"_{var_name}_var", v)
        dur_var = tk.DoubleVar(value=0.5)
        self._add_param_row(4, "拖拽时长(秒):",
                            ttk.Spinbox(self.params_frame, textvariable=dur_var, from_=0.1, to=10, increment=0.1, width=15))
        setattr(self, "_drag_dur_var", dur_var)

    def _on_type_change(self, event=None):
        t = self.type_var.get()
        builders = {
            "click": self._build_click_params,
            "wait": self._build_wait_params,
            "keypress": self._build_keypress_params,
            "typewrite": self._build_typewrite_params,
            "scroll": self._build_scroll_params,
            "drag": self._build_drag_params
        }
        builders.get(t, self._build_click_params)()

    def _ok(self):
        t = self.type_var.get()
        action = Action(type=t)

        if t == "click":
            action.x = getattr(self, "_x_var").get()
            action.y = getattr(self, "_y_var").get()
            action.button = getattr(self, "_btn_var").get()
            action.clicks = getattr(self, "_clicks_var").get()
            action.relative = getattr(self, "_rel_var").get()
        elif t == "wait":
            action.duration = getattr(self, "_dur_var").get()
        elif t == "keypress":
            action.keys = getattr(self, "_keys_var").get()
        elif t == "typewrite":
            action.text = getattr(self, "_text_var").get()
        elif t == "scroll":
            action.scroll = getattr(self, "_scroll_var").get()
        elif t == "drag":
            action.x = getattr(self, "_x1_var").get()
            action.y = getattr(self, "_y1_var").get()
            action.x2 = getattr(self, "_x2_var").get()
            action.y2 = getattr(self, "_y2_var").get()
            action.duration = getattr(self, "_drag_dur_var").get()

        self.result = action
        self.destroy()


class OCRToolApp:
    """主应用"""

    def __init__(self):
        self.root = tk.Tk()
        self.root.title("OCR 图像识别操作工具")
        self.root.geometry("1000x700")
        self.root.minsize(800, 500)

        self.engine = FlowEngine(log_callback=self._log)
        self.steps: dict[str, Step] = {}
        self.current_file: Optional[str] = None
        self.run_thread: Optional[threading.Thread] = None

        self._build_menu()
        self._build_ui()
        self._new_flow()

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_menu(self):
        menubar = tk.Menu(self.root)
        self.root.config(menu=menubar)

        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="新建流程", command=self._new_flow, accelerator="Ctrl+N")
        file_menu.add_command(label="打开流程...", command=self._open_flow, accelerator="Ctrl+O")
        file_menu.add_command(label="保存流程", command=self._save_flow, accelerator="Ctrl+S")
        file_menu.add_command(label="另存为...", command=self._save_flow_as)
        file_menu.add_separator()
        file_menu.add_command(label="退出", command=self._on_close)
        menubar.add_cascade(label="文件", menu=file_menu)

        flow_menu = tk.Menu(menubar, tearoff=0)
        flow_menu.add_command(label="添加步骤", command=self._add_step)
        flow_menu.add_command(label="编辑选中步骤", command=self._edit_step)
        flow_menu.add_command(label="删除选中步骤", command=self._delete_step)
        flow_menu.add_separator()
        flow_menu.add_command(label="截取模板图片", command=self._capture_template_standalone)
        menubar.add_cascade(label="流程", menu=flow_menu)

        run_menu = tk.Menu(menubar, tearoff=0)
        run_menu.add_command(label="▶ 运行流程", command=self._run_flow, accelerator="F5")
        run_menu.add_command(label="■ 停止运行", command=self._stop_flow, accelerator="Escape")
        menubar.add_cascade(label="运行", menu=run_menu)

        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="关于", command=lambda: messagebox.showinfo(
            "关于", "OCR 图像识别操作工具 v1.0\n\n基于 OpenCV 模板匹配 + PyAutoGUI 键鼠操作\n参考 MAA 设计思路"))
        menubar.add_cascade(label="帮助", menu=help_menu)

        self.root.bind_all("<Control-n>", lambda e: self._new_flow())
        self.root.bind_all("<Control-o>", lambda e: self._open_flow())
        self.root.bind_all("<Control-s>", lambda e: self._save_flow())
        self.root.bind_all("<F5>", lambda e: self._run_flow())
        self.root.bind_all("<Escape>", lambda e: self._stop_flow())

    def _build_ui(self):
        # ── 工具栏 ──
        toolbar = ttk.Frame(self.root, padding=5)
        toolbar.pack(fill=tk.X)

        ttk.Button(toolbar, text="新建", command=self._new_flow, width=6).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="打开", command=self._open_flow, width=6).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="保存", command=self._save_flow, width=6).pack(side=tk.LEFT, padx=2)
        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=8)

        self.run_btn = ttk.Button(toolbar, text="▶ 运行", command=self._run_flow, width=8)
        self.run_btn.pack(side=tk.LEFT, padx=2)
        self.stop_btn = ttk.Button(toolbar, text="■ 停止", command=self._stop_flow, width=8, state=tk.DISABLED)
        self.stop_btn.pack(side=tk.LEFT, padx=2)
        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=8)

        ttk.Button(toolbar, text="添加步骤", command=self._add_step).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="编辑步骤", command=self._edit_step).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="删除步骤", command=self._delete_step).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="截取模板", command=self._capture_template_standalone).pack(side=tk.LEFT, padx=2)

        # ── 主内容区 ──
        paned = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # 左侧：步骤列表
        left_frame = ttk.Frame(paned)
        paned.add(left_frame, weight=1)

        ttk.Label(left_frame, text="流程步骤列表", font=("", 10, "bold")).pack(anchor=tk.W, pady=(0, 5))

        list_frame = ttk.Frame(left_frame)
        list_frame.pack(fill=tk.BOTH, expand=True)

        cols = ("名称", "模板", "阈值")
        self.step_tree = ttk.Treeview(list_frame, columns=cols, show="headings",
                                      selectmode="browse")
        self.step_tree.heading("名称", text="名称")
        self.step_tree.heading("模板", text="模板图片")
        self.step_tree.heading("阈值", text="阈值")
        self.step_tree.column("名称", width=100)
        self.step_tree.column("模板", width=150)
        self.step_tree.column("阈值", width=50)
        self.step_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        list_scroll = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.step_tree.yview)
        list_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.step_tree.configure(yscrollcommand=list_scroll.set)
        self.step_tree.bind("<Double-1>", lambda e: self._edit_step())
        self.step_tree.bind("<Delete>", lambda e: self._delete_step())

        # 入口步骤选择
        entry_frame = ttk.Frame(left_frame)
        entry_frame.pack(fill=tk.X, pady=(5, 0))
        ttk.Label(entry_frame, text="入口步骤:").pack(side=tk.LEFT)
        self.entry_var = tk.StringVar()
        self.entry_cb = ttk.Combobox(entry_frame, textvariable=self.entry_var, state="readonly", width=25)
        self.entry_cb.pack(side=tk.LEFT, padx=5)

        # 右侧：步骤预览
        right_frame = ttk.Frame(paned)
        paned.add(right_frame, weight=2)

        ttk.Label(right_frame, text="步骤详情 (选择左侧步骤查看)", font=("", 10, "bold")).pack(anchor=tk.W, pady=(0, 5))

        self.detail_text = tk.Text(right_frame, wrap=tk.WORD, state=tk.DISABLED,
                                   font=("Consolas", 10), bg="#f5f5f5")
        detail_scroll = ttk.Scrollbar(right_frame, orient=tk.VERTICAL, command=self.detail_text.yview)
        self.detail_text.configure(yscrollcommand=detail_scroll.set)
        self.detail_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        detail_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        self.step_tree.bind("<<TreeviewSelect>>", self._on_step_select)

        # ── 日志区 ──
        log_frame = ttk.LabelFrame(self.root, text="运行日志", padding=5)
        log_frame.pack(fill=tk.BOTH, padx=5, pady=(0, 5))
        log_frame.pack_propagate(False)
        log_frame.configure(height=150)

        self.log_text = tk.Text(log_frame, wrap=tk.WORD, state=tk.DISABLED,
                                font=("Consolas", 9), bg="#1e1e1e", fg="#d4d4d4",
                                insertbackground="white")
        log_scroll = ttk.Scrollbar(log_frame, orient=tk.VERTICAL, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=log_scroll.set)
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        log_scroll.pack(side=tk.RIGHT, fill=tk.Y)

    # ── 流程管理 ──

    def _new_flow(self):
        self.steps.clear()
        self.engine.steps.clear()
        self.engine.entry_step_id = ""
        self.current_file = None
        self._refresh_step_list()
        self._update_detail()
        self._log("新建流程")

    def _open_flow(self):
        path = filedialog.askopenfilename(
            title="打开流程文件",
            filetypes=[("JSON 流程文件", "*.json"), ("所有文件", "*.*")],
            initialdir=FLOWS_DIR
        )
        if not path:
            return
        try:
            self.engine.load_flow(path)
            self.steps = self.engine.steps
            self.current_file = path
            self._refresh_step_list()
            self._update_detail()
            self.entry_var.set(self.engine.entry_step_id)
        except Exception as e:
            self._log(f"[ERROR] 加载失败: {e}")
            messagebox.showerror("错误", f"加载流程失败:\n{e}")

    def _save_flow(self):
        if self.current_file:
            self._sync_steps_to_engine()
            self.engine.save_flow(self.current_file)
        else:
            self._save_flow_as()

    def _save_flow_as(self):
        path = filedialog.asksaveasfilename(
            title="保存流程文件",
            defaultextension=".json",
            filetypes=[("JSON 流程文件", "*.json")],
            initialdir=FLOWS_DIR
        )
        if not path:
            return
        self._sync_steps_to_engine()
        self.current_file = path
        self.engine.save_flow(path)

    def _sync_steps_to_engine(self):
        self.engine.steps = self.steps
        self.engine.entry_step_id = self.entry_var.get()

    # ── 步骤操作 ──

    def _add_step(self):
        step_id = f"step_{len(self.steps) + 1}"
        step = Step(id=step_id, name=f"步骤{len(self.steps) + 1}")
        step_ids = list(self.steps.keys())
        dialog = StepDialog(self.root, step, step_ids)
        if dialog.result:
            self.steps[step.id] = step
            self._refresh_step_list()
            self._select_step(step.id)
            self._sync_steps_to_engine()

    def _edit_step(self):
        sid = self._selected_step_id()
        if not sid:
            return
        step = self.steps[sid]
        step_ids = [k for k in self.steps.keys() if k != sid]
        dialog = StepDialog(self.root, step, step_ids)
        if dialog.result:
            self._refresh_step_list()
            self._select_step(step.id)
            self._sync_steps_to_engine()

    def _delete_step(self):
        sid = self._selected_step_id()
        if not sid:
            return
        if messagebox.askyesno("确认", f"删除步骤 [{self.steps[sid].name}] ?"):
            del self.steps[sid]
            self._refresh_step_list()
            self._update_detail()
            self._sync_steps_to_engine()

    def _selected_step_id(self) -> Optional[str]:
        sel = self.step_tree.selection()
        if not sel:
            return None
        return self.step_tree.item(sel[0], "tags")[0] if self.step_tree.item(sel[0], "tags") else None

    def _select_step(self, step_id: str):
        for item in self.step_tree.get_children():
            tags = self.step_tree.item(item, "tags")
            if tags and tags[0] == step_id:
                self.step_tree.selection_set(item)
                self.step_tree.focus(item)
                self._on_step_select()
                break

    def _refresh_step_list(self):
        self.step_tree.delete(*self.step_tree.get_children())
        for sid, step in self.steps.items():
            tmpl_name = os.path.basename(step.template) if step.template else "(未设置)"
            self.step_tree.insert("", tk.END, values=(step.name, tmpl_name, f"{step.threshold:.0%}"),
                                  tags=(sid,))
        self.entry_cb["values"] = [""] + list(self.steps.keys())
        self.entry_var.set(self.engine.entry_step_id)

    def _on_step_select(self, event=None):
        sid = self._selected_step_id()
        if not sid or sid not in self.steps:
            self._update_detail()
            return
        step = self.steps[sid]
        self._update_detail(step)

    def _update_detail(self, step: Optional[Step] = None):
        self.detail_text.configure(state=tk.NORMAL)
        self.detail_text.delete(1.0, tk.END)

        if not step:
            self.detail_text.insert(tk.END, "请添加或选择一个步骤查看详情")
            self.detail_text.configure(state=tk.DISABLED)
            return

        def fmt_branch(b: Branch, title: str) -> str:
            lines = [f"  {title}:"]
            if b.actions:
                for a in b.actions:
                    desc = a.keys or a.text or f"({a.x},{a.y})"
                    lines.append(f"    - {a.type}: {desc}")
            else:
                lines.append("    (无操作)")
            if b.goto:
                goto_name = self.steps[b.goto].name if b.goto in self.steps else b.goto
                lines.append(f"    → 跳转到: {goto_name}")
            else:
                lines.append(f"    → 流程结束")
            return "\n".join(lines)

        if step.match_mode == "color":
            match_info = f"""匹配模式: 颜色匹配
目标颜色: {step.target_color}
颜色容差: ±{step.color_tolerance}"""
        else:
            match_info = f"""匹配模式: 模板匹配
模板图片: {step.template or '(未设置)'}
匹配阈值: {step.threshold:.0%}"""

        info = f"""步骤: {step.name} (ID: {step.id})
──────────────────────────────
{match_info}
超时时间: {step.timeout}s
重试间隔: {step.interval}s
搜索区域: {step.region if step.region else '全屏'}
──────────────────────────────
{fmt_branch(step.on_match, '✓ 匹配成功时')}
──────────────────────────────
{fmt_branch(step.on_no_match, '✗ 匹配失败时')}
"""
        self.detail_text.insert(tk.END, info)
        self.detail_text.configure(state=tk.DISABLED)

    # ── 模板截取 ──

    def _capture_template_standalone(self):
        """独立截取模板（不关联步骤）"""
        self.root.withdraw()
        time.sleep(0.4)

        screen_img = ImageGrab.grab(all_screens=True)
        darkened = screen_img.copy()
        darken = Image.new("RGB", darkened.size, (0, 0, 0))
        darkened = Image.blend(darkened, darken, 0.5)

        cancelled = [False]

        overlay = tk.Toplevel()
        overlay.attributes("-fullscreen", True)
        overlay.attributes("-topmost", True)
        overlay.overrideredirect(True)

        tk_img = ImageTk.PhotoImage(darkened)
        canvas = tk.Canvas(overlay, cursor="cross", highlightthickness=0,
                           width=darkened.width, height=darkened.height)
        canvas.pack(fill=tk.BOTH, expand=True)
        canvas.create_image(0, 0, anchor=tk.NW, image=tk_img, tag="bg")

        rect = [0, 0, 0, 0]
        dragging = [False]

        def on_down(e):
            dragging[0] = True
            rect[0], rect[1] = e.x, e.y
            rect[2], rect[3] = e.x, e.y

        def on_move(e):
            if not dragging[0]:
                return
            rect[2], rect[3] = e.x, e.y
            canvas.delete("sel")
            x1, y1 = min(rect[0], rect[2]), min(rect[1], rect[3])
            x2, y2 = max(rect[0], rect[2]), max(rect[1], rect[3])
            canvas.create_rectangle(x1, y1, x2, y2, outline="#00ff00", width=3, tag="sel")

        def on_up(e):
            dragging[0] = False
            overlay.destroy()

        def on_cancel(e):
            cancelled[0] = True
            overlay.destroy()

        canvas.bind("<ButtonPress-1>", on_down)
        canvas.bind("<B1-Motion>", on_move)
        canvas.bind("<ButtonRelease-1>", on_up)
        canvas.bind("<Button-3>", on_cancel)
        canvas.bind("<Escape>", on_cancel)

        overlay.focus_force()
        overlay.grab_set()
        overlay.wait_window()

        x1, y1 = min(rect[0], rect[2]), min(rect[1], rect[3])
        x2, y2 = max(rect[0], rect[2]), max(rect[1], rect[3])

        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

        if cancelled[0] or x2 - x1 < 5 or y2 - y1 < 5:
            self._log("截取取消: 区域太小")
            return

        img = screen_img.crop((x1, y1, x2, y2))
        ts = int(time.time())
        save_path = TEMPLATES_DIR / f"capture_{ts}.png"
        img.save(str(save_path))
        self._log(f"模板已保存: {save_path}")

    # ── 运行控制 ──

    def _run_flow(self):
        if not self.steps:
            self._log("[ERROR] 流程为空，请先添加步骤")
            return

        self._sync_steps_to_engine()

        # 验证模板文件存在
        for step in self.steps.values():
            if step.template and not os.path.isfile(step.template):
                self._log(f"[ERROR] 步骤 [{step.name}] 模板文件不存在: {step.template}")
                return

        self.run_btn.configure(state=tk.DISABLED)
        self.stop_btn.configure(state=tk.NORMAL)

        self.run_thread = threading.Thread(target=self._run_wrapper, daemon=True)
        self.run_thread.start()

    def _run_wrapper(self):
        try:
            self.engine.run()
        except Exception as e:
            self._log(f"[ERROR] 运行异常: {e}")
        finally:
            self.root.after(0, self._on_run_finish)

    def _on_run_finish(self):
        self.run_btn.configure(state=tk.NORMAL)
        self.stop_btn.configure(state=tk.DISABLED)
        self.run_thread = None

    def _stop_flow(self):
        self.engine.stop()
        self._log("正在停止...")

    # ── 工具方法 ──

    def _log(self, msg: str):
        """线程安全的日志输出"""
        def _write():
            self.log_text.configure(state=tk.NORMAL)
            ts = time.strftime("%H:%M:%S")
            self.log_text.insert(tk.END, f"[{ts}] {msg}\n")
            self.log_text.see(tk.END)
            self.log_text.configure(state=tk.DISABLED)
        self.root.after(0, _write)

    def _on_close(self):
        if self.engine.running:
            self.engine.stop()
        self.root.destroy()

    def run(self):
        self.root.mainloop()


# ─── Entry Point ──────────────────────────────────────────────────

def main():
    pyautogui.FAILSAFE = True
    app = OCRToolApp()
    app.run()


if __name__ == "__main__":
    main()
