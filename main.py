# main.py — 惡意併購 桌面啟動器（pywebview）

import sys
import urllib.parse

RAILWAY_URL = "https://web-production-a58c5.up.railway.app"

# ── pywebview API（JS ↔ Python）─────────────────────────────────────────────
class Api:
    def __init__(self):
        self._window = None

    def open_game(self):
        """主辦 / 加入遊戲：直接前往 Railway 落地頁"""
        if self._window:
            self._window.resize(1280, 800)
            self._window.load_url(RAILWAY_URL)

    def solo_game(self):
        """單人練習：帶 solo 參數直接進入單人局"""
        if self._window:
            self._window.resize(1280, 800)
            url = f"{RAILWAY_URL}?solo=1&name={urllib.parse.quote('玩家')}"
            self._window.load_url(url)


# ── 啟動器 HTML ───────────────────────────────────────────────────────────────
LAUNCHER_HTML = """
<!DOCTYPE html>
<html lang="zh-TW">
<head>
<meta charset="UTF-8">
<title>惡意併購</title>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  background: #0d1117; color: #e6edf3;
  font-family: 'Segoe UI', sans-serif;
  height: 100vh; display: flex; flex-direction: column;
  align-items: center; justify-content: center; gap: 0;
  -webkit-app-region: drag;
  user-select: none;
}
h1 { color: #f0c040; font-size: 2.8rem; font-weight: 800; letter-spacing: 3px; margin-bottom: 4px; }
.sub { color: #8b949e; font-size: 1rem; margin-bottom: 40px; letter-spacing: 2px; }
.btn-group { display: flex; flex-direction: column; gap: 12px; width: 280px; }
button {
  -webkit-app-region: no-drag;
  height: 52px; border-radius: 10px; border: 1px solid #30363d;
  background: #21262d; color: #e6edf3; font-size: 1rem; font-weight: 600;
  cursor: pointer; transition: background .15s;
}
button:hover { background: #30363d; }
button.primary { background: #238636; border-color: #238636; }
button.primary:hover { background: #2ea043; }
button.solo { background: #3d1f6b; border-color: #7c3aed; color: #c4b5fd; }
button.solo:hover { background: #4c2a82; }
#status { margin-top: 20px; color: #8b949e; font-size: .8rem; min-height: 22px; text-align: center; }
</style>
</head>
<body>
<h1>惡意併購</h1>
<p class="sub">Hostile Takeover</p>

<div class="btn-group">
  <button class="primary" onclick="openGame()">🏠 主辦遊戲</button>
  <button onclick="openGame()">🌐 加入遊戲</button>
  <button class="solo" onclick="soloGame()">🤖 單人練習</button>
</div>

<p id="status">需要網際網路連線</p>

<script>
async function openGame() {
  document.getElementById('status').textContent = '連線中…';
  await window.pywebview.api.open_game();
}

async function soloGame() {
  document.getElementById('status').textContent = '連線中…';
  await window.pywebview.api.solo_game();
}
</script>
</body>
</html>
"""


# ── 主程式 ────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    try:
        import webview
    except ImportError:
        print("請先安裝 pywebview：  pip install pywebview")
        sys.exit(1)

    api = Api()
    window = webview.create_window(
        "惡意併購 · Hostile Takeover",
        html=LAUNCHER_HTML,
        js_api=api,
        width=520,
        height=640,
        resizable=True,
        frameless=False,
    )
    api._window = window
    webview.start(debug=False)
