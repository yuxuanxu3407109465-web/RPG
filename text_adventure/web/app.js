/* 封城第七天 · 按钮版前端
   所有按钮最终都翻译成一句玩家指令（data-cmd），发给 /api/command 由引擎处理。
   角色创建走 /api/new → /api/answer 的一问一答。 */
(function () {
  'use strict';

  var el = {
    menu: document.getElementById('screen-menu'),
    create: document.getElementById('screen-create'),
    play: document.getElementById('screen-play'),
    menuHint: document.getElementById('menu-hint'),
    createLog: document.getElementById('create-log'),
    createPrompt: document.getElementById('create-prompt'),
    createSteps: document.getElementById('create-steps'),
    log: document.getElementById('log'),
    roomName: document.getElementById('room-name'),
    roomSub: document.getElementById('room-sub'),
    clockText: document.getElementById('clock-text'),
    clockTurns: document.getElementById('clock-turns'),
    charBody: document.getElementById('char-body'),
    actionBody: document.getElementById('action-body'),
    cmdForm: document.getElementById('cmd-form'),
    cmdInput: document.getElementById('cmd-input')
  };

  var busy = false;
  var answered = 0;
  var currentMode = 'menu';
  var lastChoices = 0;  // 当前问题有几个选项（用来支持按数字键快速选择）
  var toastTimer = null;

  // 界面用到的图标名，集中列在这里，方便和 web/icons.svg 对照检查
  var USED_ICONS = [
    'n', 's', 'e', 'w', 'up', 'down',
    'look', 'take', 'drop', 'bag', 'person', 'skills', 'map', 'stance', 'dice',
    'talk', 'save', 'load', 'help', 'exit', 'check', 'x', 'hp', 'weight',
    'equip', 'unequip', 'learn', 'plus', 'minus', 'clock', 'rest', 'item-generic'
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

  function show(name) {
    currentMode = name;
    el.menu.classList.toggle('hidden', name !== 'menu');
    el.create.classList.toggle('hidden', name !== 'create');
    el.play.classList.toggle('hidden', name !== 'play');
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
    el.actionBody.style.pointerEvents = flag ? 'none' : '';
    el.actionBody.style.opacity = flag ? '.6' : '';
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
        ' / ' + esc(state.carry.capacity) + ' kg</span></div></div>';
    }

    if (state.equipment) {
      html += '<div class="section"><h4>' + icon('stance') + '装备</h4>';
      html += '<div class="kv"><span class="k">主手</span><span class="v">' + esc(state.equipment.main_hand || '空') + '</span></div>';
      html += '<div class="kv"><span class="k">副手</span><span class="v">' + esc(state.equipment.off_hand || '空') + '</span></div>';
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
    var html = '';

    // 移动：六个方向常驻，颜色说明能不能走
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

    html += '<div class="section"><h4>' + icon('map') + '移动</h4>' +
      '<div class="dir-grid">' +
      dirBtn('up') + dirBtn('north') + dirBtn('down') +
      dirBtn('west') + '<span class="dir-center">' + esc(state.room ? state.room.name : '') + '</span>' +
      dirBtn('east') +
      '<span class="dir-empty"></span>' + dirBtn('south') + '<span class="dir-empty"></span>' +
      '</div><p class="hint-small">绿＝可以走，红＝那边有危险，暗色＝不知道，点了才知道</p></div>';

    // 这个地点
    html += '<div class="section"><h4>' + icon('look') + '这里</h4>';
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
    html += '</div>';

    // 背包
    html += '<div class="section"><h4>' + icon('bag') + '背包</h4>';
    var inv = state.inventory || [];
    if (!inv.length) {
      html += '<span class="empty">背包是空的。</span>';
    }
    inv.forEach(function (item) {
      html += '<div class="entry"><div class="entry-top">' + itemIcon(item.id) +
        '<span class="entry-name">' + esc(item.name) +
        (item.where ? ' <span class="tag">' + esc(item.where) + '</span>' : '') +
        '</span></div><div class="entry-actions">' +
        btn('查看 ' + item.name, '查看', 'look', 'small') +
        btn('装备 ' + item.name, '装备', 'equip', 'small') +
        btn('卸下 ' + item.name, '卸下', 'unequip', 'small') +
        btn('放下 ' + item.name, '放下', 'drop', 'small') +
        '</div></div>';
    });
    html += '</div>';

    // 休息
    if (state.rest) {
      html += '<div class="section"><h4>' + icon('rest') + '休息</h4><div class="btn-grid">';
      (state.rest.presets || []).forEach(function (r) {
        html += btn('休息 ' + r.minutes, r.label, 'rest', 'small');
      });
      html += '</div><p class="hint-small">' + esc(state.rest.hint) +
        '（体力满了会提前结束）</p></div>';
    }

    // 技能：能学的直接点按钮
    if (state.skills) {
      html += '<div class="section"><h4>' + icon('skills') + '技能（技能点 ' +
        esc(state.skills.points) + '）</h4>';
      (state.skills.trees || []).forEach(function (tree) {
        html += '<div class="skill-tree"><div class="skill-tree-name">' + esc(tree.name) +
          (tree.unlocked ? '' : ' · ' + esc(tree.locked_message)) + '</div><div class="btn-grid">';
        (tree.skills || []).forEach(function (s) {
          if (s.learned) {
            html += '<span class="chip chip-done">' + esc(s.name) + '</span>';
          } else if (!tree.unlocked) {
            html += '<span class="chip">' + esc(s.name) + '</span>';
          } else if (s.unmet && s.unmet.length) {
            html += '<span class="chip" title="' + esc(s.unmet.join('、')) + '">' + esc(s.name) +
              '（' + esc(s.unmet.join('、')) + '）</span>';
          } else {
            html += btn('学习 ' + s.name, s.name + ' ' + s.cost + '点', 'learn', 'small');
          }
        });
        html += '</div></div>';
      });
      html += '</div>';
    }

    // 系统
    html += '<div class="section"><h4>' + icon('help') + '系统</h4><div class="btn-grid">' +
      btn('地图', '地图', 'map', 'small') +
      btn('角色', '角色卡', 'person', 'small') +
      btn('背包', '背包', 'bag', 'small') +
      btn('技能', '技能树', 'skills', 'small') +
      btn('存档', '存档', 'save', 'small') +
      btn('读档', '读档', 'load', 'small') +
      btn('帮助', '帮助', 'help', 'small') +
      fillBtn('技能 ', '查看某棵树', 'skills') +
      fillBtn('学习 ', '学习技能', 'learn') +
      fillBtn('姿态 ', '切换姿态', 'stance') +
      fillBtn('掷骰 ', '掷骰', 'dice') +
      fillBtn('检定 ', '检定', 'check') +
      btn('退出', '退出游戏', 'exit', 'small danger') +
      '</div></div>';

    el.actionBody.innerHTML = html;
  }

  /* ---------- 请求流程 ---------- */

  function handlePayload(data) {
    if (!data) return;
    if (data.type === 'state') { applyBoot(data.state); return; }
    if (data.type === 'prompt') {
      show('create');
      appendLines(el.createLog, data.lines);
      renderPrompt(data);
      return;
    }
    if (data.type === 'play') {
      show('play');
      appendLines(el.log, data.lines);
      renderState(data.state);
      if (data.notice) showToast(data.notice);
      return;
    }
    // error
    var target = currentMode === 'create' ? el.createLog : el.log;
    if (currentMode === 'menu') { show('menu'); el.menuHint.textContent = (data.lines || []).join(' '); return; }
    appendLines(target, data.lines);
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
    var actNode = event.target.closest ? event.target.closest('[data-act]') : null;
    if (actNode) {
      event.preventDefault();
      if (actNode.getAttribute('data-act') === 'new') startNew();
      else continueGame();
    }
  });

  el.cmdForm.addEventListener('submit', function (event) {
    event.preventDefault();
    var text = el.cmdInput.value.trim();
    if (!text) return;
    el.cmdInput.value = '';
    sendCommand(text);
  });

  /* ---------- 启动 ---------- */

  function applyBoot(state) {
    if (!state) { show('menu'); return; }
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
      return;
    }
    show('menu');
    var btnContinue = document.getElementById('btn-continue');
    if (state.has_save) {
      btnContinue.disabled = false;
      el.menuHint.textContent = '检测到存档，可以继续上次的进度。';
    } else {
      btnContinue.disabled = true;
      el.menuHint.textContent = '还没有存档，先开始一局新游戏。';
    }
  }

  fetch('/api/state').then(function (res) { return res.json(); })
    .then(function (data) { applyBoot(data.state); })
    .catch(function (err) { show('menu'); el.menuHint.textContent = '连接不上服务器：' + err.message; });
})();
