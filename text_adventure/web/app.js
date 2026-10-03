/* 封城第七天 · 按钮版前端
   所有按钮最终都翻译成一句玩家指令（data-cmd），发给 /api/command 由引擎处理。
   角色创建走 /api/new → /api/answer 的一问一答。

   界面区域命名（写代码/改布局时按名字找，约定见 ../界面区域.md）：
     左侧栏 / 视图栏 / 技能栏 / 快捷区域1 / 快捷区域2 / 右侧栏
   本文件里 左侧栏 = #char-body，视图栏 = #scene-body + #bag-panel + #skill-panel
   （右上角三个页签：场景 / 背包 / 技能树，同一时刻只显示一个；
    场景这一页并排三块：左边一列地图、中间格子场景、右边一列时钟（左右两列等宽，场景才是正中的），
    点格子上的物品 / 人物弹小菜单，颜色图例在视图栏最下面一条），
   技能栏 = #skill-slots-body（10 页 × 9 格，拖入登记 / 点一下释放 / 拖出取消），
   快捷区域1 = #equip-body（装备栏，拖动装备），
   快捷区域2 = #log（文字记录）+ #cmd-form（指令输入），右侧栏 = #action-body。 */
(function () {
  'use strict';

  var el = {
    menu: document.getElementById('screen-menu'),
    create: document.getElementById('screen-create'),
    play: document.getElementById('screen-play'),
    exit: document.getElementById('screen-exit'),
    exitText: document.getElementById('exit-text'),
    exitHint: document.getElementById('exit-hint'),
    exitClose: document.getElementById('exit-close'),
    menuExit: document.getElementById('menu-exit'),
    menuHint: document.getElementById('menu-hint'),
    createLog: document.getElementById('create-log'),
    createPrompt: document.getElementById('create-prompt'),
    createSteps: document.getElementById('create-steps'),
    log: document.getElementById('log'),
    roomName: document.getElementById('room-name'),
    roomSub: document.getElementById('room-sub'),
    roomBar: document.getElementById('room-bar'),          // 视图栏顶部那条（房间信息 / 对话框）
    talkBanner: document.getElementById('talk-banner'),    // 说话时占着这条：显示当前这一句
    talkSpeaker: document.getElementById('talk-speaker'),
    talkText: document.getElementById('talk-text'),
    talkHint: document.getElementById('talk-hint'),
    charBody: document.getElementById('char-body'),   // 左侧栏
    actionBody: document.getElementById('action-body'),  // 右侧栏
    sceneBody: document.getElementById('scene-body'),  // 视图栏（格子场景）
    bagPanel: document.getElementById('bag-panel'),    // 视图栏（背包页签）
    skillPanel: document.getElementById('skill-panel'), // 视图栏（技能树页签）
    viewTabs: document.getElementById('view-tabs'),    // 视图栏右上角 场景 / 背包 / 技能树
    viewMap: document.getElementById('view-map'),      // 场景左上角：区域地图（浮在场景上）
    mapArea: document.getElementById('map-area'),      // 地图标题：当前这一层的名字
    mapViewport: document.getElementById('map-viewport'),  // 地图的可视窗口（拖动平移、滚轮缩放）
    mapBody: document.getElementById('map-body'),      // 地图本体：方块 + 连线
    mapFloors: document.getElementById('map-floors'),  // 地图下面那条：切换楼层
    mapZoom: document.getElementById('map-zoom'),      // 地图标题上的缩放比例
    mapReset: document.getElementById('map-reset'),    // 地图标题上的「复位」
    scenePanel: document.getElementById('scene-panel'),  // 场景面板（地图和时钟都装在这里面）
    viewClock: document.getElementById('view-clock'),  // 场景右上角：时钟（固定）
    skillSlotsBody: document.getElementById('skill-slots-body'),  // 技能栏（10 页 × 9 格）
    slotPage: document.getElementById('slot-page'),               // 技能栏标题上的页码
    equipBody: document.getElementById('equip-body'),  // 快捷区域1（装备栏）
    equipGrip: document.getElementById('equip-grip'),  // 装备栏标题上的持握状态
    // 快捷区域1 / 快捷区域2：留空的预留位，以后往里塞东西时直接渲染到这两个容器
    quickZone1: document.getElementById('quick-zone-1'),
    quickZone2: document.getElementById('quick-zone-2'),
    cmdForm: document.getElementById('cmd-form'),
    cmdInput: document.getElementById('cmd-input'),
    modal: document.getElementById('modal'),
    modalTitle: document.getElementById('modal-title'),
    modalBody: document.getElementById('modal-body'),
    modalClose: document.getElementById('modal-close')
  };

  var busy = false;
  var answered = 0;
  var currentMode = 'menu';
  var lastChoices = 0;  // 当前问题有几个选项（用来支持按数字键快速选择）
  var toastTimer = null;
  var modalKind = null;  // 'skills' / 'confirm' / null
  var lastState = null;
  var saveMode = null;   // 存档盘上选中的动作：'save' / 'load' / 'clear'
  var restMinutes = 60;  // 休息滑条当前选的分钟数（重绘界面后要保留）
  var bagPage = 0;       // 背包面板当前第几页（从 0 开始）
  var itemMenuSid = null;  // 背包里点开的那一堆（弹出查看 / 使用 / 拆分…）
  var splitSid = null;     // 正在拆分的那一堆
  var thingMenuId = null;  // 场景里点开的那件东西（地上的物品 / 人物，弹出拿取 / 查看 / 说话）

  // 这一次打开页面的身份：心跳和每条请求都带着它，服务端据此知道“还有哪个页面在看”。
  // 关标签页时也用它报一声，所以关掉一个页面不会把另一个页面也结束掉。
  var PAGE_ID = 'p' + Date.now().toString(36) + Math.random().toString(36).slice(2, 8);

  // 界面用到的图标名，集中列在这里，方便和 web/icons.svg 对照检查
  var USED_ICONS = [
    'n', 's', 'e', 'w', 'up', 'down',
    'look', 'take', 'drop', 'bag', 'person', 'skills', 'map', 'stance', 'dice',
    'talk', 'save', 'load', 'help', 'exit', 'check', 'x', 'hp', 'weight',
    'equip', 'unequip', 'learn', 'plus', 'minus', 'clock', 'rest', 'use', 'item-generic',
    'split', 'stack'
  ];

  // world.json 里的方向 id 是 north/south/... 图标名是 n/s/...
  var DIR_ICON = { north: 'n', south: 's', east: 'e', west: 'w', up: 'up', down: 'down' };

  /* ---------- 小工具 ---------- */

  function esc(text) {
    return String(text === null || text === undefined ? '' : text)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  // 图标精灵是内联在页面里的，缺哪个图标就自动降级成不显示，不会出现空白方块
  function hasIcon(name) {
    return !!document.getElementById('i-' + name);
  }

  function icon(name) {
    if (!name || !hasIcon(name)) return '';
    return '<svg class="ico" aria-hidden="true"><use href="#i-' + name + '"></use></svg>';
  }

  // 物品 id 里的下划线换成连字符就是图标名（如 first_aid_kit → item-first-aid-kit）
  function itemIcon(itemId) {
    var name = 'item-' + String(itemId || '').replace(/_/g, '-');
    return icon(hasIcon(name) ? name : 'item-generic');
  }

  function btn(cmd, label, iconName, cls) {
    return '<button type="button" class="btn ' + (cls || '') + '" data-cmd="' + esc(cmd) + '">' +
      icon(iconName) + '<span>' + esc(label) + '</span></button>';
  }

  function fillBtn(prefix, label, iconName) {
    return '<button type="button" class="btn" data-fill="' + esc(prefix) + '">' +
      icon(iconName) + '<span>' + esc(label) + '</span></button>';
  }

  function modalBtn(kind, label, iconName, cls) {
    return '<button type="button" class="btn ' + (cls || '') + '" data-modal="' + esc(kind) + '">' +
      icon(iconName) + '<span>' + esc(label) + '</span></button>';
  }

  function show(name) {
    currentMode = name;
    el.menu.classList.toggle('hidden', name !== 'menu');
    el.create.classList.toggle('hidden', name !== 'create');
    el.play.classList.toggle('hidden', name !== 'play');
    el.exit.classList.toggle('hidden', name !== 'exit');
  }

  function clear(node) {
    while (node.firstChild) node.removeChild(node.firstChild);
  }

  function appendLines(node, lines) {
    if (!lines) return;
    for (var i = 0; i < lines.length; i++) {
      var text = lines[i];
      if (text === null || text === undefined) continue;
      var parts = String(text).split('\n');
      for (var j = 0; j < parts.length; j++) {
        var p = document.createElement('p');
        p.className = 'line';
        var body = parts[j];
        if (body.indexOf('> ') === 0) p.className += ' cmd';
        else if (/^【.*】$/.test(body.trim())) p.className += ' room';
        else if (/^(提示|（|注意)/.test(body.trim())) p.className += ' sys';
        p.textContent = body;
        node.appendChild(p);
      }
    }
    node.scrollTop = node.scrollHeight;
  }

  // 移动不在文字栏留痕：走一步就往文字栏丢一句“> 走 北”＋一格结果，问一句 / 走一步就刷一屏。
  // 走到哪儿看视图栏的场景图，走不通由浮层提示。这里把移动的回声和它那一段结果都滤掉。
  // 注意：直接敲方向（“东”“n”“north”）也是移动（engine.DIRECTIONS 那套），别漏掉。
  var MOVE_WORDS = ['走', '去', 'go'];
  var DIR_WORDS = ['北', '南', '东', '西', '上', '下',
                   'n', 's', 'e', 'w', 'u', 'd',
                   'north', 'south', 'east', 'west', 'up', 'down'];
  function isMoveLine(line) {
    var text = String(line || '').trim();
    if (text.indexOf('> ') === 0) text = text.slice(2).trim();
    if (!text) return false;
    var lower = text.toLowerCase();
    if (DIR_WORDS.indexOf(lower) >= 0) return true;          // 光敲一个方向
    if (lower.split(/\s+/)[0] === 'go') return true;
    for (var i = 0; i < MOVE_WORDS.length; i++) {
      if (text.indexOf(MOVE_WORDS[i]) === 0) return true;    // 走 北 / 去 东
    }
    return false;
  }

  // 文字栏只收真正的反馈：移动结果和台词都不往里写
  // （台词由视图栏的对话框显示，服务端也不会把这些行下发到 lines 里）
  function logLines(lines) {
    if (!lines) return [];
    var out = [];
    for (var i = 0; i < lines.length; i++) {
      if (isMoveLine(lines[i])) {
        // 这一段后面紧跟着的是走路结果（【新地点】和描写），一起跳过
        while (i + 1 < lines.length && !isMoveLine(lines[i + 1]) &&
               String(lines[i + 1]).indexOf('> ') !== 0) i++;
        continue;
      }
      out.push(lines[i]);
    }
    return out;
  }

  function setBusy(flag) {
    busy = flag;
    // 右侧栏和技能栏是两块面板，请求中都要点不动（技能栏格子也能点，别让人连点两下）
    [el.actionBody, el.skillSlotsBody].forEach(function (node) {
      if (!node) return;
      node.style.pointerEvents = flag ? 'none' : '';
      node.style.opacity = flag ? '.6' : '';
    });
  }

  // 走不通、体力不够这类提示：直接浮在页面上，不用去日志里找
  function showToast(text) {
    var box = document.getElementById('toast');
    if (!box || !text) return;
    box.textContent = text;
    box.classList.remove('hidden');
    if (toastTimer) clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { box.classList.add('hidden'); }, 3000);
  }

  /* ---------- 浮层：技能树 / 二次确认 ---------- */

  function openModal(kind, title) {
    modalKind = kind;
    el.modalTitle.textContent = title;
    el.modal.classList.remove('hidden');
  }

  function closeModal() {
    if (modalKind === 'death') return;   // 死了不能关掉“你死了”，只能读档或回主菜单
    modalKind = null;
    el.modal.classList.add('hidden');
    clear(el.modalBody);
  }

  function showConfirm(title, text, onYes) {
    openModal('confirm', title);
    el.modalBody.innerHTML =
      '<p class="modal-note">' + esc(text) + '</p>' +
      '<div class="answer">' +
      '<button type="button" class="btn primary" id="confirm-yes">' + icon('check') +
      '<span>确定</span></button>' +
      '<button type="button" class="btn" data-close="1">' + icon('x') + '<span>取消</span></button>' +
      '</div>';
    document.getElementById('confirm-yes').addEventListener('click', function () {
      closeModal();
      onYes();
    });
  }

  // 一行技能：学过的绿色不可点，条件不够的灰色不可点，能学的给按钮
  function skillRow(tree, skill) {
    var meta = [skill.cost + ' 点'];
    if (skill.active) meta.push('主动');
    if (skill.ap_cost) meta.push(skill.ap_cost + ' 行动点');
    if (skill.cooldown) meta.push(skill.cooldown);
    if (skill.weapon) meta.push('需要手持' + skill.weapon);
    var state2 = skillLearnState(tree, skill);
    var action;
    if (state2.kind === 'learned') {
      action = '<span class="skill-done">' + icon('check') + '<span>已学会</span></span>';
    } else if (state2.kind === 'locked') {
      action = '<span class="skill-locked">' + icon('x') + '<span>' + esc(state2.why) + '</span></span>';
    } else if (state2.kind === 'unmet') {
      action = '<span class="skill-locked" title="' + esc(state2.why) + '">' +
        icon('x') + '<span>' + esc(state2.why) + '</span></span>';
    } else {
      action = '<button type="button" class="btn small primary" data-learn="' + esc(skill.name) + '">' +
        icon('learn') + '<span>学习（' + state2.cost + ' 点）</span></button>';
    }
    var desc = skill.description;
    if (skill.details && skill.details.length) {
      desc += '\n' + skill.details.join('\n');
    }
    return '<div class="skill-row">' +
      '<div class="skill-info">' +
      '<div class="skill-name">' + esc(skill.name) +
      ' <span class="skill-meta">' + esc(meta.join(' · ')) + '</span></div>' +
      '<div class="skill-desc">' + esc(desc) + '</div>' +
      '</div>' +
      '<div class="skill-action">' + action + '</div>' +
      '</div>';
  }

  function renderSkillsModal(state) {
    var sk = state && state.skills;
    if (!sk) return;
    var html = '<p class="modal-note">可用技能点：<strong>' + esc(sk.points) +
      '</strong>　绿色＝已学会，灰色＝条件不够（鼠标悬停看缺什么），亮着的按钮点了就能学。</p>';
    sk.trees.forEach(function (tree) {
      html += '<div class="tree-block">' +
        '<div class="tree-title"><h3>' + esc(tree.name) + '</h3>' +
        (tree.attribute || tree.special ? '<span class="tag">' + esc(tree.attribute || '特殊') + '</span>' : '') +
        (tree.unlocked ? '' : '<span class="tag">' + esc(tree.locked_message) + '</span>') +
        '</div>' +
        '<p class="tree-desc">' + esc(tree.description) + '</p>';

      var groups = [];
      if (tree.branches && tree.branches.length) {
        if (tree.skills.some(function (s) { return !s.branch; })) {
          groups.push({ name: '通用', id: '' });
        }
        tree.branches.forEach(function (b) { groups.push({ name: b.name, id: b.id }); });
      } else {
        groups.push({ name: '', id: '' });
      }
      groups.forEach(function (group) {
        var list = tree.skills.filter(function (s) { return (s.branch || '') === group.id; });
        if (!list.length) return;
        if (group.name) html += '<div class="branch-title">—— ' + esc(group.name) + ' ——</div>';
        list.forEach(function (s) { html += skillRow(tree, s); });
      });
      html += '</div>';
    });
    el.modalBody.innerHTML = html;
  }

  /* ---------- 技能栏的登记格子（10 页 × 9 格） ---------- */

  // 一格最多登记一件东西：技能（点一下「用 <技能>」）或物品（点一下使用 / 装备 / 查看）。
  // 存在浏览器本地（localStorage），按「页 × 9 + 格」编号存放；背包里已经没有的物品
  // 会在每次拿到新状态时自动清掉登记（见 pruneSlots）。
  var SLOT_KEY = 'fengcheng.slots';
  var SLOT_PAGES = 10;
  var SLOT_PER_PAGE = 9;
  var SLOT_TOTAL = SLOT_PAGES * SLOT_PER_PAGE;
  var slotPageNo = 0;          // 技能栏当前第几页（从 0 开始）
  var slots = loadSlots();

  function loadSlots() {
    var list = new Array(SLOT_TOTAL);
    for (var i = 0; i < SLOT_TOTAL; i++) list[i] = null;
    try {
      var saved = JSON.parse(window.localStorage.getItem(SLOT_KEY) || '[]');
      if (Object.prototype.toString.call(saved) !== '[object Array]') return list;
      for (var n = 0; n < SLOT_TOTAL && n < saved.length; n++) list[n] = normReg(saved[n]);
    } catch (err) { /* 读不出来就当没登记过 */ }
    return list;
  }

  // 登记项统一成 {kind:'skill'|'item', id, name, cmd(只有物品要)}
  function normReg(entry) {
    if (!entry || !entry.id) return null;
    if (entry.kind === 'skill') return { kind: 'skill', id: entry.id, name: entry.name || entry.id };
    if (entry.kind === 'item') {
      return { kind: 'item', id: entry.id, name: entry.name || entry.id, cmd: entry.cmd || '' };
    }
    // 老版本的背包快捷栏只存了 {id, name}：当物品登记读进来
    return { kind: 'item', id: entry.id, name: entry.name || entry.id, cmd: entry.cmd || '' };
  }

  function saveSlots() {
    try { window.localStorage.setItem(SLOT_KEY, JSON.stringify(slots)); } catch (err) { /* 无痕模式就算了 */ }
  }

  // 同一个东西只在技能栏里占一格：登记新格子时先摘掉旧的
  function slotIndexOf(kind, id) {
    for (var i = 0; i < SLOT_TOTAL; i++) {
      var e = slots[i];
      if (e && e.kind === kind && e.id === id) return i;
    }
    return -1;
  }

  function registerSlot(slot, kind, id, name, cmd) {
    if (slot < 0 || slot >= SLOT_TOTAL || !id) return;
    var at = slotIndexOf(kind, id);
    if (at >= 0) slots[at] = null;
    slots[slot] = { kind: kind, id: id, name: name || id, cmd: cmd || '' };
    saveSlots();
    refreshSlots();
  }

  function clearSlotReg(slot) {
    if (slot < 0 || slot >= SLOT_TOTAL) return;
    slots[slot] = null;
    saveSlots();
    refreshSlots();
  }

  // 两格对调（拖到别的格子上就是交换）
  function swapSlots(a, b) {
    if (a === b || a < 0 || b < 0 || a >= SLOT_TOTAL || b >= SLOT_TOTAL) return;
    var tmp = slots[a];
    slots[a] = slots[b];
    slots[b] = tmp;
    saveSlots();
    refreshSlots();
  }

  // 登记的技能 / 物品现在还作数吗？物品不在背包里就直接清掉登记（用完了不再占着格子）
  function slotAlive(state, entry) {
    if (!entry) return false;
    var inv = (state && state.inventory) || [];
    if (entry.kind === 'item') {
      return inv.some(function (x) { return x.id === entry.id; });
    }
    var active = (state && state.active_skills) || [];
    return active.some(function (x) { return x.id === entry.id; });
  }

  function pruneSlots(state) {
    var changed = false;
    for (var i = 0; i < SLOT_TOTAL; i++) {
      if (slots[i] && !slotAlive(state, slots[i])) { slots[i] = null; changed = true; }
    }
    if (changed) saveSlots();
    return changed;
  }

  function refreshSlots() {
    if (!lastState) return;
    renderSlotsPanel(lastState);
    if (viewMode === 'bag') renderBag(lastState);
  }

  function skillById(state, id) {
    var list = (state && state.active_skills) || [];
    for (var i = 0; i < list.length; i++) {
      if (list[i].id === id) return list[i];
    }
    return null;
  }

  // 一格：空的是拖动目标，有东西的能拖走 / 点一下用 / 右上角 ✕ 取消登记
  function slotCell(state, index) {
    var entry = slots[index];
    var inPage = index % SLOT_PER_PAGE + 1;
    if (!entry) {
      return '<span class="slot-cell slot-empty-cell" data-slot-cell="' + index + '" tabindex="0" title="第 ' +
        (index + 1) + ' 格：把背包里的物品或技能树里已学会的主动技能拖进来登记">' +
        '<span class="slot-index">' + inPage + '</span><span class="slot-name">&nbsp;</span><span class="slot-sub">空</span></span>';
    }
    var cmd = entry.kind === 'skill' ? ('用 ' + entry.name) : (entry.cmd || ('查看 ' + entry.name));
    var sub = entry.kind === 'skill' ? '技能' : '物品';
    var extra = '';
    if (entry.kind === 'skill') {
      var sk = skillById(state, entry.id);
      if (sk) {
        sub = sk.ap_cost ? (sk.ap_cost + ' 行动点') : '技能';
        extra = ' title="' + esc(entry.name + '：点一下释放（' + sub + '）；拖到别的格子＝交换，拖出技能栏＝取消登记') + '"';
      }
    } else {
      extra = ' title="' + esc(entry.name + '：点一下' + (entry.cmd ? '使用' : '查看') +
        '；拖到别的格子＝交换，拖出技能栏＝取消登记') + '"';
    }
    // 注意：这里必须是 <div>，不能是 <button>——Chromium 里 button 起不了
    // HTML5 拖动（dragstart 根本不触发），格子就永远拖不动。
    // role / tabindex 保留键盘可达性，点击照旧走 document 上的事件委托。
    return '<div class="slot-cell filled ' +
      (entry.kind === 'skill' ? 'slot-skill' : 'slot-item') + '" data-slot-cell="' + index +
      '" data-cast="' + (entry.kind === 'skill' ? esc(entry.name) : '') + '" data-cmd="' +
      (entry.kind === 'item' ? esc(cmd) : '') + '" draggable="true" tabindex="0" role="button"' + extra + '>' +
      '<span class="slot-index">' + inPage + '</span>' +
      '<span class="slot-name">' + esc(entry.name) + '</span>' +
      '<span class="slot-sub">' + esc(sub) + '</span>' +
      '<span class="slot-x" data-slot-clear="' + index + '" title="取消登记">✕</span></div>';
  }

  function slotsPanel(state) {
    var html = '<div class="slot-grid">';
    for (var i = 0; i < SLOT_PER_PAGE; i++) {
      html += slotCell(state, slotPageNo * SLOT_PER_PAGE + i);
    }
    return html + '</div>' +
      '<div class="slot-pager">' +
      '<button type="button" class="btn" data-slot-page="prev"' +
      (slotPageNo === 0 ? ' disabled' : '') + '>‹ 上一页</button>' +
      '<span class="page-now">第 ' + (slotPageNo + 1) + ' / ' + SLOT_PAGES + ' 页</span>' +
      '<button type="button" class="btn" data-slot-page="next"' +
      (slotPageNo >= SLOT_PAGES - 1 ? ' disabled' : '') + '>下一页 ›</button>' +
      '<button type="button" class="btn" data-slot-page="1">回到第 1 页</button>' +
      '</div>';
  }

  function renderSlotsPanel(state) {
    if (el.slotPage) el.slotPage.textContent = '第 ' + (slotPageNo + 1) + ' / ' + SLOT_PAGES + ' 页';
    if (!el.skillSlotsBody) return;
    el.skillSlotsBody.innerHTML = slotsPanel(state);
    bindSlotsDrag();
  }

  // 格子之间拖动 = 交换；拖到技能栏外面松手 = 取消登记
  // 「拖到哪儿」由 drop 说了算（dragHandled），不靠松手时的坐标判断：
  // 坐标判断会把「拖到空格子上」「落在格子缝隙里」误当成「拖到外面」，
  // 于是登记被当成取消，格子就挪不动了。
  function bindSlotsDrag() {
    if (!el.skillSlotsBody) return;
    Array.prototype.forEach.call(el.skillSlotsBody.querySelectorAll('.slot-cell'), function (cell) {
      var index = parseInt(cell.getAttribute('data-slot-cell'), 10);
      // 这里绝对不要加 mousedown + preventDefault 来「顺手」挡文字选择：
      // 实测它会连 HTML5 拖动一起掐掉（dragstart 根本不触发，格子就拖不动了）。
      // 文字选择交给 CSS 的 user-select: none。
      cell.addEventListener('dragover', function (event) {
        if (!dragSlot && !dragItem) return;
        event.preventDefault();
        cell.classList.remove('drop-ok', 'drop-no');
        var ok = dragSlot !== null ? true : canDropIntoSlot(dragItem, index);
        cell.classList.add(ok ? 'drop-ok' : 'drop-no');
      });
      cell.addEventListener('dragleave', function () {
        cell.classList.remove('drop-ok', 'drop-no');
      });
      cell.addEventListener('drop', function (event) {
        event.preventDefault();
        event.stopPropagation();
        dragHandled = true;   // 被格子接住了：dragend 不许再当成「取消登记」
        cell.classList.remove('drop-ok', 'drop-no');
        if (dragSlot !== null) {
          swapSlots(dragSlot, index);   // 格子之间：交换
          dragSlot = null;
          return;
        }
        if (!dragItem) return;
        if (!canDropIntoSlot(dragItem, index)) {
          showToast('这一格只能放技能或背包里的物品');
          dragItem = null;
          return;
        }
        registerSlot(index, dragItem.kind, dragItem.id, dragItem.name, dragItem.cmd);
        dragItem = null;
      });
      if (!cell.getAttribute('draggable')) return;
      cell.addEventListener('dragstart', function (event) {
        dragSlot = index;
        dragHandled = false;
        cell.classList.add('dragging');
        if (event.dataTransfer) {
          event.dataTransfer.effectAllowed = 'move';
          // 故意不给 text/plain：给了浏览器会当成「拖着一段选中的文字」，
          // 松手时弹「松开鼠标以搜索文本」。内部拖动靠 dragSlot / dragItem 就够。
          try { event.dataTransfer.setData('text/plain', ''); } catch (err) { /* 有的浏览器不给设，无所谓 */ }
        }
      });
      cell.addEventListener('dragend', function () {
        cell.classList.remove('dragging');
        tagDropOut(false);
        // 落在别处（没被任何格子 / 技能栏接住）= 取消登记
        if (dragSlot !== null && !dragHandled) clearSlotReg(dragSlot);
        dragSlot = null;
        dragItem = null;
        dragHandled = false;
        clearDropHints();
      });
    });
    // 往技能栏任意位置拖（包括格子之间的空隙）：有空位就登记过去，已经有东西的格子
    // 自己会先接住（stopPropagation），轮不到这里
    if (!el.skillSlotsBody.getAttribute('data-slot-bound')) {
      el.skillSlotsBody.setAttribute('data-slot-bound', '1');
      el.skillSlotsBody.addEventListener('dragover', function (event) {
        if (!dragSlot && !dragItem) return;
        event.preventDefault();
        tagDropOut(true);
      });
      el.skillSlotsBody.addEventListener('drop', function (event) {
        event.preventDefault();
        dragHandled = true;   // 落在技能栏里面（哪怕是缝隙）：不算取消登记
        tagDropOut(false);
        if (dragSlot !== null) { dragSlot = null; return; }   // 空格子之间落在缝隙上：什么也不做
        if (!dragItem) return;
        registerSlot(freeSlotInPage(), dragItem.kind, dragItem.id, dragItem.name, dragItem.cmd);
        dragItem = null;
      });
    }
  }

  function tagDropOut(on) {
    if (el.skillSlotsBody) el.skillSlotsBody.classList.toggle('drop-out', !!on);
  }

  // 这一页第一个空格；满了就顶掉第一格
  function freeSlotInPage() {
    var base = slotPageNo * SLOT_PER_PAGE;
    for (var i = 0; i < SLOT_PER_PAGE; i++) {
      if (!slots[base + i]) return base + i;
    }
    return base;
  }

  function canDropIntoSlot(drag, index) {
    if (!drag || index < 0 || index >= SLOT_TOTAL) return false;
    if (drag.kind === 'skill') return !!skillById(lastState, drag.id);
    if (drag.kind === 'item') return !!bagItemById(drag.id) || !!(lastState && (lastState.inventory || []).some(function (x) {
      return x.id === drag.id;
    }));
    return false;
  }

  /* ---------- 技能树：能学 / 已学 / 学不了 ---------- */

  // 一行技能的状态：浮层和视图栏的技能树页签共用这一份判断
  function skillLearnState(tree, skill) {
    if (skill.learned) return { kind: 'learned' };
    if (!tree.unlocked) return { kind: 'locked', why: tree.locked_message };
    if (skill.unmet && skill.unmet.length) return { kind: 'unmet', why: skill.unmet.join('、') };
    return { kind: 'can', cost: skill.cost };
  }

  /* ---------- 视图栏的「技能树」页签：一页一屏、翻页、选中才展开 ---------- */

  var SKILL_PER_PAGE = 32;      // 一页最多几个技能格子（技能一格很小，一页放得下）
  var skillPageNo = 0;
  var onlyLearned = false;      // 只显示已学会（挑技能栏要登记的技能时好用）
  var skillSelId = null;        // 选中的技能（下面那块详细描述）

  // 把技能按技能树切成"一页一屏"的块：一棵树一个块，超过 SKILL_PER_PAGE 再拆页。
  // 分支只用一行小字标出来，不再各占一页（不然 39 个技能要翻 18 页）。
  function skillBlocks(state, onlyLearnedFlag) {
    var sk = state && state.skills;
    if (!sk || !sk.trees) return [];
    var blocks = [];
    sk.trees.forEach(function (tree) {
      var items = [];
      var groups = [];
      if (tree.branches && tree.branches.length) {
        if (tree.skills.some(function (s) { return !s.branch; })) groups.push({ name: '', id: '' });
        tree.branches.forEach(function (b) { groups.push({ name: b.name, id: b.id }); });
      } else {
        groups.push({ name: '', id: '' });
      }
      groups.forEach(function (group) {
        var list = tree.skills.filter(function (s) {
          if ((s.branch || '') !== group.id) return false;
          return onlyLearnedFlag ? s.learned : true;
        });
        if (list.length) items.push({ group: group.name, items: list });
      });
      if (!items.length) return;
      var rest = items.slice();
      while (rest.length) {
        var take = [], count = 0;
        while (rest.length) {
          var head = rest[0];
          var room = SKILL_PER_PAGE - count;
          if (count && head.items.length > room) break;   // 这一组放不进本页，留给下一页
          take.push({ group: head.group, items: head.items.slice(0, room) });
          count += Math.min(head.items.length, room);
          if (head.items.length > room) {
            rest[0] = { group: head.group, items: head.items.slice(room) };
          } else {
            rest.shift();
          }
          if (count >= SKILL_PER_PAGE) break;
        }
        blocks.push({ tree: tree, title: tree.name, groups: take });
      }
    });
    return blocks;
  }

  function skillTile(tree, skill) {
    var st = skillLearnState(tree, skill);
    var cls = 'skill-tile ' + (st.kind === 'learned' ? 'learned' : st.kind === 'can' ? 'can-learn' : 'locked');
    if (skill.id === skillSelId) cls += ' sel';
    var active = skill.active ? '主动' : '被动';
    var title = skill.name + '（' + active + '）：点一下在下面看详细说明';
    var drag = skill.learned && skill.active ? ' draggable="true"' : '';
    return '<button type="button" class="' + cls + '" data-skill-sel="' + esc(skill.id) +
      '" data-skill-drag="' + esc(skill.name) + '"' + drag + ' title="' + esc(title) + '">' +
      esc(skill.name) + '<span class="tile-cost">·' + skill.cost + '点</span></button>';
  }

  function skillTreePage(state) {
    var blocks = skillBlocks(state, onlyLearned);
    if (skillPageNo >= blocks.length) skillPageNo = Math.max(0, blocks.length - 1);
    var body;
    if (!blocks.length) {
      body = '<div class="skill-group-title">' +
        (onlyLearned ? '还没有学会任何技能。' : '这棵树里没有技能。') + '</div>';
    } else {
      var page = blocks[skillPageNo];
      var html = '<div class="skill-group-title">' + esc(page.title) +
        (page.tree.unlocked ? '' : '（' + esc(page.tree.locked_message) + '）') + '</div>';
      html += '<div class="skill-tiles">';
      page.groups.forEach(function (group) {
        if (group.group) {
          html += '<span class="tile-branch">' + esc(group.group) + '</span>';
        }
        group.items.forEach(function (s) { html += skillTile(page.tree, s); });
      });
      html += '</div>';
      body = html;
    }
    return '<div class="skill-list">' + body + '</div>' +
      '<div class="bag-pager">' +
      '<button type="button" class="btn" data-skill-page="prev"' +
      (skillPageNo === 0 ? ' disabled' : '') + '>‹</button>' +
      '<span class="page-now">第 ' + (blocks.length ? skillPageNo + 1 : 0) + ' / ' + blocks.length + ' 页</span>' +
      '<button type="button" class="btn" data-skill-page="next"' +
      (skillPageNo >= blocks.length - 1 ? ' disabled' : '') + '>›</button>' +
      '</div>';
  }

  // 选中的技能：详细描述 + 能不能学 / 学不学得起，学习按钮就在这儿
  function skillDetail(state) {
    if (!skillSelId) {
      return '<div class="skill-detail"><p class="detail-empty">' +
        '点上面的技能格子看详细说明；已学会的主动技能可以直接拖到下面的技能栏登记。</p></div>';
    }
    var found = null;
    (state.skills.trees || []).forEach(function (tree) {
      tree.skills.forEach(function (s) { if (s.id === skillSelId) found = { tree: tree, skill: s }; });
    });
    if (!found) {
      skillSelId = null;
      return '<div class="skill-detail"><p class="detail-empty">这个技能不在当前技能树里了。</p></div>';
    }
    var skill = found.skill;
    var st = skillLearnState(found.tree, skill);
    var meta = [skill.cost + ' 点', skill.active ? '主动' : '被动'];
    if (skill.ap_cost) meta.push(skill.ap_cost + ' 行动点');
    if (skill.cooldown) meta.push(skill.cooldown);
    if (skill.weapon) meta.push('需要手持' + skill.weapon);
    var desc = skill.description;
    if (skill.details && skill.details.length) desc += '\n' + skill.details.join('\n');

    var act;
    if (st.kind === 'learned') {
      act = '<span class="skill-done">' + icon('check') + '<span>已学会</span></span>' +
        (skill.active ? '<span class="detail-meta">已学会的主动技能可以拖到下面的技能栏登记</span>' : '');
    } else if (st.kind === 'locked') {
      act = '<span class="skill-locked">' + icon('x') + '<span>' + esc(st.why) + '</span></span>';
    } else if (st.kind === 'unmet') {
      act = '<span class="skill-locked">' + icon('x') + '<span>还差：' + esc(st.why) + '</span></span>';
    } else {
      act = '<button type="button" class="btn small primary" data-learn="' + esc(skill.name) + '">' +
        icon('learn') + '<span>学习（' + st.cost + ' 点）</span></button>';
    }
    return '<div class="skill-detail">' +
      '<div class="detail-head"><span class="detail-name">' + esc(skill.name) + '</span>' +
      '<span class="detail-meta">' + esc(found.tree.name + ' · ' + meta.join(' · ')) + '</span></div>' +
      '<p class="detail-desc">' + esc(desc) + '</p>' +
      '<div class="detail-act">' + act + '</div>' +
      '</div>';
  }

  function renderSkillPanel(state) {
    if (!el.skillPanel) return;
    var sk = state && state.skills;
    if (!sk) { el.skillPanel.innerHTML = '<p class="detail-empty">还没有角色。</p>'; return; }
    el.skillPanel.innerHTML =
      '<div class="skill-top">' +
      '<span>可用技能点：<strong>' + esc(sk.points) + '</strong></span>' +
      '<span class="detail-meta">绿色＝已学会，亮边框＝现在能学，灰的＝条件不够</span>' +
      '<button type="button" class="btn small fold-btn' + (onlyLearned ? ' on' : '') +
      '" data-skill-only="1">' + (onlyLearned ? '显示全部' : '只看已学会') + '</button>' +
      '</div>' +
      '<div class="skill-list-wrap">' +
      skillTreePage(state) +
      skillDetail(state) + '</div>';
    bindSkillTileDrag();
  }

  // 已学会的主动技能可以拖到技能栏登记（拖的时候记下 name，点一下就是「用 <name>」）
  function bindSkillTileDrag() {
    if (el.skillPanel && !el.skillPanel.getAttribute('data-tile-bound')) {
      el.skillPanel.setAttribute('data-tile-bound', '1');
      el.skillPanel.addEventListener('dragstart', function (event) {
        var tile = event.target.closest ? event.target.closest('[data-skill-drag]') : null;
        if (!tile || !tile.getAttribute('draggable')) return;
        dragItem = { from: 'skill', kind: 'skill', id: tile.getAttribute('data-skill-sel'),
                     name: tile.getAttribute('data-skill-drag') };
        tile.classList.add('dragging');
        if (event.dataTransfer) {
          event.dataTransfer.effectAllowed = 'move';
          // 不给 text/plain：给了浏览器会当成「拖着一段选中的文字」，松手弹「搜索文本」
          try { event.dataTransfer.setData('text/plain', ''); } catch (err) { /* 无所谓 */ }
        }
      });
      el.skillPanel.addEventListener('dragend', function (event) {
        var tile = event.target.closest ? event.target.closest('[data-skill-drag]') : null;
        if (tile) tile.classList.remove('dragging');
        tagDropOut(false);
        dragItem = null;
        clearDropHints();
      });
    }
  }

  // 技能树页签里点技能 / 翻页，都只是重画这一块
  function refreshSkillPanel() {
    if (lastState && viewMode === 'skills') renderSkillPanel(lastState);
  }

  /* ---------- 浮层里要显示什么，由 modalKind 决定 ---------- */

  function renderModal(state) {
    if (!state) return;
    if (modalKind === 'skills') renderSkillsModal(state);
  }

  /* ---------- 存档槽位 ---------- */

  // 主菜单里的存档行：完整的描述 + 读档 / 清空
  function slotRow(slot) {
    var cls = 'slot' + (slot.exists ? '' : ' slot-empty') + (slot.current ? ' slot-current' : '');
    var info;
    if (slot.exists && !slot.broken) {
      info = '<div class="slot-name">' + esc(slot.name) + '</div>' +
        '<div class="slot-meta">' + esc(slot.level) + ' 级' +
        (slot.background ? ' · ' + esc(slot.background) : '') +
        ' · ' + esc(slot.room) + ' · ' + esc(slot.time) + '</div>' +
        (slot.saved_at ? '<div class="slot-saved-at">最后保存：' + esc(slot.saved_at) + '</div>' : '');
    } else if (slot.broken) {
      info = '<div class="slot-name">存档损坏</div>' +
        '<div class="slot-meta">读不了，可以清空它，或者进游戏直接存新档覆盖</div>';
    } else {
      info = '<div class="slot-name">空存档位</div><div class="slot-meta">还没有存过</div>';
    }
    var actions = '';
    if (slot.exists && !slot.broken) {
      actions += '<button type="button" class="btn small" data-load="' + slot.slot + '">' +
        icon('load') + '<span>读档</span></button>';
    }
    if (slot.exists) {
      actions += '<button type="button" class="btn small danger" data-clear="' + slot.slot + '">' +
        icon('x') + '<span>清空</span></button>';
    }
    return '<div class="' + cls + '"><div class="slot-no">' + slot.slot + ' 号</div>' +
      '<div class="slot-info">' + info + '</div>' +
      '<div class="slot-actions">' + actions + '</div></div>';
  }

  function renderMenuSlots(state) {
    var box = document.getElementById('menu-slots');
    if (!box) return;
    var slots = (state && state.slots) || [];
    box.innerHTML = slots.map(function (s) { return slotRow(s); }).join('');
    var any = slots.some(function (s) { return s.exists && !s.broken; });
    el.menuHint.textContent = any ? '选一个存档读进来，或者开始新游戏。' : '还没有存档，先开始一局新游戏。';
  }

  /* ---------- 游戏里的存档盘：两排按钮 ---------- */

  var SAVE_MODE_LABEL = { save: '存档', load: '读档', clear: '清空' };

  function savePad(state) {
    var slots = (state && state.slots) || [];
    var html = '<div class="save-pad"><div class="save-row">';
    ['save', 'load', 'clear'].forEach(function (mode) {
      var on = saveMode === mode ? ' active' : '';
      var ico = mode === 'save' ? 'save' : (mode === 'load' ? 'load' : 'x');
      html += '<button type="button" class="btn small save-mode' + on + '" data-save-mode="' + mode +
        '">' + icon(ico) + '<span>' + SAVE_MODE_LABEL[mode] + '</span></button>';
    });
    html += '</div><div class="save-row">';
    for (var n = 1; n <= 3; n++) {
      var slot = slots.filter(function (x) { return x.slot === n; })[0] || { slot: n, exists: false };
      var cls = 'btn small slot-no-btn';
      if (slot.exists) cls += ' has-save';
      if (slot.current) cls += ' current';
      var sub = slot.broken ? '损坏' : (slot.exists ? '有档' : '空');
      var title = !slot.exists ? (n + ' 号：空存档位')
        : (slot.broken ? (n + ' 号：存档损坏')
          : (n + ' 号：' + slot.name + ' · ' + slot.level + ' 级 · ' + slot.room + ' · ' + slot.time));
      html += '<button type="button" class="' + cls + '" data-slot-no="' + n + '" title="' + esc(title) + '">' +
        '<span class="no">' + n + '</span><span class="sub">' + esc(sub) + '</span></button>';
    }
    html += '</div></div>';
    // 只留一句最短的：动作按钮选中会变绿，当前槽用琥珀色圈标出来
    return html + '<p class="hint-small">当前槽：' + esc((state && state.current_slot) || 1) + ' 号</p>';
  }

  function slotById(n) {
    return ((lastState && lastState.slots) || []).filter(function (x) { return x.slot === n; })[0];
  }

  function doSlotAction(n) {
    var slot = slotById(n) || { slot: n, exists: false };
    if (!saveMode) {
      showToast('先在 1 / 2 / 3 上面选一个动作：存档 / 读档 / 清空。');
      return;
    }
    if (saveMode === 'save') {
      var text = (slot.exists && !slot.broken)
        ? (n + ' 号槽已经有存档了（' + slot.name + ' · ' + slot.time + '），覆盖它吗？')
        : ('把当前进度存到 ' + n + ' 号槽？');
      showConfirm('存档到 ' + n + ' 号', text, function () { saveSlot(n); });
      return;
    }
    if (saveMode === 'load') {
      if (!slot.exists) { showToast(n + ' 号槽是空的，没有东西可读。'); return; }
      if (slot.broken) { showToast(n + ' 号存档损坏了，读不出来；可以先清空它。'); return; }
      showConfirm('读取 ' + n + ' 号', '读取 ' + n + ' 号槽？现在没存档的进度会丢掉。', function () { loadSlot(n); });
      return;
    }
    if (!slot.exists) { showToast(n + ' 号槽本来就是空的。'); return; }
    showConfirm('清空 ' + n + ' 号', '确定清空 ' + n + ' 号存档？清空之后没法恢复。', function () { clearSlot(n); });
  }

  function post(url, body) {
    var payload = body || {};
    payload.page = PAGE_ID;   // 每条请求都带上页面身份，服务端才知道这个页面还活着
    return fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    }).then(function (res) {
      return res.json().catch(function () { return { type: 'error', lines: ['服务器返回了无法解析的内容。'] }; });
    });
  }

  function fail(err) {
    appendLines(currentMode === 'create' ? el.createLog : el.log,
      ['【连接失败】' + (err && err.message ? err.message : err) + '（服务可能已经停止）']);
  }

  /* ---------- 角色创建：渲染一个问题 ---------- */

  function renderPrompt(data) {
    var hint = data.input || { kind: 'text' };
    var box = el.createPrompt;
    clear(box);
    el.createSteps.textContent = answered > 0 ? '已填 ' + answered + ' 项' : '';

    var q = document.createElement('p');
    q.className = 'q';
    q.textContent = data.prompt || '';
    box.appendChild(q);

    var form = document.createElement('form');
    form.className = 'answer';
    form.autocomplete = 'off';

    function submit(value) {
      if (busy) return;
      answered += 1;
      setBusy(true);
      post('/api/answer', { value: value }).then(function (res) {
        setBusy(false);
        handlePayload(res);
      }).catch(function (err) { setBusy(false); fail(err); });
    }

    if (hint.kind === 'choice') {
      var list = document.createElement('div');
      list.className = 'choices';
      var options = hint.options || [];
      options.forEach(function (label, index) {
        var b = document.createElement('button');
        b.type = 'button';
        b.className = 'choice';
        b.innerHTML = '<span class="num">' + (index + 1) + '</span><span class="label">' + esc(label) + '</span>';
        b.addEventListener('click', function () { submit(String(index + 1)); });
        list.appendChild(b);
      });
      box.appendChild(list);
      lastChoices = options.length;
      return;
    }

    lastChoices = 0;

    if (hint.kind === 'attributes') {
      renderAttributes(box, hint, submit);
      return;
    }

    if (hint.kind === 'perks') {
      renderPerks(box, hint, submit);
      return;
    }

    if (hint.kind === 'confirm') {
      var yes = document.createElement('button');
      yes.type = 'button';
      yes.className = 'btn primary';
      yes.innerHTML = icon('check') + '<span>是</span>';
      yes.addEventListener('click', function () { submit('y'); });
      var no = document.createElement('button');
      no.type = 'button';
      no.className = 'btn';
      no.innerHTML = icon('x') + '<span>否</span>';
      no.addEventListener('click', function () { submit('n'); });
      form.appendChild(yes);
      form.appendChild(no);
      box.appendChild(form);
      return;
    }

    var input = document.createElement('input');
    if (hint.kind === 'number') {
      input.type = 'number';
      if (hint.min !== undefined && hint.min !== null) input.min = hint.min;
      if (hint.max !== undefined && hint.max !== null) input.max = hint.max;
      input.step = '1';
      var tip = document.createElement('span');
      tip.className = 'range-hint';
      tip.textContent = '范围 ' + hint.min + ' ~ ' + hint.max;
      form.appendChild(tip);
    } else {
      input.type = 'text';
      if (hint.max_length) input.maxLength = hint.max_length;
      if (hint.default) input.placeholder = '直接回车用默认：' + hint.default;
    }
    input.autofocus = true;

    var ok = document.createElement('button');
    ok.type = 'submit';
    ok.className = 'btn primary';
    ok.innerHTML = icon('check') + '<span>确定</span>';

    form.appendChild(input);
    form.appendChild(ok);
    form.addEventListener('submit', function (event) {
      event.preventDefault();
      submit(input.value);
    });
    box.appendChild(form);
    setTimeout(function () { input.focus(); }, 30);
  }

  // 选 perk：点卡片切换选中，剩余点数实时更新，选好后点“继续”一次提交（规则最终由服务端再查一遍）
  function renderPerks(box, hint, submit) {
    var perks = hint.perks || [];
    var chosen = [];
    var byId = {};
    perks.forEach(function (p) { byId[p.id] = p; });

    function left(sel) {
      var n = hint.base || 0;
      sel.forEach(function (id) { n += (byId[id].perk_points || 0) - byId[id].cost; });
      return n;
    }
    function clashes(id, sel) {
      return sel.filter(function (o) {
        return (byId[id].conflicts || []).indexOf(o) >= 0 || (byId[o].conflicts || []).indexOf(id) >= 0;
      });
    }

    var list = document.createElement('div');
    list.className = 'perk-list';
    var status = document.createElement('div');
    status.className = 'attr-remaining';
    var done = document.createElement('button');
    done.type = 'button';
    done.className = 'btn primary';
    done.innerHTML = icon('check') + '<span>继续</span>';
    done.addEventListener('click', function () { submit(JSON.stringify(chosen)); });

    function refresh() {
      var n = left(chosen);
      status.textContent = '剩余 perk 点：' + n;
      status.classList.toggle('bad', n < 0);
      done.disabled = n < 0;
      perks.forEach(function (p) {
        var card = list.querySelector('[data-perk="' + p.id + '"]');
        var on = chosen.indexOf(p.id) >= 0;
        var why = '';
        if (on) {
          if (left(chosen.filter(function (x) { return x !== p.id; })) < 0) why = '取消后 perk 点不够';
        } else if (clashes(p.id, chosen).length) {
          why = '和' + byId[clashes(p.id, chosen)[0]].name + '冲突';
        } else if (left(chosen.concat([p.id])) < 0) {
          why = 'perk 点不够';
        }
        card.classList.toggle('on', on);
        card.disabled = !!why;
        card.querySelector('.perk-why').textContent = why;
      });
    }

    perks.forEach(function (p) {
      var card = document.createElement('button');
      card.type = 'button';
      card.className = 'perk-card';
      card.setAttribute('data-perk', p.id);
      card.innerHTML =
        '<span class="perk-head"><span class="perk-name">' + esc(p.name) + '</span>' +
        '<span class="perk-cost">' + (p.cost ? '消耗 ' + p.cost + ' 点' : '有正有负 · 不花点') + '</span></span>' +
        '<span class="perk-desc">' + esc(p.description) + '</span>' +
        '<span class="perk-why"></span>';
      card.addEventListener('click', function () {
        var i = chosen.indexOf(p.id);
        if (i >= 0) chosen.splice(i, 1); else chosen.push(p.id);
        refresh();
      });
      list.appendChild(card);
    });

    var actions = document.createElement('div');
    actions.className = 'answer';
    actions.appendChild(status);
    actions.appendChild(done);
    box.appendChild(list);
    box.appendChild(actions);
    refresh();
  }

  // 属性分配：每个属性一行，加减号调整，调够了才能点“完成”
  function renderAttributes(box, hint, submit) {
    var rules = hint.rules || { min: 3, max: 10, total: 33 };
    var defs = hint.defs || [];
    var start = hint.attributes || {};
    var values = {};

    defs.forEach(function (d) { values[d.id] = start[d.id]; });

    function used() {
      var total = 0;
      defs.forEach(function (d) { total += values[d.id]; });
      return total;
    }

    var list = document.createElement('div');
    list.className = 'attr-list';

    var remaining = document.createElement('div');
    remaining.className = 'attr-remaining';

    var done = document.createElement('button');
    done.type = 'button';
    done.className = 'btn primary';
    done.innerHTML = icon('check') + '<span>完成</span>';
    done.addEventListener('click', function () {
      submit(JSON.stringify(values));
    });

    var reset = document.createElement('button');
    reset.type = 'button';
    reset.className = 'btn';
    reset.innerHTML = icon('x') + '<span>重置</span>';
    reset.addEventListener('click', function () {
      defs.forEach(function (d) { values[d.id] = start[d.id]; });
      refresh();
    });

    function refresh() {
      var left = rules.total - used();
      remaining.textContent = '剩余点数：' + left +
        '（每项 ' + rules.min + '~' + rules.max + '，合计 ' + rules.total + '）';
      remaining.classList.toggle('bad', left !== 0);
      done.disabled = left !== 0;
      defs.forEach(function (d) {
        var row = list.querySelector('[data-attr="' + d.id + '"]');
        if (!row) return;
        row.querySelector('.attr-value').textContent = values[d.id];
        row.querySelector('.attr-minus').disabled = values[d.id] <= rules.min;
        row.querySelector('.attr-plus').disabled = values[d.id] >= rules.max || left <= 0;
      });
    }

    defs.forEach(function (d) {
      var row = document.createElement('div');
      row.className = 'attr-row';
      row.setAttribute('data-attr', d.id);
      row.innerHTML =
        '<div class="attr-info"><span class="attr-name">' + esc(d.name) + '</span>' +
        '<span class="attr-desc">' + esc(d.description) + '</span></div>' +
        '<div class="attr-controls">' +
        '<button type="button" class="btn icon-btn attr-minus">' + icon('minus') + '</button>' +
        '<span class="attr-value"></span>' +
        '<button type="button" class="btn icon-btn attr-plus">' + icon('plus') + '</button>' +
        '</div>';
      row.querySelector('.attr-plus').addEventListener('click', function () {
        if (values[d.id] < rules.max && used() < rules.total) {
          values[d.id] += 1;
          refresh();
        }
      });
      row.querySelector('.attr-minus').addEventListener('click', function () {
        if (values[d.id] > rules.min) {
          values[d.id] -= 1;
          refresh();
        }
      });
      list.appendChild(row);
    });

    var actions = document.createElement('div');
    actions.className = 'answer';
    actions.appendChild(remaining);
    actions.appendChild(reset);
    actions.appendChild(done);

    box.appendChild(list);
    box.appendChild(actions);
    refresh();
  }

  document.addEventListener('keydown', function (event) {
    if (currentMode !== 'create' || !lastChoices || busy) return;
    var tag = (event.target && event.target.tagName) || '';
    if (tag === 'INPUT' || tag === 'TEXTAREA') return;
    var n = parseInt(event.key, 10);
    if (!n || n < 1 || n > lastChoices) return;
    var nodes = el.createPrompt.querySelectorAll('button.choice');
    if (nodes[n - 1]) nodes[n - 1].click();
  });

  /* ---------- 游戏界面：渲染状态 ---------- */

  // 时钟：固定在视图栏右上角（不跟页签走），时间 + 回合数
  function renderClock(state) {
    if (!el.viewClock) return;
    if (!state || !state.time) { el.viewClock.innerHTML = ''; return; }
    var turns = (typeof state.turns === 'number') ? '第 ' + state.turns + ' 回合' : '';
    el.viewClock.innerHTML =
      '<div class="clock-chip" title="' + esc(state.time.text + (turns ? ' · ' + turns : '')) + '">' +
      icon('clock') + '<span class="clock-text">' + esc(state.time.text) + '</span>' +
      (turns ? '<span class="clock-turns">' + esc(turns) + '</span>' : '') + '</div>';
  }

  // “你死了”菜单：写明死因，只能读档或返回主菜单
  function renderDeath(state) {
    if (state.death) {
      if (modalKind !== 'death') openModal('death', '你死了');
      if (el.modalClose) el.modalClose.style.display = 'none';
      el.modalBody.innerHTML =
        '<p class="death-title">你死了</p>' +
        '<p class="death-cause">死因：' + esc(state.death.cause) + '</p>' +
        '<div class="answer">' +
        '<button type="button" class="btn primary" data-act="continue">' + icon('load') + '<span>读档</span></button>' +
        '<button type="button" class="btn" data-death-menu="1">' + icon('exit') + '<span>返回菜单</span></button>' +
        '</div>';
    } else if (modalKind === 'death') {
      modalKind = null;
      if (el.modalClose) el.modalClose.style.display = '';
      el.modal.classList.add('hidden');
      clear(el.modalBody);
    }
  }

  /* ---------- 视图栏顶部的对话框（横幅） ---------- */

  // 说话 / 往下接话时，房间信息让位给对话框：横幅上写当前这一句。
  // state.talk 是服务端给的（{speaker, text}），不在说话时是 null。
  function renderTalk(state) {
    if (!el.talkBanner) return;
    var talk = state && state.talk;
    if (talk) {
      el.talkSpeaker.textContent = talk.speaker ? talk.speaker + '：' : '';
      el.talkText.textContent = talk.text || '';
      el.talkBanner.classList.remove('hidden');
    } else {
      el.talkBanner.classList.add('hidden');
      el.talkSpeaker.textContent = '';
      el.talkText.textContent = '';
    }
    if (el.roomBar) el.roomBar.classList.toggle('talking', !!talk);
    // 说话时把左上角的地图收起来（横幅铺开成一大块，浮在上面的地图会压住台词）
    if (el.viewMap) el.viewMap.classList.toggle('talking', !!talk);
  }

  // 点视图栏任意位置：对话框还开着就往下接一句。
  // 但只有"场景"这一块算：技能树 / 背包面板里的点击要留给它们自己
  //（不然说着话就点不了技能格子、也点不开背包里的东西）。
  function clickTalkBanner(event) {
    if (!lastState || !lastState.talk) return false;
    if (viewMode !== 'scene') return false;   // 不在场景页签里，点击是那个页签自己的操作
    if (busy) return true;                    // 正在等上一句的回复，别重复发
    if (event) {
      var node = event.target;
      // 页签、指令行这类控件还是按它们自己的功能走
      while (node && node !== document.body) {
        if (node.id === 'view-tabs' || node.id === 'cmd-form') return false;
        if (node.id === 'skill-panel' || node.id === 'bag-panel') return false;
        // 地图和时钟浮在场景上：点它们是在看地图 / 切楼层，不算「继续」
        if (node.id === 'view-map' || node.id === 'view-clock') return false;
        node = node.parentNode;
      }
    }
    return sendCommand('继续') !== null;
  }

  function renderState(state) {
    if (!state) return;
    lastState = state;
    // 背包里已经没有的东西（用完了 / 丢掉了）不再占着技能栏的登记格子
    pruneSlots(state);
    renderTalk(state);
    if (state.room) {
      el.roomName.textContent = state.room.name;
      var bits = [];
      if (typeof state.turns === 'number') bits.push('第 ' + state.turns + ' 回合');
      if (state.stance) bits.push('姿态：' + state.stance);
      el.roomSub.textContent = bits.join(' · ');
    }
    renderChar(state);
    renderActions(state);
    renderView(state);   // 视图栏：场景 / 背包 / 技能树（三个页签）
    renderSlotsPanel(state);   // 技能栏：10 页 × 9 格
    renderDeath(state);
  }

  /* ---------- 可折叠的分区（左侧栏） ---------- */

  var COLLAPSE_KEY = 'fengcheng.collapsed';
  var collapsed = loadCollapsed();  // 哪个分区被收起来了（属性 / 战斗 / 状态）

  function loadCollapsed() {
    try { return JSON.parse(localStorage.getItem(COLLAPSE_KEY)) || {}; } catch (e) { return {}; }
  }

  function saveCollapsed() {
    try { localStorage.setItem(COLLAPSE_KEY, JSON.stringify(collapsed)); } catch (e) { /* 存不了就算了 */ }
  }

  function toggleSection(key) {
    collapsed[key] = !collapsed[key];
    saveCollapsed();
    if (lastState) renderChar(lastState);
  }

  // 分区外壳：标题栏点一下收起 / 展开，收起状态记在本地
  function section(key, title, iconName, bodyHtml) {
    var open = !collapsed[key];
    return '<div class="section' + (open ? '' : ' collapsed') + '" data-section="' + esc(key) + '">' +
      '<h4 class="section-head">' + icon(iconName) + esc(title) +
      '<span class="chev" title="收起 / 展开">▼</span></h4>' +
      '<div class="section-body">' + bodyHtml + '</div></div>';
  }

  var LOAD_CLASS = { '轻载': 'light', '中载': 'medium', '重载': 'heavy', '超重': 'over', '严重超重': 'over' };

  function loadTag(label) {
    if (!label) return '';
    return '<span class="load-tag ' + (LOAD_CLASS[label] || '') + '">' + esc(label) + '</span>';
  }

  function renderChar(state) {
    var c = state.character;
    if (!c) { clear(el.charBody); return; }

    var hpMax = c.hp_max || 1;
    var pct = Math.max(0, Math.min(100, Math.round((c.hp / hpMax) * 100)));

    var html = '';
    html += '<p class="char-name">' + esc(c.name) + '</p>';
    // 年龄 / 身高自由填写：纯数字才加“岁”“cm”
    var isNum = function (v) { return /^\d+$/.test(String(v)); };
    html += '<p class="char-meta">' + esc(c.gender) + ' · ' + esc(c.age) + (isNum(c.age) ? ' 岁' : '') + ' · ' +
      esc(c.height) + (isNum(c.height) ? ' cm' : '') + ' · ' + esc(c.background) + '</p>';

    // 等级和技能点放在生命值 / 体力条上面
    html += '<div class="kv"><span class="k">等级</span><span class="v">' + esc(c.level) +
      '（经验 ' + esc(c.xp) + '）</span></div>';
    html += '<div class="kv"><span class="k">技能点</span><span class="v">' + esc(c.skill_points) + '</span></div>';

    html += '<div class="hp-row">' + icon('hp') + '<span class="res-label">生命</span><div class="hp-track"><div class="hp-fill" style="width:' +
      pct + '%"></div></div><span>' + esc(c.hp) + '/' + esc(hpMax) + '</span></div>';

    if (state.stamina) {
      var st = state.stamina;
      var sPct = Math.max(0, Math.min(100, Math.round(st.value / Math.max(1, st.max) * 100)));
      var sCls = st.value <= 0 ? ' empty' : (st.exhausted ? ' low' : '');
      html += '<div class="hp-row">' + icon('rest') + '<span class="res-label">体力</span><div class="hp-track stamina-track">' +
        '<div class="hp-fill stamina-fill' + sCls + '" style="width:' + sPct + '%"></div></div><span>' +
        esc(st.value) + '/' + esc(st.max) + '</span></div>';
    }

    // 行动点（紫）：每回合（1 分钟）获得 gain 点，上限 max
    if (state.ap) {
      var ap = state.ap;
      var aPct = Math.max(0, Math.min(100, Math.round(ap.value / Math.max(1, ap.max) * 100)));
      html += '<div class="hp-row" title="每回合（1 分钟）获得 ' + esc(ap.gain) + ' 点，用完或点“结束回合”就过 1 分钟">' +
        icon('clock') + '<span class="res-label">行动</span><div class="hp-track ap-track">' +
        '<div class="hp-fill ap-fill" style="width:' + aPct + '%"></div></div><span>' +
        esc(ap.value) + '/' + esc(ap.max) + '</span></div>';
    }

    // 食物（绿）、水源（蓝）
    if (state.needs) {
      [['food', '食物', 'food-fill'], ['water', '水源', 'water-fill']].forEach(function (n) {
        var v = state.needs[n[0]], max = state.needs.max || 100;
        var p = Math.max(0, Math.min(100, Math.round(v / max * 100)));
        var stage = state.needs[n[0] + '_stage'] || 0;
        html += '<div class="hp-row">' + icon(n[0] === 'food' ? 'item-generic' : 'rest') +
          '<span class="res-label">' + n[1] + '</span><div class="hp-track need-track">' +
          '<div class="hp-fill ' + n[2] + (stage ? ' stage' + stage : '') + '" style="width:' + p + '%"></div></div><span>' +
          esc(v) + '/' + esc(max) + '</span></div>';
      });
    }

    // 负重写出轻载 / 中载 / 重载
    if (state.carry) {
      html += '<div class="kv"><span class="k">负重</span><span class="v">' + esc(state.carry.weight) +
        ' / ' + esc(state.carry.capacity) + ' kg ' + loadTag(state.carry.label) +
        (state.backpack_reduction ? '（背包减重 ' + esc(state.backpack_reduction) + '%）' : '') +
        '</span></div>';
    }

    // 常驻状态栏：没有异常状态时也显示“无”，可以收起来
    var statusBody = '';
    if (state.conditions && state.conditions.length) {
      state.conditions.forEach(function (x) {
        statusBody += '<div class="cond"><span class="cond-name">' + esc(x.name) + '</span>' +
          '<span class="cond-eff">' + esc(x.effect) + '</span>' +
          (x.note ? '<span class="cond-note">' + esc(x.note) + '</span>' : '') + '</div>';
      });
    } else {
      statusBody = '<div class="kv"><span class="k">异常状态</span><span class="v">无</span></div>';
    }
    statusBody += '<div class="kv"><span class="k">姿态</span><span class="v">' + esc(state.stance || '无') + '</span></div>';
    html += section('status', '状态', 'hp', statusBody);

    var attrBody = '<div class="attr-grid">';
    (c.attributes || []).forEach(function (a) {
      attrBody += '<div class="attr"><span class="n">' + esc(a.name) + '</span><span class="v">' + esc(a.value) + '</span></div>';
    });
    attrBody += '</div>';
    html += section('attributes', '属性', 'person', attrBody);

    if (state.combat) {
      var cb = state.combat;
      var combatBody = '';
      combatBody += '<div class="kv"><span class="k">行动点</span><span class="v">每回合 ' + esc(cb.ap_per_turn) +
        '（上限 ' + esc(cb.ap_cap) + (cb.armor_ap_penalty ? '，重甲 −' + esc(cb.armor_ap_penalty) + '%' : '') +
        '）</span></div>';
      (cb.weapons || []).forEach(function (w) {
        var mult = w.damage_multiplier || 1;   // 服务端算好的总倍率（加算 / 乘算规则在 stats.py）
        var dmg = w.damage ? w.damage + (mult !== 1 ? ' ×' + Number(mult.toFixed(3)) : '') +
          '（暴击 ' + w.crit_range + '）' : '未定';
        combatBody += '<div class="kv"><span class="k">' + esc(w.hand) + '·' + esc(w.name) + '</span><span class="v">精准 ' +
          esc(w.accuracy) + ' · 伤害 ' + esc(dmg) + '</span></div>';
      });
      combatBody += '<div class="kv"><span class="k">护甲</span><span class="v">' + esc(cb.armor) +
        ((cb.worn || []).length ? '（' + cb.worn.map(function (p) {
          return esc(p.slot) + ' ' + esc(p.name) + ' +' + esc(p.value);
        }).join('、') + '）' : '') + '</span></div>';
      combatBody += '<div class="kv"><span class="k">闪避</span><span class="v">' + esc(cb.dodge) + '</span></div>';
      combatBody += '<div class="kv"><span class="k">先攻</span><span class="v">' + esc(cb.initiative) + '</span></div>';
      combatBody += '<div class="kv"><span class="k">视野</span><span class="v">' + esc(cb.sight) + ' 格</span></div>';
      combatBody += '<div class="kv"><span class="k">行动点消耗</span><span class="v">攻击 ' + esc(cb.attack_cost) +
        ' · 移动 ' + esc(cb.move_cost) + ' · 物品 ' + esc(cb.item_cost) + '</span></div>';
      html += section('combat', '战斗', 'stance', combatBody);
    }

    if (c.companions && c.companions.length) {
      var mates = '';
      c.companions.forEach(function (p) {
        mates += '<div class="kv"><span class="k">' + esc(p.relationship || '同伴') + '</span><span class="v">' +
          esc(p.name) + '（' + esc(p.age) + (/^\d+$/.test(String(p.age)) ? ' 岁' : '') + '）</span></div>';
      });
      html += section('companions', '同伴', 'talk', mates);
    }

    el.charBody.innerHTML = html;
    Array.prototype.forEach.call(el.charBody.querySelectorAll('.section-head'), function (head) {
      head.addEventListener('click', function () {
        toggleSection(head.parentNode.getAttribute('data-section'));
      });
    });
  }

  function renderActions(state) {
    // 按界面区域分工（区域约定见 ../界面区域.md）：
    //   技能栏 = #skill-slots-body，右侧栏 = #action-body（休息 / 存档读档 / 系统），
    //   快捷区域1 = #equip-body 的装备栏，快捷区域2 = #log + #cmd-form。
    //   背包 / 技能树 = 视图栏的两个页签（点视图栏右上角）；
    //   地上的物品和人物在场景里点方块出菜单（thingMenu），不再占右侧栏。
    renderEquip(state);
    el.actionBody.innerHTML =
      (state.rest ? restSection(state) : '') +
      saveSection(state) +
      systemSection(state);
    bindActionControls();
  }

  /* ---------- 快捷区域1：装备栏（拖动装备 / 脱下） ---------- */

  // 拖动中的东西：{from, id, name} —— from 是 'bag'（背包里的某一堆，带 sid）或装备位 id
  var dragItem = null;
  var dragSlot = null;   // 技能栏里正在拖的那一格（格子之间拖动＝交换，拖出去＝取消登记）
  var dragHandled = false;   // 这一次拖动有没有被某个格子 / 技能栏接住（没接住才是取消登记）

  function chip(name, detail, cls) {
    return '<span class="item-chip ' + (cls || '') + '" title="' + esc(name + (detail ? '（' + detail + '）' : '')) + '">' +
      '<span class="chip-name">' + esc(name) + '</span>' +
      (detail ? '<span class="chip-detail">' + esc(detail) + '</span>' : '') + '</span>';
  }

  function renderEquip(state) {
    if (!el.equipBody) return;
    var slots = state.equip_slots || [];
    if (el.equipGrip) el.equipGrip.textContent = state.grip || '徒手';

    var html = '<div class="equip-grid">';
    slots.forEach(function (s) {
      var item = s.item;
      html += '<div class="equip-slot' + (item ? ' filled' : '') + '" data-slot="' + esc(s.slot) +
        '" data-accepts="' + esc(s.kind) + '" title="' + esc(s.label + '：拖动物品放进来装备；把里面的东西拖出去就是脱下') + '">' +
        (item
          ? chip(item.name, item.detail, 'draggable') 
          : '<span class="slot-label">' + esc(s.label) + '</span><span class="slot-label">空</span>') +
        '</div>';
    });
    el.equipBody.innerHTML = html;
    bindEquipDrag();
  }

  // 装备位的方框：能接收拖动，也能把里面的东西拖出去
  function bindEquipDrag() {
    Array.prototype.forEach.call(el.equipBody.querySelectorAll('.equip-slot'), function (slot) {
      var slotId = slot.getAttribute('data-slot');
      var chipNode = slot.querySelector('.item-chip');
      if (chipNode) {
        chipNode.setAttribute('draggable', 'true');
        chipNode.addEventListener('dragstart', function (event) {
          var held = currentSlotItem(slotId);
          dragItem = { id: held ? held.id : slotId, name: held ? held.name : '',
                       from: slotId, count: 1 };
          chipNode.classList.add('dragging');
          if (event.dataTransfer) {
            event.dataTransfer.effectAllowed = 'move';
            // 同上：不给 text/plain，免得变成「拖文字」
            try { event.dataTransfer.setData('text/plain', ''); } catch (err) { /* 无所谓 */ }
          }
        });
        chipNode.addEventListener('dragend', function () {
          chipNode.classList.remove('dragging');
          dragItem = null;
          clearDropHints();
        });
      }
      slot.addEventListener('dragover', function (event) {
        if (!dragItem) return;
        event.preventDefault();
        slot.classList.remove('drop-ok', 'drop-no');
        slot.classList.add(canDrop(dragItem, slotId) ? 'drop-ok' : 'drop-no');
      });
      slot.addEventListener('dragleave', function () {
        slot.classList.remove('drop-ok', 'drop-no');
      });
      slot.addEventListener('drop', function (event) {
        event.preventDefault();
        event.stopPropagation();
        clearDropHints();
        if (!dragItem) return;
        if (!canDrop(dragItem, slotId)) {
          showToast('这个位置装不下' + dragItem.name);
          dragItem = null;
          return;
        }
        if (dragItem.from === slotId) { dragItem = null; return; }
        sendCommand('装备 ' + dragItem.name + handHint(dragItem, slotId));
        dragItem = null;
      });
    });
  }

  // 某件东西能不能放进这个装备位（背包里的看 slots，身上穿着的一样看 slots）
  function slotAccepts(item, slotId) {
    return !!(item && item.slots && item.slots.indexOf(slotId) >= 0);
  }

  // 能拿在手上的东西（武器、盾牌）：装备位下发的 slots 里带主手 / 副手
  function canHold(item) {
    return !!(item && item.slots &&
      (item.slots.indexOf('main_hand') >= 0 || item.slots.indexOf('off_hand') >= 0));
  }

  // 单手物：主手副手都能拿的那种（双手物只能拿在主手）。
  // 前端判断换手用这个，不再看是不是武器——盾牌也是单手物，一样能换手。
  function oneHanded(item) {
    return canHold(item) && item.slots.indexOf('off_hand') >= 0;
  }

  function bagItemById(itemId) {
    return ((lastState && lastState.inventory) || []).filter(function (x) { return x.id === itemId; })[0];
  }

  // 拖动的来源是背包里的某一堆时，拿它的数据；否则拿装备位上的
  function dragPayloadItem(drag) {
    if (!drag) return null;
    if (drag.from === 'bag') return stackBySid(lastState, drag.sid) || bagItemById(drag.id);
    var held = currentSlotItem(drag.from);
    return held || null;
  }

  function canDrop(drag, slotId) {
    var slot = equipSlotById(slotId);
    if (!slot) return false;
    if (drag.from === slotId) return false;
    var item = dragPayloadItem(drag);
    if (!item) return false;
    if (!slotAccepts(item, slotId)) return false;
    if (drag.from !== 'bag') {
      // 从别的装备位拖过来：对面那件也得能塞进这边，否则换手会换出个装不下的东西
      var other = slot.item;
      if (other) {
        var otherPayload = bagItemById(other.id) || other;
        if (!slotAccepts({ slots: otherPayload.slots || [] }, drag.from)) return false;
        // 换手：两只手上的东西都得是单手物（武器、盾牌都算）才换得动
        if (drag.from === 'main_hand' || drag.from === 'off_hand') {
          return oneHanded(item) && oneHanded(otherPayload);
        }
      }
    }
    return true;
  }

  // 武器 / 盾牌拖到哪只手的方框上，就让引擎放进哪只手；护甲 / 饰品不用带这个尾巴
  function handHint(drag, slotId) {
    if (slotId !== 'main_hand' && slotId !== 'off_hand') return '';
    var item = dragPayloadItem(drag);
    if (!canHold(item)) return '';
    return slotId === 'main_hand' ? ' 主手' : ' 副手';
  }

  function clearDropHints() {
    var roots = [el.equipBody, el.bagPanel, el.actionBody];
    roots.forEach(function (root) {
      if (!root) return;
      Array.prototype.forEach.call(root.querySelectorAll('.drop-ok, .drop-no'), function (n) {
        n.classList.remove('drop-ok', 'drop-no');
      });
    });
  }

  // 拖到装备栏以外的地方松手 = 脱下（挂在 document 上）
  document.addEventListener('dragover', function (event) {
    if (dragItem && dragItem.from !== 'bag' && el.equipBody &&
        !el.equipBody.contains(event.target)) {
      event.preventDefault();
    }
  });
  document.addEventListener('drop', function (event) {
    if (!dragItem) return;
    if (el.equipBody && el.equipBody.contains(event.target)) return;  // 装备栏自己处理
    if (dragItem.from === 'bag') { dragItem = null; return; }
    event.preventDefault();
    var name = dragItem.name;
    dragItem = null;
    sendCommand('卸下 ' + name);   // 拖出装备区域松手 = 脱下
    showToast('已脱下' + name);
  });

  /* ---------- 视图栏：场景 / 背包 / 技能树三个页签 ---------- */

  var VIEW_KEY = 'fengcheng.view';
  var VIEW_TABS = { scene: 1, bag: 1, skills: 1 };
  var viewMode = loadView();   // 'scene' = 场景，'bag' = 背包，'skills' = 技能树

  function loadView() {
    try {
      var saved = window.localStorage.getItem(VIEW_KEY);
      return VIEW_TABS[saved] ? saved : 'scene';
    } catch (err) { return 'scene'; }
  }

  function saveView() {
    try { window.localStorage.setItem(VIEW_KEY, viewMode); } catch (err) { /* 存不了就算了 */ }
  }

  function setView(mode) {
    viewMode = VIEW_TABS[mode] ? mode : 'scene';
    saveView();
    itemMenuSid = null;
    splitSid = null;
    thingMenuId = null;
    if (lastState) renderView(lastState);
  }

  // 这一栏要么显示场景，要么显示背包，要么显示技能树（不叠着来）
  function renderView(state) {
    var scene = viewMode === 'scene';
    var bagging = viewMode === 'bag';
    var skilling = viewMode === 'skills';
    if (el.bagPanel) el.bagPanel.classList.toggle('hidden', !bagging);
    if (el.skillPanel) el.skillPanel.classList.toggle('hidden', !skilling);
    if (el.scenePanel) el.scenePanel.classList.toggle('hidden', !scene);
    if (el.sceneBody) el.sceneBody.classList.toggle('hidden', !scene);
    // 地图和时钟装在场景面板里：切到背包 / 技能树时整个场景面板都收起来，
    // 背包格子和技能树按钮前面就没有东西挡着了
    if (el.viewMap) el.viewMap.classList.toggle('hidden', !scene);
    if (el.viewClock) el.viewClock.classList.toggle('hidden', !scene);
    if (el.viewTabs) {
      Array.prototype.forEach.call(el.viewTabs.querySelectorAll('.view-tab'), function (tab) {
        tab.classList.toggle('active', tab.getAttribute('data-view-tab') === viewMode);
      });
    }
    if (bagging) renderBag(state);
    else if (skilling) renderSkillPanel(state);
    else renderScene(state);
    renderMap(state);    // 地图是场景面板里单独的一块，场景重建不影响它，所以放在最后单独画
    renderClock(state);
  }

  /* ---------- 视图栏左边一列：区域地图（可以拖动平移、滚轮缩放） ---------- */

  // 一个方块多大（CSS 里的字号、方块高度都按这个比例缩放）
  // 方块做小：100% 时一层楼的整体结构就能在小地图里看全。方块里只写名字 + 出口箭头，
  // 全名和出口去哪儿放在 title 里（鼠标停一下就能看到）
  var MAP_CELL = 34;
  var MAP_CELL_H = 26;
  var MAP_GAP = 8;
  var MAP_PAD = 5;

  // 地图那一列多宽多高由 style.css 的 --w-map / --h-map 定死（换楼层 / 换建筑都不变），
  // 这里只读它量出来的可视窗口大小，不再自己按比例算

  var MAP_SCALE_STEP = 1.12;
  // 方块本身已经很小（100% 就能看全一层），放大到 3 倍可以看清名字和出口
  var MAP_SCALE_MIN = 0.6;
  var MAP_SCALE_MAX = 3;

  var mapScale = 1;         // 缩放比例（1 = 方块原大小）
  var mapPan = { x: 0, y: 0 };   // 地图相对窗口左上角平移了多少像素
  var mapSpan = { w: 0, h: 0 };  // 整张地图多大（不随楼层变）
  var mapBounds = { min_x: 0, min_y: 0, w: 1, h: 1 };  // 地图的格子范围（后端算好）
  var mapViewportSize = { w: 0, h: 0 };                // 可视窗口的像素大小
  var mapGroupWanted = null;     // 手动看哪一栋（点楼层条时按那层所在的建筑定）
  var mapPlayersArea = null;     // 上一次人物所在的楼层（换了就把地图跟回去）
  var mapAreaWanted = null;      // 手动看哪一层（点楼层条时记下来）
  var mapFollowKey = null;       // 上一次自动跟到哪个房间（人物一换房间就把地图挪过去）
  var mapCenterRoom = null;      // 下一次重画要把哪间房摆到窗口中间（重画完清掉）

  // 下次重画时把某间房摆到窗口中间；room 为空就只把它所属的那一栋切过去
  function lookAtRoom(groupName, room) {
    mapGroupWanted = groupName || null;
    mapCenterRoom = room || null;
    if (lastState) renderMap(lastState);
  }

  function mapScaleOf() { return mapScale; }
  function mapStep() { return (MAP_CELL + MAP_GAP) * mapScale; }
  function mapStepY() { return (MAP_CELL_H + MAP_GAP) * mapScale; }

  // 整张地图的像素尺寸：按所有建筑、所有的层里的最大范围算，所以换楼层尺寸不变
  function mapContentSize() {
    return {
      w: (MAP_PAD * 2 + mapSpan.w * MAP_CELL + (mapSpan.w - 1) * MAP_GAP) * mapScale,
      h: (MAP_PAD * 2 + mapSpan.h * MAP_CELL_H + (mapSpan.h - 1) * MAP_GAP) * mapScale
    };
  }

  // 方向 → 方块上那个小箭头
  var MAP_ARROW = { north: '↑', south: '↓', east: '→', west: '←', up: '↑', down: '↓' };

  // 一个地点（方框）：名字 + 出口。出口直接写下一个场景的名字，不用「门」这种符号。
  function mapRoomBlock(room) {
    var cls = 'map-room';
    if (room.visited) cls += ' visited';
    if (room.current) cls += ' current';
    var html = '<span class="map-room-name">' + esc(room.name) + '</span>';
    var exits = room.exits || [];
    if (exits.length) {
      html += '<span class="map-room-exits">';
      exits.forEach(function (e) {
        var state = e.blocked ? 'blocked' : 'open';
        var arrow = MAP_ARROW[e.id] || '·';
        html += '<button type="button" class="map-exit ' + state + '"' +
          (e.blocked ? ' disabled' : '') + ' data-map-go="' + esc(e.id) + '"' +
          ' title="' + esc(e.name + (e.blocked ? '：现在过不去' : '：点一下走过去')) + '">' +
          arrow + '</button>';
      });
      html += '</span>';
    }
    return '<div class="' + cls + '" title="' + esc(room.name + (room.current ? '（你在这儿）' : '')) + '">' +
      '<span class="map-at" title="你现在在这儿">◆</span>' + html + '</div>';
  }

  // 房间之间通不通：横的看东西，竖的看南北；连线在两格之间的空隙里
  function mapLine(grid, kind, x, y) {
    var ax = x, ay = y, bx = x, by = y;
    if (kind === 'h') bx = x + 1; else by = y + 1;
    if (!grid[ax + ',' + ay] || !grid[bx + ',' + by]) return '';
    // 连线画在两个方块之间的空隙里（坐标和方块一样，先减掉地图的最小坐标）
    var scale = mapScaleOf();
    var cw = MAP_CELL * scale, ch = MAP_CELL_H * scale;
    var cx = mapStep() * ((x - mapBounds.min_x) + 0.5);    // 这一格方块的中心
    var cy = mapStepY() * ((y - mapBounds.min_y) + 0.5);
    var left, top, w, h;
    if (kind === 'h') {
      left = cx + cw / 2;
      top = cy - 1;
      w = mapStep() - cw;
      h = 2;
    } else {
      left = cx - 1;
      top = cy + ch / 2;
      w = 2;
      h = mapStepY() - ch;
    }
    return '<span class="map-link ' + kind + '" style="left:' + left.toFixed(1) + 'px;top:' +
      top.toFixed(1) + 'px;width:' + w.toFixed(1) + 'px;height:' + h.toFixed(1) + 'px"></span>';
  }

  // 可视窗口的大小：CSS 定死的（--w-map / --h-map），这里只量一下给夹取用
  function sizeMapViewport() {
    if (!el.mapViewport) return;
    var box = el.mapViewport.getBoundingClientRect();
    var w = Math.round(box.width), h = Math.round(box.height);
    // 页签不在「场景」上时整块是 display:none，量出来是 0：那就留着上次的大小，别把平移夹坏
    if (w > 0 && h > 0) mapViewportSize = { w: w, h: h };
  }

  // 平移的范围：地图最边上的那间房也能被摆到窗口正中（所以人物所在的房间永远可以居中），
  // 再往外就不让拖了，免得整张地图被拖丢
  function clampMapPan() {
    var vp = mapViewportSize;
    var size = mapContentSize();
    var x = Math.min(vp.w / 2, Math.max(vp.w / 2 - size.w, mapPan.x));
    var y = Math.min(vp.h / 2, Math.max(vp.h / 2 - size.h, mapPan.y));
    mapPan.x = Math.round(x);
    mapPan.y = Math.round(y);
  }

  // 把地图挪到某一格（一间房）正中间，并夹回可视范围里
  function centerMapOn(room) {
    var vp = mapViewportSize;
    mapPan.x = vp.w / 2 - mapStep() * ((room.x - mapBounds.min_x) + 0.5);
    mapPan.y = vp.h / 2 - mapStepY() * ((room.y - mapBounds.min_y) + 0.5);
    clampMapPan();
  }

  // 地图重画：地图挂在场景面板上，不跟着页签、也不跟着场景重建，所以自己重画自己
  function renderMap(state) {
    if (!el.viewMap || !el.mapBody || !el.mapViewport) return;
    var map = state && state.map;
    if (!map || !map.groups || !map.groups.length) {
      el.viewMap.classList.add('hidden');
      return;
    }
    el.viewMap.classList.remove('hidden');
    mapBounds = map.bounds || { min_x: 0, min_y: 0, w: 1, h: 1 };
    mapSpan = { w: Math.max(1, mapBounds.w || 1), h: Math.max(1, mapBounds.h || 1) };

    // 人物换了一栋楼，就把地图跟过去（手动看别栋的让位给当前这栋）。
    // 注意：这里比的是「上一次人物所在的楼层」，不能跟当前显示的那一层混着用，
    // 否则每次重画都会把手动选的那层清掉（点楼层条就永远切不过去）。
    if (map.current_area !== mapPlayersArea) {
      mapPlayersArea = map.current_area;
      mapGroupWanted = null;
      mapAreaWanted = null;
    }
    var group = null;
    if (mapGroupWanted) {
      for (var i = 0; i < map.groups.length; i++) {
        if (map.groups[i].name === mapGroupWanted) { group = map.groups[i]; break; }
      }
    }
    if (!group) group = map.groups[map.group] || map.groups[0];
    var areas = group.areas || [];
    // 先看手动选的那一层（点楼层条换的），没有就跟人物当前那一层，再不行就这栋楼的第一层
    var area = null;
    var wanted = [mapAreaWanted, map.current_area];
    for (var n = 0; n < wanted.length && !area; n++) {
      if (!wanted[n]) continue;
      for (var i = 0; i < areas.length; i++) {
        if (areas[i].name === wanted[n]) { area = areas[i]; break; }
      }
    }
    if (!area) {
      for (var i = 0; i < areas.length; i++) {
        if (areas[i].rooms && areas[i].rooms.length) { area = areas[i]; break; }
      }
    }
    if (!area) area = areas[0];
    if (!area) { el.viewMap.classList.add('hidden'); return; }

    // 标题这一行窄，完整层名放进 title，鼠标停一下能看全
    if (el.mapArea) {
      el.mapArea.textContent = area.name;
      el.mapArea.title = area.name;
    }

    // 人物换了房间（换楼也算）：待会儿把窗口挪到他那间房上，一眼就看得出自己在哪儿
    var here = null;
    (area.rooms || []).forEach(function (r) { if (r.current) here = r; });
    var key = map.current_area + '/' + (here ? here.id : '');
    if (here && key !== mapFollowKey) {
      mapFollowKey = key;
      mapCenterRoom = here;
    }

    var scale = mapScaleOf();
    var grid = {};
    (area.rooms || []).forEach(function (r) { grid[r.x + ',' + r.y] = r; });

    var html = '';
    (area.links || []).forEach(function (l) { html += mapLine(grid, l[0], l[1], l[2]); });
    (area.rooms || []).forEach(function (r) {
      var left = mapStep() * ((r.x - mapBounds.min_x) + 0.5) - (MAP_CELL * scale) / 2;
      var top = mapStepY() * ((r.y - mapBounds.min_y) + 0.5) - (MAP_CELL_H * scale) / 2;
      html += '<div class="map-cell" style="left:' + left.toFixed(1) + 'px;top:' + top.toFixed(1) +
        'px;width:' + (MAP_CELL * scale) + 'px">' + mapRoomBlock(r) + '</div>';
    });

    var size = mapContentSize();
    el.mapBody.style.width = size.w + 'px';
    el.mapBody.style.height = size.h + 'px';
    el.mapBody.innerHTML = html;
    el.mapBody.style.setProperty('--map-room-h', (MAP_CELL_H * scale).toFixed(1) + 'px');
    el.mapBody.style.setProperty('--map-name-size', Math.max(6, 8 * scale).toFixed(1) + 'px');
    el.mapBody.style.setProperty('--map-exit-size', Math.max(6, 7 * scale).toFixed(1) + 'px');

    sizeMapViewport();
    if (mapCenterRoom) { centerMapOn(mapCenterRoom); mapCenterRoom = null; }
    clampMapPan();
    el.mapBody.style.transform = 'translate(' + mapPan.x + 'px,' + mapPan.y + 'px)';
    el.viewMap.classList.toggle('map-zoomed', Math.abs(scale - 1) > 0.01);
    if (el.mapZoom) el.mapZoom.textContent = Math.round(scale * 100) + '%';

    // 楼层切换条：这一栋里每一层一条，点了就把地图切过去看（不影响人物站在哪儿）。
    // 这一条的高度是写死的（只有一层也留着地方），这样换楼层 / 换建筑时地图可视窗口大小不变。
    // 地图那一列窄，所以按钮上只写楼层（「4F」「B1」）—— 建筑名已经写在上面一行了
    if (el.mapFloors) {
      var floors = '';
      areas.forEach(function (a) {
        var here = false;
        (a.rooms || []).forEach(function (r) { if (r.current) here = true; });
        var on = (a.name === area.name);
        // 地图那一列窄，按钮上只写楼层（「4F」「B1」「街道一带」这种没有空格的照旧）——
        // 建筑名已经写在地图上面那一行了；完整层名还在 data-map-area 和 title 里
        var label = a.name;
        var parts = label.split(/[\s\u3000]+/);
        if (parts.length > 1 && parts[parts.length - 1]) label = parts[parts.length - 1];
        floors += '<button type="button" class="map-floor' + (on ? ' on' : '') + (here ? ' here' : '') +
          '" data-map-area="' + esc(a.name) + '" title="' +
          esc(a.name + (here ? '（你在这层）' : '') + '：点一下看这层的地图') + '">' +
          esc(label) + '</button>';
      });
      if (areas.length < 2) floors += '<span class="map-floor-none">只有这一层</span>';
      el.mapFloors.innerHTML = floors;
    }
  }

  // 换一层楼：只重画地图，并把新看的那层摆到窗口中间（点楼层条不影响人物站在哪儿）
  function setMapArea(name) {
    if (!lastState || !lastState.map) return;
    var found = null;
    (lastState.map.groups || []).forEach(function (g) {
      (g.areas || []).forEach(function (a) {
        if (a.name !== name || found) return;
        var here = null;
        (a.rooms || []).forEach(function (r) { if (r.current) here = r; });
        found = { group: g.name, room: here || (a.rooms || [])[0] || null, area: a.name };
      });
    });
    if (!found) return;
    mapAreaWanted = found.area;
    lookAtRoom(found.group, found.room);
  }

  // 复位：缩放回 100%，并把地图摆回人物所在的那间房（按钮上的提示就是这么写的）。
  // 光清 mapCenterRoom 不够 —— 那样只是把平移留着不动，人物那间房有可能已经被拖到窗口外了，
  // 所以连 mapFollowKey 一起清掉，让下一次重画重新跟一次人物。
  function resetMapView() {
    mapScale = 1;
    mapCenterRoom = null;
    mapFollowKey = null;
    if (lastState) renderMap(lastState);
  }

  /* ---------- 视图栏的背包面板：一格一堆，翻页 / 点菜单 / 拖动 ---------- */

  var BAG_PER_PAGE = 48;
  var splitValue = 1;   // 拆分弹窗里当前选的数量

  function stackBySid(state, sid) {
    var inv = (state && state.inventory) || [];
    for (var i = 0; i < inv.length; i++) {
      if (inv[i].sid === sid) return inv[i];
    }
    return null;
  }

  // 背包里同一种东西占了几格（≥2 才谈得上堆叠）
  function stackCount(state, itemId) {
    var inv = (state && state.inventory) || [];
    var n = 0;
    for (var i = 0; i < inv.length; i++) {
      if (inv[i].id === itemId) n++;
    }
    return n;
  }

  function bagTop(state, inv) {
    var carry = (state && state.carry) || {};
    return '<div class="bag-top"><span>背包：' + esc(carry.slots || 0) + ' 件 · 占 ' +
      inv.length + ' 格</span>' + loadTag(carry.label) +
      '<span class="bag-weight">负重 ' + esc(carry.weight) + ' / ' + esc(carry.capacity) +
      ' kg</span></div>';
  }

  // 一格 = 一堆东西：小方块里写名字，右上角是数量，点一下才出菜单
  function bagCell(item) {
    var cls = 'bag-cell' + (itemMenuSid === item.sid ? ' sel' : '');
    var title = item.name + (item.count > 1 ? ' ×' + item.count : '') +
      '（' + item.detail + '，' + item.weight + ' kg/个）';
    if (item.usable && item.use_hint) title += '　' + item.use_hint;
    return '<div class="' + cls + '" data-sid="' + item.sid + '" data-item="' + esc(item.id) +
      '" draggable="true" title="' + esc(title) + '">' +
      '<span class="bag-icon">' + esc(item.name) + '</span>' +
      (item.count > 1 ? '<span class="bag-count">×' + item.count + '</span>' : '') +
      (item.stackable && !item.auto
        ? '<span class="bag-loose" title="手动拆出来的这一堆，不会被自动堆叠">散</span>' : '') +
      '<span class="bag-name">' + esc(item.detail) + '</span></div>';
  }

  function bagPager(pages, inv) {
    return '<div class="bag-pager">' +
      '<button type="button" class="btn small" data-bag-page="prev"' +
      (bagPage <= 0 ? ' disabled' : '') + '>‹ 上一页</button>' +
      '<span class="page-now">第 ' + (bagPage + 1) + ' / ' + pages + ' 页 · 共 ' + inv.length + ' 格</span>' +
      '<button type="button" class="btn small" data-bag-page="next"' +
      (bagPage >= pages - 1 ? ' disabled' : '') + '>下一页 ›</button></div>';
  }

  // 点物品弹出来的菜单：查看 / 使用 / 装备 / 拆分 / 快捷栏 / 丢弃
  function itemMenu(state) {
    var item = stackBySid(state, itemMenuSid);
    if (!item) return '';
    var at = slotIndexOf('item', item.id);
    var html = '<div class="bag-menu" id="bag-menu"><div class="menu-title">' + esc(item.name) +
      (item.count > 1 ? ' <small>×' + item.count + '</small>' : '') +
      '<br><small>' + esc(item.detail) + ' · ' + esc(item.weight) + ' kg/个</small></div>';
    html += '<button type="button" data-bag-act="look">' + icon('look') + '<span>查看</span></button>';
    if (item.usable) {
      html += '<button type="button" data-bag-act="use">' + icon('use') + '<span>使用</span></button>';
    }
    if (item.slots && item.slots.length) {
      html += '<button type="button" data-bag-act="equip">' + icon('equip') + '<span>装备</span></button>';
    }
    html += '<div class="menu-sep"></div>';
    if (item.stackable && item.count > 1) {
      html += '<button type="button" data-bag-act="split">' + icon('split') +
        '<span>拆分…</span></button>';
    }
    if (stackCount(state, item.id) > 1) {
      html += '<button type="button" data-bag-act="stack">' + icon('stack') +
        '<span>堆叠</span></button>';
    }
    html += '<button type="button" data-bag-act="pin">' + icon('bag') + '<span>' +
      (at >= 0 ? '已在技能栏第 ' + (at % SLOT_PER_PAGE + 1) + ' 格（再点取消）' : '登记到技能栏') +
      '</span></button>';
    html += '<div class="menu-sep"></div>';
    html += '<button type="button" class="danger" data-bag-act="drop">' + icon('drop') +
      '<span>丢弃 1 个</span></button>';
    if (item.count > 1) {
      html += '<button type="button" class="danger" data-bag-act="dropall">' + icon('drop') +
        '<span>丢弃全部 ×' + item.count + '</span></button>';
    }
    return html + '</div>';
  }

  // 拆分：滑条和输入框都能改数量
  function splitBox(state) {
    var item = stackBySid(state, splitSid);
    if (!item) return '';
    var max = item.count - 1;
    if (splitValue > max) splitValue = max;
    if (splitValue < 1) splitValue = 1;
    return '<div class="bag-split">' +
      '<span>' + esc(item.name) + ' 这堆 ' + item.count + ' 个，拆出</span>' +
      '<input type="range" id="split-range" min="1" max="' + max + '" step="1" value="' +
      splitValue + '" title="拖动选择拆出几个">' +
      '<input type="number" id="split-num" min="1" max="' + max + '" step="1" value="' +
      splitValue + '" title="也可以直接填个数">' +
      '<span>个</span>' +
      '<button type="button" class="btn small primary" id="split-ok">' + icon('check') +
      '<span>拆分</span></button>' +
      '<button type="button" class="btn small" data-split-cancel="1">' + icon('x') +
      '<span>取消</span></button></div>';
  }

  function renderBag(state) {
    if (!el.bagPanel) return;
    var inv = (state && state.inventory) || [];
    var pages = Math.max(1, Math.ceil(inv.length / BAG_PER_PAGE));
    if (bagPage > pages - 1) bagPage = pages - 1;
    if (bagPage < 0) bagPage = 0;
    if (itemMenuSid !== null && !stackBySid(state, itemMenuSid)) itemMenuSid = null;
    if (splitSid !== null && !stackBySid(state, splitSid)) splitSid = null;
    var slice = inv.slice(bagPage * BAG_PER_PAGE, (bagPage + 1) * BAG_PER_PAGE);

    var html = bagTop(state, inv) +
      '<p class="hint-small">点物品出菜单（查看 / 使用 / 拆分 / 堆叠 / 丢弃）；拖到左边装备框＝装备，' +
      '拖到同种物品上＝叠成一堆，拖到技能栏（下排中间）＝登记到技能格子。</p>' +
      '<div class="bag-grid" id="bag-grid">';
    if (!inv.length) html += '<span class="bag-empty">背包是空的。捡东西、或者从身上脱下装备都会回到这里。</span>';
    slice.forEach(function (item) { html += bagCell(item); });
    if (itemMenuSid !== null) html += itemMenu(state);
    html += '</div>' + bagPager(pages, inv);
    if (splitSid !== null) html += splitBox(state);
    el.bagPanel.innerHTML = html;
    bindBag();
    bindSplitBox();
  }

  function bindBag() {
    var grid = document.getElementById('bag-grid');
    if (!grid) return;
    placeItemMenu(grid);

    // 点空白处把菜单 / 拆分条收起来
    grid.addEventListener('click', function (event) {
      if (event.target !== grid) return;
      if (itemMenuSid === null && splitSid === null) return;
      itemMenuSid = null;
      splitSid = null;
      renderBag(lastState);
    });

    Array.prototype.forEach.call(grid.querySelectorAll('.bag-cell'), function (cell) {
      var sid = parseInt(cell.getAttribute('data-sid'), 10);
      var item = stackBySid(lastState, sid);
      if (!item) return;

      cell.addEventListener('click', function (event) {
        if (event.target.closest && event.target.closest('.bag-menu')) return;
        itemMenuSid = (itemMenuSid === sid) ? null : sid;
        splitSid = null;
        renderBag(lastState);
      });
      cell.addEventListener('dragstart', function (event) {
        // kind/cmd 是给技能栏格子登记用的（点一下就用 / 装备 / 查看）
        dragItem = { from: 'bag', sid: sid, id: item.id, name: item.name, count: item.count,
                     kind: 'item', cmd: (item.quick && item.quick.cmd) || ('查看 ' + item.name) };
        cell.classList.add('dragging');
        if (event.dataTransfer) {
          event.dataTransfer.effectAllowed = 'move';
          // 同上：不给 text/plain，免得变成「拖文字」
          try { event.dataTransfer.setData('text/plain', ''); } catch (err) { /* 无所谓 */ }
        }
      });
      cell.addEventListener('dragend', function () {
        cell.classList.remove('dragging');
        dragItem = null;
        clearDropHints();
      });
      // 拖到同种物品上：两堆摞起来
      cell.addEventListener('dragover', function (event) {
        if (!dragItem) return;
        event.preventDefault();
        cell.classList.remove('drop-ok', 'drop-no');
        var same = dragItem.from === 'bag' && dragItem.id === item.id && dragItem.sid !== sid;
        cell.classList.add(same ? 'drop-ok' : 'drop-no');
      });
      cell.addEventListener('dragleave', function () {
        cell.classList.remove('drop-ok', 'drop-no');
      });
      cell.addEventListener('drop', function (event) {
        event.preventDefault();
        event.stopPropagation();
        cell.classList.remove('drop-ok', 'drop-no');
        if (!dragItem) return;
        var from = dragItem;
        dragItem = null;
        if (from.from !== 'bag') { showToast('身上的装备要先脱下来，才进得了背包。'); return; }
        if (from.id !== item.id) { showToast('只有同一种东西才摞得起来。'); return; }
        if (from.sid === sid) return;
        sendCommand('堆叠 ' + from.sid + ' ' + sid);
      });
    });
  }

  // 菜单跟着点开的那一格走；贴边时往回收一收，别跑出面板
  function placeItemMenu(grid) {
    var menu = document.getElementById('bag-menu');
    var cell = grid.querySelector('.bag-cell.sel');
    if (!menu || !cell) return;
    var left = cell.offsetLeft + cell.offsetWidth + 6;
    if (left + menu.offsetWidth > grid.clientWidth + grid.scrollLeft) {
      left = Math.max(2, cell.offsetLeft - menu.offsetWidth - 6);
    }
    var top = cell.offsetTop;
    if (top + menu.offsetHeight > grid.scrollHeight) {
      top = Math.max(2, grid.scrollHeight - menu.offsetHeight - 2);
    }
    menu.style.left = left + 'px';
    menu.style.top = top + 'px';
  }

  // 技能栏格子里的东西怎么登记：见上面「技能栏的登记格子」一节
  function currentSlotItem(slotId) {
    var slot = equipSlotById(slotId);
    return slot && slot.item ? slot.item : null;
  }

  function equipSlotById(slotId) {
    return ((lastState && lastState.equip_slots) || []).filter(function (s) { return s.slot === slotId; })[0];
  }

  /* ---------- 视图栏：格子场景 ---------- */

  function sceneDirName(id) {
    return { north: '北', south: '南', east: '东', west: '西', up: '上', down: '下' }[id] || id;
  }

  function renderScene(state) {
    if (!el.sceneBody) return;
    var sc = state && state.scene;
    if (!sc) {
      el.sceneBody.innerHTML = '<span class="empty">这个地点还没有场景图；用方向键走动，或者点场景里能走的格子。</span>';
      return;
    }
    var things = {};
    (sc.things || []).forEach(function (t) { things[t.x + ',' + t.y] = t; });
    var doors = {};
    (state.exits || []).forEach(function (e) { if (e.tile === 'door' || e.tile === 'stairs') doors[e.id] = e; });
    var doorTiles = {};
    Object.keys(sc.doors || {}).forEach(function (dir) { doorTiles[sc.doors[dir].join(',')] = dir; });
    var px = sc.player[0], py = sc.player[1];
    // 菜单开着的那件东西如果已经不在这一格了（拿走了 / 换了房间），自动关掉
    if (thingMenuId && !sceneThing(state, thingMenuId)) thingMenuId = null;

    var html = '<div class="scene-grid" style="--scene-w:' + sc.width + '">';
    for (var y = 0; y < sc.height; y++) {
      var row = sc.tiles[y] || '';
      for (var x = 0; x < sc.width; x++) {
        var ch = row.charAt(x) || '#';
        var key = x + ',' + y;
        var cls = 'scene-cell';
        var inner = '';
        var here = things[key] || null;
        var thing = null;
        if (ch === '#') cls += ' wall';
        else if (ch === '~') cls += ' obstacle';
        else { cls += ' walkable'; }
        if (ch === '+') cls += ' door';
        else if (ch === '<' || ch === '>') cls += ' stairs';
        else if (ch === '.') cls += ' floor';

        var title = '';
        if (x === px && y === py) {
          cls += ' player-here';
          if (here) {
            // 人和东西挤在同一格：方块写东西的名字（点一下就能拿），别让它看不见
            thing = here;
            inner = chip(here.name, '我在这里', 'chip-player' + (here.kind === 'npc' ? ' chip-npc' : ''));
            title = (here.kind === 'npc' ? '人物：' : '物品：') + here.name + '（你正站在这一格）';
          } else {
            inner = chip('我', '', 'chip-player');
            title = '你现在站在这里';
          }
        } else if (here && here.kind === 'enemy') {
          thing = here;
          inner = chip(here.name, here.hp + '/' + here.max_hp, 'chip-enemy' + (here.aware ? '' : ' chip-unaware'));
          title = '敌人：' + here.name + '（生命 ' + here.hp + '/' + here.max_hp + (here.aware ? '' : '，还没发现你') + '；点一下出菜单）';
        } else if (here) {
          thing = here;
          inner = chip(here.name, '', here.kind === 'npc' ? 'chip-npc' : '');
          title = (here.kind === 'npc' ? '人物：' : '物品：') + here.name + '（点一下出菜单）';
        } else {
          var dir = doorTiles[key];
          if (dir) {
            var exit = doors[dir] || {};
            var label = exit.target ? exit.target : sceneDirName(dir);
            inner = chip((ch === '<' ? '上楼 ' : ch === '>' ? '下楼 ' : '门 ') + label, '', 'chip-stairs');
            title = '出口：' + sceneDirName(dir) + (exit.target ? ' → ' + exit.target : '');
            if (exit.danger) title += '（' + exit.danger + '）';
          } else if (ch === '<' || ch === '>') {
            inner = chip(ch === '<' ? '上楼' : '下楼', '', 'chip-stairs');
          }
        }
        if (title) title = title.replace(/"/g, '');
        var attrs = ' data-x="' + x + '" data-y="' + y + '"';
        if (thing) {
          cls += ' has-thing' + (thingMenuId === thing.id ? ' thing-sel' : '');
          attrs += ' data-thing="' + esc(thing.id) + '"';
        }
        html += '<div class="' + cls + '"' + attrs + ' title="' + esc(title) + '">' + inner + '</div>';
      }
    }
    html += '</div>';
    // 地图与时钟不在这儿：它们是视图栏上的浮层（renderMap / renderClock），
    // 场景重画不会把它们一起清掉。这里只画场景本体 + 颜色图例 + 点东西的菜单
    el.sceneBody.innerHTML = html + sceneLegend() + thingMenu(state);
    bindScene();
    placeThingMenu();
  }

  // 颜色图例：视图栏最下面一条（以前跟地图并排，把地图挤到右边去了）
  function sceneLegend() {
    return '<div class="scene-legend">' +
      '<span class="lg"><span class="swatch" style="background:#1b2028"></span>墙</span>' +
      '<span class="lg"><span class="swatch" style="background:#23242b"></span>障碍物</span>' +
      '<span class="lg"><span class="swatch" style="background:#10141a"></span>地板</span>' +
      '<span class="lg"><span class="swatch" style="background:#2a2418"></span>门 / 楼梯</span>' +
      '<span class="lg lg-note">黑底白字方块 = 人物与物品（点一下出菜单）</span></div>';
  }

  // 场景里的某件东西（按 id 找，拿走了就找不到）
  function sceneThing(state, id) {
    if (!id) return null;
    var list = (state && state.scene && state.scene.things) || [];
    for (var i = 0; i < list.length; i++) {
      if (list[i].id === id) return list[i];
    }
    return null;
  }

  // 点场景里的物品 / 人物弹出的小菜单：拿取（或说话）/ 查看
  function thingMenu(state) {
    var t = sceneThing(state, thingMenuId);
    if (!t) return '';
    if (t.kind === 'enemy') {
      return '<div class="bag-menu scene-menu" id="scene-menu">' +
        '<div class="menu-title">' + esc(t.name) + '<br><small>敌人 · 生命 ' + t.hp + '/' + t.max_hp +
        (t.aware ? '' : ' · 还没发现你') + '</small></div>' +
        '<button type="button" data-scene-act="attack" data-scene-name="' + esc(t.name) + '">' +
        icon('stance') + '<span>' + (t.aware ? '攻击' : '偷袭') + '</span></button>' +
        '<button type="button" data-scene-act="look" data-scene-name="' + esc(t.name) + '">' +
        icon('look') + '<span>查看</span></button></div>';
    }
    var html = '<div class="bag-menu scene-menu" id="scene-menu">' +
      '<div class="menu-title">' + esc(t.name) + '<br><small>' +
      (t.kind === 'npc' ? '这里的人' : '地上的东西') + '</small></div>';
    // 拿取 / 说话要走到跟前（同格或相邻一格，斜角也算）：不在跟前就先给一个「走过去」
    var sc = state && state.scene;
    var onTile = sc && sc.player[0] === t.x && sc.player[1] === t.y;
    if (!onTile) {
      html += '<button type="button" data-scene-act="move" data-scene-name="' + esc(t.name) + '">' +
        icon('map') + '<span>走过去</span></button>';
    }
    if (t.kind === 'npc') {
      html += '<button type="button" data-scene-act="talk" data-scene-name="' + esc(t.name) + '">' +
        icon('talk') + '<span>说话</span></button>';
    } else {
      html += '<button type="button" data-scene-act="take" data-scene-name="' + esc(t.name) + '">' +
        icon('take') + '<span>拿取</span></button>';
    }
    html += '<button type="button" data-scene-act="look" data-scene-name="' + esc(t.name) + '">' +
      icon('look') + '<span>查看</span></button>';
    return html + '</div>';
  }

  // 菜单贴着点开的那一格；贴边时往回收，别跑出视图栏
  function placeThingMenu() {
    var menu = document.getElementById('scene-menu');
    if (!menu || !thingMenuId) return;
    var cell = el.sceneBody.querySelector('.scene-cell.thing-sel');
    if (!cell) return;
    var wrap = el.sceneBody;
    var cr = cell.getBoundingClientRect();
    var wr = wrap.getBoundingClientRect();
    var left = cr.right - wr.left + wrap.scrollLeft + 6;
    if (left + menu.offsetWidth > wrap.clientWidth + wrap.scrollLeft) {
      left = Math.max(2, cr.left - wr.left + wrap.scrollLeft - menu.offsetWidth - 6);
    }
    var top = cr.top - wr.top + wrap.scrollTop;
    if (top + menu.offsetHeight > wrap.clientHeight + wrap.scrollTop) {
      top = Math.max(2, wrap.clientHeight + wrap.scrollTop - menu.offsetHeight - 2);
    }
    menu.style.left = left + 'px';
    menu.style.top = top + 'px';
  }

  // 地图上的交互：
  //   · 拖动 = 平移视角（鼠标按住地图往哪边拖，地图就往哪边走）
  //   · 滚轮 = 缩放（以鼠标指着的那一点为中心，最多 42% ~ 180%）
  //   · 点出口 = 往那个方向走；点楼层切换条 = 换一层看；点「复位」= 回 100% 并居中
  function bindMap() {
    if (!el.viewMap || el.viewMap.getAttribute('data-map-bound')) return;
    el.viewMap.setAttribute('data-map-bound', '1');

    el.viewMap.addEventListener('click', function (event) {
      var node = event.target;
      while (node && node !== el.viewMap) {
        if (node.getAttribute) {
          var go = node.getAttribute('data-map-go');
          if (go) {
            if (!node.disabled) sendCommand('走 ' + sceneDirName(go));
            return;
          }
          var area = node.getAttribute('data-map-area');
          if (area) { setMapArea(area); return; }
        }
        node = node.parentNode;
      }
    });

    // 拖动平移（指针事件：鼠标 / 触摸 / 触控笔都走这一套）
    if (el.mapViewport) {
      var drag = null;
      var moved = false;
      // 注意：这里不能用 setPointerCapture —— 捕获以后 pointerup 会被重定向到窗口本身，
      // 浏览器就把紧随其后的 click 派发到窗口（而不是被点的那个出口胶囊），
      // 于是「点地图上的出口走过去」永远没反应。改成拖动期间在 window 上收事件。
      var onDragMove = function (event) {
        if (!drag || event.pointerId !== drag.id) return;
        var x = event.clientX - drag.dx, y = event.clientY - drag.dy;
        if (Math.abs(x - mapPan.x) > 2 || Math.abs(y - mapPan.y) > 2) moved = true;
        mapPan.x = x;
        mapPan.y = y;
        clampMapPan();
        el.mapBody.style.transform = 'translate(' + mapPan.x + 'px,' + mapPan.y + 'px)';
      };
      var endDrag = function (event) {
        if (!drag || (event && event.pointerId !== drag.id)) return;
        drag = null;
        el.mapViewport.classList.remove('dragging');
        window.removeEventListener('pointermove', onDragMove);
        window.removeEventListener('pointerup', endDrag);
        window.removeEventListener('pointercancel', endDrag);
      };
      el.mapViewport.addEventListener('pointerdown', function (event) {
        if (event.button !== 0) return;
        drag = { dx: event.clientX - mapPan.x, dy: event.clientY - mapPan.y, id: event.pointerId };
        moved = false;
        el.mapViewport.classList.add('dragging');
        window.addEventListener('pointermove', onDragMove);
        window.addEventListener('pointerup', endDrag);
        window.addEventListener('pointercancel', endDrag);
      });
      // 拖过就别把这一次当成点击（避免手一抖走出去一格）
      el.mapViewport.addEventListener('click', function (event) {
        if (!moved) return;
        moved = false;
        event.preventDefault();
        event.stopPropagation();
      }, true);

      // 滚轮缩放：以鼠标指着的那一点为中心
      el.mapViewport.addEventListener('wheel', function (event) {
        var next = mapScale * (event.deltaY < 0 ? MAP_SCALE_STEP : 1 / MAP_SCALE_STEP);
        next = Math.max(MAP_SCALE_MIN, Math.min(MAP_SCALE_MAX, next));
        if (Math.abs(next - mapScale) < 0.001) return;
        event.preventDefault();
        var rect = el.mapViewport.getBoundingClientRect();
        var px = event.clientX - rect.left;
        var py = event.clientY - rect.top;
        var ratio = next / mapScale;
        mapScale = next;
        mapPan.x = px - (px - mapPan.x) * ratio;
        mapPan.y = py - (py - mapPan.y) * ratio;
        if (lastState) renderMap(lastState);
      }, { passive: false });
    }

    if (el.mapReset) el.mapReset.addEventListener('click', resetMapView);
  }

  function bindScene() {
    // 说话时点视图栏任意位置 = 继续下一句。捕获阶段就动手，免得同时把角色走了一格。
    var viewRoot = document.querySelector('[data-region="视图栏"]');
    if (viewRoot && !viewRoot.getAttribute('data-talk-bound')) {
      viewRoot.setAttribute('data-talk-bound', '1');
      viewRoot.addEventListener('click', function (event) {
        if (!clickTalkBanner(event)) return;
        event.preventDefault();
        event.stopPropagation();
      }, true);
    }
    Array.prototype.forEach.call(el.sceneBody.querySelectorAll('.scene-cell'), function (cell) {
      var thingId = cell.getAttribute('data-thing');
      if (thingId) {
        // 这一格上有物品 / 人物：点一下出菜单，不走路
        cell.addEventListener('click', function () {
          thingMenuId = (thingMenuId === thingId) ? null : thingId;
          if (lastState) renderScene(lastState);
        });
        return;
      }
      if (!cell.classList.contains('walkable')) return;
      cell.addEventListener('click', function () {
        if (thingMenuId) {   // 先点一下别处收起菜单，免得手一抖就走了一格
          thingMenuId = null;
          if (lastState) renderScene(lastState);
          return;
        }
        var sc = lastState && lastState.scene;
        if (!sc) return;
        var to = [parseInt(cell.getAttribute('data-x'), 10), parseInt(cell.getAttribute('data-y'), 10)];
        var from = sc.player;
        var steps = scenePath(from, to, sc);
        if (!steps) { showToast('那边走不过去'); return; }
        if (!steps.length) return;
        walkAlong(steps);
      });
    });
  }

  // 在场景里找一条路（4 向，墙和障碍物不能走）。
  // 门 / 楼梯（'+' '<' '>'）是「跨地图的交互点」：踩上去就换场景。自动寻路只能把它当**终点**，
  // 绝不从它上面穿过去 —— 否则点远处一格时人会半路拐进另一张地图，
  // 要找的人 / 东西（走过去再拿 / 说话）也就永远走不到了。
  function scenePath(from, to, sc) {
    var dirs = [[0, -1, '北'], [0, 1, '南'], [1, 0, '东'], [-1, 0, '西']];
    var key = function (p) { return p[0] + ',' + p[1]; };
    var charAt = function (p) {
      if (p[0] < 0 || p[1] < 0 || p[1] >= sc.height || p[0] >= sc.width) return '#';
      return (sc.tiles[p[1]] || '').charAt(p[0]);
    };
    var blocked = function (p) {
      var ch = charAt(p);
      return ch === '#' || ch === '~';
    };
    // 门 / 楼梯那几格（sc.doors 是引擎给的权威位置，字符判断兜底）
    var doorKeys = {};
    Object.keys(sc.doors || {}).forEach(function (dir) { doorKeys[sc.doors[dir].join(',')] = true; });
    var isDoor = function (p) {
      var ch = charAt(p);
      return ch === '+' || ch === '<' || ch === '>' || !!doorKeys[key(p)];
    };
    var isTo = function (p) { return p[0] === to[0] && p[1] === to[1]; };
    var foes = {};
    (sc.things || []).forEach(function (t) { if (t.kind === 'enemy') foes[t.x + ',' + t.y] = true; });
    var baseBlocked = blocked;
    blocked = function (p) { return baseBlocked(p) || (!!foes[key(p)] && !isTo(p)); };   // 敌人挡路（终点除外）
    if (baseBlocked(to)) return null;
    var seen = {}, prev = {}, queue = [from];
    seen[key(from)] = true;
    while (queue.length) {
      var cur = queue.shift();
      if (isTo(cur)) break;
      if (isDoor(cur)) continue;   // 站在门上就会换场景，这里不再往外扩
      for (var i = 0; i < dirs.length; i++) {
        var nxt = [cur[0] + dirs[i][0], cur[1] + dirs[i][1]];
        if (blocked(nxt) || seen[key(nxt)]) continue;
        if (isDoor(nxt) && !isTo(nxt)) continue;   // 门只能当终点，不能路过
        seen[key(nxt)] = true;
        prev[key(nxt)] = [cur, dirs[i][2]];
        queue.push(nxt);
      }
    }
    if (!seen[key(to)]) return null;
    var steps = [];
    var node = to;
    while (prev[key(node)]) {
      steps.unshift(prev[key(node)][1]);
      node = prev[key(node)][0];
    }
    return steps;
  }

  // 顺着路线一格一格走；中途换了房间（踩到门）就停下。
  // 走完之后（还留在同一个房间）会调 after，场景菜单靠它实现“先走过去再拿 / 再说话”。
  function walkAlong(steps, after) {
    var roomId = lastState && lastState.room ? lastState.room.id : null;
    var i = 0;
    lastInterrupt = false;
    function step() {
      if (lastInterrupt) return;   // 发现敌人：强制中断，等玩家下一步指示（后面的动作也不做了）
      if (i >= steps.length) {
        if (after) after();
        return;
      }
      if (busy) { setTimeout(step, 140); return; }
      var dir = steps[i++];
      var done = sendCommand('走 ' + dir);
      if (!done) { setTimeout(step, 140); return; }
      done.then(function () {
        if (!lastState || !lastState.room || lastState.room.id !== roomId) return;
        step();
      });
    }
    step();
  }

  /* ---------- 右侧栏的几段 ---------- */

  // 存档 / 读档：两排按钮，先选动作再选槽位
  function saveSection(state) {
    return '<div class="section"><h4>' + icon('save') + '存档 / 读档</h4>' +
      savePad(state) + '</div>';
  }

  function systemSection(state) {
    // 遇敌中断：点一下在“首个敌人 / 每个敌人”之间切换（规则在引擎的“设置”指令里）
    var every = !!(state && state.settings && state.settings.interrupt_every_enemy);
    return '<div class="section"><h4>' + icon('help') + '系统</h4><div class="btn-grid">' +
      '<button type="button" class="btn small" data-cmd="设置 遇敌中断" title="首个敌人：只在视野里出现第一个敌人（进入战斗）时打断行动；每个敌人：每有敌人新进入视野都打断">' +
      icon('stance') + '<span>遇敌中断：' + (every ? '每个敌人' : '首个敌人') + '</span></button>' +
      btn('地图', '地图', 'map', 'small') +
      btn('角色', '角色卡', 'person', 'small') +
      btn('帮助', '帮助', 'help', 'small') +
      fillBtn('姿态 ', '切换姿态', 'stance') +
      fillBtn('掷骰 ', '掷骰', 'dice') +
      fillBtn('检定 ', '检定', 'check') +
      '<button type="button" class="btn small danger" data-new-game="1">' +
      icon('person') + '<span>新游戏</span></button>' +
      '<button type="button" class="btn small danger" data-quit="1">' +
      icon('exit') + '<span>退出游戏</span></button>' +
      '</div></div>';
  }

  /* ---------- 休息滑条 ---------- */

  function fmtMinutes(minutes) {
    minutes = Math.round(minutes);
    if (minutes < 60) return minutes + ' 分钟';
    var hours = Math.floor(minutes / 60);
    var rest = minutes % 60;
    return rest ? (hours + ' 小时 ' + rest + ' 分钟') : (hours + ' 小时');
  }

  function setRestMinutes(minutes) {
    restMinutes = Math.max(1, Math.round(minutes));
    var range = document.getElementById('rest-range');
    if (range) range.value = restMinutes;
    var label = document.getElementById('rest-label');
    if (label) label.textContent = fmtMinutes(restMinutes);
  }

  function restSection(state) {
    var rest = state.rest || {};
    var min = rest.min || 1;
    var max = rest.max || 480;
    if (restMinutes < min) restMinutes = min;
    if (restMinutes > max) restMinutes = max;
    var full = state.stamina && state.stamina.value >= state.stamina.max;
    var html = '<div class="section"><h4>' + icon('rest') + '休息</h4><div class="rest-box">' +
      '<input type="range" class="rest-range" id="rest-range" min="' + min + '" max="' + max +
      '" step="1" value="' + restMinutes + '" title="拖动选择休息时长">' +
      '<div class="rest-readout"><span id="rest-label">' + esc(fmtMinutes(restMinutes)) + '</span>' +
      '<button type="button" class="btn small primary" id="rest-go">' + icon('rest') +
      '<span>休息</span></button>' + btn('结束回合', '结束回合', 'clock', 'small') + '</div>' +
      '<div class="rest-chips">';
    (rest.presets || []).forEach(function (preset) {
      html += '<button type="button" class="chip-btn" data-rest-preset="' + preset.minutes + '">' +
        esc(preset.label) + '</button>';
    });
    html += '</div></div>';
    if (full) {
      html += '<p class="hint-small warn">体力已满，休息只会让时间白白过去。</p>';
    }
    return html + '</div>';
  }

  // 滑条、快捷档位、休息按钮都是重绘出来的，每次渲染后要重新挂事件
  function bindActionControls() {
    var range = document.getElementById('rest-range');
    if (range) {
      range.addEventListener('input', function () { setRestMinutes(range.value); });
    }
    var go = document.getElementById('rest-go');
    if (go) {
      go.addEventListener('click', function () { sendCommand('休息 ' + restMinutes); });
    }
    var chips = el.actionBody.querySelectorAll('[data-rest-preset]');
    for (var i = 0; i < chips.length; i++) {
      chips[i].addEventListener('click', (function (node) {
        return function () { setRestMinutes(parseInt(node.getAttribute('data-rest-preset'), 10)); };
      })(chips[i]));
    }
  }

  /* ---------- 请求流程 ---------- */

  function handlePayload(data) {
    if (!data) return;
    if (data.type === 'state') { applyBoot(data.state); return; }
    if (data.type === 'pong') return;
    if (data.type === 'prompt') {
      show('create');
      appendLines(el.createLog, data.lines);
      renderPrompt(data);
      return;
    }
    if (data.type === 'quit') {
      stopHeartbeat();
      show('exit');
      if (data.lines) appendLines(el.log, logLines(data.lines));
      if (el.exitText && data.lines && data.lines.length) el.exitText.textContent = data.lines[0];
      return;
    }
    if (data.type === 'play') {
      show('play');
      appendLines(el.log, logLines(data.lines));
      renderState(data.state);
      if (data.notice) showToast(data.notice);
      // 在输入框里打“退出”也算退出：把服务和这一局一起结束
      if (data.quit) finishQuit();
      return;
    }
    if (data.type === 'menu') {
      // 主菜单里的操作（比如清空存档）留在主菜单，不要把人踢进游戏界面
      if (modalKind === 'death') { modalKind = null; el.modal.classList.add('hidden'); }
      show('menu');
      renderMenuSlots(data.state);
      if (data.notice) {
        showToast(data.notice);
        el.menuHint.textContent = data.notice;
      }
      return;
    }
    // error
    var target = currentMode === 'create' ? el.createLog : el.log;
    if (currentMode === 'menu') {
      show('menu');
      el.menuHint.textContent = (data.lines || []).join(' ');
      if (data.lines) showToast(data.lines[0]);
      if (data.state) renderMenuSlots(data.state);
      return;
    }
    appendLines(target, data.lines);
    if (data.lines && data.lines.length) showToast(data.lines[0]);
    if (data.state) renderState(data.state);
  }

  function startNew() {
    if (busy) return;
    answered = 0;
    clear(el.createLog);
    clear(el.createPrompt);
    setBusy(true);
    post('/api/new').then(function (res) {
      setBusy(false);
      handlePayload(res);
    }).catch(function (err) { setBusy(false); fail(err); });
  }

  function continueGame() {
    if (busy) return;
    setBusy(true);
    show('play');
    post('/api/continue').then(function (res) {
      setBusy(false);
      handlePayload(res);
    }).catch(function (err) { setBusy(false); fail(err); });
  }

  function saveSlot(slot) {
    if (busy) return;
    setBusy(true);
    post('/api/save', { slot: slot }).then(function (res) {
      setBusy(false);
      handlePayload(res);
    }).catch(function (err) { setBusy(false); fail(err); });
  }

  function loadSlot(slot) {
    if (busy) return;
    setBusy(true);
    post('/api/load', { slot: slot }).then(function (res) {
      setBusy(false);
      handlePayload(res);
    }).catch(function (err) { setBusy(false); fail(err); });
  }

  function clearSlot(slot) {
    if (busy) return;
    setBusy(true);
    post('/api/clear', { slot: slot }).then(function (res) {
      setBusy(false);
      handlePayload(res);
    }).catch(function (err) { setBusy(false); fail(err); });
  }

  /* ---------- 退出游戏 ---------- */

  function finishQuit() {
    post('/api/quit').then(function (res) {
      handlePayload(res);
    }).catch(function () {
      // 服务已经停了也没关系，至少把界面切到“已结束”
      stopHeartbeat();
      show('exit');
    });
  }

  function quitGame() {
    if (busy) return;
    busy = true;
    finishQuit();
  }

  /* ---------- 页面存活：让服务知道这个页面还开着 / 已经关了 ---------- */

  var heartbeatTimer = null;
  var heartbeatFails = 0;

  function beat() {
    return post('/api/heartbeat').then(function () {
      heartbeatFails = 0;
    }).catch(function () {
      // 服务已经没了（被 Ctrl+C 关掉、或者页面这边服务真的挂了）：连丢几次就告诉玩家，别空转
      heartbeatFails += 1;
      if (heartbeatFails >= 3) {
        stopHeartbeat();
        if (el.exitText) el.exitText.textContent = '本地服务已经停止，这一局结束了。';
        if (el.exitHint) el.exitHint.textContent = '想接着玩：再双击一次桌面上的“封城第七天”。';
        show('exit');
      }
    });
  }

  function startHeartbeat() {
    if (heartbeatTimer) return;
    beat();   // 先立刻报一次到，免得刚打开页面这段时间被当成“已经没有页面了”
    heartbeatTimer = setInterval(beat, 20000);
  }

  function stopHeartbeat() {
    if (heartbeatTimer) {
      clearInterval(heartbeatTimer);
      heartbeatTimer = null;
    }
  }

  // 关标签页 / 刷新 / 跳到别的地址：用 sendBeacon 报一声“我要关了”。
  // 服务端收到之后会结束这一局并自己退出；刷新会在十几秒宽限期里重新报到，服务不会跟着关。
  function sayGoodbye() {
    stopHeartbeat();
    if (!navigator.sendBeacon) return;   // 报不出去也没关系，服务端还有心跳超时兜底
    try {
      navigator.sendBeacon('/api/bye', new Blob(
        [JSON.stringify({ page: PAGE_ID })], { type: 'application/json' }));
    } catch (err) { /* 同上 */ }
  }

  window.addEventListener('pagehide', sayGoodbye);
  window.addEventListener('pageshow', function (event) {
    // 从浏览器的“后退缓存”里回来：重新报一次到
    if (event.persisted) { heartbeatFails = 0; startHeartbeat(); }
  });

  var lastInterrupt = false;   // 上一句指令被“视野里出现敌人”打断了：自动寻路到此为止
  function sendCommand(text) {
    if (busy || !text) return null;
    setBusy(true);
    var done = post('/api/command', { text: text }).then(function (res) {
      setBusy(false);
      lastInterrupt = !!(res && res.interrupt);
      handlePayload(res);
    }).catch(function (err) { setBusy(false); fail(err); });
    return done;  // 场景里连走几格时要等这一句处理完
  }

  // 菜单里的每一项：翻译成一句玩家指令（规则都在引擎里，前端不做判断）
  function doBagAction(act) {
    var item = stackBySid(lastState, itemMenuSid);
    if (!item) return;
    var name = item.name;
    if (act === 'look') { itemMenuSid = null; sendCommand('查看 ' + name); return; }
    if (act === 'use') { itemMenuSid = null; sendCommand('使用 ' + name); return; }
    if (act === 'equip') { itemMenuSid = null; sendCommand('装备 ' + name); return; }
    if (act === 'drop') { itemMenuSid = null; sendCommand('放下 ' + name); return; }
    if (act === 'dropall') { itemMenuSid = null; sendCommand('放下 ' + name + ' ' + item.count); return; }
    if (act === 'stack') { itemMenuSid = null; sendCommand('堆叠 ' + name); return; }
    if (act === 'split') {
      splitSid = item.sid;
      splitValue = Math.max(1, Math.floor(item.count / 2));
      if (lastState) renderBag(lastState);
      return;
    }
    if (act === 'pin') {
      // 已经登记过就取消，没登记过就放到当前这一页的空格
      var at = slotIndexOf('item', item.id);
      if (at >= 0) {
        clearSlotReg(at);
        showToast('把' + name + '从技能栏第 ' + (at % SLOT_PER_PAGE + 1) + ' 格取下。');
      } else {
        var cmd = (item.quick && item.quick.cmd) || ('查看 ' + name);
        var target = freeSlotInPage();
        registerSlot(target, 'item', item.id, name, cmd);
        showToast('把' + name + '登记到技能栏第 ' + (target % SLOT_PER_PAGE + 1) + ' 格。');
      }
      itemMenuSid = null;
      if (lastState) renderBag(lastState);
      return;
    }
  }

  // 场景菜单里的每一项：也翻译成一句玩家指令（拿 / 说话 / 查看，判断都在引擎里）。
  // 拿取 / 说话要走到跟前，所以会先自己找路走过去，走到了才真的发那句指令。
  function doSceneAction(act, name) {
    var t = sceneThing(lastState, thingMenuId);
    var sc = lastState && lastState.scene;
    thingMenuId = null;
    if (act === 'move') {
      // 走过去但不拿：自己找一条路，走到那件东西 / 那个人所在的格子
      if (!sc || !t) return;
      var move = scenePath(sc.player, [t.x, t.y], sc);
      if (!move) { showToast('那边走不过去'); return; }
      walkAlong(move);
      return;
    }
    if (act === 'attack') {
      // 够得着（相邻一格）就直接打；够不着先走到它旁边再打
      var hit = '攻击 ' + name;
      if (!sc || !t || nearThing(sc.player, t)) { sendCommand(hit); return; }
      var path = scenePath(sc.player, [t.x, t.y], sc);
      if (!path || path.length < 2) { showToast('那边走不过去'); return; }
      walkAlong(path.slice(0, -1), function () { sendCommand(hit); });
      return;
    }
    if (act === 'take' || act === 'talk') {
      var cmd = (act === 'take' ? '拿 ' : '说话 ') + name;
      // 已经在跟前（同一格或相邻一格，斜角也算）就直接发指令，不用白跑一趟
      if (!sc || !t || nearThing(sc.player, t)) { sendCommand(cmd); return; }
      var steps = scenePath(sc.player, [t.x, t.y], sc);
      if (!steps) { showToast('那边走不过去'); return; }
      walkAlong(steps, function () { sendCommand(cmd); });
      return;
    }
    sendCommand('查看 ' + name);
  }

  // 玩家是不是已经站在这件东西 / 这个人跟前（同一格或相邻一格，斜角也算）
  function nearThing(player, thing) {
    if (!player || !thing) return false;
    return Math.max(Math.abs(player[0] - thing.x), Math.abs(player[1] - thing.y)) <= 1;
  }

  // 拆分弹窗：滑条和输入框互相跟着走，点「拆分」才真的发指令
  function bindSplitBox() {
    var range = document.getElementById('split-range');
    var num = document.getElementById('split-num');
    var ok = document.getElementById('split-ok');
    if (!range || !num || !ok) return;

    function set(value) {
      var max = parseInt(num.getAttribute('max'), 10) || 1;
      splitValue = Math.max(1, Math.min(max, parseInt(value, 10) || 1));
      range.value = splitValue;
      num.value = splitValue;
    }
    range.addEventListener('input', function () { set(range.value); });
    num.addEventListener('input', function () { set(num.value); });
    num.addEventListener('change', function () { set(num.value); });
    ok.addEventListener('click', function () {
      var sid = splitSid;
      if (!sid) return;
      splitSid = null;
      itemMenuSid = null;
      sendCommand('拆分 ' + sid + ' ' + splitValue);
    });
  }

  /* ---------- 事件绑定 ---------- */

  document.addEventListener('click', function (event) {
    // 技能栏格子里的 ✕ 长在格子按钮里面，要先拦下来
    var slotClear = event.target.closest ? event.target.closest('[data-slot-clear]') : null;
    if (slotClear) {
      event.preventDefault();
      event.stopPropagation();
      clearSlotReg(parseInt(slotClear.getAttribute('data-slot-clear'), 10));
      return;
    }
    // 技能栏翻页
    var slotPageNode = event.target.closest ? event.target.closest('[data-slot-page]') : null;
    if (slotPageNode) {
      event.preventDefault();
      var want = slotPageNode.getAttribute('data-slot-page');
      if (want === 'prev') slotPageNo -= 1;
      else if (want === 'next') slotPageNo += 1;
      else slotPageNo = parseInt(want, 10) - 1;
      slotPageNo = Math.max(0, Math.min(SLOT_PAGES - 1, slotPageNo));
      renderSlotsPanel(lastState);
      return;
    }
    // 技能栏里点已登记的技能：快捷释放（发「用 <技能>」）
    var castNode = event.target.closest ? event.target.closest('[data-cast]') : null;
    if (castNode && castNode.getAttribute('data-cast')) {
      event.preventDefault();
      sendCommand('用 ' + castNode.getAttribute('data-cast'));
      return;
    }
    var cmdNode = event.target.closest ? event.target.closest('[data-cmd]') : null;
    if (cmdNode) {
      event.preventDefault();
      sendCommand(cmdNode.getAttribute('data-cmd'));
      return;
    }
    // 视图栏的三个页签：场景 / 背包 / 技能树
    var tabNode = event.target.closest ? event.target.closest('[data-view-tab]') : null;
    if (tabNode) {
      event.preventDefault();
      setView(tabNode.getAttribute('data-view-tab'));
      return;
    }
    // 技能树页签：翻页 / 只看已学会
    var skillPageNode = event.target.closest ? event.target.closest('[data-skill-page]') : null;
    if (skillPageNode) {
      event.preventDefault();
      skillPageNo += (skillPageNode.getAttribute('data-skill-page') === 'next') ? 1 : -1;
      if (skillPageNo < 0) skillPageNo = 0;
      refreshSkillPanel();
      return;
    }
    if (event.target.closest && event.target.closest('[data-skill-only]')) {
      event.preventDefault();
      onlyLearned = !onlyLearned;
      skillPageNo = 0;
      refreshSkillPanel();
      return;
    }
    // 技能树页签：点一个技能，下面展开详细描述
    var skillSel = event.target.closest ? event.target.closest('[data-skill-sel]') : null;
    if (skillSel) {
      event.preventDefault();
      var picked = skillSel.getAttribute('data-skill-sel');
      skillSelId = (skillSelId === picked) ? null : picked;
      refreshSkillPanel();
      return;
    }
    // 背包翻页
    var pageNode = event.target.closest ? event.target.closest('[data-bag-page]') : null;
    if (pageNode) {
      event.preventDefault();
      bagPage += (pageNode.getAttribute('data-bag-page') === 'next') ? 1 : -1;
      itemMenuSid = null;
      splitSid = null;
      if (lastState) renderBag(lastState);
      return;
    }
    // 背包里点物品弹出来的菜单
    var bagAct = event.target.closest ? event.target.closest('[data-bag-act]') : null;
    if (bagAct) {
      event.preventDefault();
      doBagAction(bagAct.getAttribute('data-bag-act'));
      return;
    }
    // 场景里点物品 / 人物弹出来的菜单
    var sceneAct = event.target.closest ? event.target.closest('[data-scene-act]') : null;
    if (sceneAct) {
      event.preventDefault();
      doSceneAction(sceneAct.getAttribute('data-scene-act'), sceneAct.getAttribute('data-scene-name'));
      return;
    }
    if (event.target.closest && event.target.closest('[data-split-cancel]')) {
      event.preventDefault();
      splitSid = null;
      if (lastState) renderBag(lastState);
      return;
    }
    var fillNode = event.target.closest ? event.target.closest('[data-fill]') : null;
    if (fillNode) {
      event.preventDefault();
      el.cmdInput.value = fillNode.getAttribute('data-fill');
      el.cmdInput.focus();
      return;
    }
    var learnNode = event.target.closest ? event.target.closest('[data-learn]') : null;
    if (learnNode) {
      event.preventDefault();
      sendCommand('学习 ' + learnNode.getAttribute('data-learn'));
      return;
    }
    // 存档盘：先选动作（存档 / 读档 / 清空），再点 1 / 2 / 3
    var modeNode = event.target.closest ? event.target.closest('[data-save-mode]') : null;
    if (modeNode) {
      event.preventDefault();
      var picked = modeNode.getAttribute('data-save-mode');
      saveMode = (saveMode === picked) ? null : picked;
      if (lastState) renderActions(lastState);
      return;
    }
    var slotNode = event.target.closest ? event.target.closest('[data-slot-no]') : null;
    if (slotNode) {
      event.preventDefault();
      doSlotAction(parseInt(slotNode.getAttribute('data-slot-no'), 10));
      return;
    }
    var loadNode = event.target.closest ? event.target.closest('[data-load]') : null;
    if (loadNode) {
      event.preventDefault();
      var n = parseInt(loadNode.getAttribute('data-load'), 10);
      showConfirm('读档', '读取 ' + n + ' 号槽？当前没存档的进度会丢失。', function () { loadSlot(n); });
      return;
    }
    var clearNode = event.target.closest ? event.target.closest('[data-clear]') : null;
    if (clearNode) {
      event.preventDefault();
      var c = parseInt(clearNode.getAttribute('data-clear'), 10);
      showConfirm('清空存档', '确定清空 ' + c + ' 号存档？清空之后没法恢复。', function () { clearSlot(c); });
      return;
    }
    var quitNode = event.target.closest ? event.target.closest('[data-quit]') : null;
    if (quitNode) {
      event.preventDefault();
      showConfirm('退出游戏', '退出会结束这一局并关掉本地服务（没存档的进度会丢），确定吗？', quitGame);
      return;
    }
    var newNode = event.target.closest ? event.target.closest('[data-new-game]') : null;
    if (newNode) {
      event.preventDefault();
      showConfirm('新游戏', '开始新游戏会丢掉当前这一局没存档的进度，确定吗？', startNew);
      return;
    }
    var deathMenuNode = event.target.closest ? event.target.closest('[data-death-menu]') : null;
    if (deathMenuNode) {
      event.preventDefault();
      modalKind = null;
      if (el.modalClose) el.modalClose.style.display = '';
      el.modal.classList.add('hidden');
      post('/api/menu').then(handlePayload).catch(fail);
      return;
    }
    var closeNode = event.target.closest ? event.target.closest('[data-close]') : null;
    if (closeNode) {
      event.preventDefault();
      closeModal();
      return;
    }
    var actNode = event.target.closest ? event.target.closest('[data-act]') : null;
    if (actNode) {
      event.preventDefault();
      if (actNode.getAttribute('data-act') === 'new') startNew();
      else continueGame();
    }
  });

  // 点浮层背景或按 Esc 关闭
  el.modal.addEventListener('click', function (event) {
    if (event.target === el.modal) closeModal();
  });
  el.modalClose.addEventListener('click', closeModal);
  document.addEventListener('keydown', function (event) {
    if (event.key === 'Escape' && !el.modal.classList.contains('hidden')) { closeModal(); return; }
    // 方向键在场景里走动（正在输入框里打字时不抢键）
    var tag = (event.target && event.target.tagName) || '';
    if (tag === 'INPUT' || tag === 'TEXTAREA') return;
    // 技能栏格子：按 Delete / Backspace 取消登记
    var cell = event.target && event.target.closest ? event.target.closest('[data-slot-cell]') : null;
    if (cell && (event.key === 'Delete' || event.key === 'Backspace')) {
      event.preventDefault();
      clearSlotReg(parseInt(cell.getAttribute('data-slot-cell'), 10));
      return;
    }
    if (currentMode !== 'play' || busy) return;
    if (viewMode !== 'scene') return;   // 背包 / 技能树页签里按方向键不该让角色乱走    var dir = { ArrowUp: '走 北', ArrowDown: '走 南', ArrowRight: '走 东', ArrowLeft: '走 西' }[event.key];
    if (!dir) return;
    event.preventDefault();
    sendCommand(dir);
  });

  el.cmdForm.addEventListener('submit', function (event) {
    event.preventDefault();
    var text = el.cmdInput.value.trim();
    if (!text) return;
    el.cmdInput.value = '';
    sendCommand(text);
  });

  // 主菜单上的“退出游戏”：结束服务，不用再去关那个黑窗口
  if (el.menuExit) {
    el.menuExit.addEventListener('click', function () {
      showConfirm('退出游戏', '退出会关掉本地服务（进度已经存在 saves 文件夹里），确定吗？', quitGame);
    });
  }

  // 退出页上的“关闭此页面”：浏览器不一定让脚本关标签页，关不掉就给提示
  if (el.exitClose) {
    el.exitClose.addEventListener('click', function () {
      window.close();
      setTimeout(function () {
        el.exitHint.textContent = '页面还开着的话：浏览器一般不允许脚本关掉不是它自己打开的标签页，' +
          '按 Ctrl+W，或者点标签上的 × 就行。';
      }, 400);
    });
  }

  /* ---------- 启动 ---------- */

  bindMap();   // 地图的点击就绑一次，之后重画地图不影响（用事件委托）
  bindScene(); // 说话横幅的「点视图栏继续」也在这儿绑一次
  // 窗口大小变了：地图的可视窗口是按场景大小算的，跟着重算一遍（拖动的偏移会被夹回范围里）
  window.addEventListener('resize', function () { if (lastState) renderMap(lastState); });

  function applyBoot(state) {
    if (!state) { show('menu'); return; }
    if (state.mode === 'quit') { show('exit'); return; }
    if (state.mode === 'create') {
      // 上一轮创建角色还没走完（例如中途刷新了页面）：把当前问题要回来接着答
      show('create');
      appendLines(el.createLog, ['（继续未完成的角色创建）']);
      post('/api/new').then(handlePayload).catch(fail);
      return;
    }
    if (state.started && state.running !== false) {
      // 页面刷新后重新接上正在进行的这一局（文字记录不保留）
      show('play');
      appendLines(el.log, ['（页面重新连接，之前的文字记录没有保留）', state.room ? '你还在' + state.room.name + '。' : '']);
      renderState(state);
      if (location.hash === '#skills') {
        openModal('skills', '技能树');
        renderModal(state);
      } else if (location.hash === '#bag') {
        setView('bag');   // 背包现在占视图栏，不是浮层
      }
      return;
    }
    show('menu');
    renderMenuSlots(state);
  }

  // 每隔一会儿报个活，这样再次双击启动时不会又开一个新标签页
  startHeartbeat();

  fetch('/api/state').then(function (res) { return res.json(); })
    .then(function (data) { applyBoot(data.state); })
    .catch(function (err) { show('menu'); el.menuHint.textContent = '连接不上服务器：' + err.message; });
})();
