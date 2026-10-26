/* Sổ lệnh bot, hai nguồn:
   • Lệnh của bot (data/live-dip.json, data/live-trend.json): những gì bot thật sự làm trên sàn,
     lời lỗ USDT thật, kể cả lệnh bạn đóng qua Telegram. VPS đẩy lên GitHub mỗi giờ.
   • Sổ giấy (data/crypto-ideas.json, data/trend-ideas.json): những gì luật nói, quy lời lỗ ra
     USDT theo số tiền mỗi lệnh người xem nhập.
   Giá trực tiếp cho lệnh đang mở, so từng chiến lược với backtest (data/crypto-backtest.json). */
(function(){
  'use strict';
  var $ = function(id){ return document.getElementById(id); };

  var BOTS = {
    crypto: { file: 'data/crypto-ideas.json', live: 'data/live-dip.json', label: 'Bắt đáy 1h', size: 'sz-c' },
    trend:  { file: 'data/trend-ideas.json',  live: 'data/live-trend.json', label: 'Xu hướng ngày', size: 'sz-t' }
  };
  var REASON = {
    stop: ['Chạm cắt lỗ', 'c-down'], trail: ['Cắt lỗ dời chạm', ''], tp: ['Đạt mục tiêu', 'c-up'],
    max_hold: ['Hết hạn giữ', ''], strategy: ['Về trung bình 24h', ''], rule: ['Thủng đáy 10 ngày', ''],
    tg: ['Bạn đóng qua Telegram', ''], manual: ['Bạn chốt tay', ''], panic: ['Bán khẩn cấp', ''],
    gone: ['Số dư biến mất', ''], dust: ['Còn quá ít để bán', '']
  };
  var PX_HOSTS = ['https://data-api.binance.vision', 'https://api.binance.com'];
  var FEE = 0.001;

  var CLOSED = [], OPEN = [], BT = {}, META = {}, LIVE = {}, liveAt = null;
  var DATA = { live: { CLOSED: [], OPEN: [], META: {} }, paper: { CLOSED: [], OPEN: [], META: {} } };
  var F = { bot: '', strat: '', res: '' }, sortKey = 'exitTs', sortAsc = false;

  /* ---------- định dạng ---------- */
  function vn(n, d){
    if (n == null || isNaN(n)) return '—';
    return Number(n).toLocaleString('vi-VN', { minimumFractionDigits: d || 0, maximumFractionDigits: d || 0 });
  }
  function sg(n, d, unit){ return n == null || isNaN(n) ? '—' : (n > 0 ? '+' : '') + vn(n, d) + (unit || ''); }
  function cls(n){ return n > 0 ? 'c-up' : n < 0 ? 'c-down' : ''; }
  function px(v){
    if (v == null) return '—';
    var a = Math.abs(v), d = a >= 1000 ? 2 : a >= 1 ? 4 : a >= 0.01 ? 5 : 8;
    return Number(v).toLocaleString('vi-VN', { maximumFractionDigits: d, minimumFractionDigits: a >= 1000 ? 2 : 0 });
  }
  function when(ts){
    if (!ts) return '—';
    return new Date(ts).toLocaleString('vi-VN', { timeZone: 'Asia/Ho_Chi_Minh', day: '2-digit', month: '2-digit',
      hour: '2-digit', minute: '2-digit', hour12: false });
  }
  function dur(ms){
    if (ms == null || ms < 0) return '—';
    var h = Math.round(ms / 3600000), d = Math.floor(h / 24);
    return d ? d + 'n ' + (h % 24) + 'h' : h + 'h';
  }
  function esc(s){ return String(s == null ? '' : s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }
  function pair(s){ return s.replace(/USDT$/, '/USDT'); }
  function status(node, text, kind){ if (node){ node.textContent = text; node.className = 'lab-status' + (kind ? ' is-' + kind : ''); } }
  function store(k, v){ try { if (v === undefined) return localStorage.getItem(k); localStorage.setItem(k, v); } catch (e) { return null; } }

  /* ---------- tiền ---------- */
  function size(bot){ var v = parseFloat($(BOTS[bot].size).value); return v > 0 ? v : 0; }
  function net(entry, exit){
    var g = exit / entry;
    return ($('fee').checked ? g * (1 - FEE) / (1 + FEE) : g) - 1;
  }
  function money(t, exit){
    if (t.real){
      // Lệnh của bot: lệnh đã đóng dùng lời lỗ sàn ghi (đã gồm phí); đang mở thì tạm tính theo vốn bỏ ra.
      if (t.usdtReal != null && exit === t.exitPrice) return { pct: t.pctReal, usdt: t.usdtReal };
      var g = exit / t.entry - 1;
      return { pct: g * 100, usdt: g * (t.cost || 0) };
    }
    var n = net(t.entry, exit); return { pct: n * 100, usdt: n * size(t.bot) };
  }

  /* ---------- nạp dữ liệu ---------- */
  function getJSON(url){
    return fetch(url, { cache: 'no-cache' }).then(function(r){ if (!r.ok) throw new Error(r.status); return r.json(); });
  }
  function norm(bot, it){
    return {
      bot: bot, symbol: it.symbol, strategy: it.strategy || '—',
      entryTs: it.entryTs, entry: it.entry, exitTs: it.exitTs, exitPrice: it.exitPrice,
      reason: it.exitReason, r: it.r, stop: it.stop, stop0: it.stop0, tp: it.tp,
      exitLevel: it.exitLevel, lastPrice: it.lastPrice, lastTs: it.lastTs
    };
  }

  // "2026-10-26 07:10" (giờ VN, cách sổ trên sàn ghi) → mốc thời gian
  function vnTime(s){ var t = s ? Date.parse(s.replace(' ', 'T') + ':00+07:00') : NaN; return isNaN(t) ? null : t; }

  // Lệnh trên sàn → cùng dạng với lệnh sổ giấy. Trên testnet giá khớp lệch giá thật, nên mọi
  // mức giá được quy về giá thị trường thật (chia cho k = giá khớp / giá sổ giấy lúc mua)
  // để so được với giá Binance trực tiếp và chart.
  function normLive(bot, p){
    var k = p.k || 1, e = p.paperEntry || p.entryPrice;
    return {
      bot: bot, symbol: p.symbol, strategy: p.strategy || (bot === 'trend' ? 'donchian_btc' : '—'),
      entryTs: p.entryMs || p.entryTs, entry: e, fill: p.entryPrice,
      exitTs: p.exitMs || vnTime(p.exitTime), exitPrice: p.exitPrice ? p.exitPrice / k : null, exitFill: p.exitPrice,
      reason: p.exitReason, real: true, usdtReal: p.pnlUsdt, pctReal: p.pnlPct, cost: p.cost,
      stop: p.liveStop ? p.liveStop / k : p.exitLevel, tp: p.liveTp ? p.liveTp / k : null, exitLevel: p.exitLevel,
      r: p.pnlPct != null && p.paperStop0 && e ? p.pnlPct / 100 / (1 - p.paperStop0 / e) : null,
      user: p.status === 'user', lastPrice: null
    };
  }

  Promise.all([
    getJSON(BOTS.crypto.file).catch(function(){ return null; }),
    getJSON(BOTS.trend.file).catch(function(){ return null; }),
    getJSON(BOTS.crypto.live).catch(function(){ return null; }),
    getJSON(BOTS.trend.live).catch(function(){ return null; }),
    getJSON('data/crypto-backtest.json').catch(function(){ return null; })
  ]).then(function(res){
    ['crypto', 'trend'].forEach(function(bot, k){
      var d = res[k], L = res[k + 2];
      DATA.paper.META[bot] = d;
      DATA.live.META[bot] = L;
      if (d){
        (d.closed || []).forEach(function(it){ if (it.exitPrice && it.entry) DATA.paper.CLOSED.push(norm(bot, it)); });
        (d.open || []).forEach(function(it){ DATA.paper.OPEN.push(norm(bot, it)); });
      }
      if (L){
        (L.closed || []).forEach(function(p){ if (p.exitPrice) DATA.live.CLOSED.push(normLive(bot, p)); });
        (L.open || []).forEach(function(p){ DATA.live.OPEN.push(normLive(bot, p)); });
      }
    });
    ((res[4] && res[4].results) || []).forEach(function(r){
      if (r.variant === 'gốc' || (!r.variant && !BT[r.name])) BT[r.name] = r;
    });
    var src = store('solenh.src') === 'paper' ? 'paper' : 'live';
    // Chưa có sổ trên sàn (bot chưa đẩy lên) thì mở sổ giấy, khỏi thấy trang trống.
    if (src === 'live' && !res[2] && !res[3]) src = 'paper';
    setSource(src);
    setInterval(refreshPrices, 30000);
  });

  var SRC = 'live';
  function setSource(src){
    SRC = src;
    var D = DATA[src];
    CLOSED = D.CLOSED; OPEN = D.OPEN; META = D.META;
    [].forEach.call($('f-src').querySelectorAll('.chip'), function(x){ x.classList.toggle('on', x.getAttribute('data-v') === src); });
    [].forEach.call(document.querySelectorAll('.paper-only'), function(x){ x.hidden = src !== 'paper'; });
    var mode = ['crypto', 'trend'].map(function(b){ return DATA.live.META[b] && DATA.live.META[b].mode; }).filter(Boolean)[0];
    $('f-money').textContent = src === 'paper' ? 'Không. Đây là sổ giấy' :
      mode === 'live' ? 'Có. Lệnh thật trên Binance' : 'Không. Binance testnet, tiền ảo';
    $('f-c').textContent = factOf('crypto');
    $('f-t').textContent = factOf('trend');
    var strats = {};
    CLOSED.concat(OPEN).forEach(function(t){ strats[t.strategy] = 1; });
    if (F.strat && !strats[F.strat]) F.strat = '';
    $('f-strat').innerHTML = '<option value="">Mọi chiến lược</option>' + Object.keys(strats).sort().map(function(s){
      return '<option value="' + esc(s) + '"' + (s === F.strat ? ' selected' : '') + '>' + esc(s) + '</option>';
    }).join('');
    var upd = ['crypto', 'trend'].map(function(b){ return META[b] && META[b].updatedAt; }).filter(Boolean).sort().pop();
    status($('stt'), (src === 'live' ? 'Lệnh của bot trên sàn · ' : 'Sổ giấy · ') + CLOSED.length + ' lệnh đã đóng · ' +
      OPEN.length + ' đang mở' + (upd ? ' · ghi lúc ' + upd : ''), CLOSED.length || OPEN.length ? 'live' : 'wait');
    render();
    refreshPrices();
  }

  function factOf(bot){
    var d = META[bot];
    if (!d) return 'chưa có lệnh nào';
    return (d.open || []).length + ' mở · ' + (d.closed || []).length + ' đã đóng';
  }

  /* ---------- giá trực tiếp ---------- */
  function refreshPrices(){
    var syms = OPEN.map(function(t){ return t.symbol; }).filter(function(s, i, a){ return a.indexOf(s) === i; });
    if (!syms.length){ renderOpen(); return; }
    var q = '/api/v3/ticker/price?symbols=' + encodeURIComponent(JSON.stringify(syms));
    (function tryHost(k){
      if (k >= PX_HOSTS.length){
        status($('px-stt'), 'không lấy được giá Binance — đang dùng giá trong sổ', 'wait');
        renderOpen();
        return;
      }
      getJSON(PX_HOSTS[k] + q).then(function(rows){
        rows.forEach(function(r){ LIVE[r.symbol] = parseFloat(r.price); });
        liveAt = new Date();
        status($('px-stt'), 'giá Binance lúc ' + liveAt.toLocaleTimeString('vi-VN', { hour12: false }), 'live');
        renderOpen();
      }).catch(function(){ tryHost(k + 1); });
    })(0);
  }

  /* ---------- lọc ---------- */
  function pass(t){
    if (F.bot && t.bot !== F.bot) return false;
    if (F.strat && t.strategy !== F.strat) return false;
    return true;
  }
  function closedRows(){
    return CLOSED.filter(pass).map(function(t){
      var m = money(t, t.exitPrice);
      return Object.assign({}, t, { pct: m.pct, usdt: m.usdt, hold: t.exitTs - t.entryTs });
    });
  }

  function render(){ renderSummary(); renderOpen(); renderClosed(); renderStrats(); }

  /* ---------- 01 tổng quan ---------- */
  function renderSummary(){
    var rows = closedRows().sort(function(a, b){ return a.exitTs - b.exitTs; });
    var n = rows.length, wins = rows.filter(function(t){ return t.pct > 0; }), loss = rows.filter(function(t){ return t.pct <= 0; });
    var sum = function(a, k){ return a.reduce(function(s, t){ return s + (t[k] || 0); }, 0); };
    var tot = sum(rows, 'usdt'), rs = rows.filter(function(t){ return t.r != null; });
    var cum = 0, peak = 0, dd = 0;
    rows.forEach(function(t){ cum += t.usdt; peak = Math.max(peak, cum); dd = Math.min(dd, cum - peak); });
    var best = rows.reduce(function(b, t){ return !b || t.pct > b.pct ? t : b; }, null);
    var worst = rows.reduce(function(b, t){ return !b || t.pct < b.pct ? t : b; }, null);
    var openU = OPEN.filter(pass).reduce(function(s, t){
      var p = LIVE[t.symbol] || t.lastPrice; return p ? s + money(t, p).usdt : s;
    }, 0);

    var card = function(k, v, c, sub){
      return '<div><dt>' + k + '</dt><dd class="' + (c || '') + '">' + v + (sub ? '<small>' + sub + '</small>' : '') + '</dd></div>';
    };
    $('cards').innerHTML = [
      card('Đã đóng', vn(n) + ' lệnh', '', n < 30 ? 'cần ≥ 30 để kết luận' : ''),
      card('Tỷ lệ thắng', n ? vn(wins.length / n * 100, 1) + '%' : '—', '', n ? wins.length + ' lời · ' + loss.length + ' lỗ' : ''),
      card('Tổng lời lỗ', sg(tot, 2, ' USDT'), cls(tot), n ? sg(sum(rows, 'pct'), 2, '%') + ' cộng dồn' : ''),
      card('R trung bình', rs.length ? sg(sum(rs, 'r') / rs.length, 2, 'R') : '—', cls(rs.length && sum(rs, 'r')), rs.length ? (SRC === 'live' ? 'đã gồm phí sàn' : 'chưa trừ phí') + ' · ' + rs.length + ' lệnh' : 'bot xu hướng không đặt R'),
      card('Lệnh lời TB', wins.length ? sg(sum(wins, 'pct') / wins.length, 2, '%') : '—', 'c-up'),
      card('Lệnh lỗ TB', loss.length ? sg(sum(loss, 'pct') / loss.length, 2, '%') : '—', 'c-down'),
      card('Sụt vốn lớn nhất', n ? vn(dd, 2) + ' USDT' : '—', dd < 0 ? 'c-down' : '', 'từ đỉnh lời cộng dồn'),
      card('Tốt nhất / tệ nhất', best ? sg(best.pct, 1, '%') + ' / ' + sg(worst.pct, 1, '%') : '—', '',
        best ? pair(best.symbol) + ' · ' + pair(worst.symbol) : ''),
      card('Đang mở (tạm tính)', OPEN.filter(pass).length ? sg(openU, 2, ' USDT') : '—', cls(openU), OPEN.filter(pass).length + ' lệnh')
    ].join('');
    drawCurve(rows);
  }

  function drawCurve(rows){
    var box = $('curve');
    if (rows.length < 2){
      box.innerHTML = '<p class="empty">Cần ít nhất 2 lệnh đã đóng để vẽ đường lời lỗ.</p>';
      $('curve-hover').textContent = '';
      return;
    }
    var W = 800, H = 200, L = 46, R = 10, T = 10, B = 22;
    var pts = [{ v: 0, t: null }], cum = 0;
    rows.forEach(function(t){ cum += t.usdt; pts.push({ v: cum, t: t }); });
    var lo = Math.min(0, Math.min.apply(null, pts.map(function(p){ return p.v; })));
    var hi = Math.max(0, Math.max.apply(null, pts.map(function(p){ return p.v; })));
    if (hi === lo) hi = lo + 1;
    var x = function(i){ return L + (W - L - R) * i / (pts.length - 1); };
    var y = function(v){ return T + (H - T - B) * (hi - v) / (hi - lo); };
    var path = pts.map(function(p, i){ return (i ? 'L' : 'M') + x(i).toFixed(1) + ' ' + y(p.v).toFixed(1); }).join('');
    var last = pts[pts.length - 1].v, col = last >= 0 ? 'var(--up)' : 'var(--down)';
    var area = path + 'L' + x(pts.length - 1).toFixed(1) + ' ' + y(0).toFixed(1) + 'L' + x(0) + ' ' + y(0).toFixed(1) + 'Z';
    var ticks = [hi, (hi + lo) / 2, lo].map(function(v){
      return '<text x="' + (L - 6) + '" y="' + (y(v) + 3) + '" text-anchor="end">' + vn(v, Math.abs(hi - lo) < 10 ? 2 : 0) + '</text>';
    }).join('');
    var dots = pts.map(function(p, i){
      if (!i) return '';
      return '<circle cx="' + x(i).toFixed(1) + '" cy="' + y(p.v).toFixed(1) + '" r="' + (pts.length > 80 ? 1.5 : 3) +
        '" fill="' + (p.t.pct > 0 ? 'var(--up)' : 'var(--down)') + '" data-i="' + i + '"/>';
    }).join('');
    box.innerHTML = '<svg viewBox="0 0 ' + W + ' ' + H + '" role="img" aria-label="Lời lỗ cộng dồn: ' + sg(last, 2, ' USDT') + '">' +
      '<line x1="' + L + '" x2="' + (W - R) + '" y1="' + y(0) + '" y2="' + y(0) + '" stroke="var(--line)" stroke-dasharray="3 3"/>' +
      ticks + '<path d="' + area + '" fill="' + col + '" opacity=".08"/>' +
      '<path d="' + path + '" fill="none" stroke="' + col + '" stroke-width="2" stroke-linejoin="round"/>' + dots +
      '<rect x="' + L + '" y="0" width="' + (W - L - R) + '" height="' + H + '" fill="transparent" id="curve-hit"/></svg>';
    var hov = $('curve-hover'), svg = box.querySelector('svg');
    var show = function(i){
      var p = pts[i];
      hov.innerHTML = p.t ? '<b>#' + i + '</b> ' + esc(pair(p.t.symbol)) + ' · ' + when(p.t.exitTs) + ' · ' +
        '<span class="' + cls(p.t.usdt) + '">' + sg(p.t.usdt, 2, ' USDT') + '</span> → cộng dồn <b class="' + cls(p.v) + '">' +
        sg(p.v, 2, ' USDT') + '</b>' : '';
    };
    show(pts.length - 1);
    svg.addEventListener('pointermove', function(e){
      var r = svg.getBoundingClientRect(), vx = (e.clientX - r.left) / r.width * W;
      show(Math.max(1, Math.min(pts.length - 1, Math.round((vx - L) / (W - L - R) * (pts.length - 1)))));
    });
    svg.addEventListener('pointerleave', function(){ show(pts.length - 1); });
  }

  /* ---------- 02 đang mở ---------- */
  function renderOpen(){
    var rows = OPEN.filter(pass);
    if (!rows.length){
      $('open').innerHTML = '<p class="empty">Không có lệnh nào đang mở' + (F.bot || F.strat ? ' theo bộ lọc này' : '') + '.</p>';
      if (CLOSED.length || OPEN.length) renderSummaryCardsOnly();
      return;
    }
    $('open').innerHTML = '<div class="tbl-scroll"><table class="ledger"><thead><tr>' +
      '<th class="l">Cặp</th><th class="l">Bot · chiến lược</th><th>Vào lúc</th><th>Giá vào</th><th>Hiện tại</th>' +
      '<th>Lời lỗ</th><th>Cắt lỗ</th><th>Mục tiêu / ngưỡng thoát</th><th>Đã giữ</th></tr></thead><tbody>' +
      rows.map(function(t){
        var p = LIVE[t.symbol] || t.lastPrice, m = p ? money(t, p) : null;
        var stopD = t.stop && p ? (t.stop / p - 1) * 100 : null;
        var tgt = t.tp || t.exitLevel, tgtD = tgt && p ? (tgt / p - 1) * 100 : null;
        return '<tr><td class="l"><span class="sym">' + esc(pair(t.symbol)) + '</span>' +
          (t.user ? '<small>bạn đã giành quyền</small>' : '') + '</td>' +
          '<td class="l"><span class="tag tag-bot">' + BOTS[t.bot].label + '</span> ' + esc(t.strategy) + '</td>' +
          '<td>' + when(t.entryTs) + '</td><td>' + px(t.entry) + fillNote(t, t.fill, t.entry) + '</td>' +
          '<td>' + px(p) + (LIVE[t.symbol] || !p ? '' : '<small>giá trong sổ</small>') + '</td>' +
          '<td class="' + cls(m && m.pct) + '">' + (m ? sg(m.pct, 2, '%') + '<small>' + sg(m.usdt, 2, ' USDT') + '</small>' : '—') + '</td>' +
          '<td>' + px(t.stop) + (stopD != null ? '<small>cách ' + vn(stopD, 1) + '%</small>' : '') + '</td>' +
          '<td>' + px(tgt) + (tgtD != null ? '<small>' + (t.tp ? 'chốt lời' : 'ngưỡng thoát') + ' · ' + sg(tgtD, 1, '%') + '</small>' : '') + '</td>' +
          '<td>' + dur(Date.now() - t.entryTs) + '</td></tr>';
      }).join('') + '</tbody></table></div>';
    renderSummaryCardsOnly();
  }
  // Ô "Đang mở (tạm tính)" phụ thuộc giá trực tiếp: vẽ lại riêng phần tổng quan khi giá về.
  var summaryQueued = false;
  function renderSummaryCardsOnly(){
    if (summaryQueued) return;
    summaryQueued = true;
    requestAnimationFrame(function(){ summaryQueued = false; renderSummary(); });
  }

  // Trên testnet giá khớp lệch giá thật: ghi kèm giá khớp trên sàn để đối chiếu.
  function fillNote(t, fill, shown){
    if (!t.real || !fill || !shown) return '';
    return Math.abs(fill / shown - 1) > 0.0005 ? '<small>khớp sàn ' + px(fill) + '</small>' : '';
  }

  /* ---------- 03 lịch sử ---------- */
  var COLS = [
    ['symbol', 'Cặp', 'l'], ['strategy', 'Bot · chiến lược', 'l'], ['entryTs', 'Vào lúc', ''], ['entry', 'Giá vào', ''],
    ['exitTs', 'Ra lúc', ''], ['exitPrice', 'Giá ra', ''], ['hold', 'Giữ', ''], ['pct', 'Lời lỗ', ''],
    ['r', 'R', ''], ['reason', 'Lý do thoát', 'l']
  ];
  function renderClosed(){
    var rows = closedRows().filter(function(t){
      return !F.res || (F.res === 'win' ? t.pct > 0 : t.pct <= 0);
    });
    if (!rows.length){
      $('closed').innerHTML = '<p class="empty">' + (CLOSED.length ? 'Không có lệnh nào khớp bộ lọc.' :
        'Chưa có lệnh nào đóng. Bot ghi lệnh vào sổ ngay khi có điểm bán, trang sẽ tự hiện ở đây.') + '</p>';
      return;
    }
    rows.sort(function(a, b){
      var x = a[sortKey], y = b[sortKey];
      if (x == null) return 1; if (y == null) return -1;
      var c = typeof x === 'string' ? x.localeCompare(y) : x - y;
      return sortAsc ? c : -c;
    });
    $('closed').innerHTML = '<div class="tbl-scroll"><table class="ledger"><thead><tr>' +
      COLS.map(function(c){
        return '<th data-k="' + c[0] + '" class="' + c[2] + (c[0] === sortKey ? ' sorted' + (sortAsc ? ' asc' : '') : '') + '">' + c[1] + '</th>';
      }).join('') + '</tr></thead><tbody>' +
      rows.map(function(t){
        var rs = REASON[t.reason] || [t.reason || '—', ''];
        return '<tr><td class="l"><span class="sym">' + esc(pair(t.symbol)) + '</span></td>' +
          '<td class="l"><span class="tag tag-bot">' + BOTS[t.bot].label + '</span> ' + esc(t.strategy) + '</td>' +
          '<td>' + when(t.entryTs) + '</td><td>' + px(t.entry) + fillNote(t, t.fill, t.entry) + '</td>' +
          '<td>' + when(t.exitTs) + '</td><td>' + px(t.exitPrice) + fillNote(t, t.exitFill, t.exitPrice) + '</td>' +
          '<td>' + dur(t.hold) + '</td>' +
          '<td class="' + cls(t.pct) + '">' + sg(t.pct, 2, '%') + '<small>' + sg(t.usdt, 2, ' USDT') + '</small></td>' +
          '<td class="' + cls(t.r) + '">' + (t.r == null ? '—' : sg(t.r, 2, 'R')) + '</td>' +
          '<td class="l"><span class="tag ' + (t.pct > 0 ? 'tag-win' : 'tag-loss') + '">' + (t.pct > 0 ? 'LỜI' : 'LỖ') + '</span> ' +
          '<span class="' + rs[1] + '">' + esc(rs[0]) + '</span></td></tr>';
      }).join('') + '</tbody></table></div>';
  }
  $('closed').addEventListener('click', function(e){
    var th = e.target.closest('th[data-k]');
    if (!th) return;
    var k = th.getAttribute('data-k');
    if (k === sortKey) sortAsc = !sortAsc; else { sortKey = k; sortAsc = COLS.some(function(c){ return c[0] === k && c[2] === 'l'; }); }
    renderClosed();
  });

  /* ---------- 04 theo chiến lược ---------- */
  function renderStrats(){
    var g = {};
    closedRows().forEach(function(t){
      var k = t.bot + '|' + t.strategy;
      (g[k] = g[k] || { bot: t.bot, strategy: t.strategy, rows: [] }).rows.push(t);
    });
    OPEN.filter(pass).forEach(function(t){
      var k = t.bot + '|' + t.strategy;
      g[k] = g[k] || { bot: t.bot, strategy: t.strategy, rows: [] };
      g[k].open = (g[k].open || 0) + 1;
    });
    var list = Object.keys(g).map(function(k){ return g[k]; });
    if (!list.length){ $('strats').innerHTML = '<p class="empty">Chưa có lệnh nào.</p>'; return; }
    list.sort(function(a, b){ return b.rows.length - a.rows.length; });
    $('strats').innerHTML = '<div class="tbl-scroll"><table class="ledger" style="min-width:760px"><thead><tr>' +
      '<th class="l">Chiến lược</th><th>Đã đóng</th><th>Đang mở</th><th>Tỷ lệ thắng</th><th>Lời lỗ TB</th>' +
      '<th>Tổng USDT</th><th>R TB</th><th>Backtest: thắng · R TB</th></tr></thead><tbody>' +
      list.map(function(s){
        var r = s.rows, n = r.length, w = r.filter(function(t){ return t.pct > 0; }).length;
        var tot = r.reduce(function(a, t){ return a + t.usdt; }, 0), avg = n ? r.reduce(function(a, t){ return a + t.pct; }, 0) / n : null;
        var rr = r.filter(function(t){ return t.r != null; }), ar = rr.length ? rr.reduce(function(a, t){ return a + t.r; }, 0) / rr.length : null;
        var bt = s.bot === 'crypto' ? BT[s.strategy] : null;
        return '<tr><td class="l"><span class="sym">' + esc(s.strategy) + '</span><small>' + BOTS[s.bot].label + '</small></td>' +
          '<td>' + n + '</td><td>' + (s.open || 0) + '</td>' +
          '<td>' + (n ? vn(w / n * 100, 0) + '%' : '—') + '</td>' +
          '<td class="' + cls(avg) + '">' + sg(avg, 2, '%') + '</td>' +
          '<td class="' + cls(tot) + '">' + (n ? sg(tot, 2) : '—') + '</td>' +
          '<td class="' + cls(ar) + '">' + (ar == null ? '—' : sg(ar, 2, 'R')) + '</td>' +
          '<td>' + (bt ? vn(bt.winRatePct, 0) + '% · <span class="' + cls(bt.avgR) + '">' + sg(bt.avgR, 2, 'R') + '</span>' +
            '<small>' + vn(bt.trades) + ' lệnh / 3 năm</small>' : '—') + '</td></tr>';
      }).join('') + '</tbody></table></div>';
  }

  /* ---------- điều khiển ---------- */
  function chips(id, key){
    $(id).addEventListener('click', function(e){
      var b = e.target.closest('.chip');
      if (!b) return;
      [].forEach.call(this.querySelectorAll('.chip'), function(x){ x.classList.toggle('on', x === b); });
      F[key] = b.getAttribute('data-v');
      render();
    });
  }
  $('f-src').addEventListener('click', function(e){
    var b = e.target.closest('.chip');
    if (!b) return;
    store('solenh.src', b.getAttribute('data-v'));
    setSource(b.getAttribute('data-v'));
  });
  chips('f-bot', 'bot');
  chips('f-res', 'res');
  $('f-strat').addEventListener('change', function(){ F.strat = this.value; render(); });
  ['sz-c', 'sz-t'].forEach(function(id){
    var saved = parseFloat(store('solenh.' + id));
    if (saved > 0) $(id).value = saved;
    $(id).addEventListener('input', function(){ store('solenh.' + id, this.value); render(); });
  });
  if (store('solenh.fee') === '0') $('fee').checked = false;
  $('fee').addEventListener('change', function(){ store('solenh.fee', this.checked ? '1' : '0'); render(); });
})();
