@echo off
echo ====================================
echo  惡意併購 - 打包成 .exe
echo ====================================

:: 安裝 PyInstaller（若未安裝）
pip install pyinstaller -q

:: 清除舊的打包結果
if exist dist rmdir /s /q dist
if exist build rmdir /s /q build
if exist "惡意併購.spec" del "惡意併購.spec"

:: 打包
pyinstaller ^
  --onedir ^
  --windowed ^
  --name "惡意併購" ^
  --add-data "templates;templates" ^
  --hidden-import flask ^
  --hidden-import flask_socketio ^
  --hidden-import engineio ^
  --hidden-import engineio.async_drivers.threading ^
  --hidden-import socketio ^
  --hidden-import socketio.async_server ^
  --hidden-import webview ^
  --hidden-import webview.platforms.winforms ^
  --hidden-import clr ^
  --collect-all webview ^
  main.py

echo.
echo ====================================
if exist "dist\惡意併購\惡意併購.exe" (
    echo  打包完成！
    echo  執行檔位置：dist\惡意併購\惡意併購.exe
    echo  把整個 dist\惡意併購 資料夾壓縮成 zip 分享給朋友
) else (
    echo  打包失敗，請查看上面的錯誤訊息
)
echo ====================================
pause
