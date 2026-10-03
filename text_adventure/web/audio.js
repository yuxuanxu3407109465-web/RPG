/* 封城第七天 · 打击音效与背景音乐（全部现场合成，不加载任何音频文件）
   为什么不用音频文件：这是本地网页版，不联网、不引第三方库，也很难找到版权干净的素材；
   索性全部用 Web Audio 现场合成——打击声是「噪声爆破 + 低频冲击」，背景音乐是几段极简氛围循环。
   离线可用、没有版权问题、不占体积，也不会发出任何网络请求。

   用法（接线都在 app.js）：
     · 页面第一次点击时调一次 GameAudio.unlock()：浏览器要求有用户手势才允许出声；
     · GameAudio.play('hit' / 'crit' / ...) 放一个音效；
     · GameAudio.music.scene('street' / 'interior' / 'danger' / 'night') 按场景自动换曲，
       设置面板里可以用 music.play(id) 手选曲目、music.setVolume(v) 调背景音乐音量。
   两条底线：
     · 没有 AudioContext（老浏览器、node 里跑）、还没解锁、音效名或曲目 id 不认识 —— 一律静默返回，绝不抛异常；
     · 音量、音乐开关、选过的曲目存在 localStorage 的 fengcheng.audio 里，下次打开还是这套设置。 */
var GameAudio = (function () {
  'use strict';

  var STORE_KEY = 'fengcheng.audio';   // localStorage 里就用这一个键，几项设置打包成一个 JSON

  var root = (typeof window !== 'undefined' && window) ? window : {};

  var ctx = null;             // AudioContext：用户第一次点击（unlock）之后才建
  var sfxGain = null;         // 音效总音量
  var musicGain = null;       // 音乐总音量（音效和音乐各走一条 GainNode，互不牵连）
  var noiseBuf = null;        // 白噪声缓冲：现场生成一次，之后所有噪声类音效共用

  var sfxVolume = 0.8;        // 打击音效默认给大一点：默认偏小会「打上去没感觉」，正是这次要修的问题
  var musicVolume = 0.5;      // 背景音乐默认 0.5：氛围音乐是垫底的，不该盖过文字栏
  var autoOn = true;          // 默认按场景自动换曲
  var sceneName = '';         // 最近一次场景提示（street / interior / danger / night）
  var wanted = '';            // 最近一次「想放哪首」：解锁前先记着，解锁后再补上
  var curId = null;           // 正在响的曲目 id（null = 没在放）

  /* ================= 通用小工具 ================= */

  function clamp01(v) {
    v = Number(v);
    if (isNaN(v)) return 0;
    if (v < 0) return 0;
    if (v > 1) return 1;
    return v;
  }

  function now() { return ctx ? ctx.currentTime : 0; }

  // 平滑改一个增益：先把当前值钉住，再线性过渡过去。
  // 为什么不用 setTargetAtTime：它按指数逼近，永远到不了 0，音量拖到 0 还会留一点余音。
  function ramp(node, value, seconds) {
    if (!node) return;
    var t = now();
    try {
      node.gain.cancelScheduledValues(t);
      node.gain.setValueAtTime(node.gain.value, t);
      node.gain.linearRampToValueAtTime(value, t + (seconds || 0.08));
    } catch (e) {
      try { node.gain.value = value; } catch (e2) {}
    }
  }

  // 用完就断开：不然每响一声都留一串节点挂在图上，玩久了越堆越多，帧率和内存都吃亏
  function drop() {
    for (var i = 0; i < arguments.length; i++) {
      try { if (arguments[i] && arguments[i].disconnect) arguments[i].disconnect(); } catch (e) {}
    }
  }

  function timerSet(fn, ms) {
    if (typeof setInterval === 'function') return setInterval(fn, ms);
    if (root.setInterval) return root.setInterval(fn, ms);
    return null;
  }

  function timerClear(id) {
    if (id === null || id === undefined) return;
    try {
      if (typeof clearInterval === 'function') clearInterval(id);
      else if (root.clearInterval) root.clearInterval(id);
    } catch (e) {}
  }

  function timerLater(fn, ms) {
    if (typeof setTimeout === 'function') return setTimeout(fn, ms);
    if (root.setTimeout) return root.setTimeout(fn, ms);
    return null;
  }

  // AudioParam 的最小可用写法：老实现里可能连 setValueAtTime 都没有，直接给 value 赋值也能响
  function setParam(param, value, at) {
    try {
      if (param && param.setValueAtTime) param.setValueAtTime(value, at);
      else if (param) param.value = value;
    } catch (e) {}
  }

  function setDetune(osc, cents, at) {
    try { if (osc.detune) setParam(osc.detune, cents, at); } catch (e) {}
  }

  function setQ(filter, q, at) {
    try { if (filter.Q) setParam(filter.Q, q, at); } catch (e) {}
  }

  // 让一个参数「滑」到目标值（频率下滑、滤波扫频都用它）；指数过渡听感最自然，但要避开 0
  function sweep(param, value, at) {
    try {
      if (param && param.exponentialRampToValueAtTime) {
        param.exponentialRampToValueAtTime(Math.max(1, value), at);
      } else {
        setParam(param, value, at);
      }
    } catch (e) {}
  }

  /* ================= 基础发声零件 ================= */

  // 白噪声：一段两秒的随机波形，噪声类音效（爆破、呼啸、气声）都从它取样
  function noiseBuffer() {
    if (noiseBuf || !ctx) return noiseBuf;
    try {
      var len = Math.floor(ctx.sampleRate * 2);
      noiseBuf = ctx.createBuffer(1, len, ctx.sampleRate);
      var data = noiseBuf.getChannelData(0);
      for (var i = 0; i < len; i++) data[i] = Math.random() * 2 - 1;
    } catch (e) {
      noiseBuf = null;
    }
    return noiseBuf;
  }

  // 一个简单的振荡器音符：包络写成「很快起音 + 指数衰减」——打击乐、拨弦的听感就是这么来的。
  // glideFreq 给「往下掉」的音用（闷响、呼啸、心跳）；attack 给需要慢慢起来的音（pad、气声）用。
  function tone(type, freq, at, dur, peak, bus, glideFreq, attack) {
    if (!ctx || !bus) return null;
    try {
      var osc = ctx.createOscillator();
      var g = ctx.createGain();
      osc.type = type;
      setParam(osc.frequency, freq, at);
      if (glideFreq) sweep(osc.frequency, glideFreq, at + dur);
      var rise = attack || Math.min(0.012, dur * 0.25);
      g.gain.setValueAtTime(0.0001, at);
      g.gain.exponentialRampToValueAtTime(Math.max(0.0002, peak), at + rise);
      g.gain.exponentialRampToValueAtTime(0.0001, at + dur);
      osc.connect(g);
      g.connect(bus);
      osc.start(at);
      osc.stop(at + dur + 0.03);
      osc.onended = function () { drop(osc, g); };
      return { osc: osc, gain: g };
    } catch (e) {
      return null;
    }
  }

  // 噪声音：滤波器（低通 = 闷响、带通 = 呼啸/金属、高通 = 细碎）扫频 + 包络，需要多长给多长
  function noise(at, dur, bus, type, freq, q, sweepTo, peak, attack) {
    if (!ctx || !bus) return null;
    var buf = noiseBuffer();
    if (!buf) return null;
    try {
      var src = ctx.createBufferSource();
      src.buffer = buf;
      src.loop = true;
      var filter = ctx.createBiquadFilter();
      filter.type = type || 'lowpass';
      setParam(filter.frequency, freq, at);
      if (sweepTo) sweep(filter.frequency, sweepTo, at + dur);
      if (q) setQ(filter, q, at);
      var g = ctx.createGain();
      var rise = attack || Math.min(0.008, dur * 0.3);
      g.gain.setValueAtTime(0.0001, at);
      g.gain.exponentialRampToValueAtTime(Math.max(0.0002, peak), at + rise);
      g.gain.exponentialRampToValueAtTime(0.0001, at + dur);
      src.connect(filter);
      filter.connect(g);
      g.connect(bus);
      src.start(at);
      src.stop(at + dur + 0.03);
      src.onended = function () { drop(src, filter, g); };
      return { src: src, gain: g };
    } catch (e) {
      return null;
    }
  }

  // 持续音 / 和弦垫：起音和收尾都很慢，一整段循环垫在底下；尾音允许跨过循环点自然衰减
  function pad(at, dur, freq, type, peak, cutoff, bus, attack, detuneCents) {
    if (!ctx || !bus) return null;
    try {
      var osc = ctx.createOscillator();
      osc.type = type;
      setParam(osc.frequency, freq, at);
      if (detuneCents) setDetune(osc, detuneCents, at);
      var filter = ctx.createBiquadFilter();
      filter.type = 'lowpass';
      setParam(filter.frequency, cutoff, at);
      var g = ctx.createGain();
      var rise = attack || Math.min(2.5, dur * 0.25);
      var hold = Math.max(rise + 0.01, dur * 0.55);
      g.gain.setValueAtTime(0.0001, at);
      g.gain.linearRampToValueAtTime(peak, at + rise);
      g.gain.setValueAtTime(peak, at + hold);
      g.gain.linearRampToValueAtTime(0.0001, at + dur);
      osc.connect(filter);
      filter.connect(g);
      g.connect(bus);
      osc.start(at);
      osc.stop(at + dur + 0.05);
      osc.onended = function () { drop(osc, filter, g); };
      return { osc: osc, gain: g };
    } catch (e) {
      return null;
    }
  }

  // 稀疏的旋律音：慢一点的起音 + 长衰减，像拨弦 / 木琴，不刺耳；空旷感主要靠留白
  function pluck(at, freq, dur, bus, peak) {
    if (!ctx || !bus) return null;
    try {
      var osc = ctx.createOscillator();
      osc.type = 'triangle';
      setParam(osc.frequency, freq, at);
      var filter = ctx.createBiquadFilter();
      filter.type = 'lowpass';
      setParam(filter.frequency, 2400, at);
      var g = ctx.createGain();
      g.gain.setValueAtTime(0.0001, at);
      g.gain.linearRampToValueAtTime(peak, at + 0.04);
      g.gain.exponentialRampToValueAtTime(0.0001, at + dur);
      osc.connect(filter);
      filter.connect(g);
      g.connect(bus);
      osc.start(at);
      osc.stop(at + dur + 0.05);
      osc.onended = function () { drop(osc, filter, g); };
      return { osc: osc, gain: g };
    } catch (e) {
      return null;
    }
  }

  /* ================= 打击音效 =================
     清一色现场合成：噪声给「质感」（肉体/金属/空气），低频正弦给「冲击」（身体的钝响）。
     时长都压在一两百毫秒，连打起来才不会糊成一片。 */

  var SFX = {
    // 普通命中：肉上的一记闷击（低通噪声爆破）+ 身体里的低频冲击
    hit: function (at) {
      noise(at, 0.12, sfxGain, 'lowpass', 1400, 0.7, 300, 0.5, 0.004);
      tone('sine', 150, at, 0.14, 0.55, sfxGain, 55);
    },
    // 暴击：更响、更低、更长，再加一层中频「咔嚓」，一听就比普通命中重
    crit: function (at) {
      noise(at, 0.18, sfxGain, 'lowpass', 2200, 0.7, 420, 0.7, 0.002);
      noise(at + 0.012, 0.1, sfxGain, 'bandpass', 950, 1.2, 260, 0.35, 0.003);
      tone('sine', 110, at, 0.34, 0.8, sfxGain, 32);
      tone('triangle', 220, at, 0.18, 0.24, sfxGain, 70);
    },
    // 挥空：短促的呼啸——带通噪声的音调从高处往下滑，只有空气没有撞击
    miss: function (at) {
      noise(at, 0.16, sfxGain, 'bandpass', 2600, 3.5, 600, 0.22, 0.02);
    },
    // 你被打中：闷击 + 一声压低的痛哼（锯齿下滑），比命中更「近」
    hurt: function (at) {
      noise(at, 0.16, sfxGain, 'lowpass', 900, 0.8, 200, 0.55, 0.004);
      tone('sine', 190, at, 0.22, 0.5, sfxGain, 90);
      tone('sawtooth', 150, at, 0.28, 0.16, sfxGain, 80);
    },
    // 格挡成功：金属碰撞——两个不成谐波关系的高频方波 + 极快衰减，末尾一点撞击噪声
    block: function (at) {
      noise(at, 0.08, sfxGain, 'bandpass', 3200, 2, 2000, 0.3, 0.002);
      tone('square', 1180, at, 0.16, 0.22, sfxGain, 900);
      tone('square', 1730, at, 0.13, 0.16, sfxGain, 1320);
      tone('triangle', 2600, at, 0.09, 0.1, sfxGain, 2200);
    },
    // 敌人倒地：低沉的闷响，末尾往下掉一截，像身体砸在地上
    kill: function (at) {
      noise(at, 0.3, sfxGain, 'lowpass', 700, 1, 120, 0.5, 0.006);
      tone('sine', 90, at, 0.45, 0.75, sfxGain, 26);
      tone('triangle', 160, at + 0.02, 0.3, 0.18, sfxGain, 50);
    },
    // 捡东西：两声很轻的（小件东西落进口袋）
    pickup: function (at) {
      noise(at, 0.07, sfxGain, 'bandpass', 1800, 1.6, 1200, 0.16, 0.004);
      tone('triangle', 660, at + 0.02, 0.09, 0.14, sfxGain, 780);
      tone('triangle', 990, at + 0.1, 0.07, 0.1, sfxGain, 880);
    },
    // 开门 / 换场景：门轴的吱呀（低频锯齿慢慢下滑）+ 落定的一声轻响
    door: function (at) {
      noise(at, 0.3, sfxGain, 'bandpass', 700, 1.1, 300, 0.16, 0.05);
      tone('sawtooth', 180, at, 0.34, 0.09, sfxGain, 110);
      noise(at + 0.34, 0.06, sfxGain, 'highpass', 1500, 1, 1200, 0.12, 0.003);
    },
    // 走不通 / 不行：两声往下的小钝音，听着就不像成功
    fail: function (at) {
      tone('square', 220, at, 0.09, 0.12, sfxGain, 200);
      tone('square', 165, at + 0.11, 0.13, 0.12, sfxGain, 140);
    },
    // 点按钮：极短的一声，不能抢戏
    ui: function (at) {
      tone('sine', 1250, at, 0.05, 0.09, sfxGain, 900);
      noise(at, 0.03, sfxGain, 'highpass', 2500, 1, 2000, 0.06, 0.002);
    },
    // 吃东西：两三下含糊的咀嚼（低通噪声的小脉冲）
    eat: function (at) {
      noise(at, 0.1, sfxGain, 'lowpass', 800, 1.4, 300, 0.22, 0.01);
      noise(at + 0.16, 0.09, sfxGain, 'lowpass', 700, 1.4, 280, 0.18, 0.01);
      noise(at + 0.3, 0.08, sfxGain, 'lowpass', 620, 1.4, 250, 0.13, 0.01);
    },
    // 喝水：咽下去的两声（带通噪声先升后落）
    drink: function (at) {
      noise(at, 0.14, sfxGain, 'bandpass', 400, 1.6, 900, 0.2, 0.012);
      noise(at + 0.2, 0.16, sfxGain, 'bandpass', 380, 1.6, 800, 0.14, 0.012);
    },
    // 休息：一声很轻的呼气（低通噪声慢慢起来再落下），别把人吓一跳
    rest: function (at) {
      noise(at, 1.6, sfxGain, 'lowpass', 500, 0.8, 220, 0.1, 0.6);
    }
  };

  function play(name) {
    if (!ctx || !sfxGain) return;         // 还没解锁：静默（浏览器也不允许这时候出声）
    var fx = SFX[name];
    if (!fx) return;                      // 不认识的音效名：同样静默，绝不抛异常
    try { fx(now() + 0.001); } catch (e) {}
  }

  /* ================= 音乐：音高、音色 ================= */

  var SEMI = { c: 0, cs: 1, d: 2, ds: 3, e: 4, f: 5, fs: 6, g: 7, gs: 8, a: 9, as: 10, b: 11 };

  // 十二平均律，A4 = 440Hz。写曲子时用 note('a', 2) 这种写法，比抄频率数字好改
  function note(name, octave) {
    return 440 * Math.pow(2, (SEMI[name] + (octave - 4) * 12 - 9) / 12);
  }

  /* 事件工厂：曲子里每个音都是一个 {t, every, run} 事件，t 是「循环内第几秒」。
     run 里只引用工厂的参数（不引用循环变量），这样每遍循环取到的值才不会串。 */
  function evTone(t, type, freq, dur, peak, glideFreq, attack, every) {
    return { t: t, every: every, run: function (at, bus) {
      tone(type, freq, at, dur, peak, bus, glideFreq, attack);
    } };
  }

  function evNoise(t, dur, type, freq, q, sweepFreq, peak, attack, every) {
    return { t: t, every: every, run: function (at, bus) {
      noise(at, dur, bus, type, freq, q, sweepFreq, peak, attack);
    } };
  }

  function evPad(t, dur, freq, type, peak, cutoff, attack, detune, every) {
    return { t: t, every: every, run: function (at, bus) {
      pad(at, dur, freq, type, peak, cutoff, bus, attack, detune);
    } };
  }

  function evPluck(t, freq, dur, peak, every) {
    return { t: t, every: every, run: function (at, bus) {
      pluck(at, freq, dur, bus, peak);
    } };
  }

  function sorted(list) {
    list.sort(function (a, b) { return a.t - b.t; });
    return list;
  }

  /* ================= 音乐：四首氛围曲 =================
     都是 4 小节一段、首尾能接上的极简循环：音符不超过循环点太多，长音允许尾巴自然衰减。
     音量都压得很低（pad 0.05~0.16），是垫在文字底下的背景，不是主角。 */

  // 白昼街道：中低音持续音 + 稀疏的小调琶音 + 偶尔一声远处的金属敲击
  function buildStreet(spb, bar) {
    var loop = bar * 4;
    var out = [];
    // 持续音：A2 + E3 铺底，整段都挂着，尾巴多留一点和下一遍叠上，接缝就听不出来
    out.push(evPad(0, loop + 1.2, note('a', 2), 'triangle', 0.16, 520, 2.0, 0));
    out.push(evPad(0, loop + 1.2, note('e', 3), 'sine', 0.08, 700, 2.4, 0));
    // 小调琶音：A 小调（A C E D B），一小节只落两三个音，剩下的都是空白
    var mel = [
      [0, 0, 'a', 4, 1.6], [0, 2.5, 'c', 5, 1.2],
      [1, 1, 'e', 5, 1.0], [1, 3, 'd', 5, 1.4],
      [2, 0.5, 'c', 5, 1.1], [2, 2, 'b', 4, 1.0], [2, 3.5, 'a', 4, 1.0],
      [3, 0, 'e', 4, 1.4], [3, 2.5, 'a', 4, 2.0]
    ];
    for (var i = 0; i < mel.length; i++) {
      var m = mel[i];
      out.push(evPluck((m[0] * 4 + m[1]) * spb, note(m[2], m[3]), m[4] * spb, 0.075));
    }
    // 远处的金属敲击：两遍循环才响一次，稀疏才不会变成节拍器
    out.push(evTone((2 * 4 + 2) * spb, 'square', 1568, 0.5, 0.04, 1552, 0.004, 2));
    out.push(evTone((2 * 4 + 2) * spb, 'square', 2349, 0.4, 0.026, 2320, 0.004, 2));
    out.push(evNoise((2 * 4 + 2) * spb, 0.1, 'bandpass', 3000, 2.5, 1700, 0.05, 0.002, 2));
    return sorted(out);
  }

  // 楼里：暗色小三和弦长音（微微失谐 → 有室内空间感）+ 偶尔的低频脉冲 + 一层很闷的空气声
  function buildInterior(spb, bar) {
    var loop = bar * 4;
    var out = [];
    // D 小调三和弦（D F A）：每个音做两条微微失谐的振荡器，听着就像屋里有混响
    var chord = [['d', 3, 0.07, 420], ['f', 3, 0.055, 440], ['a', 3, 0.045, 480]];
    for (var i = 0; i < chord.length; i++) {
      var c = chord[i];
      out.push(evPad(0, loop + 2.0, note(c[0], c[1]), 'triangle', c[2], c[3], 3.0, -4));
      out.push(evPad(0, loop + 2.0, note(c[0], c[1]), 'triangle', c[2] * 0.8, c[3], 3.6, 5));
    }
    // 低频脉冲：像楼里某处还在运转的机器，一小节半才来一下
    out.push(evTone(1 * bar, 'sine', 73.42, 1.8, 0.1, 66, 0.25));
    out.push(evTone(3 * bar + 2 * spb, 'sine', 73.42, 1.6, 0.075, 68, 0.3));
    // 空气声：一层很低很闷的噪声垫底，别让pad之间空得太干净（室内不会那么「干」）
    out.push(evNoise(0, loop + 1.0, 'lowpass', 260, 0.7, 200, 0.03, 3.5));
    return sorted(out);
  }

  // 危险逼近：心跳般的低音重拍 + 不协和的半音簇 + 偶尔一声三全音，紧张但按着节奏走
  function buildDanger(spb, bar) {
    var out = [];
    // 心跳：每小节的第 1、3 拍各来一下「扑通」（一重一轻紧跟），节奏感全靠它
    for (var i = 0; i < 4; i++) {
      out.push(evTone((i * 4) * spb, 'sine', 58, 0.34, 0.3, 40, 0.005));
      out.push(evTone((i * 4 + 0.8) * spb, 'sine', 50, 0.26, 0.18, 36, 0.005));
      out.push(evTone((i * 4 + 2) * spb, 'sine', 58, 0.34, 0.26, 40, 0.005));
      out.push(evTone((i * 4 + 2.8) * spb, 'sine', 50, 0.26, 0.15, 36, 0.005));
    }
    // 不协和的半音簇（C 和升 C 一起响）：两小节涨一次落一次，都走低通，所以刺耳不起来
    out.push(evPad(0, bar * 2.2, note('c', 4), 'sawtooth', 0.045, 620, 1.4, 0));
    out.push(evPad(0, bar * 2.2, note('cs', 4), 'sawtooth', 0.045, 620, 1.4, 0));
    out.push(evPad(bar * 2, bar * 2.2, note('c', 4), 'sawtooth', 0.04, 560, 1.4, 0));
    out.push(evPad(bar * 2, bar * 2.2, note('cs', 4), 'sawtooth', 0.04, 560, 1.4, 0));
    // 三全音（增四度）：两遍循环才响一次，专门用来「不对劲」
    out.push(evTone((2 * 4 + 2) * spb, 'triangle', note('fs', 5), 1.4, 0.05, note('fs', 5) * 0.98, 0.02, 2));
    // 一层很轻的气声，把脉动之间的空隙填上，别让它听着像节拍器
    out.push(evNoise(0, bar * 4, 'lowpass', 420, 0.7, 220, 0.035, 2.5));
    return sorted(out);
  }

  // 夜色：很高很轻的正弦点缀 + 很低的持续音，稀疏到近乎无声
  function buildNight(spb, bar) {
    var loop = bar * 4;
    var out = [];
    // 低频持续音：A1 + E2，几乎是「房间自己在嗡嗡响」，是这几首里最安静的一首
    out.push(evPad(0, loop + 2.0, note('a', 1), 'sine', 0.12, 320, 4.0, 0));
    out.push(evPad(0, loop + 2.0, note('e', 2), 'sine', 0.06, 380, 4.5, 6));
    // 高音点缀：一小节最多一个，起音很慢、衰减很长，像远处闪一下的灯
    var dots = [[0, 1, 'g', 6], [1, 2.5, 'c', 7], [2, 0.5, 'e', 7], [3, 3, 'g', 6]];
    for (var i = 0; i < dots.length; i++) {
      var d = dots[i];
      var f = note(d[2], d[3]);
      out.push(evTone((d[0] * 4 + d[1]) * spb, 'sine', f, 2.6, 0.035, f * 0.995, 0.5));
    }
    return sorted(out);
  }

  var TRACKS = [
    { id: 'street', name: '白昼街道',
      desc: '中低音持续音 + 稀疏的 A 小调琶音，偶尔一声远处的金属敲击（约 66 BPM，4 小节循环）',
      bpm: 66, bars: 4, level: 1, build: buildStreet },
    { id: 'interior', name: '楼里',
      desc: '暗色小三和弦长音（微微失谐）+ 偶尔的低频脉冲，压抑、有室内空间感（约 60 BPM，4 小节循环）',
      bpm: 60, bars: 4, level: 1, build: buildInterior },
    { id: 'danger', name: '危险逼近',
      desc: '心跳般的低音重拍 + 不协和的半音簇，紧张但有节奏、不刺耳（约 80 BPM，4 小节循环）',
      bpm: 80, bars: 4, level: 0.9, build: buildDanger },
    { id: 'night', name: '夜色',
      desc: '很高很轻的正弦点缀 + 很低的持续音，稀疏得几乎无声（约 50 BPM，4 小节循环）',
      bpm: 50, bars: 4, level: 1, build: buildNight }
  ];

  // 场景提示 → 曲目：室外白天 / 建筑里 / 看得见敌人 / 室外夜里
  var SCENE_TRACK = { street: 'street', interior: 'interior', danger: 'danger', night: 'night' };

  function findTrack(id) {
    for (var i = 0; i < TRACKS.length; i++) {
      if (TRACKS[i].id === id) return TRACKS[i];
    }
    return null;
  }

  /* ================= 音乐：前瞻调度器 =================
     每 100ms 醒一次，把「从现在起 0.35 秒内该响的音符」按 ctx.currentTime 提前排进去。
     为什么不用 setTimeout 逐音符堆：定时器越堆越飘，鼓点会散；按音频时钟排时间就不会。 */

  var LOOKAHEAD = 0.35;      // 提前排多久
  var TICK_MS = 100;         // 多久醒一次

  var timer = null;          // setInterval 的句柄
  var curBus = null;         // 当前曲目的增益节点（换曲时交叉淡化用）
  var oldBus = null;         // 上一首的增益节点：正在淡出，淡完断开；再来新曲就直接快刀切掉它
  var curEvents = null;      // 当前曲目这一遍循环的事件表（按 t 排好）
  var curLoop = 0;           // 一遍循环多长（秒）
  var curIdx = 0;            // 下一个要排的事件下标
  var curStart = 0;          // 这一遍循环的起点（ctx 时间）
  var curLoops = 0;          // 已经放了多少遍（给 every 用）
  var pausedId = '';         // 切到后台时暂停的那首：回到前台接着放它

  function scheduleStep() {
    if (!ctx || !curEvents || !curBus) return;
    var t = ctx.currentTime;
    // 落后太多（标签页被浏览器挂起过）：这一遍不要了，从现在重新铺，
    // 否则积压的音符会在同一瞬间一股脑补上来，糊成一声巨响
    if (curStart + curLoop <= t) {
      curStart = t + 0.05;
      curIdx = 0;
      curLoops++;
    }
    var horizon = t + LOOKAHEAD;
    while (curIdx < curEvents.length) {
      var ev = curEvents[curIdx];
      var at = curStart + ev.t;
      if (at > horizon) break;
      curIdx++;
      if (at < t) continue;                                   // 已经过去的音符直接跳过，不补
      if (ev.every && (curLoops % ev.every) !== 0) continue;  // 隔几遍才响一次的音
      try { ev.run(at, curBus); } catch (e) {}
    }
    if (curIdx >= curEvents.length) {   // 这一遍排完了：接着排下一遍，循环是无缝的
      curStart += curLoop;
      curIdx = 0;
      curLoops++;
    }
  }

  function startTimer() {
    if (timer !== null && timer !== undefined) return;
    timer = timerSet(scheduleStep, TICK_MS);
    if (timer === null || timer === undefined) scheduleStep();   // 极端环境里没有定时器：至少排一次
  }

  function stopTimer() {
    timerClear(timer);
    timer = null;
  }

  // 把一条音乐总线淡出后丢掉（换曲、停止都走这里，别让上一首突然断掉）
  function fadeBus(bus, seconds) {
    if (!bus) return;
    var s = seconds || 0.4;
    ramp(bus, 0, s);
    timerLater(function () { drop(bus); }, Math.round(s * 1000) + 200);
  }

  function musicPlay(id) {
    var def = findTrack(id);
    if (!def) return;                     // 不认识的曲目 id：静默返回
    wanted = def.id;
    saveSettings();
    if (!ctx || !musicGain) return;        // 还没解锁：先记下想放哪首，unlock 的时候补上
    if (curId === def.id && curBus) return; // 同一首再调不重启（不然设置面板每点一次就从头开始）
    var spb = 60 / def.bpm;
    var bar = spb * 4;
    var events, loop;
    try {
      events = def.build(spb, bar);
      loop = bar * def.bars;
    } catch (e) {
      return;
    }
    // 换曲：上一首淡出，新的淡入，听感是「叠过去」不是「切一刀」。
    // 只留一条正在淡出的总线：连着点几首也不会把三四个曲子的音符全叠在耳朵里（节点也省）。
    if (oldBus) { fadeBus(oldBus, 0.12); oldBus = null; }
    oldBus = curBus;
    fadeBus(oldBus, 0.5);
    try {
      var bus = ctx.createGain();
      bus.gain.value = 0;
      bus.connect(musicGain);
      ramp(bus, def.level, 0.8);          // 新的一首淡入
      curBus = bus;
    } catch (e) {
      return;
    }
    curId = def.id;
    curEvents = events;
    curLoop = loop;
    curIdx = 0;
    curLoops = 0;
    curStart = ctx.currentTime + 0.08;
    startTimer();
    scheduleStep();                       // 先排一批，别等第一个 100ms
  }

  // 停下调度和声音（不动 wanted、也不写设置）：给「切到后台先暂停」用
  function halt() {
    stopTimer();
    fadeBus(curBus, 0.3);
    fadeBus(oldBus, 0.12);
    curBus = null;
    oldBus = null;
    curEvents = null;
    curId = null;
  }

  function musicStop() {
    halt();
    wanted = '';
    saveSettings();
  }

  /* 切到后台就先停：浏览器会把后台页面的 setInterval 降到 1 秒一次，
     前瞻（0.35 秒）根本来不及排音符，音乐会一顿一顿的；不如安静下来，回来再从头放。
     顺便也省 CPU（后台页面不该还在合成音频）。 */
  function bindVisibility() {
    if (typeof document === 'undefined' || !document || !document.addEventListener) return;
    try {
      document.addEventListener('visibilitychange', function () {
        if (document.hidden) {
          if (curId) { pausedId = curId; halt(); }
        } else {
          resume();
          if (pausedId) { var id = pausedId; pausedId = ''; musicPlay(id); }
        }
      }, false);
    } catch (e) {}
  }

  function scene(name) {
    sceneName = name || '';
    if (!autoOn) return;                  // 手动选过曲目（关掉 auto）就不跟着场景走了
    var id = SCENE_TRACK[sceneName];
    if (!id) return;                      // 不认识的场景名：静默
    musicPlay(id);
  }

  /* ================= 设置存取 ================= */

  function saveSettings() {
    try {
      if (typeof localStorage === 'undefined' || !localStorage) return;
      localStorage.setItem(STORE_KEY, JSON.stringify({
        sfx: sfxVolume, music: musicVolume, auto: autoOn, track: wanted || ''
      }));
    } catch (e) {}                        // 隐私模式里 localStorage 会直接抛，静默跳过
  }

  function loadSettings() {
    var raw = null;
    try {
      if (typeof localStorage === 'undefined' || !localStorage) return;
      raw = localStorage.getItem(STORE_KEY);
    } catch (e) { return; }
    if (!raw) return;
    try {
      var d = JSON.parse(raw);
      if (typeof d.sfx === 'number') sfxVolume = clamp01(d.sfx);
      if (typeof d.music === 'number') musicVolume = clamp01(d.music);
      if (typeof d.auto === 'boolean') autoOn = d.auto;
      if (typeof d.track === 'string') wanted = d.track;
    } catch (e) {}
  }

  loadSettings();   // 先读上次的设置，这样 unlock 时按老音量直接起来，不用等界面同步
  bindVisibility(); // 切后台就先安静下来（后台定时器被降频，音乐会卡）

  /* ================= 解锁与对外接口 ================= */

  function resume() {
    if (!ctx) return;
    try {
      if (ctx.state === 'suspended' && ctx.resume) {
        var p = ctx.resume();
        if (p && p.catch) p.catch(function () {});   // 有些浏览器返回 Promise，拒绝了也别炸
      }
    } catch (e) {}
  }

  /* 第一次用户点击时调一次。之后每次点击再调也无妨（浏览器把上下文挂起时顺便唤醒）。
     没有 AudioContext 的环境（老浏览器 / node）直接返回，调用方不用判断。 */
  function unlock() {
    if (ctx) { resume(); return; }
    var Ctor = root.AudioContext || root.webkitAudioContext;
    if (!Ctor) return;
    try {
      ctx = new Ctor();
    } catch (e) {
      ctx = null;
      return;
    }
    try {
      sfxGain = ctx.createGain();
      sfxGain.gain.value = sfxVolume;
      sfxGain.connect(ctx.destination);
      musicGain = ctx.createGain();
      musicGain.gain.value = musicVolume;
      musicGain.connect(ctx.destination);
    } catch (e) {
      sfxGain = null;
      musicGain = null;
      ctx = null;
      return;
    }
    resume();
    noiseBuffer();          // 白噪声缓冲先建好，第一次打人时不用等着生成
    // 解锁之前就有过请求：这时候补上（场景优先，其次是手动选的曲目）
    if (autoOn && sceneName && SCENE_TRACK[sceneName]) musicPlay(SCENE_TRACK[sceneName]);
    else if (wanted) musicPlay(wanted);
    else musicPlay('street');   // 什么提示都没有：先放最中性的一首，免得调了音量却听不到东西
  }

  function setSfxVolume(v) {
    sfxVolume = clamp01(v);
    ramp(sfxGain, sfxVolume, 0.08);
    saveSettings();
    return sfxVolume;
  }

  function setMusicVolume(v) {
    musicVolume = clamp01(v);
    ramp(musicGain, musicVolume, 0.12);
    saveSettings();
    return musicVolume;
  }

  function setAuto(on) {
    autoOn = !!on;
    saveSettings();
    if (autoOn && sceneName) scene(sceneName);   // 重新打开自动换曲：立刻跟上当前场景
  }

  function listTracks() {
    var out = [];
    for (var i = 0; i < TRACKS.length; i++) {
      out.push({ id: TRACKS[i].id, name: TRACKS[i].name, desc: TRACKS[i].desc });
    }
    return out;
  }

  return {
    unlock: unlock,
    play: play,
    setSfxVolume: setSfxVolume,
    getSfxVolume: function () { return sfxVolume; },
    music: {
      setVolume: setMusicVolume,
      getVolume: function () { return musicVolume; },
      list: listTracks,
      play: musicPlay,
      // 当前曲目 id：没在放（例如刚切到后台暂停）时返回最近选定的那首；从没选过就是空字符串
      current: function () { return curId || wanted || ''; },
      setAuto: setAuto,
      auto: function () { return autoOn; },
      scene: scene,
      stop: musicStop
    }
  };
})();
