@echo off
chcp 65001 >nul
title Scenario 5 - 一键部署

echo ============================================================
echo   场景 5 双轨浏览器自动化 Agent - 一键部署
echo ============================================================
cd /d "%~dp0"

:: ---------- 1. 检测 Python ----------
where python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] 未检测到 Python，请先安装 Python 3.10+ 并勾选 "Add to PATH"
    echo 下载地址: https://www.python.org/downloads/
    pause & exit /b 1
)
for /f "tokens=2" %%i in ('python --version 2^>^&1') do set PYVER=%%i
echo [1/5] 检测到 Python %PYVER%

:: ---------- 2. 创建虚拟环境并安装依赖 ----------
where uv >nul 2>nul
if not errorlevel 1 (
    echo [2/5] 使用 uv 创建虚拟环境并安装依赖...
    if not exist ".venv\Scripts\python.exe" uv venv .venv
    uv pip install --python .venv -r pyproject.toml
) else (
    echo [2/5] 未检测到 uv，使用 python -m venv + pip...
    if not exist ".venv\Scripts\python.exe" python -m venv .venv
    .venv\Scripts\python.exe -m pip install --upgrade pip -q
    .venv\Scripts\python.exe -m pip install -r pyproject.toml -q
)

:: ---------- 3. GPU 加速（可选）----------
choice /c YN /m "[3/5] 是否安装 GPU (CUDA 12.8) 版 PyTorch 加速推理? 检测到 NVIDIA 显卡建议选 Y"
if errorlevel 2 goto skip_gpu
where uv >nul 2>nul
if not errorlevel 1 (
    uv pip install --python .venv torch --index-url https://download.pytorch.org/whl/cu128 --reinstall-package torch
) else (
    .venv\Scripts\python.exe -m pip install torch --index-url https://download.pytorch.org/whl/cu128 --force-reinstall --no-deps -q
)
:skip_gpu

:: ---------- 4. 生成本地配置 ----------
echo [4/5] 生成本地配置...
if not exist ".env" copy .env.example .env >nul

:: ---------- 5. 下载模型权重（约 650MB，已存在则跳过）----------
echo [5/5] 检查模型权重...
.venv\Scripts\python.exe tools\download_model.py
if errorlevel 1 (
    echo [WARN] 模型下载失败，Agent 仍可以内置规则模式运行（双击 run.bat 即用）
)

:: ---------- 冒烟自检 ----------
echo.
echo 正在执行冒烟自检...
.venv\Scripts\python.exe test_smoke.py
if errorlevel 1 (
    echo [WARN] 自检存在问题，可运行 test_smoke.py 查看详情；不影响交互模式试用
)

echo.
echo ============================================================
echo   部署完成！双击 start.bat 启动（菜单选择 GPU 模型服务 / API / Agent）
echo   或双击 run.bat 仅以内置规则模式启动
echo ============================================================
pause
