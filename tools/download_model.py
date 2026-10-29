"""
下载 Laya 浏览器微调模型权重至 models/laya-browser/
优先使用 hf-mirror.com 镜像（国内可达），失败时回退 huggingface.co 官方站。
模型已存在时自动跳过。
"""
import os
import sys
import time
from pathlib import Path

REPO_ID = "cklxx/laya-browser"
TARGET_DIR = Path(__file__).resolve().parent / "models" / "laya-browser"
# 权重与配置为必需文件，测试日志与演示媒体不下载
IGNORE_PATTERNS = ["results/*", "assets/*", "code/finetune/*", "code/kernels/*"]


def already_downloaded() -> bool:
    """核心文件齐全即视为已下载"""
    required = [
        TARGET_DIR / "model.safetensors",
        TARGET_DIR / "config.json",
        TARGET_DIR / "laya_browser.py",
        TARGET_DIR / "tokenizer" / "tokenizer.json",
    ]
    return all(f.exists() and f.stat().st_size > 0 for f in required)


def download(endpoint: str) -> str:
    os.environ["HF_ENDPOINT"] = endpoint
    # 延迟导入，保证 --check 模式无需安装依赖也能运行
    from huggingface_hub import snapshot_download
    return snapshot_download(
        repo_id=REPO_ID,
        local_dir=str(TARGET_DIR),
        ignore_patterns=IGNORE_PATTERNS,
        max_workers=4,
    )


def main():
    if "--check" in sys.argv:
        print("已下载" if already_downloaded() else "未下载")
        return 0

    if already_downloaded():
        print(f"✔ 模型已存在，跳过下载: {TARGET_DIR}")
        return 0

    print("=" * 60)
    print(f" 正在下载模型仓库: {REPO_ID}")
    print(f" 目标路径: {TARGET_DIR}  (约 650MB)")
    print("=" * 60)

    endpoints = ["https://hf-mirror.com", "https://huggingface.co"]
    last_err = None
    for ep in endpoints:
        try:
            print(f"-> 尝试端点: {ep}")
            start = time.time()
            download(ep)
            print(f"✔ 下载完成，用时 {time.time() - start:.0f} 秒")
            print(f"模型位置: {TARGET_DIR}")
            return 0
        except Exception as e:
            last_err = e
            print(f"✘ 端点 {ep} 失败: {e}")

    print(f"\n✘ 全部端点下载失败: {last_err}")
    print("提示: 可手动访问 https://hf-mirror.com/cklxx/laya-browser 下载文件至上述目录")
    return 1


if __name__ == "__main__":
    sys.exit(main())
