@echo off
REM 火巡智策 · 生产模式演示启动（答辩/录屏推荐）
REM 与 dev 模式区别：页面切换零编译等待、首屏即最终性能。
REM 前提：后端与 YOLO 检测服务已在运行（见 docs/答辩速查卡.md）。

cd /d "%~dp0..\frontend"
echo [1/2] 构建生产产物...
call npm run build
if errorlevel 1 (
    echo build 失败，演示中止。
    exit /b 1
)
echo [2/2] 启动生产服务 http://localhost:4173/
start "火巡智策-生产模式(4173)" cmd /k npx vite preview --port 4173
timeout /t 2 >nul
start http://localhost:4173/
echo.
echo 已打开 http://localhost:4173/ —— 生产模式，切页零等待。
echo 如页面无数据：检查后端 8000 是否带 FIRE_YOLO_ENDPOINT 启动（docs/YOLO队员交付说明.md）。
