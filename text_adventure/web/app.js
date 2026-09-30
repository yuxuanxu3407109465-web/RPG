/* 封城第七天 · 按钮版前端
   所有按钮最终都翻译成一句玩家指令（data-cmd），发给 /api/command 由引擎处理。
   角色创建走 /api/new → /api/answer 的一问一答。

   界面区域命名（写代码/改布局时按名字找，约定见 ../界面区域.md）：
     左侧栏 / 文字栏 / 移动栏 / 快捷区域1 / 快捷区域2 / 右侧栏
   本文件里 左侧栏 = #char-body，文字栏 = #log，移动栏 = #move-body，
   右侧栏 = #action-body，快捷区域1/2 = #quick-zone-1 / #quick-zone-2（暂时留空）。 */
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
    clockText: document.getElementById('clock-text'),
    clockTurns: document.getElementById('clock-turns'),
    charBody: document.getElementById('char-body'),   // 左侧栏
    moveBody: document.getElementById('move-body'),    // 移动栏
    actionBody: document.getElementById('action-body'),  // 右侧栏
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
  var modalKind = null;  // 'skills' / 'bag' / 'confirm' / null
  var lastState = null;
  var saveMode = null;   // 存档盘上选中的动作：'save' / 'load' / 'clear'
  var restMinutes = 60;  // 休息滑条当前选的分钟数（重绘界面后要保留）

  // 界面用到的图标名，集中列在这里，方便和 web/icons.svg 对照检查
  var USED_ICONS = [
    'n', 's', 'e', 'w', 'up', 'down',
    'look', 'take', 'drop', 'bag', 'person', 'skills', 'map', 'stance', 'dice',
    'talk', 'save', 'load', 'help', 'exit', 'check', 'x', 'hp', 'weight',
    'equip', 'unequip', 'learn', 'plus', 'minus', 'clock', 'rest', 'use', 'item-generic'
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

  /* ---------- 背包：弹层 + 右侧 3 格快捷栏 ---------- */

  var QUICK_KEY = 'fengcheng.quick';
  var QUICK_MAX = 3;
  var pinned = loadPinned();  // 玩家钉在快捷栏上的物品 id

  function loadPinned() {
    try {
      var list = JSON.parse(window.localStorage.getItem(QUICK_KEY) || '[]');
      return Object.prototype.toString.call(list) === '[object Array]' ? list : [];
    } catch (err) {
      return [];
    }
  }

  function savePinned() {
    try { window.localStorage.setItem(QUICK_KEY, JSON.stringify(pinned)); } catch (err) { /* 无痕模式就算了 */ }
  }

  function isPinned(id) { return pinned.indexOf(id) >= 0; }

  function togglePin(id) {
    var at = pinned.indexOf(id);
    if (at >= 0) pinned.splice(at, 1);
    else pinned.unshift(id);
    savePinned();
    if (lastState) {
      renderActions(lastState);
      if (modalKind === 'bag') renderBagModal(lastState);
    }
  }

  // 快捷栏里放哪三件：先放玩家钉过的，剩下用背包顺序补齐
  function quickItems(state) {
    var inv = (state && state.inventory) || [];
    var picked = [];
    pinned.forEach(function (id) {
      if (picked.length >= QUICK_MAX) return;
      var hit = inv.filter(function (x) { return x.id === id; })[0];
      if (hit && picked.indexOf(hit) < 0) picked.push(hit);
    });
    inv.forEach(function (item) {
      if (picked.length < QUICK_MAX && picked.indexOf(item) < 0) picked.push(item);
    });
    return picked;
  }

  function quickBar(state) {
    var items = quickItems(state);
    var html = '<div class="quick-grid">';
    for (var i = 0; i < QUICK_MAX; i++) {
      var item = items[i];
      if (!item) {
        html += '<span class="quick quick-empty"><span class="quick-name">空</span></span>';
        continue;
      }
      var quick = item.quick || { cmd: '查看 ' + item.name, label: '查看' };
      html += '<button type="button" class="quick" data-cmd="' + esc(quick.cmd) + '" title="' +
        esc(item.name + '：点一下就是「' + quick.label + '」；在背包里点 ★ 可以换快捷物品') + '">' +
        itemIcon(item.id) + '<span class="quick-name">' + esc(item.name) + '</span>' +
        '<span class="quick-act">' + esc(quick.label) + '</span></button>';
    }
    return html + '</div>';
  }

  function bagRow(item) {
    var acts = '';
    if (item.usable) acts += btn('使用 ' + item.name, '使用', 'use', 'small');
    acts += btn('查看 ' + item.name, '查看', 'look', 'small');
    acts += btn('装备 ' + item.name, '装备', 'equip', 'small');
    acts += btn('卸下 ' + item.name, '卸下', 'unequip', 'small');
    acts += btn('放下 ' + item.name, '放下', 'drop', 'small');
    var pin = isPinned(item.id);
    return '<div class="entry bag-entry">' +
      '<div class="entry-top">' + itemIcon(item.id) +
      '<span class="entry-name">' + esc(item.name) + '</span>' +
      (item.where ? '<span class="tag">' + esc(item.where) + '</span>' : '') +
      '<span class="tag">' + esc(item.weight) + ' kg</span>' +
      '<button type="button" class="btn small pin' + (pin ? ' pinned' : '') + '" data-pin="' +
      esc(item.id) + '" title="放进 / 移出右边的快捷栏">★</button>' +
      '</div>' +
      (item.desc ? '<div class="entry-desc">' + esc(item.desc) + '</div>' : '') +
      (item.use_hint ? '<div class="entry-desc">' + esc(item.use_hint) + '</div>' : '') +
      '<div class="entry-actions">' + acts + '</div></div>';
  }

  function renderBagModal(state) {
    var inv = (state && state.inventory) || [];
    var carry = state && state.carry;
    var html = '<p class="modal-note">背包里一共 ' + inv.length + ' 件，负重 ' +
      esc(carry ? carry.weight : '?') + ' / ' + esc(carry ? carry.capacity : '?') +
      ' kg。点 ★ 可以把物品钉到右边那 3 格快捷栏上。</p>';
    if (!inv.length) html += '<span class="empty">背包是空的。</span>';
    inv.forEach(function (item) { html += bagRow(item); });
    el.modalBody.innerHTML = html;
  }

  // 浮层里要显示什么，由 modalKind 决定
  function renderModal(state) {
    if (!state) return;
    if (modalKind === 'skills') renderSkillsModal(state);
    else if (modalKind === 'bag') renderBagModal(state);
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
    var hint = saveMode
      ? '已选「' + SAVE_MODE_LABEL[saveMode] + '」，点下面 1 / 2 / 3 对那个槽执行。'
      : '先点上面一个动作（选中会变绿），再点 1 / 2 / 3。当前槽：' + ((state && state.current_slot) || 1) + ' 号。';
    return html + '<p class="hint-small">' + esc(hint) + '</p>';
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
    return fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body || {})
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

  function renderState(state) {
    if (!state) return;
    lastState = state;
    if (state.time) {
      el.clockText.textContent = state.time.text;
      el.clockTurns.textContent = (typeof state.turns === 'number') ? '第 ' + state.turns + ' 回合' : '';
    }
    if (state.room) {
      el.roomName.textContent = state.room.name;
      var bits = [];
      if (typeof state.turns === 'number') bits.push('第 ' + state.turns + ' 回合');
      if (state.stance) bits.push('姿态：' + state.stance);
      el.roomSub.textContent = bits.join(' · ');
    }
    renderChar(state);
    renderActions(state);
    // 技能 / 背包浮层开着的话，用完东西之后要跟着刷新
    if ((modalKind === 'skills' || modalKind === 'bag') && !el.modal.classList.contains('hidden')) {
      renderModal(state);
    }
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

    html += '<div class="hp-row">' + icon('hp') + '<div class="hp-track"><div class="hp-fill" style="width:' +
      pct + '%"></div></div><span>' + esc(c.hp) + '/' + esc(hpMax) + '</span></div>';

    if (state.stamina) {
      var st = state.stamina;
      var sPct = Math.max(0, Math.min(100, Math.round(st.value / Math.max(1, st.max) * 100)));
      var sCls = st.value <= 0 ? ' empty' : (st.exhausted ? ' low' : '');
      html += '<div class="hp-row">' + icon('rest') + '<div class="hp-track stamina-track">' +
        '<div class="hp-fill stamina-fill' + sCls + '" style="width:' + sPct + '%"></div></div><span>' +
        esc(st.value) + '/' + esc(st.max) + '</span></div>';
      html += '<div class="kv"><span class="k">行动消耗</span><span class="v">×' +
        esc(Number(st.cost_multiplier).toFixed(2)) +
        (state.attack_penalty ? '　攻击 ' + esc(state.attack_penalty) + '%' : '') + '</span></div>';
    }

    html += '<div class="kv"><span class="k">等级</span><span class="v">' + esc(c.level) +
      '（经验 ' + esc(c.xp) + '）</span></div>';
    html += '<div class="kv"><span class="k">技能点</span><span class="v">' + esc(c.skill_points) + '</span></div>';

    html += '<div class="section"><h4>' + icon('person') + '属性</h4><div class="attr-grid">';
    (c.attributes || []).forEach(function (a) {
      html += '<div class="attr"><span class="n">' + esc(a.name) + '</span><span class="v">' + esc(a.value) + '</span></div>';
    });
    html += '</div></div>';

    if (state.combat) {
      var cb = state.combat;
      html += '<div class="section"><h4>' + icon('stance') + '战斗</h4>';
      html += '<div class="kv"><span class="k">行动点</span><span class="v">每回合 ' + esc(cb.ap_per_turn) +
        '（上限 ' + esc(cb.ap_cap) + (cb.armor_ap_penalty ? '，重甲 −' + esc(cb.armor_ap_penalty) : '') +
        '）</span></div>';
      (cb.weapons || []).forEach(function (w) {
        var mult = 1;
        (w.damage_modifiers || []).forEach(function (m) { mult *= (100 + m[1]) / 100; });
        var dmg = w.damage ? w.damage + (mult !== 1 ? ' ×' + Number(mult.toFixed(3)) : '') +
          '（暴击 ' + w.crit_range + '）' : '未定';
        html += '<div class="kv"><span class="k">' + esc(w.hand) + '·' + esc(w.name) + '</span><span class="v">精准 ' +
          esc(w.accuracy) + ' · 伤害 ' + esc(dmg) + '</span></div>';
      });
      html += '<div class="kv"><span class="k">护甲</span><span class="v">' + esc(cb.armor) +
        ((cb.worn || []).length ? '（' + cb.worn.map(function (p) {
          return esc(p.slot) + ' ' + esc(p.name) + ' +' + esc(p.value);
        }).join('、') + '）' : '') + '</span></div>';
      html += '<div class="kv"><span class="k">闪避</span><span class="v">' + esc(cb.dodge) + '</span></div>';
      html += '<div class="kv"><span class="k">先攻</span><span class="v">' + esc(cb.initiative) + '</span></div>';
      html += '<div class="kv"><span class="k">行动点消耗</span><span class="v">攻击 ' + esc(cb.attack_cost) +
        ' · 移动 ' + esc(cb.move_cost) + ' · 物品 ' + esc(cb.item_cost) + '</span></div>';
      html += '</div>';
    }

    if (state.conditions && state.conditions.length) {
      html += '<div class="section"><h4>' + icon('x') + '异常状态</h4>';
      state.conditions.forEach(function (x) {
        html += '<div class="cond"><span class="cond-name">' + esc(x.name) + '</span>' +
          '<span class="cond-eff">' + esc(x.effect) + '</span>' +
          (x.note ? '<span class="cond-note">' + esc(x.note) + '</span>' : '') + '</div>';
      });
      html += '</div>';
    }

    if (state.carry) {
      html += '<div class="section"><h4>' + icon('weight') + '负重</h4>' +
        '<div class="kv"><span class="k">当前</span><span class="v">' + esc(state.carry.weight) +
        ' / ' + esc(state.carry.capacity) + ' kg' +
        (state.backpack_reduction ? '（背包减重 ' + esc(state.backpack_reduction) + '%）' : '') +
        '</span></div></div>';
    }

    if (state.equipment) {
      html += '<div class="section"><h4>' + icon('stance') + '装备</h4>';
      html += '<div class="kv"><span class="k">持握</span><span class="v">' + esc(state.grip || '徒手') + '</span></div>';
      html += '<div class="kv"><span class="k">主手</span><span class="v">' + esc(state.equipment.main_hand || '空') + '</span></div>';
      html += '<div class="kv"><span class="k">副手</span><span class="v">' + esc(state.equipment.off_hand || '空') + '</span></div>';
      (state.gear || []).forEach(function (g) {
        html += '<div class="kv"><span class="k">' + esc(g.slot) + '</span><span class="v">' + esc(g.name || '空') + '</span></div>';
      });
      html += '<div class="kv"><span class="k">姿态</span><span class="v">' + esc(state.stance || '无') + '</span></div>';
      html += '</div>';
    }

    if (c.companions && c.companions.length) {
      html += '<div class="section"><h4>' + icon('talk') + '同伴</h4>';
      c.companions.forEach(function (p) {
        html += '<div class="kv"><span class="k">' + esc(p.relationship || '同伴') + '</span><span class="v">' +
          esc(p.name) + '（' + esc(p.age) + ' 岁）</span></div>';
      });
      html += '</div>';
    }

    el.charBody.innerHTML = html;
  }

  function renderActions(state) {
    // 按界面区域分工（区域约定见 ../界面区域.md）：
    //   移动栏 = #move-body，右侧栏 = #action-body，快捷区域1/2 暂时留空。
    if (el.moveBody) el.moveBody.innerHTML = moveSection(state);
    el.actionBody.innerHTML =
      hereSection(state) +
      bagSection(state) +
      (state.rest ? restSection(state) : '') +
      saveSection(state) +
      systemSection();
    bindActionControls();
  }

  /* ---------- 移动栏（文字栏下面正中间那块） ---------- */

  function moveSection(state) {
    // 六个方向常驻，颜色说明能不能走
    var byDir = {};
    (state.exits || []).forEach(function (e) { byDir[e.id] = e; });

    function dirBtn(id) {
      var e = byDir[id];
      if (!e) return '<span class="dir-empty"></span>';
      var cls = e.state === 'open' ? 'dir-open' : (e.state === 'danger' ? 'dir-danger' : 'dir-unknown');
      var sub, title;
      if (e.state === 'danger') {
        sub = '危险';
        title = e.danger || '那边有危险';
      } else if (e.state === 'open') {
        sub = e.target || '未探索';
        title = (e.target ? '通往 ' + e.target : '还没走过那边') +
          '（' + e.cost + ' 点体力 / ' + e.minutes + ' 分钟）';
      } else {
        sub = '？';
        title = '不知道那边能不能走，走走看（' + e.cost + ' 点体力 / ' + e.minutes + ' 分钟）';
      }
      return '<button type="button" class="dir ' + cls + '" data-cmd="走 ' + esc(e.name) +
        '" title="' + esc(title) + '">' + icon(DIR_ICON[id] || 'map') +
        '<span class="dir-name">' + esc(e.name) + '</span>' +
        '<span class="dir-sub">' + esc(sub) + '</span></button>';
    }

    return '<div class="dir-grid">' +
      dirBtn('up') + dirBtn('north') + dirBtn('down') +
      dirBtn('west') + '<span class="dir-center">' + esc(state.room ? state.room.name : '') + '</span>' +
      dirBtn('east') +
      '<span class="dir-empty"></span>' + dirBtn('south') + '<span class="dir-empty"></span>' +
      '</div><p class="hint-small">绿＝可以走，红＝那边有危险，暗色＝不知道，点了才知道</p>';
  }

  /* ---------- 右侧栏的几段 ---------- */

  // 这个地点
  function hereSection(state) {
    var html = '<div class="section"><h4>' + icon('look') + '这里</h4>';
    var here = state.room_items || [];
    var npcs = state.npcs || [];
    if (!here.length && !npcs.length) {
      html += '<span class="empty">没有值得注意的东西。</span>';
    }
    here.forEach(function (item) {
      html += '<div class="entry"><div class="entry-top">' + itemIcon(item.id) +
        '<span class="entry-name">' + esc(item.name) + '</span></div><div class="entry-actions">' +
        btn('拿 ' + item.name, '拿取', 'take', 'small') +
        btn('查看 ' + item.name, '查看', 'look', 'small') +
        '</div></div>';
    });
    npcs.forEach(function (npc) {
      html += '<div class="entry"><div class="entry-top">' + icon('talk') +
        '<span class="entry-name">' + esc(npc.name) + '</span></div><div class="entry-actions">' +
        btn('说话 ' + npc.name, '交谈', 'talk', 'small') +
        '</div></div>';
    });
    return html + '</div>';
  }

  // 背包：右侧只留 3 格快捷栏，完整列表点按钮展开（和技能树一样的浮层）
  function bagSection(state) {
    return '<div class="section"><h4>' + icon('bag') + '背包快捷栏</h4>' +
      quickBar(state) +
      '<div class="btn-grid mt8">' + modalBtn('bag', '打开背包', 'bag', 'small') + '</div>' +
      '<p class="hint-small">点物品＝使用 / 装备 / 查看；在背包里点 ★ 可以换快捷栏里的东西。</p></div>';
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
      btn('背包', '背包', 'bag', 'small') +
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
    html += '</div></div><p class="hint-small">' + esc(rest.hint || '') + '</p>';
    if (full) {
      html += '<p class="hint-small warn">体力已经是满的：休息不会拦着你，时间照样会过去。</p>';
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

  /* ---------- 心跳：让再次启动的进程知道页面还开着 ---------- */

  var heartbeatTimer = null;

  function startHeartbeat() {
    if (heartbeatTimer) return;
    heartbeatTimer = setInterval(function () {
      post('/api/heartbeat').catch(function () { /* 服务关了就算了 */ });
    }, 20000);
  }

  function stopHeartbeat() {
    if (heartbeatTimer) {
      clearInterval(heartbeatTimer);
      heartbeatTimer = null;
    }
  }

  function sendCommand(text) {
    if (busy || !text) return;
    setBusy(true);
    post('/api/command', { text: text }).then(function (res) {
      setBusy(false);
      handlePayload(res);
    }).catch(function (err) { setBusy(false); fail(err); });
  }

  /* ---------- 事件绑定 ---------- */

  document.addEventListener('click', function (event) {
    var cmdNode = event.target.closest ? event.target.closest('[data-cmd]') : null;
    if (cmdNode) {
      event.preventDefault();
      sendCommand(cmdNode.getAttribute('data-cmd'));
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
      var kind = modalNode.getAttribute('data-modal') || 'skills';
      openModal(kind, kind === 'bag' ? '背包' : '技能树');
      renderModal(lastState);
      return;
    }
    var pinNode = event.target.closest ? event.target.closest('[data-pin]') : null;
    if (pinNode) {
      event.preventDefault();
      togglePin(pinNode.getAttribute('data-pin'));
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
    if (event.key === 'Escape' && !el.modal.classList.contains('hidden')) closeModal();
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
        openModal('bag', '背包');
        renderModal(state);
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
