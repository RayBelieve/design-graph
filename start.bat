@echo off
setlocal EnableExtensions
title Design Graph
rem ============================================================
rem  Design Graph 一键启动
rem  - 双击运行，或在终端执行：start.bat
rem  - serve.py 的参数会原样透传，例如：
rem      start.bat --draft D:\path\to\draft
rem      start.bat --port 4000
rem  - 端口已被占用时不重复起服务，只打开浏览器
rem  - 想换默认端口：set PORT=4000 之后再运行本脚本
rem  - 设 DG_NO_BROWSER=1 可只起服务不开浏览器
rem  - 重要：netstat/find/findstr/ping 一律用 System32 下的绝对路径，
rem    这样即使机器 PATH 里缺少 System32 也能正常启动（否则会闪退）
rem ============================================================

set "HERE=%~dp0"
cd /d "%HERE%"

rem ── 系统自带工具走绝对路径，不依赖 PATH ──
set "SYS=%SystemRoot%\System32"
if not exist "%SYS%\netstat.exe" set "SYS=C:\Windows\System32"

rem ── 是否双击启动：是的话，任何退出路径都先暂停，避免闪退看不到原因 ──
set "DBLCLK=0"
if exist "%SYS%\find.exe" echo %cmdcmdline% | "%SYS%\find.exe" /i "%~f0" >nul 2>nul && set "DBLCLK=1"
if "%DBLCLK%"=="0" if defined DG_ALWAYS_PAUSE set "DBLCLK=1"

rem ── 默认端口；已设置 PORT 环境变量则尊重它 ──
if not defined PORT set "PORT=3333"
rem ── 从参数里认出 --port N（不影响原样透传给 serve.py）──
:parse
if "%~1"=="" goto :parsed
if /i "%~1"=="--port" if not "%~2"=="" set "PORT=%~2"
shift
goto :parse
:parsed
set "URL=http://127.0.0.1:%PORT%/"

rem ── 找 Python（先试 python，再试 py 启动器，最后试常见安装位置）──
set "PY="
python --version >nul 2>nul && set "PY=python"
if not defined PY ( py -3 --version >nul 2>nul && set "PY=py -3" )
if not defined PY ( python3 --version >nul 2>nul && set "PY=python3" )
if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Python313\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
if not defined PY if exist "C:\Python313\python.exe" set "PY=C:\Python313\python.exe"
if not defined PY (
  echo [x] 没找到可用的 Python 3，请先安装并勾选 "Add python.exe to PATH"。
  goto :fail
)

if not exist "%HERE%serve.py" (
  echo [x] 找不到 serve.py，请确认 start.bat 和 serve.py 在同一个文件夹。
  goto :fail
)

rem ── 端口已被占用？只开浏览器，不重复起服务 ──
set "INUSE=0"
if exist "%SYS%\netstat.exe" (
  "%SYS%\netstat.exe" -ano 2>nul | "%SYS%\findstr.exe" /c:":%PORT% " 2>nul | "%SYS%\findstr.exe" /i "LISTENING" >nul 2>nul && set "INUSE=1"
)
if "%INUSE%"=="1" (
  echo [=] 端口 %PORT% 已有 Design Graph 在跑，直接打开页面。
  if not defined DG_NO_BROWSER start "" "%URL%"
  if "%DBLCLK%"=="1" pause
  exit /b 0
)

echo [i] Design Graph: %URL%    按 Ctrl+C 停止
rem 后台等约 2 秒再开浏览器，给 serve.py 一点启动时间
if not defined DG_NO_BROWSER if exist "%SYS%\ping.exe" start "" /min cmd /c ""%SYS%\ping.exe" -n 3 127.0.0.1 >nul & start "" "%URL%""
if not defined DG_NO_BROWSER if not exist "%SYS%\ping.exe" start "" "%URL%"

%PY% "%HERE%serve.py" %*
set "RC=%errorlevel%"
echo.
if not "%RC%"=="0" goto :fail_run
echo [i] 服务已停止。
if "%DBLCLK%"=="1" pause
exit /b 0

:fail_run
echo [x] 服务异常退出，退出码 %RC%。
:fail
echo.
if "%DBLCLK%"=="1" pause
exit /b 1
