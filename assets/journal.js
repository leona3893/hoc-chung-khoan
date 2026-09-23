/* Nhật ký giao dịch giả lập — ghi lệnh trên giấy, lưu trong localStorage của trình duyệt.
   Không kết nối tài khoản thật, không gửi dữ liệu đi đâu.
   Journal.mount(el, { getPrice: fn(symbol) -> number|null }) */
(function(){
  'use strict';
  var KEY = 'ck-nhat-ky-v1';

  function load(){
    try { var a = JSON.parse(localStorage.getItem(KEY) || '[]'); return Array.isArray(a) ? a : []; }
    catch(e){ return []; }
  }
  function save(list){
    try { localStorage.setItem(KEY, JSON.stringify(list)); return true; }
    catch(e){ return false; }
  }
  function uid(){ return Date.now().toString(36) + Math.random().toString(36).slice(2,7); }
  function esc(s){
    return String(s === null || s === undefined ? '' : s)
      .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  }
  function num(v){ var n = parseFloat(String(v).replace(/[ ,]/g,'')); return isFinite(n) ? n : null; }
  function fmt(n, d){
    if (n === null || n === undefined || !isFinite(n)) return '—';
    if (d === undefined) d = Math.abs(n) >= 1000 ? 0 : Math.abs(n) >= 1 ? 2 : 4;
    return n.toLocaleString('vi-VN', { minimumFractionDigits:d, maximumFractionDigits:d });
  }
  function today(){
    var d = new Date(Date.now() + 7*3600*1000);
    return d.toISOString().slice(0,10);
  }

  /* Một lệnh: {id, market, symbol, side, entry, stop, target, qty, openDate, note,
                closePrice, closeDate, closeNote} */
  function metrics(t, live){
    var dir = t.side === 'short' ? -1 : 1;
    var riskPerUnit = t.stop !== null ? (t.entry - t.stop) * dir : null;
    var rewardPerUnit = t.target !== null ? (t.target - t.entry) * dir : null;
    var rr = (riskPerUnit && riskPerUnit > 0 && rewardPerUnit !== null) ? rewardPerUnit / riskPerUnit : null;
    var ref = t.closePrice !== null && t.closePrice !== undefined ? t.closePrice : live;
    var pnl = null, pnlPct = null, rMultiple = null;
    if (ref !== null && ref !== undefined && isFinite(ref)){
      pnl = (ref - t.entry) * dir * (t.qty || 0);
      pnlPct = t.entry ? (ref - t.entry) * dir / t.entry * 100 : null;
      if (riskPerUnit && riskPerUnit > 0) rMultiple = (ref - t.entry) * dir / riskPerUnit;
    }
    var riskTotal = riskPerUnit !== null && riskPerUnit > 0 ? riskPerUnit * (t.qty || 0) : null;
    return { rr:rr, pnl:pnl, pnlPct:pnlPct, r:rMultiple, riskTotal:riskTotal, ref:ref,
      open: t.closePrice === null || t.closePrice === undefined };
  }

  function mount(host, opt){
    opt = opt || {};
    var list = load();
    var getPrice = opt.getPrice || function(){ return null; };
    var unitHint = opt.unitHint || {};

    host.innerHTML =
      '<form class="jn-form" autocomplete="off">' +
        '<div class="jn-grid">' +
          '<label><span>Thị trường</span><select name="market">' +
            '<option value="vn">Cổ phiếu VN</option><option value="crypto">Coin</option></select></label>' +
          '<label><span>Mã</span><input name="symbol" placeholder="HPG / BTCUSDT" required></label>' +
          '<label><span>Chiều</span><select name="side">' +
            '<option value="long">Mua (long)</option><option value="short">Bán khống (short)</option></select></label>' +
          '<label><span>Giá vào</span><input name="entry" inputmode="decimal" required></label>' +
          '<label><span>Cắt lỗ</span><input name="stop" inputmode="decimal" placeholder="bắt buộc với bản thân bạn"></label>' +
          '<label><span>Chốt lời</span><input name="target" inputmode="decimal"></label>' +
          '<label><span>Khối lượng</span><input name="qty" inputmode="decimal" required></label>' +
          '<label><span>Ngày vào</span><input name="openDate" type="date"></label>' +
        '</div>' +
        '<label class="jn-wide"><span>Lý do vào lệnh — viết trước khi bấm, một câu</span>' +
          '<input name="note" placeholder="VD: giá bật lên từ vùng hỗ trợ 20.5 kèm khối lượng gấp đôi"></label>' +
        '<p class="jn-calc" aria-live="polite"></p>' +
        '<div class="jn-actions"><button type="submit" class="jn-primary">Ghi lệnh</button>' +
          '<button type="button" class="jn-ghost" data-act="demo">Nạp 3 lệnh mẫu</button>' +
          '<button type="button" class="jn-ghost" data-act="export">Xuất JSON</button>' +
          '<button type="button" class="jn-ghost" data-act="clear">Xoá hết</button></div>' +
      '</form>' +
      '<div class="jn-stats"></div>' +
      '<div class="jn-list"></div>';

    var form = host.querySelector('.jn-form');
    var calcEl = host.querySelector('.jn-calc');
    var statsEl = host.querySelector('.jn-stats');
    var listEl = host.querySelector('.jn-list');
    form.openDate.value = today();

    function readForm(){
      return {
        market: form.market.value,
        symbol: (form.symbol.value || '').trim().toUpperCase(),
        side: form.side.value,
        entry: num(form.entry.value),
        stop: num(form.stop.value),
        target: num(form.target.value),
        qty: num(form.qty.value),
        openDate: form.openDate.value || today(),
        note: (form.note.value || '').trim()
      };
    }

    function calc(){
      var t = readForm();
      if (t.entry === null || t.qty === null){ calcEl.textContent = ''; return; }
      var m = metrics({ side:t.side, entry:t.entry, stop:t.stop, target:t.target, qty:t.qty, closePrice:null }, null);
      var cur = unitHint[t.market] || '';
      var bits = ['Vốn vào lệnh ≈ <b>' + fmt(t.entry * t.qty) + cur + '</b>'];
      if (m.riskTotal !== null) bits.push('rủi ro nếu chạm cắt lỗ <b>' + fmt(m.riskTotal) + cur + '</b>');
      else bits.push('<b>chưa đặt cắt lỗ</b> — bạn đang không biết mình mạo hiểm bao nhiêu');
      if (m.rr !== null) bits.push('tỷ lệ lãi/lỗ <b>' + m.rr.toFixed(2) + ':1</b>' + (m.rr < 1.5 ? ' — dưới 1.5, cân nhắc bỏ qua' : ''));
      calcEl.innerHTML = bits.join(' · ');
    }
    form.addEventListener('input', calc);
    form.addEventListener('change', calc);

    form.addEventListener('submit', function(e){
      e.preventDefault();
      var t = readForm();
      if (!t.symbol || t.entry === null || t.qty === null) return;
      t.id = uid(); t.closePrice = null; t.closeDate = null; t.closeNote = '';
      list.unshift(t); save(list);
      form.reset(); form.openDate.value = today(); calcEl.textContent = '';
      render();
    });

    host.querySelector('[data-act="clear"]').addEventListener('click', function(){
      if (!list.length) return;
      if (!confirm('Xoá toàn bộ ' + list.length + ' lệnh trong nhật ký? Không khôi phục được.')) return;
      list = []; save(list); render();
    });
    host.querySelector('[data-act="export"]').addEventListener('click', function(){
      var blob = new Blob([JSON.stringify(list, null, 2)], { type:'application/json' });
      var a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = 'nhat-ky-giao-dich-' + today() + '.json';
      a.click();
      setTimeout(function(){ URL.revokeObjectURL(a.href); }, 1000);
    });
    host.querySelector('[data-act="demo"]').addEventListener('click', function(){
      if (list.length && !confirm('Nhật ký đang có ' + list.length + ' lệnh. Thêm 3 lệnh mẫu vào cùng?')) return;
      var d = [
        { market:'vn', symbol:'HPG', side:'long', entry:20600, stop:20000, target:22400, qty:1000,
          openDate:'2026-07-21', note:'Bật lên từ vùng 20.1–20.5 sau cú gãy, khối lượng cạn dần.',
          closePrice:22200, closeDate:'2026-08-27', closeNote:'Chốt khi giá đi ngang dưới 22.5 ba phiên.' },
        { market:'crypto', symbol:'BTCUSDT', side:'long', entry:84000, stop:80500, target:93000, qty:0.05,
          openDate:'2026-09-10', note:'Giữ trên MA50 ngày, RSI về 45 rồi bật.', closePrice:null, closeDate:null, closeNote:'' },
        { market:'vn', symbol:'MWG', side:'long', entry:64500, stop:61500, target:72000, qty:300,
          openDate:'2026-09-02', note:'Mua khi giá vượt đỉnh cũ, nhưng khối lượng không xác nhận.',
          closePrice:61500, closeDate:'2026-09-21', closeNote:'Chạm cắt lỗ, cắt theo kế hoạch — không gồng.' }
      ];
      d.forEach(function(t){ t.id = uid(); list.unshift(t); });
      save(list); render();
    });

    listEl.addEventListener('click', function(e){
      var btn = e.target.closest ? e.target.closest('[data-id]') : null;
      if (!btn) return;
      var id = btn.getAttribute('data-id'), act = btn.getAttribute('data-do');
      var i = list.findIndex(function(t){ return t.id === id; });
      if (i < 0) return;
      var t = list[i];
      if (act === 'del'){
        if (confirm('Xoá lệnh ' + t.symbol + '?')){ list.splice(i,1); save(list); render(); }
      } else if (act === 'close'){
        var live = getPrice(t.symbol, t.market);
        var p = prompt('Giá đóng lệnh ' + t.symbol + (live ? ' (giá hiện tại ' + fmt(live) + ')' : '') + ':',
          live !== null && live !== undefined ? String(live) : '');
        if (p === null) return;
        var v = num(p);
        if (v === null) return;
        t.closePrice = v; t.closeDate = today();
        t.closeNote = prompt('Một câu: vì sao bạn đóng lệnh này?', t.closeNote || '') || '';
        save(list); render();
      } else if (act === 'reopen'){
        t.closePrice = null; t.closeDate = null; save(list); render();
      }
    });

    function stats(){
      var closed = list.filter(function(t){ return t.closePrice !== null && t.closePrice !== undefined; });
      var rs = [], wins = 0, losses = 0, sumR = 0, hasR = 0;
      closed.forEach(function(t){
        var m = metrics(t, null);
        if (m.pnl !== null){ if (m.pnl > 0) wins++; else if (m.pnl < 0) losses++; }
        if (m.r !== null){ rs.push(m.r); sumR += m.r; hasR++; }
      });
      var openCount = list.length - closed.length;
      var winRate = (wins + losses) ? wins/(wins+losses)*100 : null;
      var avgWin = 0, nW = 0, avgLoss = 0, nL = 0;
      rs.forEach(function(r){ if (r > 0){ avgWin += r; nW++; } else if (r < 0){ avgLoss += r; nL++; } });
      avgWin = nW ? avgWin/nW : null; avgLoss = nL ? avgLoss/nL : null;
      var noStop = list.filter(function(t){ return t.stop === null; }).length;

      if (!list.length){
        statsEl.innerHTML = '<p class="jn-empty">Chưa có lệnh nào. Ghi lệnh đầu tiên ở trên — hoặc bấm “Nạp 3 lệnh mẫu” để xem nhật ký trông như thế nào.</p>';
        return;
      }
      var cards = [
        ['Đang mở', openCount + ' lệnh'],
        ['Đã đóng', closed.length + ' lệnh'],
        ['Tỷ lệ thắng', winRate === null ? '—' : winRate.toFixed(0) + '%'],
        ['Tổng R', hasR ? (sumR >= 0 ? '+' : '') + sumR.toFixed(2) + 'R' : '—'],
        ['R trung bình', hasR ? (sumR/hasR >= 0 ? '+' : '') + (sumR/hasR).toFixed(2) + 'R' : '—'],
        ['Lệnh không cắt lỗ', noStop + '/' + list.length]
      ];
      var note = '';
      if (hasR >= 3){
        var exp = sumR/hasR;
        note = exp > 0
          ? 'Kỳ vọng dương: trung bình mỗi lệnh bạn kiếm được <b>' + exp.toFixed(2) + 'R</b>. Điều đáng giữ là quy trình, không phải con số.'
          : 'Kỳ vọng âm: trung bình mỗi lệnh mất <b>' + Math.abs(exp).toFixed(2) + 'R</b>. Đọc lại lý do vào lệnh của các lệnh lỗ — thường có một mẫu lặp lại.';
        if (winRate !== null && avgWin !== null && avgLoss !== null && winRate < 50 && sumR > 0)
          note += ' Thắng dưới nửa số lệnh mà vẫn dương, vì lệnh thắng lớn hơn lệnh thua — đó chính là điều tỷ lệ lãi/lỗ làm được.';
      }
      if (noStop > 0) note += (note ? ' ' : '') + '<b>' + noStop + ' lệnh không có điểm cắt lỗ</b> — với những lệnh đó không tính được R, và trong thực tế đó là cách tài khoản biến mất.';
      statsEl.innerHTML =
        '<dl class="jn-cards">' + cards.map(function(c){
          return '<div><dt>' + c[0] + '</dt><dd>' + c[1] + '</dd></div>';
        }).join('') + '</dl>' + (note ? '<p class="jn-note">' + note + '</p>' : '');
    }

    function render(){
      stats();
      if (!list.length){ listEl.innerHTML = ''; return; }
      var rows = list.map(function(t){
        var live = t.closePrice === null || t.closePrice === undefined ? getPrice(t.symbol, t.market) : null;
        var m = metrics(t, live);
        var cur = unitHint[t.market] || '';
        var cls = m.pnl === null ? '' : m.pnl > 0 ? 'is-up' : m.pnl < 0 ? 'is-down' : '';
        var badge = m.open
          ? '<span class="jn-badge is-open">đang mở</span>'
          : '<span class="jn-badge">đã đóng ' + esc(t.closeDate || '') + '</span>';
        var pnlTxt = m.pnl === null
          ? '<span class="jn-muted">chưa có giá tham chiếu</span>'
          : '<b>' + (m.pnl >= 0 ? '+' : '−') + fmt(Math.abs(m.pnl)) + cur + '</b> · ' +
            (m.pnlPct >= 0 ? '+' : '−') + Math.abs(m.pnlPct).toFixed(2) + '%' +
            (m.r !== null ? ' · <b>' + (m.r >= 0 ? '+' : '') + m.r.toFixed(2) + 'R</b>' : '');
        var facts = [
          ['Vào', fmt(t.entry) + cur],
          ['Cắt lỗ', t.stop === null ? '<span class="jn-warn">chưa đặt</span>' : fmt(t.stop) + cur],
          ['Chốt lời', t.target === null ? '—' : fmt(t.target) + cur],
          ['KL', fmt(t.qty, t.qty >= 100 ? 0 : 4)],
          [m.open ? 'Giá hiện tại' : 'Giá đóng', m.ref === null || m.ref === undefined ? '—' : fmt(m.ref) + cur],
          ['Lãi/lỗ', pnlTxt]
        ];
        return '<article class="jn-item ' + cls + '">' +
          '<header><span class="jn-sym">' + esc(t.symbol) + '</span>' +
            '<span class="jn-side is-' + t.side + '">' + (t.side === 'short' ? 'bán khống' : 'mua') + '</span>' +
            badge + '<span class="jn-when">' + esc(t.openDate) + '</span>' +
            '<span class="jn-tools">' +
              (m.open ? '<button type="button" data-id="' + t.id + '" data-do="close">Đóng lệnh</button>'
                      : '<button type="button" data-id="' + t.id + '" data-do="reopen">Mở lại</button>') +
              '<button type="button" data-id="' + t.id + '" data-do="del">Xoá</button>' +
            '</span></header>' +
          '<dl class="jn-facts">' + facts.map(function(f){
            return '<div><dt>' + f[0] + '</dt><dd>' + f[1] + '</dd></div>';
          }).join('') + '</dl>' +
          (t.note ? '<p class="jn-why"><b>Vì sao vào:</b> ' + esc(t.note) + '</p>' : '') +
          (t.closeNote ? '<p class="jn-why"><b>Vì sao đóng:</b> ' + esc(t.closeNote) + '</p>' : '') +
          '</article>';
      });
      listEl.innerHTML = rows.join('');
    }

    render();
    return { refresh: render, all: function(){ return list.slice(); } };
  }

  window.Journal = { mount: mount };
})();
