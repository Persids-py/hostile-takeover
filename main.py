# main.py — 惡意併購 桌面啟動器（pywebview）

import threading, time, socket, sys

# ── 取得區域網 IP ──────────────────────────────────────────────────────────
def get_lan_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

# ── Flask 伺服器（背景執行緒）────────────────────────────────────────────────
_server_started = False
_server_lock = threading.Lock()

def start_server():
    global _server_started
    with _server_lock:
        if _server_started:
            return
        _server_started = True
    from app import socketio, app
    socketio.run(app, host="0.0.0.0", port=5000, log_output=False, use_reloader=False)


# ── pywebview API（JS ↔ Python）─────────────────────────────────────────────
class Api:
    def __init__(self):
        self._window = None   # 由外部在 webview.start 前設定

    def host_game(self):
        """主辦遊戲：啟動伺服器，返回 LAN IP"""
        threading.Thread(target=start_server, daemon=True).start()
        time.sleep(1.2)
        lan_ip = get_lan_ip()
        if self._window:
            self._window.resize(1280, 800)
            self._window.load_url("http://localhost:5000")
        return lan_ip

    def join_game(self, host_ip):
        """加入他人遊戲：輸入對方 LAN IP"""
        host_ip = host_ip.strip()
        url = f"http://{host_ip}:5000"
        if self._window:
            self._window.resize(1280, 800)
            self._window.load_url(url)
        return url

    def solo_game(self, name):
        """單人練習：啟動伺服器，帶名字參數直接進入單人局"""
        name = (name or "玩家").strip()[:16]
        threading.Thread(target=start_server, daemon=True).start()
        time.sleep(1.2)
        if self._window:
            self._window.resize(1280, 800)
            import urllib.parse
            self._window.load_url(f"http://localhost:5000?solo=1&name={urllib.parse.quote(name)}")
        return name

    def get_lan_ip(self):
        return get_lan_ip()


# ── 啟動器 HTML（嵌入在程式碼中，不需外部檔案）────────────────────────────
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
#join-row {
  display: none; flex-direction: column; gap: 8px; width: 280px;
  margin-top: 8px;
}
#join-row input {
  -webkit-app-region: no-drag;
  padding: 12px; background: #161b22; border: 1px solid #30363d;
  border-radius: 8px; color: #e6edf3; font-size: 1rem; outline: none;
}
#join-row input:focus { border-color: #388bfd; }
#status { margin-top: 20px; color: #f0c040; font-size: .9rem; min-height: 22px; text-align: center; }
#err { color: #ff7b72; font-size: .85rem; min-height: 18px; margin-top: 6px; }
</style>
</head>
<body>
<h1>惡意併購</h1>
<p class="sub">Hostile Takeover</p>

<div class="btn-group">
  <button class="primary" onclick="hostGame()">🏠 主辦遊戲</button>
  <button onclick="showJoin()">🌐 加入遊戲（區域網）</button>
  <button class="solo" onclick="soloGame()">🤖 單人練習</button>
</div>

<div id="join-row">
  <input id="ip-input" placeholder="輸入主機 IP，例如 192.168.1.5" autocomplete="off">
  <button onclick="joinGame()" style="height:44px">確認加入</button>
</div>

<p id="status"></p>
<p id="err"></p>

<script>
const status = document.getElementById('status');
const err = document.getElementById('err');

function showJoin() {
  document.getElementById('join-row').style.display = 'flex';
  document.getElementById('ip-input').focus();
}

async function soloGame() {
  status.textContent = '啟動中…';
  err.textContent = '';
  try {
    await window.pywebview.api.solo_game('玩家');
  } catch(e) {
    err.textContent = '啟動失敗：' + e;
    status.textContent = '';
  }
}

async function hostGame() {
  status.textContent = '啟動伺服器中…';
  try {
    const lan_ip = await window.pywebview.api.host_game();
    status.textContent = `區域網地址：${lan_ip}:5000（分享給同一網路的朋友）`;
  } catch(e) {
    err.textContent = '啟動失敗：' + e;
    status.textContent = '';
  }
}

async function joinGame() {
  const addr = document.getElementById('ip-input').value.trim();
  if (!addr) { err.textContent = '請輸入 IP 或 ngrok 網址'; return; }
  status.textContent = `連線中…`;
  err.textContent = '';
  try {
    await window.pywebview.api.join_game(addr);
  } catch(e) {
    err.textContent = '連線失敗：' + e;
    status.textContent = '';
  }
}

document.getElementById('ip-input')?.addEventListener('keydown', e => {
  if (e.key === 'Enter') joinGame();
});
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
        width=1080,
        height=720,
        resizable=True,
        frameless=False,
    )
    api._window = window
    webview.start(debug=False)
