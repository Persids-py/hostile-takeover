# 惡意併購 · Hostile Takeover

一款 3–7 人即時連線策略卡牌遊戲。每位玩家都有秘密身份和公開角色，透過傳遞、拒收機密或發動技能，達成陣營或個人的勝利條件。單人練習會安排三位電腦玩家陪玩。

![惡意併購的遊戲首頁](docs/preview.webp)

## 本機試玩

需要 Python 3.11 以上。安裝依賴後啟動伺服器。

```sh
python -m pip install -r requirements.txt
python app.py
```

在瀏覽器開啟 [http://localhost:5000](http://localhost:5000)，選擇「單人練習」即可開始。要試多人房間，可用另一個分頁加入同一房間，再由房主補一位電腦玩家。

## 程式結構

| 檔案 | 職責 |
| --- | --- |
| `game.py` | 管理選牌、回合、響應視窗、角色技能與勝負判定，並依玩家過濾手牌與身份資訊 |
| `app.py` | 以 Flask 和 Socket.IO 處理房間、即時事件及電腦玩家排程 |
| `bot.py` | 根據手牌、機密與陣營推測，決定傳牌、接收、棄牌和使用功能牌 |
| `templates/index.html`、`static/` | 呈現首頁、等候室與桌面／手機牌桌 |
| `simulate.py` | 自動執行七位電腦玩家的對局，檢查對局能否正常結束 |

Socket.IO 用戶端 4.8.4 隨專案提供，啟動和試玩時的瀏覽器資源由同一台伺服器提供。首頁主視覺為生成圖像。

## 驗證

```sh
python -m unittest discover -s tests
python simulate.py 1000
```

房間狀態保存在伺服器記憶體。`Procfile` 使用單一 Gunicorn worker 維持房間狀態一致。管理後台需透過 `ADMIN_PASSWORD` 啟用，可用 `SECRET_KEY` 設定固定的工作階段簽章金鑰。
