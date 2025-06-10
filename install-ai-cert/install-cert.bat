@echo off
set CERT_FILE=selfsigned.crt

echo 🛡 安裝自簽憑證到 [受信任的根憑證授權單位] 中...
certutil -addstore "Root" "%CERT_FILE%"
if %ERRORLEVEL% EQU 0 (
    echo ✅ 安裝成功！
) else (
    echo ❌ 憑證安裝失敗，請確認你有系統管理員權限。
)
pause