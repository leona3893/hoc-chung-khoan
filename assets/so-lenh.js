/* Sổ lệnh bot: đọc sổ của hai bot crypto (data/crypto-ideas.json, data/trend-ideas.json),
   quy lời lỗ ra USDT theo số tiền mỗi lệnh người xem nhập, lấy giá trực tiếp cho lệnh đang mở,
   và so thành tích từng chiến lược với backtest (data/crypto-backtest.json). */
(function(){
  'use strict';
  var $ = function(id){ return document.getElementById(id); };

  var BOTS = {
    crypto: { file: 'data/crypto-ideas.json', label: 'Bắt đáy 1h', size: 'sz-c' },
    trend:  { file: 'data/trend-ideas.json',  label: 'Xu hướng ngày', size: 'sz-t' }
  };
  var REASON = {
    stop: ['Chạm cắt lỗ', 'c-down'], trail: ['Cắt lỗ dời chạm', ''], tp: ['Đạt mục tiêu', 'c-up'],
    max_hold: ['Hết hạn giữ', ''], strategy: ['Về trung bình 24h', ''], rule: ['Thủng đáy 10 ngày', '']
  };
  var PX_HOSTS = ['https://data-api.binance.vision', 'https://api.binance.com'];
  var FEE = 0.001;

  var CLOSED = [], OPEN = [], BT = {}, META = {}, LIVE = {}, liveAt = null;
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
  function money(t, exit){ var n = net(t.entry, exit); return { pct: n * 100, usdt: n * size(t.bot) }; }

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

  Promise.all([
    getJSON(BOTS.crypto.file).catch(function(){ return null; }),
    getJSON(BOTS.trend.file).catch(function(){ return null; }),
    getJSON('data/crypto-backtest.json').catch(function(){ return null; })
  ]).then(function(res){
    ['crypto', 'trend'].forEach(function(bot, k){
      var d = res[k];
      META[bot] = d;
      if (!d) return;
      (d.closed || []).forEach(function(it){ if (it.exitPrice && it.entry) CLOSED.push(norm(bot, it)); });
      (d.open || []).forEach(function(it){ OPEN.push(norm(bot, it)); });
    });
    ((res[2] && res[2].results) || []).forEach(function(r){
      if (r.variant === 'gốc' || (!r.variant && !BT[r.name])) BT[r.name] = r;
    });

    $('f-c').textContent = factOf('crypto');
    $('f-t').textContent = factOf('trend');
    var strats = {};
    CLOSED.concat(OPEN).forEach(function(t){ strats[t.strategy] = 1; });
    $('f-strat').innerHTML += Object.keys(strats).sort().map(function(s){
      return '<option value="' + esc(s) + '">' + esc(s) + '</option>';
    }).join('');

    var upd = ['crypto', 'trend'].map(function(b){ return META[b] && META[b].updatedAt; }).filter(Boolean).sort().pop();
    status($('stt'), CLOSED.length + ' lệnh đã đóng · ' + OPEN.length + ' đang mở' +
      (upd ? ' · sổ ghi lúc ' + upd : ''), CLOSED.length || OPEN.length ? 'live' : 'wait');
    render();
    refreshPrices();
    setInterval(refreshPrices, 30000);
  });

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
      card('R trung bình', rs.length ? sg(sum(rs, 'r') / rs.length, 2, 'R') : '—', cls(rs.length && sum(rs, 'r')), rs.length ? 'chưa trừ phí · ' + rs.length + ' lệnh' : 'bot xu hướng không đặt R'),
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
        return '<tr><td class="l"><span class="sym">' + esc(pair(t.symbol)) + '</span></td>' +
          '<td class="l"><span class="tag tag-bot">' + BOTS[t.bot].label + '</span> ' + esc(t.strategy) + '</td>' +
          '<td>' + when(t.entryTs) + '</td><td>' + px(t.entry) + '</td>' +
          '<td>' + px(p) + (LIVE[t.symbol] ? '' : '<small>giá trong sổ</small>') + '</td>' +
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
          '<td>' + when(t.entryTs) + '</td><td>' + px(t.entry) + '</td>' +
          '<td>' + when(t.exitTs) + '</td><td>' + px(t.exitPrice) + '</td>' +
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
