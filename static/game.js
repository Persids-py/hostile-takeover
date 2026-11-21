const socket = io();

let myPid = null;
let roomCode = null;
let state = null;
let selectedCardIid = null;
let discardMode = false;
let discardSelected = [];
let extraCardIid = null;
let extraCallback = null;
let _destroyTargets = [];   // 銷毀帳冊對話框用，供 updateDestroySecrets 存取

// ── 決策計時器 ──────────────────────────────────────────────────────────────
const DECISION_TIMEOUT = 25;
let _timerInterval = null;
let _timerFid = null;
let _timerSecs = 0;

function _startDecisionTimer(fid) {
  if (_timerFid === fid) return;
  _clearDecisionTimer();
  _timerFid = fid;
  _timerSecs = DECISION_TIMEOUT;
  _renderTimer();
  _timerInterval = setInterval(() => {
    _timerSecs--;
    _renderTimer();
    if (_timerSecs <= 0) {
      _clearDecisionTimer();
      _autoTimeoutAction();
    }
  }, 1000);
}

function _clearDecisionTimer() {
  if (_timerInterval) { clearInterval(_timerInterval); _timerInterval = null; }
  _timerFid = null;
  _timerSecs = 0;
  _renderTimer();
}

function _renderTimer() {
  const el = document.getElementById('table-timer');
  if (!el) return;
  if (_timerSecs > 0) {
    el.textContent = `${_timerSecs} 秒`;
    el.style.color = _timerSecs <= 5 ? '#fca5a5' : '#fcd34d';
  } else {
    el.textContent = '';
  }
}

function _autoTimeoutAction() {
  if (!state || !state.transit) return;
  socket.emit(canRefuseTransit(state) ? 'refuse' : 'accept', {});
}

function canRefuseTransit(d) {
  const { sender, going_back } = d.transit;
  const player = d.players.find(p => p.pid === myPid);
  return !going_back && player?.locked_by !== sender;
}

// ── 新手提示系統 ────────────────────────────────────────────────────────────
let _tutorialMode = new URLSearchParams(window.location.search).get('solo') === '1';
const _shownHints = new Set();
let _hintTimer = null;
let _hintQueue = [];   // [{id, priority}]
let _hintActive = false;
let _lastHintId = null;
let _highlightEl = null;
const HINT_DURATION = 8000;

const HINTS = {
  draft_identity: '這是抽身份牌階段！點選任一張牌背來抽取你的秘密身份。身份只有你自己看得到，千萬不要告訴別人！',
  draft_role:     '這是選角色牌階段！每張角色牌都有獨特的技能和個人任務。選一張最符合你策略的角色，其他兩張會被放回去。',
  my_turn:        '輪到你了！從下方手牌區選一張牌，然後點「傳出」送給下一位玩家。',
  transmit_mode:  '每張牌都有固定的傳遞方式：加密雲端（面朝下往右傳）、公開新聞稿（公開往右傳）、私人信件（傳給指定玩家，拒收退回自己）。',
  got_blue:       '你收到了藍色機密！你的陣營目標：集齊 3 張藍色機密即可獲勝。',
  got_red:        '你收到了紅色機密！你的陣營目標：集齊 3 張紅色機密即可獲勝。',
  got_black:      '⚠️ 你收到了有毒資產（黑牌）！累積 3 張就會破產出局，小心！可以用「銷毀帳冊」或「債務轉移」處理掉它。',
  got_dual:       '你收到了雙色機密！它藍紅兩方都能計入，是很有價值的牌。',
  black_danger:   '🚨 你已有 2 張黑牌，再接收一張就會破產！試著拒收黑牌，或用功能牌把它轉給別人。',
  near_win:       '✨ 再差一張就能獲勝了！注意別讓對手阻止你接收關鍵機密。',
  func_in_hand:   '你手上有功能牌（紫色邊框的牌）。點它可以在符合時機時發動特殊效果，不需要消耗傳牌次數。',
  response_win:   '響應視窗出現了！你可以趁現在打出功能牌干預局面，或點「不響應」跳過。',
  got_refuse:     '對方拒收了你的牌，它會繼續往下一位玩家傳過去。',
  bankrupt:       '有玩家破產了！累積 3 張黑色機密會強制出局，身份也會被公開。',
  discard:        '手牌超過上限，需要棄牌。點選你要丟棄的牌，然後確認。',
  independent:    '你是獨立投資人，沒有隊友！囤積 6 張任意機密，或完成角色專屬任務，就能單獨獲勝。',
};

// 優先級（越高越緊急，>=9 可插隊打斷目前提示）
const HINT_PRIORITY = {
  black_danger:10, discard:9, bankrupt:8,
  response_win:7, my_turn:6, got_refuse:5, near_win:4,
  got_black:3, got_blue:3, got_red:3, got_dual:3,
  transmit_mode:2, func_in_hand:2, independent:2,
  draft_identity:1, draft_role:1,
};

// 提示對應要高亮的 UI 元素
const HINT_HIGHLIGHT = {
  my_turn:      ()=>document.getElementById('my-hand'),
  discard:      ()=>document.getElementById('my-hand'),
  func_in_hand: ()=>document.getElementById('hand-cards'),
  response_win: ()=>document.getElementById('table-actions'),
  got_refuse:   ()=>document.getElementById('table-area'),
  transmit_mode:()=>document.getElementById('table-area'),
};

function showHint(id){
  if(!_tutorialMode) return;
  if(_shownHints.has(id)) return;
  if(!HINTS[id]) return;
  _shownHints.add(id);

  const priority = HINT_PRIORITY[id] || 1;
  // 緊急提示（priority>=9）插隊打斷目前顯示中的提示
  if(priority >= 9 && _hintActive){
    clearTimeout(_hintTimer);
    _clearHighlight();
    _hintQueue.unshift({id, priority});
    _hintActive = false;
    _processHintQueue();
  } else {
    _hintQueue.push({id, priority});
    _hintQueue.sort((a,b)=>b.priority - a.priority);
    if(!_hintActive) _processHintQueue();
  }
}

function _processHintQueue(){
  if(!_hintQueue.length){ _hintActive=false; return; }
  _hintActive = true;
  const {id} = _hintQueue.shift();
  _displayHint(id);
}

function _displayHint(id){
  _lastHintId = id;
  clearTimeout(_hintTimer);
  _clearHighlight();

  const box = document.getElementById('hint-box');
  const bar = document.getElementById('hint-bar');
  document.getElementById('hint-text').textContent = HINTS[id];
  box.classList.remove('visible');
  void box.offsetWidth;
  box.classList.add('visible');
  bar.style.transition = 'none';
  bar.style.width = '100%';
  requestAnimationFrame(()=>{
    bar.style.transition = `width ${HINT_DURATION}ms linear`;
    bar.style.width = '0%';
  });

  // 高亮相關 UI 元素
  const getEl = HINT_HIGHLIGHT[id];
  if(getEl){ const el=getEl(); if(el){ el.classList.add('hint-highlight'); _highlightEl=el; } }

  // 顯示重看按鈕
  document.getElementById('hint-replay-btn').style.display = 'flex';

  _hintTimer = setTimeout(()=>{
    _clearHighlight();
    document.getElementById('hint-box').classList.remove('visible');
    _hintActive = false;
    setTimeout(_processHintQueue, 350);
  }, HINT_DURATION);
}

function _clearHighlight(){
  if(_highlightEl){ _highlightEl.classList.remove('hint-highlight'); _highlightEl=null; }
}

function dismissHint(){
  clearTimeout(_hintTimer);
  _clearHighlight();
  document.getElementById('hint-box').classList.remove('visible');
  _hintActive = false;
  setTimeout(_processHintQueue, 350);
}

function replayLastHint(){
  if(!_lastHintId) return;
  _shownHints.delete(_lastHintId);
  _hintQueue.unshift({id:_lastHintId, priority:HINT_PRIORITY[_lastHintId]||1});
  if(!_hintActive) _processHintQueue();
}

function _checkHints(d){
  if(!_tutorialMode) return;
  const me = d.players.find(p=>p.pid===myPid);
  if(!me) return;

  // 輪到自己
  if(d.phase==='choose_card' && d.current_turn_pid===myPid){
    showHint('my_turn');
  }
  // 棄牌
  if(d.phase==='discard' && d.current_turn_pid===myPid){
    showHint('discard');
  }
  // 響應視窗
  const win = d.response_window;
  if(win && win.waiting_for.includes(myPid) && win.wtype!=='pre_receive'){
    showHint('response_win');
  }
  // 功能牌在手
  if(me.hand && me.hand.some(c=>c.func)){
    showHint('func_in_hand');
  }
  // 身份相關
  if(me.identity==='independent') showHint('independent');
  // 機密區顏色
  if(me.secrets){
    if(me.secrets.some(c=>c.color==='blue'))  showHint('got_blue');
    if(me.secrets.some(c=>c.color==='red'))   showHint('got_red');
    if(me.secrets.some(c=>c.color==='black')) showHint('got_black');
    if(me.secrets.some(c=>c.color==='dual'))  showHint('got_dual');
  }
  // 黑牌危機
  if(me.black >= 2) showHint('black_danger');
  // 接近獲勝
  if(me.identity==='board'    && me.blue>=2)  showHint('near_win');
  if(me.identity==='vulture'  && me.red>=2)   showHint('near_win');
  if(me.identity==='independent' && (me.blue+me.red+me.black)>=5) showHint('near_win');
  // 傳遞方式說明（第一次有牌在傳）
  if(d.transit) showHint('transmit_mode');
  // 拒收提示（我送出的牌被拒收了）
  if(d.transit && d.transit.visited && d.transit.visited.length>1 && d.transit.sender===myPid){
    showHint('got_refuse');
  }
  // 有人破產
  if(d.players.some(p=>p.is_bankrupt)) showHint('bankrupt');
}

// ── 音效 ──────────────────────────────────────────────────────────────────
const SFX = (() => {
  let ctx = null;
  let enabled = true;
  const init = () => {
    if (!ctx) ctx = new (window.AudioContext || window.webkitAudioContext)();
    if (ctx.state === 'suspended') ctx.resume();
  };
  const tone = (freq, type, dur, vol=0.25, delay=0) => {
    const t = ctx.currentTime + delay;
    const osc = ctx.createOscillator();
    const g = ctx.createGain();
    osc.connect(g); g.connect(ctx.destination);
    osc.type = type; osc.frequency.setValueAtTime(freq, t);
    g.gain.setValueAtTime(vol, t);
    g.gain.exponentialRampToValueAtTime(0.001, t + dur);
    osc.start(t); osc.stop(t + dur);
  };
  const noise = (dur, vol=0.1, cutoff=1800) => {
    const buf = ctx.createBuffer(1, ctx.sampleRate * dur, ctx.sampleRate);
    const d = buf.getChannelData(0);
    for (let i=0; i<d.length; i++) d[i] = Math.random()*2-1;
    const src = ctx.createBufferSource();
    const flt = ctx.createBiquadFilter();
    const g = ctx.createGain();
    flt.type = 'bandpass'; flt.frequency.value = cutoff;
    src.buffer = buf; src.connect(flt); flt.connect(g); g.connect(ctx.destination);
    g.gain.setValueAtTime(vol, ctx.currentTime);
    g.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + dur);
    src.start(); src.stop(ctx.currentTime + dur);
  };
  return {
    play(name) {
      if (!enabled) return;
      try {
        init();
        if (name==='fly')    { noise(0.18, 0.09, 2200); tone(280,'sine',0.12,0.06,0.04); }
        else if(name==='accept') { tone(523,'sine',0.1,0.2); tone(659,'sine',0.13,0.2,0.09); }
        else if(name==='refuse') { tone(330,'sine',0.1,0.2); tone(220,'sine',0.18,0.18,0.09); }
        else if(name==='turn')   { tone(440,'triangle',0.09,0.14); }
        else if(name==='func')   {
          const t=ctx.currentTime;
          const osc=ctx.createOscillator(); const g=ctx.createGain();
          osc.connect(g); g.connect(ctx.destination); osc.type='sine';
          osc.frequency.setValueAtTime(900,t);
          osc.frequency.exponentialRampToValueAtTime(300,t+0.18);
          g.gain.setValueAtTime(0.28,t);
          g.gain.exponentialRampToValueAtTime(0.001,t+0.18);
          osc.start(t); osc.stop(t+0.2);
        }
        else if(name==='win')    { [523,659,784,1047].forEach((f,i)=>tone(f,'sine',0.28,0.22,i*0.11)); }
        else if(name==='card_flip'){ noise(0.07,0.13,3500); tone(520,'sine',0.06,0.12,0.03); }
        else if(name==='card_pick'){ tone(660,'sine',0.08,0.18); tone(880,'sine',0.1,0.16,0.07); }
      } catch(e) {}
    },
    toggle() { enabled = !enabled; return enabled; }
  };
})();

// ── 響應視窗自動 Pass 計時器 ────────────────────────────────────────────────
const PASS_TIMEOUT = 15;
let _passTimerFid = null;
let _passTimerSecs = 0;
let _passTimerInterval = null;

function _startPassTimer(fid) {
  if (_passTimerFid === fid) return;
  _clearPassTimer();
  _passTimerFid = fid;
  _passTimerSecs = PASS_TIMEOUT;
  _renderPassTimer();
  _passTimerInterval = setInterval(() => {
    _passTimerSecs--;
    _renderPassTimer();
    if (_passTimerSecs <= 0) { _clearPassTimer(); socket.emit('pass_response', {}); }
  }, 1000);
}
function _clearPassTimer() {
  if (_passTimerInterval) { clearInterval(_passTimerInterval); _passTimerInterval = null; }
  _passTimerFid = null; _passTimerSecs = 0; _renderPassTimer();
}
function _renderPassTimer() {
  const el = document.getElementById('pass-timer');
  if (!el) return;
  if (_passTimerSecs > 0) {
    el.textContent = `⏱ ${_passTimerSecs}s`;
    el.style.color = _passTimerSecs <= 5 ? '#fca5a5' : 'var(--text-muted)';
  } else { el.textContent = ''; }
}

// ── 牌庫速查 ──────────────────────────────────────────────────────────────
const CARD_REF = {
  blue: [
    {name:'盡職調查', tx:'加密雲端', desc:'【自己回合】秘密檢視一名玩家的機密區'},
    {name:'公開財報', tx:'公開新聞稿', desc:'【自己回合】隨機抽取他人一張手牌與你的一張互換'},
    {name:'資源挹注', tx:'公開新聞稿', desc:'【自己回合】抽牌，黑牌越多抽越多'},
    {name:'法務攔截', tx:'私人信件', desc:'【響應鏈中】使最後一張功能牌無效'},
    {name:'吹哨者舉報', tx:'加密雲端', desc:'【自己回合】看他人手牌並強制棄一張'},
  ],
  red: [
    {name:'內線交易',   tx:'私人信件', desc:'【他人宣告傳出時】要求對方傳出指定顏色，否則看手牌'},
    {name:'惡意截胡',   tx:'加密雲端', desc:'【他人宣告接收時】將機密強行截至自己面前'},
    {name:'惡意干擾',   tx:'加密雲端', desc:'【他人宣告接收時】取消接收，機密繼續往下傳'},
    {name:'惡意帶風向', tx:'公開新聞稿', desc:'【他人宣告傳遞目標時】強制改變傳遞目標'},
    {name:'惡意鎖定',   tx:'私人信件', desc:'【任意時機】指定玩家本輪無法拒收'},
  ],
  black: [
    {name:'有毒資產', tx:'加密雲端', desc:'無功能牌。累積三張即破產出局（空殼公司角色門檻為4張）'},
    {name:'債務轉移', tx:'公開新聞稿', desc:'【機密傳至自己時】強制轉給指定玩家，對方無法拒收'},
    {name:'銷毀帳冊', tx:'私人信件', desc:'【任意時機】棄置場上任一玩家已接收的黑色機密'},
    {name:'偷天換日', tx:'加密雲端', desc:'【私函退回傳出者時】替換成另一張牌改公開重傳'},
  ],
  dual: [
    {name:'核心機密', tx:'加密雲端', desc:'【任意時機】秘密偷看傳遞中的加密機密'},
    {name:'駭客入侵', tx:'私人信件', desc:'【任意時機】秘密查看一名玩家的整副手牌'},
  ],
};
const TX_COLOR = {加密雲端:'#64748b', 公開新聞稿:'#3b82f6', 私人信件:'#a855f7'};

function toggleRef() {
  const m = document.getElementById('ref-modal');
  m.classList.toggle('open');
  if (m.classList.contains('open')) showRefTab('blue');
}
function showRefTab(tab) {
  document.querySelectorAll('.ref-tab').forEach(button => {
    button.classList.toggle('active', button.dataset.refTab === tab);
  });
  const body = document.getElementById('ref-body');
  if (tab === 'win') {
    const wins = [
      {label:'🏦 董事會', color:'#3b82f6', desc:'收集 3 張藍色機密', detail:'與同陣營成員共同勝利'},
      {label:'🦅 禿鷹基金', color:'#ef4444', desc:'收集 3 張紅色機密', detail:'與同陣營成員共同勝利'},
      {label:'💼 獨立投資人', color:'#a855f7', desc:'囤積 6 張機密', detail:'完成角色任務亦可獲勝，無隊友，單獨勝利'},
    ];
    body.innerHTML = `<div id="ref-win-list">${wins.map(w=>`
      <div class="ref-win-item" style="border-left:3px solid ${w.color}">
        <div style="color:${w.color};font-weight:700;font-size:.95rem;margin-bottom:4px">${w.label}</div>
        <div style="color:var(--text);font-size:.85rem;margin-bottom:3px">勝利條件：${w.desc}</div>
        <div style="color:var(--text-muted);font-size:.78rem">${w.detail}</div>
      </div>`).join('')}</div>`;
  } else {
    const cards = CARD_REF[tab] || [];
    body.innerHTML = cards.map(c=>`
      <div class="ref-card ${tab}">
        <div class="ref-card-name">${esc(c.name)}</div>
        <div class="ref-card-tag" style="color:${TX_COLOR[c.tx]||'#888'}">傳遞方式：${c.tx}</div>
        <div class="ref-card-desc">${esc(c.desc)}</div>
      </div>`).join('');
  }
}

// ── 大廳 ──────────────────────────────────────────────────────────────────

const lobbyModes = {
  host: { title: '主辦遊戲', description: '建立房間後，把代碼分享給朋友。', button: '建立房間', event: 'create_room' },
  join: { title: '加入遊戲', description: '輸入房主分享的代碼。', button: '確認加入', event: 'join_room_req' },
  solo: { title: '單人練習', description: '與 3 位電腦玩家對戰。', button: '開始練習', event: 'solo_start' },
};
let lobbyMode = 'host';
let landingTrigger = null;

function goLobby(mode){
  lobbyMode = mode;
  landingTrigger = document.activeElement;
  document.getElementById('landing').style.display='none';
  document.getElementById('header').style.display='block';
  document.getElementById('lobby').style.display='flex';
  const { title, description, button } = lobbyModes[mode];
  const codeInput = document.getElementById('code-input');
  const joining = mode === 'join';
  document.getElementById('room-code-field').hidden = !joining;
  codeInput.disabled = !joining;
  codeInput.required = joining;
  document.getElementById('lobby-mode-title').textContent = title;
  document.getElementById('lobby-mode-description').textContent = description;
  document.getElementById('lobby-submit').textContent = button;
  document.getElementById('lobby-error').textContent = '';
  document.getElementById('name-input').focus();
}

function openRules(){
  document.getElementById('rules-overlay').showModal();
}
function closeRules(){
  document.getElementById('rules-overlay').close();
}
function switchRulesTab(name){
  document.querySelectorAll('.rules-tab').forEach((t,i)=>{
    const tabs=['overview','flow','cards','roles'];
    t.classList.toggle('active', tabs[i]===name);
  });
  document.querySelectorAll('.rules-section').forEach(s=>{
    s.classList.toggle('active', s.id==='rules-tab-'+name);
  });
}

function showLanding(){
  document.getElementById('landing').style.display='flex';
  document.getElementById('header').style.display='none';
  document.getElementById('lobby').style.display='none';
  document.getElementById('lobby-error').textContent='';
  landingTrigger?.focus();
}

function submitLobby(event){
  event?.preventDefault();
  const name = document.getElementById('name-input').value.trim();
  const room_code = document.getElementById('code-input').value.trim().toUpperCase();
  const submit = document.getElementById('lobby-submit');
  if (submit.disabled) return;
  if (!name) return showLobbyError('請輸入玩家名稱。');
  if (lobbyMode === 'join' && !/^[A-Z]{4}$/.test(room_code)) return showLobbyError('請輸入 4 個英文字母。');
  if (!socket.connected) return showLobbyError('正在連線，請稍後再試。');

  _tutorialMode = lobbyMode === 'solo';
  const back = document.getElementById('back-to-landing');
  showLobbyError('');
  submit.disabled = back.disabled = true;
  socket.timeout(7000).emit(lobbyModes[lobbyMode].event, { name, room_code, bot_count: 3 }, error => {
    submit.disabled = back.disabled = false;
    if (error && !myPid) showLobbyError('伺服器回應逾時，請再試一次。');
  });
}

function startGame(){
  socket.emit('start_game',{});
}

function showLobbyError(msg){
  document.getElementById('lobby-error').textContent = msg;
}

let copyLabelTimer;
async function copyRoomCode(){
  if(!roomCode) return;
  const label = document.getElementById('copy-label');
  try {
    await navigator.clipboard.writeText(roomCode);
    label.textContent = '已複製';
  } catch {
    label.textContent = '請手動抄寫';
  }
  clearTimeout(copyLabelTimer);
  copyLabelTimer = setTimeout(() => { label.textContent = '複製'; }, 2500);
}

// ── Socket 事件 ───────────────────────────────────────────────────────────

function enterRoom({ pid, room_code, solo }){
  myPid = pid;
  roomCode = room_code;
  document.getElementById('lobby-form').hidden = true;
  document.getElementById('room-code').textContent = roomCode;
  document.getElementById('waiting-room').hidden = Boolean(solo);
  showLobbyError('');
}

socket.on('room_created', enterRoom);
socket.on('room_joined', enterRoom);

// 單人練習：偵測 URL 參數 ?solo=1&name=...
(()=>{
  const p = new URLSearchParams(window.location.search);
  if(p.get('solo')==='1'){
    goLobby('solo');
    document.getElementById('name-input').value = (p.get('name') || '玩家').slice(0, 16);
    if (socket.connected) submitLobby();
    else socket.once('connect', () => {
      if (lobbyMode === 'solo' && document.getElementById('lobby').style.display === 'flex') submitLobby();
    });
  }
})();

socket.on('connect_error', () => {
  if (!myPid) showLobbyError('目前無法連上伺服器，請稍後再試。');
});

socket.on('disconnect', () => {
  if (!myPid || document.getElementById('room-closed-overlay').classList.contains('visible')) return;
  document.getElementById('room-closed-title').textContent = '連線已中斷';
  document.getElementById('room-closed-msg').textContent = '請返回首頁，重新建立或加入房間。';
  document.getElementById('room-closed-overlay').classList.add('visible');
});

socket.on('state',d=>{
  if (!myPid) return;
  const previousPhase = state?.phase;
  const changedPhase = previousPhase !== d.phase;
  if (changedPhase && d.phase === 'draft_identity') {
    if (seatDialog.open) seatDialog.close();
    lastLogSequence = 0;
    _myDraftIdentity = null;
    roleChoiceCache.clear();
    document.getElementById('log-area').replaceChildren();
    document.getElementById('role-draft-cards').removeAttribute('data-signature');
  }
  state = d;
  const screenId = { lobby: 'lobby', draft_identity: 'draft-screen', draft_role: 'role-draft-screen' }[d.phase] || 'game';
  document.getElementById('landing').style.display = 'none';
  document.getElementById('header').style.display = screenId === 'game' ? 'none' : 'block';
  for (const id of ['lobby', 'draft-screen', 'role-draft-screen', 'game']) {
    document.getElementById(id).style.display = id === screenId ? 'flex' : 'none';
  }
  if (changedPhase && (d.phase === 'draft_identity' || d.phase === 'draft_role' || previousPhase?.startsWith('draft_'))) {
    clearInterval(draftTimer);
    if (_hintActive) dismissHint();
    const screen = document.getElementById(screenId);
    if (screen.querySelector('.tutorial-slot')) mountTutorial(screen);
    if (screen.classList.contains('draft-screen')) {
      screen.querySelector('.draft-error').textContent = '';
      startDraftClock(screen);
    }
  }
  if (d.phase === 'lobby') renderLobby(d);
  else if (d.phase === 'draft_identity') renderDraft(d);
  else if (d.phase === 'draft_role') renderRoleDraft(d);
  else renderGame(d);
  if(d.phase==='game_over'){
    showGameOver(d);
  } else {
    document.getElementById('gameover-overlay').style.display = 'none';
  }
});

socket.on('error',d=>{showError(d.msg);});

socket.on('room_closed',d=>{
  const msg = d.kicked
    ? '你已被管理員移出此房間。'
    : '此房間已被管理員關閉。<br>感謝你的遊玩！';
  document.getElementById('room-closed-msg').innerHTML = msg;
  document.getElementById('room-closed-overlay').classList.add('visible');
});

socket.on('admin_broadcast',d=>{
  const box = document.createElement('div');
  box.textContent = '📢 ' + d.msg;
  Object.assign(box.style, {
    position:'fixed', top:'70px', left:'50%', transform:'translateX(-50%)',
    background:'#1d4ed8', color:'#fff', padding:'10px 20px',
    borderRadius:'8px', fontWeight:'600', zIndex:'9999',
    boxShadow:'0 4px 20px #0007', fontSize:'.9rem',
    animation:'hintSlideIn .3s ease',
  });
  document.body.appendChild(box);
  setTimeout(()=> box.remove(), 5000);
});

socket.on('chat_msg',d=>{
  const el=document.getElementById('chat-log');
  const div=document.createElement('div');
  div.className='chat-msg';
  div.innerHTML=`<span class="cn">${esc(d.name)}：</span>${esc(d.msg)}`;
  el.appendChild(div);
  el.scrollTop=el.scrollHeight;
});

socket.on('private_info',d=>{
  if(d.draft_identity){
    _myDraftIdentity=d.draft_identity;
    if(state&&state.phase==='draft_identity') _showMyDraftIdentity();
  } else if(d.hacked_card){
    alert(`核心機密：傳遞中的牌是「${d.hacked_card.name}」（${colorLabel(d.hacked_card.color)}）`);
  } else if(d.hacked_hand){
    showViewHand(d.hacked_hand);
  } else if(d.view_hand){
    showViewHand(d.view_hand);
  } else if(d.view_secrets){
    showViewSecrets(d.view_secrets);
  } else if(d.took_card){
    closeExtra();
  } else if(d.force_color){
    showError(`內線交易：對方被要求傳出 ${colorLabel(d.force_color)} 機密`);
  } else if(d.role_skill_result){
    showRoleSkillResult(d.role_skill_result);
  }
});

socket.on('need_role_extra', d=>{
  showRoleSkillDialog(d.result);
});

socket.on('need_extra',d=>{
  extraCardIid=d.card_iid;
  showExtraDialog(d);
});

function addBot(){ socket.emit('add_bot',{}); }

function removeLastBot(){
  if(!state||!state.players) return;
  const bots=state.players.filter(p=>p.is_bot);
  if(!bots.length) return;
  socket.emit('remove_bot',{bot_pid:bots[bots.length-1].pid});
}

// ── 開局選牌 ──────────────────────────────────────────────────────────────
let _myDraftIdentity = null;
let draftTimer = null;
const roleChoiceCache = new Map();

const IDENTITY_INFO = {
  board:       { label: '董事會', desc: '集齊 3 張藍色機密，與董事會成員共同獲勝。' },
  vulture:     { label: '禿鷹基金', desc: '集齊 3 張紅色機密，與禿鷹基金成員共同獲勝。' },
  independent: { label: '獨立投資人', desc: '集齊 6 張機密，或完成角色任務，即可單獨獲勝。' },
};

const ROLE_ART = {
  企業間諜: '0% 0%',
  雙面公關: '50% 0%',
  王牌律師: '100% 0%',
  禿鷹操盤手: '0% 50%',
  財務稽核: '50% 50%',
  空殼公司: '100% 50%',
  市場狙擊手: '0% 100%',
  白衣騎士: '50% 100%',
  數據掮客: '100% 100%',
};

function startDraftClock(screen) {
  const time = screen.querySelector('.draft-clock b');
  const progress = screen.querySelector('progress');
  const deadline = Date.now() + 30000;
  const tick = () => {
    const seconds = Math.max(0, Math.ceil((deadline - Date.now()) / 1000));
    time.textContent = seconds;
    progress.value = seconds;
    screen.classList.toggle('time-low', seconds <= 5);
    if (seconds === 0) clearInterval(draftTimer);
  };
  draftTimer = setInterval(tick, 250);
  tick();
}

function mountTutorial(screen) {
  const slot = screen.querySelector('.tutorial-slot');
  slot.append(document.getElementById('hint-box'), document.getElementById('hint-replay-btn'));
}

function renderDraft(d) {
  showHint('draft_identity');
  const ownSlot = d.draft_slots.find(slot => slot.identity);
  if (ownSlot) _myDraftIdentity = ownSlot.identity;
  const list = document.getElementById('draft-slots');
  const focusedSlot = list.contains(document.activeElement) ? document.activeElement.dataset.slot : null;
  list.replaceChildren(...d.draft_slots.map(slot => {
    const card = document.createElement('button');
    card.type = 'button';
    card.dataset.slot = slot.idx;
    card.className = 'draft-card';
    const identity = IDENTITY_INFO[slot.identity];
    if (identity) {
      card.classList.add('claimed-me', 'identity-' + slot.identity);
      card.innerHTML = `<span class="identity-label">你的身份</span><span class="identity-name">${identity.label}</span><span class="identity-condition">${identity.desc}</span>`;
    } else {
      const claimed = Boolean(slot.claimed_by);
      card.classList.add(claimed ? 'claimed-other' : 'available');
      card.innerHTML = '<span class="card-seal" aria-hidden="true"></span>';
      const label = document.createElement('span');
      label.className = 'card-back-label';
      label.textContent = claimed ? '已抽取' : '抽取';
      card.appendChild(label);
      if (claimed) card.title = slot.claimed_by;
      if (!claimed && !d.my_drafted) {
        card.setAttribute('aria-label', `抽取第 ${slot.idx + 1} 張身份牌`);
        card.onclick = () => draftIdentity(slot.idx);
      }
    }
    card.disabled = Boolean(slot.claimed_by) || d.my_drafted;
    return card;
  }));
  if (focusedSlot !== null && !d.my_drafted) {
    const previous = list.querySelector(`[data-slot="${focusedSlot}"]:enabled`);
    (previous || list.querySelector(':enabled'))?.focus({ preventScroll: true });
  }
  document.getElementById('draft-subtitle').textContent = d.pending_count
    ? `還有 ${d.pending_count} 位玩家未抽取` : '所有玩家已抽取';
  document.getElementById('draft-status').textContent = d.my_drafted
    ? '已抽取，等待其他玩家。' : '選一張牌翻開。身份只會顯示給你。';
}

function _showMyDraftIdentity(){
  if(state?.phase === 'draft_identity') renderDraft(state);
}

function draftIdentity(slotIdx){
  document.querySelector('#draft-screen .draft-error').textContent = '';
  SFX.play('card_flip');
  socket.emit('draft_identity', {slot_idx: slotIdx});
}

function renderRoleDraft(d) {
  showHint('draft_role');
  const list = document.getElementById('role-draft-cards');
  const signature = JSON.stringify([d.my_picked, d.my_role, d.role_choices]);
  if (list.dataset.signature !== signature) {
    list.dataset.signature = signature;
    for (const choice of d.role_choices || []) roleChoiceCache.set(choice.name, choice);
    const choices = d.my_picked
      ? [roleChoiceCache.get(d.my_role) || {
          name: d.my_role,
          skill_desc: ROLE_SKILL_DESC[d.my_role]?.desc,
          task_desc: ROLE_TASK_DESC[d.my_role]
        }]
      : d.role_choices;
    list.classList.toggle('picked-role', d.my_picked);
    list.replaceChildren(...choices.map(role => {
      const card = document.createElement(d.my_picked ? 'article' : 'button');
      card.className = 'role-card';
      const skillType = ROLE_SKILL_DESC[role.name]?.type === 'passive' ? '被動技能' : '主動技能';
      card.innerHTML = `
        <span class="role-visual" aria-hidden="true" style="--role-position:${ROLE_ART[role.name] || '50% 50%'}"></span>
        <span class="role-card-content">
          <span class="role-card-name">${esc(role.name)}</span>
          <span class="role-card-skill"><b>${skillType}</b>${esc(role.skill_desc)}</span>
          <span class="role-card-task"><b>${_myDraftIdentity === 'independent' ? '你的勝利任務' : '角色任務'}</b>${esc(role.task_desc)}</span>
          <span class="role-card-action">${d.my_picked ? '已選擇' : '選擇角色'} <span aria-hidden="true">${d.my_picked ? '✓' : '→'}</span></span>
        </span>`;
      if (!d.my_picked) {
        card.type = 'button';
        card.onclick = () => pickRole(role.name);
      }
      return card;
    }));
  }
  document.getElementById('role-draft-subtitle').textContent = d.pending_count
    ? `還有 ${d.pending_count} 位玩家未選擇` : '所有玩家已選擇';
  document.getElementById('role-draft-status').textContent = d.my_picked
    ? '角色已選定，等待其他玩家。' : '從三張牌選一個角色。技能與任務會隨角色而異。';
}

function pickRole(roleName){
  document.querySelector('#role-draft-screen .draft-error').textContent = '';
  SFX.play('card_pick');
  socket.emit('pick_role', {role_name: roleName});
}

function _roleTaskHint(role, prog){
  if(!role) return '';
  if(role==='企業間諜') return `接收來源：${(prog.received_from||[]).length}/2`;
  if(role==='雙面公關'){
    const b=prog.sent_blue_to_board?'✓':'✗';
    const r=prog.sent_red_to_vulture?'✓':'✗';
    return `傳藍→董事會${b} 傳紅→禿鷹${r}`;
  }
  if(role==='王牌律師') return `本回合功能牌：${prog.func_count_this_turn||0}/3`;
  if(role==='禿鷹操盤手') return `累計拒收：${prog.total_refusals||0}/4`;
  if(role==='財務稽核') return `已查看：${(prog.viewed_pids||[]).length} 人`;
  if(role==='空殼公司') return `黑牌任務：持有≥2張有毒+場上≥5張機密`;
  if(role==='市場狙擊手') return `私信成功：${prog.private_received||0}/4`;
  if(role==='白衣騎士') return `幫助次數：${prog.helped_count||0}/3`;
  if(role==='數據掮客') return `功能牌總計：${prog.total_func_count||0}/6`;
  return '';
}

// ── 角色技能 ──────────────────────────────────────────────────────────────

const ROLE_SKILL_TYPES = {
  '企業間諜': 'active', '雙面公關': 'active', '財務稽核': 'active',
  '白衣騎士': 'active', '數據掮客': 'active',
};

function openRoleSkillDialog(){
  // First call with no extra — server will respond with need_role_extra if more info needed
  socket.emit('use_role_skill', {extra: null});
}

function showRoleSkillDialog(result){
  if(!result) return;
  // result may be {need_role_skill: {...}} or {need_target: ...} or direct
  if(result.need_role_skill) result = result.need_role_skill;
  const type = result.type;
  // White knight: pick target + secret
  if(type === 'white_knight'){
    const playerOpts = (result.players||[]).map(p=>
      `<option value="${p.pid}">${esc(p.name)}</option>`).join('');
    const secretOpts = (result.non_black_secrets||[]).map(c=>
      `<option value="${c.iid}">${esc(c.name)}（${colorLabel(c.color)}）</option>`).join('');
    document.getElementById('extra-title').textContent = '白衣騎士技能 — 傳出機密';
    document.getElementById('extra-content').innerHTML = `
      <label>選擇接收玩家：</label>
      <select id="wk-target">${playerOpts}</select>
      <label style="margin-top:10px;display:block">選擇傳出的機密（非黑色）：</label>
      <select id="wk-secret">${secretOpts}</select>
      <p style="font-size:.75rem;color:var(--text-muted);margin-top:6px">對方無法拒收</p>
    `;
    extraCallback = () => {
      const target_pid = document.getElementById('wk-target').value;
      const secret_iid = document.getElementById('wk-secret').value;
      socket.emit('use_role_skill', {extra: {target_pid, secret_iid}});
      closeExtra();
    };
    document.getElementById('extra-overlay').style.display = 'flex';
    return;
  }
  // Data broker: pick hand card to cycle
  if(type === 'data_broker'){
    const cardOpts = (result.my_hand||[]).map(c=>
      `<option value="${c.iid}">${esc(c.name)}（${colorLabel(c.color)}）</option>`).join('');
    document.getElementById('extra-title').textContent = '數據掮客技能 — 抽換手牌';
    document.getElementById('extra-content').innerHTML = `
      <label>選擇放回牌庫的牌：</label>
      <select id="broker-card">${cardOpts}</select>
      <p style="font-size:.75rem;color:var(--text-muted);margin-top:6px">放回後立即抽1張新牌</p>
    `;
    extraCallback = () => {
      const hand_iid = document.getElementById('broker-card').value;
      socket.emit('use_role_skill', {extra: {hand_iid}});
      closeExtra();
    };
    document.getElementById('extra-overlay').style.display = 'flex';
    return;
  }
  // Generic target-select skills (企業間諜, 雙面公關, 財務稽核) — server sends need_target
  if(result.need_target || type === 'need_target'){
    const players = state.players.filter(p=>p.pid!==myPid&&!p.is_bankrupt);
    const playerOpts = players.map(p=>`<option value="${p.pid}">${esc(p.name)}</option>`).join('');
    const role = state?.players?.find(p=>p.pid===myPid)?.role || '';
    const titles = {
      '企業間諜': '企業間諜技能 — 秘密查看身份',
      '雙面公關': '雙面公關技能 — 指定跟蹤對象',
      '財務稽核': '財務稽核技能 — 查看機密區',
    };
    document.getElementById('extra-title').textContent = titles[role] || '使用技能';
    document.getElementById('extra-content').innerHTML = `
      <label>選擇目標玩家：</label>
      <select id="skill-target">${playerOpts}</select>
    `;
    extraCallback = () => {
      const target_pid = document.getElementById('skill-target').value;
      socket.emit('use_role_skill', {extra: {target_pid}});
      closeExtra();
    };
    document.getElementById('extra-overlay').style.display = 'flex';
    return;
  }
}

function showRoleSkillResult(result){
  if(!result) return;
  const t = result.type;
  if(t === 'view_identity'){
    const IDENTITY_LABELS = {board:'董事會', vulture:'禿鷹基金', independent:'獨立投資人'};
    const label = IDENTITY_LABELS[result.identity] || result.identity;
    alert(`企業間諜：${esc(result.target_name)} 的身份是【${label}】`);
  } else if(t === 'tracking_set'){
    showError(`雙面公關：你已秘密指定跟蹤 ${esc(result.target_name)}，若其獲勝則你共同勝利`);
  } else if(t === 'view_secrets'){
    showViewSecrets({pid: null, name: result.target_name, secrets: result.secrets});
  }
}

function renderLobby(d){
  const isHost = d.host_pid === myPid;
  document.getElementById('lobby-actions').hidden = !isHost;
  document.getElementById('remove-bot-btn').disabled = !d.players.some(player => player.is_bot);
  document.getElementById('add-bot-btn').disabled = d.players.length >= 7;
  document.getElementById('start-btn').disabled = d.players.length < 3;
  document.getElementById('room-count').textContent = `${d.players.length} / 7`;
  document.getElementById('room-hint').textContent = isHost
    ? '至少 3 人即可開始，可以加入電腦玩家。'
    : '等待房主開始遊戲。';
  document.getElementById('players-list').innerHTML = d.players.map(player => {
    const labels = [];
    if (player.pid === d.host_pid) labels.push('房主');
    if (player.pid === myPid) labels.push('你');
    if (player.is_bot) labels.push('電腦');
    return `<li><span class="roster-name">${esc(player.name)}</span><span class="roster-tag">${labels.join(' · ')}</span></li>`;
  }).join('');
}

// ── 遊戲渲染 ──────────────────────────────────────────────────────────────

// ── 傳牌飛行動畫 ──────────────────────────────────────────────────────────
let _flyIid = null;      // 上一次已動畫的 card iid
let _flyTarget = null;   // 上一次的 current_target pid

function _pidCenter(pid){
  const el = [...document.querySelectorAll(`[data-pid="${pid}"]`)].find(node => node.getClientRects().length);
  if(!el) return null;
  const r = el.getBoundingClientRect();
  return {x: r.left + r.width/2, y: r.top + r.height/2};
}

function animateCardFly(fromPid, toPid, transit){
  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  const from = _pidCenter(fromPid);
  const to   = _pidCenter(toPid);
  if(!from || !to) return;
  SFX.play('fly');

  const color = transit.face_up ? (transit.card.color||'unknown') : 'unknown';
  const label = transit.face_up ? transit.card.name : '???';

  const el = document.createElement('div');
  el.className = `fly-card ${color}`;
  el.textContent = label;

  // 起始位置（發牌方中心），先隱藏
  el.style.left    = from.x + 'px';
  el.style.top     = from.y + 'px';
  el.style.transform = 'translate(-50%,-50%) scale(0.7)';
  el.style.opacity = '0';
  document.body.appendChild(el);

  // 下一幀啟動動畫（先顯現，再飛向目標）
  requestAnimationFrame(()=>{
    requestAnimationFrame(()=>{
      el.style.opacity   = '1';
      el.style.left      = to.x + 'px';
      el.style.top       = to.y + 'px';
      el.style.transform = 'translate(-50%,-50%) scale(1)';

      // 到達後淡出
      setTimeout(()=>{
        el.style.transition = 'opacity .2s, transform .2s';
        el.style.opacity    = '0';
        el.style.transform  = 'translate(-50%,-50%) scale(0.6)';
        setTimeout(()=> el.remove(), 250);
      }, 480);
    });
  });
}

function _detectTransitAnim(d){
  const t = d.transit;
  if(!t){
    _flyIid = null; _flyTarget = null;
    return;
  }
  const iid = t.card?.iid;
  if(iid !== _flyIid){
    // 全新機密上路：從傳出者飛向第一個目標
    animateCardFly(t.sender, t.current_target, t);
  } else if(t.current_target !== _flyTarget){
    // 同一張牌換傳對象（拒收後繼續傳）
    animateCardFly(_flyTarget, t.current_target, t);
  }
  _flyIid    = iid;
  _flyTarget = t.current_target;
}

let _lastTurnPid = null;

function renderGame(d){
  // full-screen board: hide header for max space
  document.getElementById('header').style.display='none';

  // turn-change sound
  if(d.current_turn_pid && d.current_turn_pid !== _lastTurnPid){
    if(_lastTurnPid !== null) SFX.play('turn');
    _lastTurnPid = d.current_turn_pid;
  }
  // game-over sound
  if(d.phase==='game_over' && _lastTurnPid !== 'done'){ SFX.play('win'); _lastTurnPid='done'; }

  renderSeats(d);
  renderTableTransit(d);
  renderSelfInfo(d);
  _detectTransitAnim(d);
  renderStatus(d);
  renderHand(d);
  renderLog(d);
  renderResponseWindow(d);
  _checkHints(d);
}

const WIN_COND = {
  board:       { label:'董事會',     color:'#3b82f6', icon:'🏦', desc:'收集 3 張藍色機密' },
  vulture:     { label:'禿鷹基金',   color:'#ef4444', icon:'🦅', desc:'收集 3 張紅色機密' },
  independent: { label:'獨立投資人', color:'#f0c040', icon:'💼', desc:'囤積 6 張機密 或 完成角色任務' },
};

// 角色任務說明（client-side lookup，供其他玩家列看）
const ROLE_SKILL_DESC = {
  '企業間諜':   {type:'active',  desc:'遊戲開始時，秘密查看任意一名玩家的身份牌'},
  '雙面公關':   {type:'active',  desc:'指定一名跟蹤對象；若其以陣營勝利條件獲勝，你也共同獲勝'},
  '王牌律師':   {type:'passive', desc:'手牌上限永久提升為8張'},
  '禿鷹操盤手': {type:'passive', desc:'每當你傳出的機密被拒收一次，立即抽1張牌（每回合最多2次）'},
  '財務稽核':   {type:'active',  desc:'每局限1次，免費發動盡職調查效果（秘密查看一名玩家機密區）'},
  '空殼公司':   {type:'passive', desc:'破產門檻提高為4張有毒資產'},
  '市場狙擊手': {type:'passive', desc:'你傳出的私人信件被拒收時，可繼續往右順傳而非退回自己'},
  '白衣騎士':   {type:'active',  desc:'每局限1次，將自己機密區中1張非黑色機密無償傳給指定玩家（對方無法拒收）'},
  '數據掮客':   {type:'active',  desc:'每回合1次，將手牌中1張牌放回牌庫頂後抽1張'},
};

const ROLE_TASK_DESC = {
  '企業間諜':   '成功接收由 2 名以上不同玩家主動傳來的機密各≥1張',
  '雙面公關':   '向≥1名董事會傳出被接收的藍/雙色機密，同時也向≥1名禿鷹傳出被接收的紅/雙色機密',
  '王牌律師':   '在同一回合中打出 3 張功能牌',
  '禿鷹操盤手': '傳出的機密累計被拒收 4 次以上',
  '財務稽核':   '用功能牌查看過所有存活玩家的機密區各至少 1 次',
  '空殼公司':   '持有至少 2 張有毒資產時，場上機密總數達到 5 張',
  '市場狙擊手': '以私人信件傳出的機密累計 4 張成功被接收',
  '白衣騎士':   '幫助他人接收有利機密共計 3 張',
  '數據掮客':   '在一局遊戲中使用功能牌（含技能抽換）合計達 6 次',
};

function _winProgress(p){
  if(!p.identity) return '';
  if(p.identity === 'board')    return `${p.blue}/3`;
  if(p.identity === 'vulture')  return `${p.red}/3`;
  if(p.identity === 'independent') return `${p.secrets.length}/6`;
  return '';
}

// ── 玩家席位 ─────────────────────────────────────────────────────────────
const seatDialog = document.getElementById('seat-dialog');
let inspectedPid = null;
let seatsSignature = '';

seatDialog.addEventListener('close', () => {
  document.querySelector(`#seats-area [data-pid="${CSS.escape(inspectedPid)}"]`)?.focus();
  inspectedPid = null;
});

function seatStats(player) {
  return `
    <span class="seat-stat blue" title="藍色機密">藍 <b>${player.blue}</b></span>
    <span class="seat-stat red" title="紅色機密">紅 <b>${player.red}</b></span>
    <span class="seat-stat black" title="有毒資產">黑 <b>${player.black}</b></span>
    <span class="seat-stat hand">手牌 <b>${player.hand_count}</b></span>`;
}

function renderSeats(d) {
  const area = document.getElementById('seats-area');
  const ownSeat = d.order.indexOf(myPid);
  const order = d.order.slice(ownSeat + 1).concat(d.order.slice(0, ownSeat));
  const opponents = order.map(pid => d.players.find(player => player.pid === pid)).filter(Boolean);
  const signature = JSON.stringify([d.current_turn_pid, opponents, d.transit?.current_target]);
  if (signature === seatsSignature) return;
  seatsSignature = signature;
  document.getElementById('seat-count').textContent = opponents.length;
  const focusedPid = area.contains(document.activeElement) ? document.activeElement.dataset.pid : null;
  area.replaceChildren(...opponents.map((player, index) => {
    const seat = document.createElement('button');
    seat.type = 'button';
    seat.className = 'seat seat-card';
    seat.dataset.pid = player.pid;
    seat.setAttribute('aria-haspopup', 'dialog');
    seat.classList.toggle('active-turn', d.current_turn_pid === player.pid);
    seat.classList.toggle('bankrupt', player.is_bankrupt);
    const status = player.is_bankrupt ? '破產'
      : d.current_turn_pid === player.pid ? '回合中'
      : d.transit?.current_target === player.pid ? '接收方'
      : player.is_locked ? '已鎖定' : '';
    const position = index === 0 ? '下家' : index === opponents.length - 1 ? '上家' : '';
    seat.innerHTML = `
      <span class="seat-avatar" aria-label="席位 ${d.order.indexOf(player.pid) + 1}">${d.order.indexOf(player.pid) + 1}</span>
      <span class="seat-card-main">
        <span class="seat-name">${esc(player.name)}</span>
        <span class="seat-role">${[player.role, position].filter(Boolean).map(esc).join(' · ')}</span>
      </span>
      <span class="seat-indicator">${status || '<span aria-hidden="true">›</span>'}</span>
      <span class="seat-stat-row">${seatStats(player)}</span>`;
    seat.onclick = () => {
      inspectedPid = player.pid;
      renderSeatDialog(player);
      seatDialog.showModal();
    };
    return seat;
  }));
  if (focusedPid) area.querySelector(`[data-pid="${CSS.escape(focusedPid)}"]`)?.focus({ preventScroll: true });
  if (seatDialog.open) {
    const player = opponents.find(opponent => opponent.pid === inspectedPid);
    if (player) renderSeatDialog(player);
    else seatDialog.close();
  }
}

function renderSeatDialog(player) {
  const skill = ROLE_SKILL_DESC[player.role];
  const task = ROLE_TASK_DESC[player.role];
  const identity = IDENTITY_INFO[player.identity];
  const secrets = player.secrets.map(card =>
    `<span class="secret-chip ${colorClass(card.color).replace('-card', '')}">${esc(card.name)}</span>`).join('');
  document.getElementById('seat-dialog-title').textContent = player.name;
  document.getElementById('seat-dialog-content').innerHTML = `
    <p class="seat-profile">${[player.role, identity?.label, player.is_bankrupt && '破產', player.is_locked && '已鎖定'].filter(Boolean).map(esc).join(' · ')}</p>
    <div class="seat-stat-row">${seatStats(player)}</div>
    ${skill ? `<h3>${skill.type === 'active' ? '主動技能' : '被動技能'}</h3><p>${esc(skill.desc)}</p>` : ''}
    ${task ? `<h3>角色任務</h3><p>${esc(task)}</p>` : ''}
    <h3>已接收機密</h3>
    <div class="seat-secret-list">${secrets || '<p class="empty-secrets">尚無機密</p>'}</div>`;
}

// ── SELF INFO CARD ─────────────────────────────────────────────────────────
function renderSelfInfo(d){
  const me = d.players.find(p=>p.pid===myPid);
  if(!me) return;
  const isActive = d.current_turn_pid === myPid;
  const wc = me.identity ? WIN_COND[me.identity] : null;
  const avatarColor = {board:'#3b82f6',vulture:'#ef4444',independent:'#f0c040'}[me.identity]||'#3b82f6';

  const card = document.getElementById('self-info-card');
  if(card){
    card.dataset.pid = me.pid;
    card.classList.toggle('is-my-turn', isActive);
    if(!isActive) card.style.borderLeftColor = avatarColor;
    else card.style.borderLeftColor = '';
  }

  const orderIdx = (d.order||[]).indexOf(me.pid);
  const turnNum = orderIdx >= 0 ? orderIdx + 1 : '?';
  const avatarEl = document.getElementById('self-avatar');
  if(avatarEl){
    avatarEl.textContent = turnNum;
    avatarEl.style.background = avatarColor+'22';
    avatarEl.style.color = avatarColor;
    avatarEl.style.borderColor = avatarColor;
  }
  const nameEl = document.getElementById('self-name');
  if(nameEl) nameEl.textContent = me.name;

  const identEl = document.getElementById('self-identity-row');
  if(identEl){
    identEl.innerHTML = wc
      ? `<span class="identity-pill identity-${me.identity}">${wc.label}</span>` + (me.role ? ` <span>${esc(me.role)}</span>` : '')
      : esc(me.role);
  }

  const statEl = document.getElementById('self-stat-row');
  if(statEl) statEl.innerHTML=`
    <span class="seat-stat blue">藍 <b>${me.blue}</b></span>
    <span class="seat-stat red">紅 <b>${me.red}</b></span>
    <span class="seat-stat black">黑 <b>${me.black}</b></span>`;

  const progEl = document.getElementById('self-progress-row');
  if(progEl){
    const pt = wc ? `${wc.desc} · ${_winProgress(me)}` : '';
    progEl.textContent = pt;
    progEl.style.display = pt ? 'block' : 'none';
  }

  // Update secrets as dimmed cards
  const chips = document.getElementById('self-secrets-chips');
  if(chips){
    if(me.secrets && me.secrets.length){
      chips.innerHTML = me.secrets.map(c=>{
        const colorCls = colorClass(c.color);
        const txIcon = {encrypted:'🔒',public:'📢',private:'✉️'}[c.transmit]||'';
        return `<div class="card ${colorCls} sec" onclick="selectSecretToDestroy('${esc(me.pid)}','${esc(c.iid||'')}')" title="${esc(c.name)}">
          <div class="card-banner">
            <span class="card-banner-icon">${txIcon}</span>
          </div>
          <div class="card-body">
            <div class="card-name">${esc(c.name)}</div>
            ${c.desc?`<hr class="card-divider"><div class="card-desc">${esc(c.desc)}</div>`:''}
          </div>
        </div>`;
      }).join('');
    } else {
      chips.innerHTML = '<span class="empty-secrets">無機密</span>';
    }
  }

  // Secrets summary (count by color)
  const sumEl = document.getElementById('self-secrets-summary');
  if(sumEl && me.secrets && me.secrets.length){
    const cnt = {blue:0,red:0,black:0,dual:0};
    me.secrets.forEach(s=>{ const k=s.color==='dual'?'dual':s.color; if(cnt[k]!==undefined) cnt[k]++; });
    sumEl.style.display='flex';
    sumEl.innerHTML = [
      cnt.blue  ? `<span class="seat-stat blue">藍 <b>${cnt.blue}</b></span>` :'',
      cnt.red   ? `<span class="seat-stat red">紅 <b>${cnt.red}</b></span>`   :'',
      cnt.black ? `<span class="seat-stat black">黑 <b>${cnt.black}</b></span>`:'',
      cnt.dual  ? `<span class="seat-stat dual">雙色 <b>${cnt.dual}</b></span>` :'',
    ].join('');
  } else if(sumEl){ sumEl.style.display='none'; }

  // Skill + task description in self-info-card
  const skillInfoEl = document.getElementById('self-skill-info');
  const taskInfoEl  = document.getElementById('self-task-info');
  if(me.role){
    const sk = ROLE_SKILL_DESC[me.role];
    if(skillInfoEl && sk){
      skillInfoEl.style.display = 'block';
      skillInfoEl.innerHTML =
        `<span class="skill-type-lbl ${sk.type}">${sk.type==='active'?'主動技能':'被動技能'}</span>`+
        `<div class="skill-body">${esc(sk.desc)}</div>`;
    }
    if(taskInfoEl && me.identity === 'independent'){
      const taskDesc = ROLE_TASK_DESC[me.role] || '';
      const hint = _roleTaskHint(me.role, me.role_task_progress||{});
      const done = me.role_task_done;
      taskInfoEl.style.display = 'block';
      taskInfoEl.innerHTML =
        `<span class="task-lbl">角色任務${done?' ✓':''}</span>`+
        `<div class="task-body">${esc(taskDesc)}</div>`+
        (hint ? `<div class="task-prog">${esc(hint)}</div>` : '');
    } else if(taskInfoEl){ taskInfoEl.style.display='none'; }
  } else {
    if(skillInfoEl) skillInfoEl.style.display='none';
    if(taskInfoEl)  taskInfoEl.style.display='none';
  }

  // Locked indicator
  let lockEl = document.getElementById('self-info-card')?.querySelector('.self-lock-indicator');
  if(me.is_locked && !lockEl){
    lockEl = document.createElement('div');
    lockEl.className = 'self-lock-indicator';
    lockEl.style.cssText = 'font-size:.64rem;color:#c4b5fd;background:#1e1040;border:1px solid #7c3aed;border-radius:4px;padding:1px 6px;margin-top:3px;display:inline-block';
    lockEl.textContent = '🔒 被鎖定中';
    document.getElementById('self-info-card')?.appendChild(lockEl);
  } else if(!me.is_locked && lockEl){
    lockEl.remove();
  }
}

// ── LOG TOGGLE ─────────────────────────────────────────────────────────────
function toggleLog(){
  const open = document.getElementById('log-panel').classList.toggle('open');
  const toggle = document.getElementById('log-toggle-btn');
  toggle.setAttribute('aria-expanded', String(open));
  (open ? document.getElementById('log-panel-close') : toggle).focus();
}

function renderTableTransit(d){
  const tableArea = document.getElementById('table-area');
  const inner = document.getElementById('table-inner');
  if(!tableArea||!inner) return;

  document.getElementById('board-stage').classList.toggle('has-transit', Boolean(d.transit));
  if(!d.transit){
    tableArea.classList.remove('my-decision');
    _clearDecisionTimer();
    const active = d.players.find(player => player.pid === d.current_turn_pid);
    const choosing = d.phase === 'choose_card' && d.current_turn_pid === myPid;
    const discarding = d.phase === 'discard' && d.current_turn_pid === myPid;
    const title = choosing ? '輪到你傳出機密' : discarding ? '請選擇要棄置的手牌' : '等待機密傳遞';
    inner.innerHTML = `
      <span class="table-emblem" aria-hidden="true"></span>
      <h2 id="table-idle">${title}</h2>
      <p id="table-meta">${choosing || discarding ? '' : esc(active?.name || '') + ' 的回合'}</p>`;
    return;
  }

  const t = d.transit;
  const cardCls = t.card.color==='unknown'?'unknown':t.card.color;
  const cardName = cardCls === 'unknown' ? '未公開機密' : t.card.name;
  const modeLabel = {encrypted:'加密雲端',public:'公開新聞稿',private:'私函'}[t.mode]||t.mode;
  const win = d.response_window;
  const isMyDecision = d.phase==='in_transit' && win && win.wtype==='pre_receive'
    && t.current_target===myPid && win.waiting_for.includes(myPid);

  if(isMyDecision){
    tableArea.classList.add('my-decision');
    _startDecisionTimer(win.fid);
    inner.innerHTML=`
      <p class="table-state">機密傳到你了</p>
      <h2 class="tcard ${cardCls}">${esc(cardName)}</h2>
      <div id="table-meta">${modeLabel} · 來自 <b>${esc(t.sender_name)}</b></div>
      <div id="table-timer"></div>
      <div id="table-actions"></div>`;
    _renderTimer();
    const actEl = document.getElementById('table-actions');
    actEl.appendChild(btn('接收','btn-sm btn-accept',()=>{_clearDecisionTimer();SFX.play('accept');socket.emit('accept',{});}));
    if(canRefuseTransit(d)){
      actEl.appendChild(btn('拒收','btn-sm btn-refuse',()=>{_clearDecisionTimer();SFX.play('refuse');socket.emit('refuse',{});}));
    }
  } else {
    tableArea.classList.remove('my-decision');
    if(_timerFid && (!win || _timerFid !== win.fid)) _clearDecisionTimer();
    inner.innerHTML=`
      <p class="table-state">機密傳遞中</p>
      <h2 class="tcard ${cardCls}">${esc(cardName)}</h2>
      <div id="table-meta">${modeLabel}<br>${esc(t.sender_name)} → ${esc(t.current_target_name)}</div>`;
  }
}

let _handFP = '';
function renderHand(d){
  const me=d.players.find(p=>p.pid===myPid);
  if(!me||!me.hand) return;
  const fp = JSON.stringify(me.hand.map(c=>c.iid+c.name)) +
    me.role + (me.role_used?1:0) + (me.role_task_done?1:0) +
    JSON.stringify(me.role_task_progress||{}) + d.current_turn_pid +
    d.phase + JSON.stringify([selectedCardIid, discardSelected]);
  const cards=document.getElementById('hand-cards');
  const countEl=document.getElementById('hand-count');
  const handLimit = me.hand_limit;
  countEl.textContent=`（${me.hand.length}/${handLimit}）`;
  if(fp === _handFP) return;
  _handFP = fp;
  const scrollLeft = cards.scrollLeft;
  const focusedIid = document.activeElement?.dataset.iid;
  cards.innerHTML='';

  // Role badge + skill button
  const skillRow = document.getElementById('role-skill-row');
  const skillBtn = document.getElementById('role-skill-btn');
  const taskHint = document.getElementById('role-task-hint');
  if(me.role){
    const used = me.role_used;
    const ACTIVE_ROLES = ['企業間諜','雙面公關','財務稽核','白衣騎士','數據掮客'];
    const isActive = ACTIVE_ROLES.includes(me.role);
    const isMyTurn = d.current_turn_pid === myPid;
    const canUse = isActive && !me.role_task_done && (
      me.role === '企業間諜' || me.role === '雙面公關' ? !used :
      me.role === '數據掮客' ? isMyTurn && !me.role_state?.cycle_used_this_turn :
      isMyTurn && !used
    );
    skillRow.style.display = isActive ? 'flex' : 'none';
    skillBtn.disabled = !canUse;
    skillBtn.title = me.role_used && me.role!=='數據掮客' ? '技能已使用' : '';
    // Task hint
    const prog = me.role_task_progress || {};
    taskHint.textContent = _roleTaskHint(me.role, prog);
  } else {
    skillRow.style.display = 'none';
  }

  const COLOR_NAME = { blue: '藍色', red: '紅色', black: '黑色', dual: '雙色' };
  const TX_LABEL = { encrypted: '加密', public: '公開', private: '私函' };
  me.hand.forEach(c=>{
    const div=document.createElement('div');
    const cls=colorClass(c.color);
    const isSelected=selectedCardIid===c.iid;
    const isDiscardSel=discardSelected.includes(c.iid);
    div.className=`card hand-card ${cls}${isSelected||isDiscardSel?' selected':''}`;
    div.tabIndex = 0;
    div.setAttribute('role', 'button');
    div.dataset.iid = c.iid;
    if (discardMode) div.setAttribute('aria-pressed', String(isDiscardSel));
    const txBadge=TX_LABEL[c.transmit]||'';
    const descHtml=c.desc?`<hr class="card-divider"><div class="card-desc">${esc(c.desc)}</div>`:'';
    div.innerHTML=`
      <div class="card-banner">
        <span class="hand-card-color">${COLOR_NAME[c.color] || '功能'}</span>
        ${txBadge?`<span class="card-tx-badge">${txBadge}</span>`:''}
      </div>
      <div class="card-body">
        <div class="card-name">${esc(c.name)}</div>
        ${descHtml}
      </div>
    `;
    div.onclick = () => onCardClick(c);
    div.onkeydown = event => {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        onCardClick(c);
      }
    };
    cards.appendChild(div);
    if (focusedIid === c.iid) div.focus({ preventScroll: true });
  });
  cards.scrollLeft = scrollLeft;
  const discardBtn = document.getElementById('confirm-discard-btn');
  const needed = me.hand.length - handLimit;
  discardBtn.hidden = !discardMode;
  discardBtn.disabled = discardSelected.length !== needed;
  discardBtn.textContent = `確認棄牌（已選 ${discardSelected.length}/${needed}）`;
}

function onCardClick(c){
  if(discardMode){
    const idx=discardSelected.indexOf(c.iid);
    if(idx>=0) discardSelected.splice(idx,1);
    else discardSelected.push(c.iid);
    renderHand(state);
    return;
  }
  const hasFunc = !!c.func;
  if(state.phase==='choose_card' && state.current_turn_pid===myPid){
    selectedCardIid=c.iid;
    renderHand(state);
    if(hasFunc) showCardActionDialog(c);
    else askTransmit(c);
    return;
  }
  if(hasFunc){
    selectedCardIid=c.iid;
    renderHand(state);
    askPlayFunction(c);
  }
}

function showCardActionDialog(card){
  const modeLabel={encrypted:'加密雲端',public:'公開新聞稿',private:'私人信件'};
  document.getElementById('extra-title').textContent = card.name;
  document.getElementById('extra-content').innerHTML=`
    <p style="margin-bottom:8px;font-size:.83rem">傳遞方式：<b>${modeLabel[card.transmit]||card.transmit}</b></p>
    <p style="margin-bottom:16px;font-size:.83rem;color:#c4b5fd">功能：${esc(card.desc||card.func)}</p>
    <div style="display:flex;gap:10px">
      <button id="action-transmit" class="btn-sm btn-transmit" style="flex:1;padding:9px">📤 傳出機密</button>
      <button id="action-func" class="btn-sm btn-play" style="flex:1;padding:9px">⚡ 使用功能</button>
    </div>
  `;
  extraCardIid=card.iid;
  extraCallback=null;
  document.getElementById('extra-overlay').style.display='flex';
  const transmit = document.getElementById('action-transmit');
  const forced = state.players.find(p => p.pid === myPid)?.forced_transmit_color;
  transmit.disabled = Boolean(forced && card.color !== forced);
  transmit.onclick = () => { closeExtra(); askTransmit(card); };
  document.getElementById('action-func').onclick=()=>{ closeExtra(); askPlayFunction(card); };
}

function askTransmit(card){
  const modeLabel={encrypted:'加密雲端（面朝下往右傳）',public:'公開新聞稿（面朝上往右傳）',private:'私人信件（指定玩家）'};
  const mode=card.transmit;
  if(mode==='private'){
    showExtraTransmitPrivate(card);
  } else {
    if(confirm(`確認傳出「${card.name}」？\n方式：${modeLabel[mode]}`)){
      socket.emit('transmit',{card_iid:card.iid});
      selectedCardIid=null;
    }
  }
}

function showExtraTransmitPrivate(card){
  const others=state.players.filter(p=>p.pid!==myPid&&!p.is_bankrupt);
  document.getElementById('extra-title').textContent='私人信件 — 選擇目標';
  document.getElementById('extra-content').innerHTML=`
    <label>選擇收件人：</label>
    <select id="extra-target">${others.map(p=>`<option value="${p.pid}">${esc(p.name)}</option>`).join('')}</select>
  `;
  extraCardIid=card.iid;
  extraCallback=()=>{
    const target=document.getElementById('extra-target').value;
    socket.emit('transmit',{card_iid:card.iid,target_pid:target});
    selectedCardIid=null;
    closeExtra();
  };
  document.getElementById('extra-overlay').style.display='flex';
}

function askPlayFunction(card){
  socket.emit('play_function',{card_iid:card.iid});
  selectedCardIid=null;
  renderHand(state);
}

function confirmDiscard(){
  const me=state.players.find(p=>p.pid===myPid);
  if(!me) return;
  const needed=me.hand.length-me.hand_limit;
  if(discardSelected.length!==needed){
    showError(`需要選擇 ${needed} 張牌棄置`);
    return;
  }
  socket.emit('discard',{card_iids:discardSelected});
}

function selectSecretToDestroy(pid, iid){
  if(!state) return;
  const me=state.players.find(p=>p.pid===myPid);
  if(!me) return;
  const destroyCard=me.hand.find(c=>c.name==='銷毀帳冊');
  if(!destroyCard) return;
  if(!confirm(`使用「銷毀帳冊」移除此有毒資產？`)) return;
  socket.emit('play_function',{card_iid:destroyCard.iid,extra:{target_pid:pid,target_iid:iid}});
}

function _setResponseVisible(visible){
  document.getElementById('response-overlay').classList.toggle('active', visible);
}

function renderResponseWindow(d){
  const win=d.response_window;
  const btns=document.getElementById('resp-btns');

  if(d.phase==='choose_card' && d.current_turn_pid===myPid){
    _setResponseVisible(true);
    _clearPassTimer();
    document.getElementById('resp-title').textContent='選牌傳出';
    const me = d.players.find(p => p.pid === myPid);
    const description = document.getElementById('resp-desc');
    btns.innerHTML='';
    if (me.can_skip_transmit) {
      description.textContent = me.hand.length ? '手中沒有符合內線交易要求的機密。' : '手中沒有可傳出的機密。';
      btns.appendChild(btn('跳過傳牌', 'btn-sm btn-pass', () => socket.emit('skip_transmit', {})));
    } else if (me.forced_transmit_color) {
      description.textContent = `內線交易要求傳出${colorLabel(me.forced_transmit_color)}機密。`;
    } else {
      description.textContent = '選一張手牌傳出，也可以先使用功能牌。';
    }
    return;
  }

  if(!win || d.phase==='game_over'){
    _setResponseVisible(false);
    _clearPassTimer();
    return;
  }

  const inWaiting=win.waiting_for.includes(myPid);
  if(!inWaiting){ _setResponseVisible(false); _clearPassTimer(); return; }

  if(win.wtype==='pre_receive'){
    if(win.target===myPid){ _setResponseVisible(false); _clearPassTimer(); return; }
    _setResponseVisible(true);
    _startPassTimer(win.fid);
    const targetName=d.players.find(p=>p.pid===win.target)?.name||'?';
    document.getElementById('resp-title').textContent='接收響應';
    document.getElementById('resp-desc').textContent=`${targetName} 選擇接收。可點手牌打出功能牌，或不響應。`;
    btns.innerHTML='';
    btns.appendChild(btn('不響應','btn-sm btn-pass',()=>{_clearPassTimer();socket.emit('pass_response',{});}));
    return;
  }

  if(win.wtype==='pre_transmit'){
    _setResponseVisible(true);
    _startPassTimer(win.fid);
    const triggeredName=d.players.find(p=>p.pid===win.triggered_by)?.name||'?';
    document.getElementById('resp-title').textContent='傳出宣言';
    document.getElementById('resp-desc').textContent=`${triggeredName} 即將傳出。可點手牌打出功能牌，或不響應。`;
    btns.innerHTML='';
    btns.appendChild(btn('不響應','btn-sm btn-pass',()=>{_clearPassTimer();socket.emit('pass_response',{});}));
    return;
  }

  _setResponseVisible(false);
  _clearPassTimer();
}

let lastLogSequence = 0;
function renderLog(d){
  const log = document.getElementById('log-area');
  const sequence = d.log_seq ?? d.log.length;
  const newCount = Math.min(sequence - lastLogSequence, d.log.length);
  if (newCount <= 0) return;
  const latest = d.log.slice(-newCount);
  if (latest.some(message => message.startsWith('⚡'))) SFX.play('func');
  lastLogSequence = sequence;
  log.replaceChildren(...d.log.map(msg => {
    const div=document.createElement('div');
    let cls='log-entry';
    if(msg.startsWith('🏆')) cls+=' log-win';
    else if(msg.startsWith('💀')) cls+=' log-bankrupt';
    else if(msg.startsWith('⚡')) cls+=' log-func';
    else if(msg.startsWith('✅')) cls+=' log-receive';
    else if(msg.startsWith('──')) cls+=' log-turn';
    div.className=cls;
    div.textContent=msg;
    return div;
  }));
  log.scrollTop=log.scrollHeight;
}

function renderStatus(d){
  const phaseNames = {
    turn_draw: '抽牌', pre_transmit: '傳出宣言', choose_card: '選牌傳出',
    in_transit: '機密傳遞', pre_receive: '接收響應', discard: '棄牌', game_over: '遊戲結束'
  };
  document.getElementById('phase-label').textContent = phaseNames[d.phase] || d.phase;
  const current = d.players.find(player => player.pid === d.current_turn_pid);
  document.getElementById('turn-label').textContent = current
    ? current.pid === myPid ? '你的回合' : `${current.name}的回合` : '';
  document.getElementById('deck-info').textContent = `牌庫 ${d.deck_count} · 棄牌 ${d.discard_count}`;

  discardMode = d.phase === 'discard' && d.current_turn_pid === myPid;
  if (!discardMode) discardSelected = [];
}

// ── Extra dialog ──────────────────────────────────────────────────────────

function showExtraDialog(d){
  const r=d.result||{};

  if(r.view_hand){ showViewHand(r.view_hand); return; }
  if(r.view_secrets){ showViewSecrets(r.view_secrets); return; }
  if(r.need_hand_swap){ showHandSwap(r.need_hand_swap); return; }
  if(r.need_color){ showColorPicker(r.need_color); return; }

  if(r.need_target){
    const others=state.players.filter(p=>p.pid!==myPid&&!p.is_bankrupt);
    document.getElementById('extra-title').textContent=r.need_target;
    document.getElementById('extra-content').innerHTML=`
      <label>選擇目標玩家：</label>
      <select id="extra-target">${others.map(p=>`<option value="${p.pid}">${esc(p.name)}</option>`).join('')}</select>
    `;
    extraCallback=()=>{
      const target=document.getElementById('extra-target').value;
      socket.emit('play_function',{card_iid:extraCardIid,extra:{target_pid:target}});
      closeExtra();
    };
    document.getElementById('extra-overlay').style.display='flex';
    return;
  }

  if(r.need_swap){
    const hand = r.need_swap.my_hand || [];
    document.getElementById('extra-title').textContent='偷天換日 — 選擇替換的牌';
    document.getElementById('extra-content').innerHTML=`
      <p style="font-size:.81rem;margin-bottom:8px">選一張手牌換入傳遞中的機密，改以公開新聞稿重新傳遞：</p>
      <select id="extra-swap-sel">
        ${hand.map(c=>`<option value="${c.iid}">${esc(c.name)}（${colorLabel(c.color)}）</option>`).join('')}
      </select>
    `;
    extraCallback=()=>{
      const iid=document.getElementById('extra-swap-sel').value;
      socket.emit('play_function',{card_iid:extraCardIid,extra:{swap_iid:iid}});
      extraCardIid=null;
      closeExtra();
    };
    document.getElementById('extra-overlay').style.display='flex';
    return;
  }

  if(r.need_new_target){
    const targetPids=r.need_new_target;
    const targets=state.players.filter(p=>targetPids.includes(p.pid)&&!p.is_bankrupt);
    document.getElementById('extra-title').textContent='惡意帶風向 — 選擇新目標';
    document.getElementById('extra-content').innerHTML=`
      <p style="font-size:.81rem;margin-bottom:8px">強制將傳遞中的機密改傳至：</p>
      <select id="extra-newtarget-sel">
        ${targets.map(p=>`<option value="${p.pid}">${esc(p.name)}</option>`).join('')}
      </select>
    `;
    extraCallback=()=>{
      const target=document.getElementById('extra-newtarget-sel').value;
      socket.emit('play_function',{card_iid:extraCardIid,extra:{new_target:target}});
      extraCardIid=null;
      closeExtra();
    };
    document.getElementById('extra-overlay').style.display='flex';
    return;
  }

  if(r.need_destroy_target){
    showDestroyDialog();
    return;
  }

  document.getElementById('extra-title').textContent='需要額外資訊';
  document.getElementById('extra-content').innerHTML=`<p>未知操作</p>`;
  document.getElementById('extra-overlay').style.display='flex';
}

function showViewHand(data){
  const name=state.players.find(p=>p.pid===data.pid)?.name||data.pid;
  let html=`<b style="color:var(--text)">${esc(name)}</b> 的手牌：<br><br>`;
  data.hand.forEach(c=>{
    html+=`<span class="badge" style="margin:2px;background:var(--surface2)">${esc(c.name)}（${colorLabel(c.color)}）</span>`;
  });
  if(extraCardIid){
    html+=`<br><br><label>選擇強制棄置的牌：</label>
    <select id="extra-iid-sel">${data.hand.map(c=>`<option value="${c.iid}">${esc(c.name)}</option>`).join('')}</select>`;
    extraCallback=()=>{
      const iid=document.getElementById('extra-iid-sel').value;
      socket.emit('play_function',{card_iid:extraCardIid,extra:{target_pid:data.pid,discard_iid:iid}});
      extraCardIid=null;
      closeExtra();
    };
  }
  document.getElementById('extra-title').textContent='檢視手牌';
  document.getElementById('extra-content').innerHTML=html;
  document.getElementById('extra-overlay').style.display='flex';
}

function showViewSecrets(data){
  const name=state.players.find(p=>p.pid===data.pid)?.name||data.pid;
  let html=`<b style="color:var(--text)">${esc(name)}</b> 已接收的機密：<br><br>`;
  if(!data.secrets.length){
    html+='<span style="color:var(--text-muted)">（尚無機密）</span>';
  }
  data.secrets.forEach(c=>{
    html+=`<span class="badge" style="margin:2px;background:var(--surface2)">${esc(c.name)}（${colorLabel(c.color)}）</span>`;
  });
  document.getElementById('extra-title').textContent='盡職調查結果';
  document.getElementById('extra-content').innerHTML=html;
  extraCallback=null;
  document.getElementById('extra-overlay').style.display='flex';
}

function showHandSwap(data){
  const targetOpts=data.players.map(p=>`<option value="${p.pid}">${esc(p.name)}</option>`).join('');
  const giveOpts=data.my_hand.map(c=>`<option value="${c.iid}">${esc(c.name)}（${colorLabel(c.color)}）</option>`).join('');
  document.getElementById('extra-title').textContent='公開財報 — 手牌互換';
  document.getElementById('extra-content').innerHTML=`
    <label>選擇交換對象：</label>
    <select id="swap-target">${targetOpts}</select>
    <label style="margin-top:10px;display:block">選擇給出的牌：</label>
    <select id="swap-give">${giveOpts}</select>
    <p style="font-size:.78rem;color:var(--text-muted);margin-top:8px">對方將隨機給你一張手牌</p>
  `;
  extraCallback=()=>{
    const target=document.getElementById('swap-target').value;
    const give_iid=document.getElementById('swap-give').value;
    socket.emit('play_function',{card_iid:extraCardIid,extra:{target_pid:target,give_iid:give_iid}});
    extraCardIid=null;
    closeExtra();
  };
  document.getElementById('extra-overlay').style.display='flex';
}

function showColorPicker(data){
  const COLOR_OPTS = [
    {value:'blue',  label:'藍色機密'},
    {value:'red',   label:'紅色機密'},
    {value:'black', label:'黑色·有毒'},
    {value:'dual',  label:'雙色核心'},
  ].filter(o=>data.colors.includes(o.value));
  document.getElementById('extra-title').textContent='內線交易 — 指定顏色';
  document.getElementById('extra-content').innerHTML=`
    <p style="font-size:.81rem;margin-bottom:10px">
      要求 <b style="color:var(--text)">${esc(data.target_name)}</b> 必須傳出指定顏色，否則公開手牌：
    </p>
    <select id="color-sel">
      ${COLOR_OPTS.map(o=>`<option value="${o.value}">${o.label}</option>`).join('')}
    </select>
  `;
  extraCallback=()=>{
    const color=document.getElementById('color-sel').value;
    socket.emit('play_function',{card_iid:extraCardIid,extra:{color}});
    extraCardIid=null;
    closeExtra();
  };
  document.getElementById('extra-overlay').style.display='flex';
}

function showDestroyDialog(){
  // 自己也可以成為目標（銷毀自己的黑牌）
  _destroyTargets=state.players.filter(p=>!p.is_bankrupt&&p.black>0);
  if(!_destroyTargets.length){ showError('場上沒有可銷毀的有毒資產'); return; }
  const firstSecrets=_destroyTargets[0].secrets.filter(s=>s.color==='black');
  document.getElementById('extra-title').textContent='銷毀帳冊 — 選擇目標';
  document.getElementById('extra-content').innerHTML=`
    <label>目標玩家：</label>
    <select id="extra-target" onchange="updateDestroySecrets()">
      ${_destroyTargets.map(p=>`<option value="${p.pid}">${esc(p.name)}${p.pid===myPid?' (我)':''}</option>`).join('')}
    </select>
    <label style="margin-top:10px;display:block">選擇有毒資產：</label>
    <select id="extra-iid">
      ${firstSecrets.map(s=>`<option value="${s.iid}">${esc(s.name)}</option>`).join('')}
    </select>
  `;
  extraCallback=()=>{
    const tp=document.getElementById('extra-target').value;
    const iid=document.getElementById('extra-iid').value;
    socket.emit('play_function',{card_iid:extraCardIid,extra:{target_pid:tp,target_iid:iid}});
    closeExtra();
  };
  document.getElementById('extra-overlay').style.display='flex';
}

function updateDestroySecrets(){
  const pid=document.getElementById('extra-target')?.value;
  const tgt=_destroyTargets.find(p=>p.pid===pid);
  const secrets=tgt?tgt.secrets.filter(s=>s.color==='black'):[];
  const sel=document.getElementById('extra-iid');
  if(!sel) return;
  sel.innerHTML=secrets.map(s=>`<option value="${s.iid}">${esc(s.name)}</option>`).join('');
}

function submitExtra(){
  if(extraCallback) extraCallback();
  else closeExtra();
}

function cancelExtra(){
  extraCardIid=null;
  extraCallback=null;
  closeExtra();
}

function closeExtra(){
  document.getElementById('extra-overlay').style.display='none';
  extraCallback=null;
}

// ── Game over ─────────────────────────────────────────────────────────────

function showGameOver(d){
  document.getElementById('gameover-overlay').style.display='flex';
  document.getElementById('gameover-reason').textContent=d.win_reason||'遊戲結束';

  const IDENTITY_LABEL = {board:'董事會',vulture:'禿鷹基金',independent:'獨立投資人'};
  const IDENTITY_CLASS = {board:'go-id-board',vulture:'go-id-vulture',independent:'go-id-indie'};
  const winnerSet = new Set(d.winner_pids||[]);

  const container = document.getElementById('gameover-players');
  container.innerHTML = (d.players||[]).map(p=>{
    const isWinner = winnerSet.has(p.pid);
    const identLabel = IDENTITY_LABEL[p.identity]||'?';
    const identClass = IDENTITY_CLASS[p.identity]||'';
    const crown = isWinner ? '<div class="go-player-crown">👑</div>' : '';
    const bankruptBadge = p.is_bankrupt ? ' <span style="color:#f87171;font-size:.72rem">💀 破產</span>' : '';
    const taskBadge = (p.role && p.role_task_done != null)
      ? `<div class="go-task ${p.role_task_done?'done':'fail'}">${p.role_task_done?'✓ 任務完成':'✗ 任務未完成'}</div>` : '';
    return `<div class="go-player${isWinner?' winner':''}${p.is_bankrupt?' bankrupt':''}">
      ${crown}
      <div class="go-player-name">${esc(p.name)}${bankruptBadge}</div>
      <div><span class="go-player-identity ${identClass}">${identLabel}</span></div>
      <div class="go-player-role">🎭 ${esc(p.role||'—')}</div>
      <div class="go-player-stats">
        <span class="go-stat"><span style="color:#93c5fd">🔵</span>${p.blue}</span>
        <span class="go-stat"><span style="color:#fca5a5">🔴</span>${p.red}</span>
        <span class="go-stat"><span style="color:#9ca3af">⚫</span>${p.black}</span>
      </div>
      ${taskBadge}
    </div>`;
  }).join('');

  document.getElementById('btn-restart').style.display = d.host_pid === myPid ? 'inline-block' : 'none';
}

function restartGame(){
  document.getElementById('gameover-error').textContent = '';
  _shownHints.clear();
  _hintQueue = [];
  _hintActive = false;
  _lastHintId = null;
  socket.emit('restart_game',{});
}

// ── 聊天 ─────────────────────────────────────────────────────────────────

function sendChat(){
  const input=document.getElementById('chat-input');
  const msg=input.value.trim();
  if(!msg) return;
  socket.emit('chat',{msg});
  input.value='';
}

let _emojiCooldown = false;
function sendEmoji(emoji){
  if(_emojiCooldown) return;
  _emojiCooldown = true;
  setTimeout(()=>_emojiCooldown=false, 1500);
  socket.emit('emoji_reaction',{emoji});
}

function _showEmojiFloat(pid, emoji){
  const row = document.querySelector(`[data-pid="${CSS.escape(pid)}"]`) || document.getElementById('seats-area');
  const anchor = row;
  const rect = anchor.getBoundingClientRect();
  const el = document.createElement('div');
  el.className = 'emoji-float';
  el.textContent = emoji;
  el.style.left = (rect.left + rect.width/2 - 16) + 'px';
  el.style.top  = (rect.top + rect.height/2) + 'px';
  document.body.appendChild(el);
  setTimeout(()=> el.remove(), 1500);
}

socket.on('emoji_reaction', d=>{
  _showEmojiFloat(d.pid, d.emoji);
  // 也在聊天區顯示一行
  const log = document.getElementById('chat-log');
  const div = document.createElement('div');
  div.className = 'chat-msg';
  div.innerHTML = `<span class="cn">${esc(d.name)}</span>：${esc(d.emoji)}`;
  log.appendChild(div);
  log.scrollTop = log.scrollHeight;
});

// ── 工具函式 ──────────────────────────────────────────────────────────────

function btn(label, cls, onClick){
  const b=document.createElement('button');
  b.className='btn-sm '+cls;
  b.textContent=label;
  b.onclick=onClick;
  return b;
}

function showError(msg){
  if (document.getElementById('lobby').style.display === 'flex') return showLobbyError(msg);
  if (state?.phase?.startsWith('draft_')) {
    const screen = state.phase === 'draft_identity' ? 'draft-screen' : 'role-draft-screen';
    document.querySelector(`#${screen} .draft-error`).textContent = msg;
    return;
  }
  if (state?.phase === 'game_over') {
    document.getElementById('gameover-error').textContent = msg;
    return;
  }
  const el=document.getElementById('error-toast');
  if(!el) return;
  el.textContent=msg;
  setTimeout(()=>el.textContent='',4000);
}

function esc(s){
  return String(s ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function colorLabel(c){
  return {blue:'藍色',red:'紅色',black:'黑色·有毒',dual:'雙色核心',none:'功能牌'}[c]||c;
}

function colorClass(color){
  return {blue:'blue-card',red:'red-card',black:'black-card',dual:'dual-card'}[color]||'func-card';
}

function identityLabel(id){
  return {board:'董事會',vulture:'禿鷹基金',independent:'獨立投資人'}[id]||id;
}
