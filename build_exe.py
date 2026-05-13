"""
一键打包脚本 - 将 OCR 工具打包成单个 exe 文件
运行方式: python build_exe.py
"""
import shutil
import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).parent


def build():
    main_file = BASE_DIR / "main.py"
    output_dir = BASE_DIR / "dist"
    icon_file = BASE_DIR / "icon.ico"

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--windowed",
        "--name", "OCR识别操作工具",
        "--clean",
        "--noconfirm",
    ]

    if icon_file.exists():
        cmd.extend(["--icon", str(icon_file)])

    cmd.append(str(main_file))

    print("=" * 50)
    print("开始打包 OCR 识别操作工具...")
    print("=" * 50)

    result = subprocess.run(cmd, cwd=str(BASE_DIR))
    if result.returncode != 0:
        print(f"\n打包失败, 返回码: {result.returncode}")
        sys.exit(1)

    exe_path = output_dir / "OCR识别操作工具.exe"
    if not exe_path.exists():
        print(f"\n未找到输出文件，请检查 {output_dir} 目录")
        sys.exit(1)

    # 创建发布目录，包含 exe 和空的 templates/flows 目录
    release_dir = BASE_DIR / "release"
    release_dir.mkdir(exist_ok=True)
    shutil.copy2(exe_path, release_dir / "OCR识别操作工具.exe")
    (release_dir / "templates").mkdir(exist_ok=True)
    (release_dir / "flows").mkdir(exist_ok=True)

    print(f"\n打包成功!")
    print(f"  单文件 exe: {exe_path}")
    print(f"  发布目录 (含 exe + 数据目录): {release_dir}")
    print(f"  将整个 release 文件夹打包发给用户即可")


if __name__ == "__main__":
    build()
