import os
import sys
import subprocess
import shutil
from pathlib import Path

# Playwright Python 包版本
PLAYWRIGHT_VERSION = "1.48.0"

# 对应的 Chromium revision（Playwright 1.48.0 -> Chromium 130.0.6723.19 -> revision 1140）
CHROMIUM_REVISION = "1140"

# 淘宝镜像源
PIP_MIRROR = "https://mirrors.aliyun.com/pypi/simple/"
PLAYWRIGHT_DOWNLOAD_HOST = "https://npmmirror.com/mirrors/playwright"

# 本脚本所在目录
BASE_DIR = Path(__file__).resolve().parent

TOOLS_DIR = BASE_DIR / "Tools"

BROWSERS_PATH = TOOLS_DIR / "ms-playwright"

# ==================== 工具函数 ====================

def run_cmd(cmd, env=None, cwd=None, check=True):
    """执行命令并打印输出"""
    print(f"\n>>> {' '.join(cmd)}")
    result = subprocess.run(
        cmd,
        env=env,
        cwd=cwd,
        check=False,
        capture_output=False,
    )
    if check and result.returncode != 0:
        print(f"[ERROR] 命令执行失败，退出码: {result.returncode}")
        sys.exit(result.returncode)
    return result


def install_playwright_pip():
    """使用淘宝源安装 playwright==1.48.0"""
    print("\n" + "=" * 60)
    print(f"【步骤 1】使用淘宝源安装 playwright=={PLAYWRIGHT_VERSION}")
    print("=" * 60)

    cmd = [
        sys.executable, "-m", "pip", "install",
        f"playwright=={PLAYWRIGHT_VERSION}",
        "-i", PIP_MIRROR,
        "--trusted-host", "mirrors.aliyun.com",
    ]
    run_cmd(cmd)


def download_chromium():
    """使用淘宝镜像下载 Chromium (revision 1140)"""
    print("\n" + "=" * 60)
    print(f"【步骤 2】下载 Chromium (revision {CHROMIUM_REVISION})")
    print(f"         下载源: {PLAYWRIGHT_DOWNLOAD_HOST}")
    print(f"         存放目录: {BROWSERS_PATH}")
    print("=" * 60)

    # 设置环境变量，让 Playwright CLI 走淘宝镜像
    env = os.environ.copy()
    env["PLAYWRIGHT_DOWNLOAD_HOST"] = PLAYWRIGHT_DOWNLOAD_HOST
    env["PLAYWRIGHT_BROWSERS_PATH"] = str(BROWSERS_PATH)

    # 使用 playwright CLI 安装 chromium
    cmd = [sys.executable, "-m", "playwright", "install", "chromium"]
    run_cmd(cmd, env=env)


def verify_installation():
    """验证安装是否成功"""
    print("\n" + "=" * 60)
    print("【步骤 3】验证安装")
    print("=" * 60)

    # 检查 playwright 版本
    result = subprocess.run(
        [sys.executable, "-m", "playwright", "--version"],
        capture_output=True, text=True,
    )
    print(f"Playwright 版本: {result.stdout.strip()}")

    # 检查 Chromium 是否下载成功
    chromium_dir = BROWSERS_PATH / f"chromium-{CHROMIUM_REVISION}"
    if chromium_dir.exists():
        total_size = sum(f.stat().st_size for f in chromium_dir.rglob("*") if f.is_file())
        print(f"Chromium 目录: {chromium_dir}")
        print(f"Chromium 大小: {total_size / (1024*1024):.1f} MB ✅")
    else:
        print(f"[WARNING] 未找到 {chromium_dir}，尝试查找...")
        if BROWSERS_PATH.exists():
            for item in BROWSERS_PATH.iterdir():
                print(f"  发现: {item}")


def main():
    print("""
╔══════════════════════════════════════════════════════════╗
║     Playwright 1.48.0 + Chromium 1140 自动安装脚本       ║
║     使用淘宝镜像源 | 下载到 Tools/ 同级目录               ║
╚══════════════════════════════════════════════════════════╝
    """)

    # 创建浏览器存放目录
    BROWSERS_PATH.mkdir(parents=True, exist_ok=True)

    # 步骤 1：安装 Playwright
    install_playwright_pip()

    # 步骤 2：下载 Chromium
    download_chromium()

    # 步骤 3：验证
    verify_installation()

    print("\n" + "=" * 60)
    print("✅ 安装完成！")
    print(f"   Playwright 版本: {PLAYWRIGHT_VERSION}")
    print(f"   Chromium revision: {CHROMIUM_REVISION}")
    print(f"   浏览器路径: {BROWSERS_PATH}")
    print("=" * 60)
    print("""
后续使用提示：
  在你的 Python 代码中，设置环境变量后即可使用：

  import os
  os.environ['PLAYWRIGHT_BROWSERS_PATH'] = r'Tools/ms-playwright'

  from playwright.sync_api import sync_playwright
  with sync_playwright() as p:
      browser = p.chromium.launch(headless=True)
      page = browser.new_page()
      page.goto('https://example.com')
      print(page.title())
      browser.close()
    """)


if __name__ == "__main__":
    main()
