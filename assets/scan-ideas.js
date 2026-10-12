/* Hai mục của phòng phân tích:
   A — Quét sàn: bảng gọn mọi mã qua lọc thanh khoản (data/scan.json)
   B — Sổ theo dõi ý tưởng: điểm buy, đang theo dõi, điểm sell (data/ideas.json) */
(function(){
  'use strict';
  var $ = function(id){ return document.getElementById(id); };

  function vn(n, d){
    if (n == null || isNaN(n)) return '—';
    return Number(n).toLocaleString('vi-VN', { minimumFractionDigits: d || 0, maximumFractionDigits: d || 0 });
  }
  function pc(n, d){ return n == null ? '—' : (n > 0 ? '+' : '') + vn(n, d == null ? 2 : d) + '%'; }
  function cls(n){ return n > 0 ? 'c-up' : n < 0 ? 'c-down' : ''; }
  function ty(v){ return v == null ? '—' : vn(v / 1e9, v < 1e10 ? 1 : 0) + ' tỷ'; }
  function dmy(s){ return s ? s.slice(8,10) + '/' + s.slice(5,7) + '/' + s.slice(0,4) : '—'; }
  function esc(s){ return String(s == null ? '' : s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }
  function status(node, text, kind){ if (node){ node.textContent = text; node.className = 'lab-status' + (kind ? ' is-' + kind : ''); } }
  function recTag(key, label){ return '<span class="tag tag-' + key + '">' + esc(label) + '</span>'; }
  function trendCls(t){ return t === 'Tăng' ? 'tag-t-up' : t === 'Giảm' ? 'tag-t-down' : 'tag-t-flat'; }

  /* ============================================================
     A — Quét sàn
     ============================================================ */
  (function(){
    var BODY = $('scan-body');
    if (!BODY) return;
    var DATA = null, ROWS = [], filter = '', query = '', sortKey = 'score', sortAsc = false;

    var COLS = [
      ['symbol', 'Mã', 'left'],
      ['close', 'Giá', 'right'],
      ['chgPct', 'Phiên', 'right'],
      ['score', 'Điểm', 'right'],
      ['rec', 'Khuyến nghị', 'left'],
      ['trend', 'Xu hướng', 'left'],
      ['ret1m', '1 tháng', 'right'],
      ['ret3m', '3 tháng', 'right'],
      ['rsi', 'RSI', 'right'],
      ['value20', 'Thanh khoản', 'right'],
      ['plan', 'Cắt lỗ / mục tiêu', 'right']
    ];

    function head(){
      $('scan-head').innerHTML = '<tr>' + COLS.map(function(c){
        var on = sortKey === c[0];
        return '<th data-k="' + c[0] + '" style="cursor:pointer;text-align:' + c[2] + '">' +
          c[1] + (on ? (sortAsc ? ' ↑' : ' ↓') : '') + '</th>';
      }).join('') + '</tr>';
    }

    function val(r, k){
      if (k === 'plan') return (r.plan && r.plan.rr) || 0;
      if (k === 'rec') return r.score;
      if (k === 'trend') return r.trend === 'Tăng' ? 2 : r.trend === 'Đi ngang' ? 1 : 0;
      return r[k] == null ? -Infinity : r[k];
    }

    function render(){
      var rows = ROWS.filter(function(r){
        if (filter && r.recKey !== filter) return false;
        if (query){
          var q = query.toLowerCase();
          if (r.symbol.toLowerCase().indexOf(q) < 0 && (r.name || '').toLowerCase().indexOf(q) < 0) return false;
        }
        return true;
      });
      rows.sort(function(a, b){
        var x = val(a, sortKey), y = val(b, sortKey);
        if (typeof x === 'string') return sortAsc ? x.localeCompare(y) : y.localeCompare(x);
        return sortAsc ? x - y : y - x;
      });
      head();
      if (!rows.length){
        BODY.innerHTML = '<tr><td colspan="' + COLS.length + '" class="empty">Không mã nào khớp bộ lọc.</td></tr>';
        return;
      }
      BODY.innerHTML = rows.map(function(r){
        var p = r.plan || {};
        var scored = window.ScoredSymbols && window.ScoredSymbols[r.symbol];
        return '<tr data-sym="' + r.symbol + '"' + (scored ? ' class="can-open" style="cursor:pointer"' : '') + '>' +
          '<td class="sym-cell"><b>' + r.symbol + '</b><small>' + esc((r.name || '').slice(0, 34)) +
            (scored ? ' · xem kỹ ↓' : '') + '</small></td>' +
          '<td class="num">' + vn(r.close) + '</td>' +
          '<td class="num ' + cls(r.chgPct) + '">' + pc(r.chgPct) + '</td>' +
          '<td class="num ' + cls(r.score) + '"><b>' + (r.score > 0 ? '+' : '') + r.score + '</b></td>' +
          '<td>' + recTag(r.recKey, r.rec) + '</td>' +
          '<td><span class="tag ' + trendCls(r.trend) + '">' + esc(r.trend) + '</span></td>' +
          '<td class="num ' + cls(r.ret1m) + '">' + pc(r.ret1m, 1) + '</td>' +
          '<td class="num ' + cls(r.ret3m) + '">' + pc(r.ret3m, 1) + '</td>' +
          '<td class="num">' + vn(r.rsi, 0) + '</td>' +
          '<td class="num">' + ty(r.value20) + '</td>' +
          '<td class="num">' + vn(p.stop) + ' / ' + vn(p.target) +
            (p.rr ? ' <small class="c-muted">(' + p.rr + ':1)</small>' : '') + '</td>' +
          '</tr>';
      }).join('');
    }

    $('scan-head').addEventListener('click', function(e){
      var th = e.target.closest('[data-k]');
      if (!th) return;
      var k = th.getAttribute('data-k');
      if (k === sortKey) sortAsc = !sortAsc; else { sortKey = k; sortAsc = (k === 'symbol'); }
      render();
    });
    BODY.addEventListener('click', function(e){
      var tr = e.target.closest('[data-sym]');
      if (!tr || !tr.classList.contains('can-open')) return;
      if (window.selectScored) window.selectScored(tr.getAttribute('data-sym'));
    });
    $('scan-chips').addEventListener('click', function(e){
      var b = e.target.closest('[data-f]');
      if (!b) return;
      filter = b.getAttribute('data-f');
      $('scan-chips').querySelectorAll('.chip').forEach(function(c){ c.classList.toggle('on', c === b); });
      render();
    });
    $('scan-q').addEventListener('input', function(){ query = this.value.trim(); render(); });

    fetch('data/scan.json', { cache: 'no-cache' }).then(function(r){
      if (!r.ok) throw new Error('HTTP ' + r.status);
      return r.json();
    }).then(function(d){
      DATA = d; ROWS = d.rows || [];
      var c = d.counts || {};
      status($('scan-stt'), c.scored + '/' + c.universe + ' mã · phiên ' + dmy(d.dataDate) +
        ' · quét lúc ' + d.updatedAt, 'live');
      var by = c.byRec || {};
      $('scan-cards').innerHTML = [
        ['Rổ quét', vn(c.universe) + ' mã'],
        ['Đạt thanh khoản', vn(c.scored) + ' mã'],
        ['Bị loại vì mỏng', vn(c.thinLiquidity) + ' mã'],
        ['MUA', vn(by.buy || 0) + ' mã'],
        ['TÍCH LŨY', vn(by.acc || 0) + ' mã'],
        ['GIẢM / BÁN', vn((by.reduce || 0) + (by.sell || 0)) + ' mã']
      ].map(function(x){ return '<div><dt>' + x[0] + '</dt><dd>' + x[1] + '</dd></div>'; }).join('');
      $('scan-note').innerHTML = 'Rổ quét: <b>' + esc((d.groups || []).join(' + ')) + '</b>. ' +
        'Loại mã có giá trị khớp trung bình 20 phiên dưới <b>' + ty(d.filters.minValue20d) + '/phiên</b> — ' +
        'dưới mức đó thì bạn không vào ra được mà không tự đẩy giá. ' + esc(d.note) +
        (d.marketOk ? '' : ' <b>VN-Index đang dưới MA50 nên mọi mã bị chặn tối đa ở mức TÍCH LŨY</b> — ' +
         'đó là lý do cột MUA đang bằng 0.');
      render();
    }).catch(function(){
      status($('scan-stt'), 'chưa có dữ liệu quét', 'wait');
      BODY.innerHTML = '<tr><td colspan="' + COLS.length + '" class="empty">Chưa có <code>data/scan.json</code>. ' +
        'Chạy <code>python scripts/scan.py</code> (khoảng 4 phút cho 342 mã).</td></tr>';
    });
  })();

  /* ============================================================
     B — Sổ theo dõi ý tưởng
     ============================================================ */
  (function(){
    var OPEN = $('idea-open');
    if (!OPEN) return;

    var REASON = {
      stop: ['Chạm cắt lỗ', 'c-down'], target: ['Đạt mục tiêu', 'c-up'],
      rule: ['Bị hạ bậc', 'c-down'], time: ['Hết thời gian giữ', ''],
      gap: ['Bỏ vì nhảy giá', 'c-muted'], adjust: ['Điều chỉnh cổ tức', 'c-muted']
    };

    fetch('data/ideas.json', { cache: 'no-cache' }).then(function(r){
      if (!r.ok) throw new Error('HTTP ' + r.status);
      return r.json();
    }).then(function(d){
      var st = d.stats || {};
      status($('idea-stt'), (st.open || 0) + ' đang mở · ' + (st.closed || 0) + ' đã đóng · phiên ' +
        dmy(d.dataDate), 'live');

      $('idea-cards').innerHTML = [
        ['Đang mở', vn(st.open) + ' ý tưởng', ''],
        ['Đã đóng', vn(st.closed) + ' ý tưởng', ''],
        ['Tỷ lệ thắng', st.winRatePct == null ? '—' : vn(st.winRatePct, 1) + '%', ''],
        ['Tổng R', st.totalR == null ? '—' : (st.totalR > 0 ? '+' : '') + vn(st.totalR, 2) + 'R', cls(st.totalR)],
        ['R trung bình', st.avgR == null ? '—' : (st.avgR > 0 ? '+' : '') + vn(st.avgR, 3) + 'R', cls(st.avgR)],
        ['Bỏ vì nhảy giá', vn(st.skipped || 0), '']
      ].map(function(x){ return '<div><dt>' + x[0] + '</dt><dd class="' + x[2] + '">' + x[1] + '</dd></div>'; }).join('');

      var op = d.open || [];
      if (!op.length){
        OPEN.innerHTML = '<p class="empty">Không có ý tưởng nào đang mở. Sổ chỉ mở ý tưởng khi có mã đạt ' +
          'mức <b>MUA</b> — trong thị trường dưới MA50 thì điểm bị chặn ở TÍCH LŨY, nên không có gì để mở. ' +
          'Đó là luật đang làm việc của nó, không phải lỗi.</p>';
      } else {
        OPEN.innerHTML = '<div class="tbl-wrap"><table class="tbl"><tbody>' +
          '<tr><th>Mã</th><th>Trạng thái</th><th>Vào</th><th>Hiện tại</th><th>Lãi/lỗ</th>' +
          '<th>Cắt lỗ</th><th>Mục tiêu</th><th>Giữ</th></tr>' +
          op.map(function(it){
            var pending = it.status === 'pending';
            return '<tr' + (window.ScoredSymbols && window.ScoredSymbols[it.symbol] ? ' data-sym="' + it.symbol + '" style="cursor:pointer"' : '') + '>' +
              '<td class="sym-cell"><b>' + esc(it.symbol) + '</b><small>' + esc((it.name || '').slice(0, 28)) + '</small></td>' +
              '<td>' + (pending ? '<span class="tag tag-hold">chờ khớp</span>' : '<span class="tag tag-buy">đang theo dõi</span>') + '</td>' +
              '<td class="num">' + (pending ? '<span class="c-muted">tín hiệu ' + vn(it.signalClose) + '</span>' : vn(it.entryPrice)) + '</td>' +
              '<td class="num">' + vn(it.lastPrice) + '</td>' +
              '<td class="num ' + cls(it.openR) + '">' + (it.openR == null ? '—' :
                (it.openR > 0 ? '+' : '') + vn(it.openR, 2) + 'R · ' + pc(it.openPct)) + '</td>' +
              '<td class="num">' + vn(it.stop) + '</td>' +
              '<td class="num">' + vn(it.target) + '</td>' +
              '<td class="num">' + (pending ? '—' : vn(it.days) + ' phiên') + '</td></tr>';
          }).join('') + '</tbody></table></div>';
      }

      var cl = (d.closed || []).slice(0, 15);
      $('idea-closed').innerHTML = !cl.length ? '<p class="empty">Chưa có ý tưởng nào đóng lại.</p>' :
        '<div class="tbl-wrap"><table class="tbl"><tbody>' +
        '<tr><th>Mã</th><th>Vào</th><th>Ra</th><th>Lý do</th><th>Kết quả</th><th>Giữ</th></tr>' +
        cl.map(function(c){
          var rs = REASON[c.exitReason] || [c.exitReason, ''];
          return '<tr><td><b>' + esc(c.symbol) + '</b></td>' +
            '<td class="num">' + (c.entryPrice ? vn(c.entryPrice) + ' <small class="c-muted">' + (c.entryDate || '').slice(5) + '</small>' : '—') + '</td>' +
            '<td class="num">' + vn(c.exitPrice) + ' <small class="c-muted">' + (c.exitDate || '').slice(5) + '</small></td>' +
            '<td><span class="' + rs[1] + '">' + rs[0] + '</span></td>' +
            '<td class="num ' + cls(c.exitR) + '">' + (c.exitR == null ? '<span class="c-muted">không tính được</span>' :
              (c.exitR > 0 ? '+' : '') + vn(c.exitR, 2) + 'R · ' + pc(c.exitPct)) + '</td>' +
            '<td class="num">' + (c.days ? vn(c.days) + ' phiên' : '—') + '</td></tr>';
        }).join('') + '</tbody></table></div>';

      if (d.seeded){
        var box = document.createElement('p');
        box.className = 'warn';
        box.innerHTML = '<b>Sổ này được dựng lại từ lịch sử</b>Các ý tưởng dưới đây do máy chạy lại trên ' +
          esc(d.seeded.sessions) + ' bản lưu bảng điểm trong git (phiên ' + dmy(d.seeded.from) + ' đến ' +
          dmy(d.seeded.to) + '). Giá và ngày đều thật, nhưng kế hoạch cũ được so với chuỗi giá đã điều chỉnh ' +
          'cổ tức nên vài con số R có thể lệch chút. Từ phiên sau, sổ chạy tiến về phía trước bình thường.';
        OPEN.parentNode.insertBefore(box, OPEN);
      }
      var r = d.rules || {};
      $('idea-rules').innerHTML = 'Luật của sổ: mở khi khuyến nghị đạt <b>MUA</b>, khớp ở <b>giá mở cửa phiên sau</b> ' +
        '(mở cửa cao hơn giá tín hiệu quá ' + (r.maxGapEntry || 4) + '% thì bỏ, không mua đuổi), tối đa <b>' +
        (r.maxOpen || 5) + ' ý tưởng</b> cùng lúc, thoát khi chạm cắt lỗ, chạm mục tiêu, bị hạ bậc xuống ' +
        'GIẢM TỶ TRỌNG/BÁN, hoặc giữ quá <b>' + (r.maxHoldDays || 40) + ' phiên</b>. ' +
        'Giống luật mà mục kiểm chứng đã backtest, nên hai bộ số so được với nhau.';

      OPEN.addEventListener('click', function(e){
        var tr = e.target.closest('[data-sym]');
        if (tr && window.selectScored) window.selectScored(tr.getAttribute('data-sym'));
      });
    }).catch(function(){
      status($('idea-stt'), 'chưa có sổ theo dõi', 'wait');
      OPEN.innerHTML = '<p class="empty">Chưa có <code>data/ideas.json</code>. Chạy ' +
        '<code>python scripts/ideas.py</code> sau <code>fetch_ssi.py</code>. Sổ cần ít nhất hai phiên ' +
        'để có một vòng đời hoàn chỉnh.</p>';
    });
  })();
})();
