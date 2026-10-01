/* 封城第七天 · 按钮版前端
   所有按钮最终都翻译成一句玩家指令（data-cmd），发给 /api/command 由引擎处理。
   角色创建走 /api/new → /api/answer 的一问一答。

   界面区域命名（写代码/改布局时按名字找，约定见 ../界面区域.md）：
     左侧栏 / 视图栏 / 移动栏 / 快捷区域1 / 快捷区域2 / 右侧栏
   本文件里 左侧栏 = #char-body，视图栏 = #scene-body（格子场景，人物真的在里面走；
   左上角浮着时钟，点格子上的物品 / 人物弹小菜单，颜色图例在视图栏最下面一条），
   移动栏 = #move-body，快捷区域1 = #equip-body（装备栏，拖动装备），
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
    charBody: document.getElementById('char-body'),   // 左侧栏
    moveBody: document.getElementById('move-body'),    // 移动栏
    actionBody: document.getElementById('action-body'),  // 右侧栏
    sceneBody: document.getElementById('scene-body'),  // 视图栏（格子场景）
    bagPanel: document.getElementById('bag-panel'),    // 视图栏（背包页签）
    viewTabs: document.getElementById('view-tabs'),    // 视图栏右上角 场景 / 背包
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

  function setBusy(flag) {
    busy = flag;
    // 移动块和右侧栏是两块面板，请求中都要点不动
    [el.actionBody, el.moveBody].forEach(function (node) {
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
    var action;
    if (skill.learned) {
      action = '<span class="skill-done">' + icon('check') + '<span>已学会</span></span>';
    } else if (!tree.unlocked) {
      action = '<span class="skill-locked">' + icon('x') + '<span>' + esc(tree.locked_message) + '</span></span>';
    } else if (skill.unmet && skill.unmet.length) {
      action = '<span class="skill-locked" title="' + esc(skill.unmet.join('、')) + '">' +
        icon('x') + '<span>' + esc(skill.unmet.join('、')) + '</span></span>';
    } else {
      action = '<button type="button" class="btn small primary" data-learn="' + esc(skill.name) + '">' +
        icon('learn') + '<span>学习（' + skill.cost + ' 点）</span></button>';
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

  /* ---------- 右侧栏的背包快捷栏（3 格，手动登记） ---------- */

  var QUICK_KEY = 'fengcheng.quick';
  var QUICK_MAX = 3;
  // 固定 3 格：每格要么是空（null），要么是 {id, name}。只有手动登记 / 拖进去才有东西，
  // 背包里的东西不会自动冒上来。
  var pinned = loadPinned();

  function loadPinned() {
    var slots = [null, null, null];
    try {
      var list = JSON.parse(window.localStorage.getItem(QUICK_KEY) || '[]');
      if (Object.prototype.toString.call(list) !== '[object Array]') return slots;
      for (var i = 0; i < QUICK_MAX && i < list.length; i++) {
        var entry = list[i];
        if (!entry) continue;
        if (typeof entry === 'string') slots[i] = { id: entry, name: entry };  // 老数据：只存了 id
        else if (entry.id) slots[i] = { id: entry.id, name: entry.name || entry.id };
      }
    } catch (err) { /* 读不出来就当没登记过 */ }
    return slots;
  }

  function savePinned() {
    try { window.localStorage.setItem(QUICK_KEY, JSON.stringify(pinned)); } catch (err) { /* 无痕模式就算了 */ }
  }

  function pinnedIndex(id) {
    for (var i = 0; i < pinned.length; i++) {
      if (pinned[i] && pinned[i].id === id) return i;
    }
    return -1;
  }

  // 登记到指定格子（同一件东西在别处也会先摘掉，免得一格东西占两格）
  function pinAt(slot, id, name) {
    slot = Math.max(0, Math.min(QUICK_MAX - 1, slot));
    var at = pinnedIndex(id);
    if (at >= 0) pinned[at] = null;
    pinned[slot] = { id: id, name: name || id };
    savePinned();
    refreshQuick();
  }

  function unpin(slot) {
    pinned[slot] = null;
    savePinned();
    refreshQuick();
  }

  // 第一个空格子，没有就返回 0（顶掉第一格）
  function freeQuickSlot() {
    for (var i = 0; i < QUICK_MAX; i++) {
      if (!pinned[i]) return i;
    }
    return 0;
  }

  function refreshQuick() {
    if (!lastState) return;
    renderActions(lastState);
    if (itemMenuSid !== null) renderBag(lastState);
  }

  // 快捷栏里放哪三件：只认登记的，登记的物品不在背包里就显示成空格
  function quickItems(state) {
    var inv = (state && state.inventory) || [];
    return pinned.map(function (pin) {
      if (!pin) return null;
      var hit = inv.filter(function (x) { return x.id === pin.id; })[0];
      return hit || { id: pin.id, name: pin.name, missing: true };
    });
  }

  function quickBar(state) {
    var items = quickItems(state);
    var html = '<div class="quick-grid">';
    for (var i = 0; i < QUICK_MAX; i++) {
      var item = items[i];
      if (!item || item.missing) {
        var label = item ? esc(item.name + '（没带）') : '空';
        html += '<span class="quick quick-empty slot-target' + (item ? ' quick-missing' : '') +
          '" data-quick-slot="' + i + '" title="' +
          esc(item ? item.name + '：登记过，但背包里现在没有'
            : '空格子：把背包里的东西拖到这里就算登记（先用视图栏的「背包」页签打开背包）') + '">' +
          '<span class="quick-name">' + label + '</span></span>';
        continue;
      }
      var quick = item.quick || { cmd: '查看 ' + item.name, label: '查看' };
      html += '<button type="button" class="quick slot-target" data-quick-slot="' + i + '" data-cmd="' +
        esc(quick.cmd) + '" title="' + esc(item.name + '：点一下就是「' + quick.label +
          '」；也可以把别的物品拖进来替换') + '">' +
        itemIcon(item.id) + '<span class="quick-name">' + esc(item.name) + '</span>' +
        '<span class="quick-act">' + esc(quick.label) + '</span>' +
        '<span class="quick-x" data-quick-clear="' + i + '" title="从快捷栏取下">✕</span></button>';
    }
    return html + '</div>';
  }

  // 浮层里要显示什么，由 modalKind 决定
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

  // 时钟：视图栏里两个页签各渲染一份（场景页浮在左上角，背包页放在顶部那一行）
  function clockChip(state) {
    if (!state || !state.time) return '';
    var turns = (typeof state.turns === 'number') ? '第 ' + state.turns + ' 回合' : '';
    return '<div class="clock-chip" title="' + esc(state.time.text + (turns ? ' · ' + turns : '')) + '">' +
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

  function renderState(state) {
    if (!state) return;
    lastState = state;
    if (state.room) {
      el.roomName.textContent = state.room.name;
      var bits = [];
      if (typeof state.turns === 'number') bits.push('第 ' + state.turns + ' 回合');
      if (state.stance) bits.push('姿态：' + state.stance);
      el.roomSub.textContent = bits.join(' · ');
    }
    renderChar(state);
    renderActions(state);
    renderView(state);   // 视图栏：场景 或 背包（两个页签）
    renderDeath(state);
    // 技能浮层开着的话，学完技能要跟着刷新
    if (modalKind === 'skills' && !el.modal.classList.contains('hidden')) {
      renderModal(state);
    }
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
    html += '<p class="char-meta">' + esc(c.gender) + ' · ' + esc(c.age) + ' 岁 · ' +
      esc(c.height) + ' cm · ' + esc(c.background) + '</p>';

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
        '（上限 ' + esc(cb.ap_cap) + (cb.armor_ap_penalty ? '，重甲 −' + esc(cb.armor_ap_penalty) : '') +
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
          esc(p.name) + '（' + esc(p.age) + ' 岁）</span></div>';
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
    //   移动栏 = #move-body，右侧栏 = #action-body（背包快捷栏 / 休息 / 存档读档 / 系统），
    //   快捷区域1 = #equip-body 的装备栏，快捷区域2 = #log + #cmd-form。
    //   背包 = 视图栏的 #bag-panel（点视图栏右上角「背包」页签打开）；
    //   地上的物品和人物在场景里点方块出菜单（thingMenu），不再占右侧栏。
    if (el.moveBody) el.moveBody.innerHTML = moveSection(state);
    renderEquip(state);
    el.actionBody.innerHTML =
      bagSection(state) +
      (state.rest ? restSection(state) : '') +
      saveSection(state) +
      systemSection();
    bindActionControls();
    bindQuickSlots();   // 快捷栏每次重画都要重新挂拖动
  }

  /* ---------- 快捷区域1：装备栏（拖动装备 / 脱下） ---------- */

  // 拖动中的东西：{from, id, name} —— from 是 'bag'（背包里的某一堆，带 sid）或装备位 id
  var dragItem = null;

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
            event.dataTransfer.setData('text/plain', dragItem.id);
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
        if (drag.from === 'main_hand' || drag.from === 'off_hand') {
          // 换手只支持武器之间（盾牌不能换到主手）
          return !!(item.weapon && otherPayload.weapon);
        }
      }
    }
    return true;
  }

  // 武器拖到哪只手的方框上，就让引擎放进哪只手；护甲 / 饰品不用带这个尾巴
  function handHint(drag, slotId) {
    if (slotId !== 'main_hand' && slotId !== 'off_hand') return '';
    var item = dragPayloadItem(drag);
    if (!item || !item.weapon) return '';
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

  /* ---------- 视图栏：场景 / 背包两个页签 ---------- */

  var VIEW_KEY = 'fengcheng.view';
  var viewMode = loadView();   // 'scene' = 场景，'bag' = 背包

  function loadView() {
    try { return window.localStorage.getItem(VIEW_KEY) === 'bag' ? 'bag' : 'scene'; } catch (err) { return 'scene'; }
  }

  function saveView() {
    try { window.localStorage.setItem(VIEW_KEY, viewMode); } catch (err) { /* 存不了就算了 */ }
  }

  function setView(mode) {
    viewMode = (mode === 'bag') ? 'bag' : 'scene';
    saveView();
    itemMenuSid = null;
    splitSid = null;
    thingMenuId = null;
    if (lastState) renderView(lastState);
  }

  // 这一栏要么显示场景，要么显示背包（不叠着来）
  function renderView(state) {
    var bagging = viewMode === 'bag';
    if (el.bagPanel) el.bagPanel.classList.toggle('hidden', !bagging);
    if (el.sceneBody) el.sceneBody.classList.toggle('hidden', bagging);
    if (el.viewTabs) {
      Array.prototype.forEach.call(el.viewTabs.querySelectorAll('.view-tab'), function (tab) {
        tab.classList.toggle('active', tab.getAttribute('data-view-tab') === viewMode);
      });
    }
    if (bagging) renderBag(state); else renderScene(state);
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
      ' kg</span>' + clockChip(state) + '</div>';
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
    var at = pinnedIndex(item.id);
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
      (at >= 0 ? '从快捷栏取下' : '登记到快捷栏') + '</span></button>';
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
      '拖到同种物品上＝叠成一堆，拖到右侧快捷栏＝登记。</p>' +
      '<div class="bag-grid" id="bag-grid">';
    if (!inv.length) html += '<span class="bag-empty">背包是空的。捡东西、或者从身上脱下装备都会回到这里。</span>';
    slice.forEach(function (item) { html += bagCell(item); });
    if (itemMenuSid !== null) html += itemMenu(state);
    html += '</div>' + bagPager(pages, inv);
    if (splitSid !== null) html += splitBox(state);
    el.bagPanel.innerHTML = html;
    bindBag();
    bindSplitBox();
    bindQuickSlots();
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
        dragItem = { from: 'bag', sid: sid, id: item.id, name: item.name, count: item.count };
        cell.classList.add('dragging');
        if (event.dataTransfer) {
          event.dataTransfer.effectAllowed = 'move';
          event.dataTransfer.setData('text/plain', item.name);
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

  /* ---------- 右侧栏的快捷栏：拖动登记 ---------- */

  function bindQuickSlots() {
    var slots = el.actionBody ? el.actionBody.querySelectorAll('[data-quick-slot]') : [];
    Array.prototype.forEach.call(slots, function (slot) {
      var index = parseInt(slot.getAttribute('data-quick-slot'), 10);
      slot.addEventListener('dragover', function (event) {
        if (!dragItem || dragItem.from !== 'bag') return;
        event.preventDefault();
        slot.classList.add('drop-ok');
      });
      slot.addEventListener('dragleave', function () { slot.classList.remove('drop-ok'); });
      slot.addEventListener('drop', function (event) {
        event.preventDefault();
        event.stopPropagation();
        slot.classList.remove('drop-ok');
        if (!dragItem || dragItem.from !== 'bag') { dragItem = null; return; }
        var name = dragItem.name;
        pinAt(index, dragItem.id, name);
        dragItem = null;
        showToast('把' + name + '放到了快捷栏第 ' + (index + 1) + ' 格。');
      });
    });
  }

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
      el.sceneBody.innerHTML = '<span class="empty">这个地点还没有场景图，用下面的移动按钮走。</span>';
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
    // 地图在上、颜色图例压在最下面一整条、时钟浮在左上角
    el.sceneBody.innerHTML =
      '<div class="scene-clock">' + clockChip(state) + '</div>' + html + sceneLegend() + thingMenu(state);
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
      '<span class="lg">黑底白字方块 = 人物与物品（点一下出菜单）</span></div>';
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

  function bindScene() {
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

  // 在场景里找一条路（4 向，墙和障碍物不能走）
  function scenePath(from, to, sc) {
    var dirs = [[0, -1, '北'], [0, 1, '南'], [1, 0, '东'], [-1, 0, '西']];
    var key = function (p) { return p[0] + ',' + p[1]; };
    var blocked = function (p) {
      if (p[0] < 0 || p[1] < 0 || p[1] >= sc.height || p[0] >= sc.width) return true;
      var ch = (sc.tiles[p[1]] || '').charAt(p[0]);
      return ch === '#' || ch === '~';
    };
    if (blocked(to)) return null;
    var seen = {}, prev = {}, queue = [from];
    seen[key(from)] = true;
    while (queue.length) {
      var cur = queue.shift();
      if (cur[0] === to[0] && cur[1] === to[1]) break;
      for (var i = 0; i < dirs.length; i++) {
        var nxt = [cur[0] + dirs[i][0], cur[1] + dirs[i][1]];
        if (blocked(nxt) || seen[key(nxt)]) continue;
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
    function step() {
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

  /* ---------- 移动栏（文字栏下面正中间那块） ---------- */

  function moveSection(state) {
    // 六个方向常驻，颜色说明能不能走
    var byDir = {};
    (state.exits || []).forEach(function (e) { byDir[e.id] = e; });

    function moveTitle(e) {
      // 每 10 步才扣一次体力，没凑满的那几步写「不扣体力」
      return e.minutes + ' 分钟' + (e.cost ? '，' + e.cost + ' 点体力' : '，不扣体力');
    }

    function dirBtn(id) {
      var e = byDir[id];
      if (!e) return '<span class="dir-empty"></span>';
      var cls = e.state === 'open' ? 'dir-open' : (e.state === 'danger' ? 'dir-danger' : 'dir-unknown');
      var sub, title;
      if (e.tile === 'wall') {
        // 场景里那一格是墙 / 障碍物
        cls = 'dir-unknown';
        sub = '走不通';
        title = '那个方向走不过去';
      } else if (e.tile === 'floor') {
        sub = '空地';
        title = '往' + e.name + '走一格（' + moveTitle(e) + '）';
      } else if (e.tile === 'door' || e.tile === 'stairs') {
        if (e.state === 'blocked') {
          // 缺东西过不去（例如没带手电筒就下不了地下室）：画成走不通，悬停看原因
          cls = 'dir-unknown';
          sub = '进不去';
          title = e.danger || '这里过不去';
        } else {
          sub = e.danger ? '危险' : (e.target || (e.tile === 'stairs' ? '楼梯' : '出口'));
          title = (e.danger || (e.target ? '走过这格就通往 ' + e.target : '那边还没走过')) +
            '（' + moveTitle(e) + '）';
          if (e.danger) cls = 'dir-danger'; else cls = 'dir-open';
        }
      } else if (e.state === 'danger') {
        sub = '危险';
        title = e.danger || '那边有危险';
      } else if (e.state === 'open') {
        sub = e.target || '未探索';
        title = (e.target ? '通往 ' + e.target : '还没走过那边') + '（' + moveTitle(e) + '）';
      } else {
        sub = '？';
        title = '不知道那边能不能走，走走看（' + moveTitle(e) + '）';
      }
      return '<button type="button" class="dir ' + cls + '" data-cmd="走 ' + esc(e.name) +
        '" title="' + esc(title) + '">' + icon(DIR_ICON[id] || 'map') +
        '<span class="dir-name">' + esc(e.name) + '</span>' +
        '<span class="dir-sub">' + esc(sub) + '</span></button>';
    }

    // 四个平面方向（上下楼改成点场景里的楼梯格，按钮不再占位）
    return '<div class="dir-grid">' +
      '<span class="dir-empty"></span>' + dirBtn('north') + '<span class="dir-empty"></span>' +
      dirBtn('west') + '<span class="dir-center">' + esc(state.room ? state.room.name : '') + '</span>' +
      dirBtn('east') +
      '<span class="dir-empty"></span>' + dirBtn('south') + '<span class="dir-empty"></span>' +
      '</div><p class="hint-small">走一格：绿＝能走，红＝危险，暗＝走不通；上下楼点场景里的楼梯格</p>';
  }

  /* ---------- 右侧栏的几段 ---------- */

  // 背包快捷栏：右侧只留 3 格（手动登记），完整背包点视图栏的「背包」页签
  function bagSection(state) {
    return '<div class="section"><h4>' + icon('bag') + '背包快捷栏</h4>' +
      quickBar(state) + '</div>';
  }

  // 存档 / 读档：两排按钮，先选动作再选槽位
  function saveSection(state) {
    return '<div class="section"><h4>' + icon('save') + '存档 / 读档</h4>' +
      savePad(state) + '</div>';
  }

  function systemSection() {
    return '<div class="section"><h4>' + icon('help') + '系统</h4><div class="btn-grid">' +
      btn('地图', '地图', 'map', 'small') +
      btn('角色', '角色卡', 'person', 'small') +
      modalBtn('skills', '技能树', 'skills') +
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
      '<span>休息</span></button>' + btn('等待', '等待 1 回合', 'rest', 'small') + '</div>' +
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
      if (data.lines) appendLines(el.log, data.lines);
      if (el.exitText && data.lines && data.lines.length) el.exitText.textContent = data.lines[0];
      return;
    }
    if (data.type === 'play') {
      show('play');
      appendLines(el.log, data.lines);
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

  function sendCommand(text) {
    if (busy || !text) return null;
    setBusy(true);
    var done = post('/api/command', { text: text }).then(function (res) {
      setBusy(false);
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
      var at = pinnedIndex(item.id);
      if (at >= 0) unpin(at); else pinAt(freeQuickSlot(), item.id, name);
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
    // 快捷栏格子里的 ✕ 长在 [data-cmd] 按钮里面，要先拦下来
    var quickClear = event.target.closest ? event.target.closest('[data-quick-clear]') : null;
    if (quickClear) {
      event.preventDefault();
      event.stopPropagation();
      unpin(parseInt(quickClear.getAttribute('data-quick-clear'), 10));
      return;
    }
    var cmdNode = event.target.closest ? event.target.closest('[data-cmd]') : null;
    if (cmdNode) {
      event.preventDefault();
      sendCommand(cmdNode.getAttribute('data-cmd'));
      return;
    }
    // 视图栏的两个页签：场景 / 背包
    var tabNode = event.target.closest ? event.target.closest('[data-view-tab]') : null;
    if (tabNode) {
      event.preventDefault();
      setView(tabNode.getAttribute('data-view-tab'));
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
    var modalNode = event.target.closest ? event.target.closest('[data-modal]') : null;
    if (modalNode) {
      event.preventDefault();
      openModal('skills', '技能树');
      renderModal(lastState);
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
    if (currentMode !== 'play' || busy) return;
    if (viewMode === 'bag') return;   // 在背包页签里按方向键不该让角色乱走
    var dir = { ArrowUp: '走 北', ArrowDown: '走 南', ArrowRight: '走 东', ArrowLeft: '走 西' }[event.key];
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
