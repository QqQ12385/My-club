@echo off
chcp 65001 >nul
cd /d %~dp0
echo ================================
echo  统一消息管理后端 - 启动中...
echo  API:  http://localhost:8080/api
echo  WS :  ws://localhost:8080/ws
echo ================================
if not exist .venv (
  echo 首次运行：创建虚拟环境并安装依赖...
  python -m venv .venv
  .venv\Scripts\python.exe -m pip install -r requirements.txt
)
.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8080
pause
