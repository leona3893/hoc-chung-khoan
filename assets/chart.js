/* Phòng thực hành đọc nến — engine dùng chung cho chứng khoán VN và crypto.
   CandleLab.create({ host, bars, ... }) trả về api { setBars, pick, pickDate, setStatus }.
   bars: [[time, o, h, l, c, v], ...] — time là 'YYYY-MM-DD' hoặc 'YYYY-MM-DDTHH:MM' (giờ VN). */
(function(){
  'use strict';
  var NS = 'http://www.w3.org/2000/svg';

  function el(n, a){
    var e = document.createElementNS(NS, n);
    for (var k in a) if (a[k] !== null && a[k] !== undefined) e.setAttribute(k, a[k]);
    return e;
  }
  function vn(n){ return n.toLocaleString('vi-VN'); }

  /* ---------- chỉ báo ---------- */
  function sma(bars, n){
    var out = new Array(bars.length), s = 0;
    for (var i=0;i<bars.length;i++){
      s += bars[i][4];
      if (i >= n) s -= bars[i-n][4];
      out[i] = i >= n-1 ? s/n : null;
    }
    return out;
  }
  function bollinger(bars, n, k){
    var mid = sma(bars, n), up = [], dn = [];
    for (var i=0;i<bars.length;i++){
      if (mid[i] === null){ up.push(null); dn.push(null); continue; }
      var v = 0;
      for (var j=i-n+1;j<=i;j++){ var d = bars[j][4]-mid[i]; v += d*d; }
      var sd = Math.sqrt(v/n);
      up.push(mid[i] + k*sd); dn.push(mid[i] - k*sd);
    }
    return { mid:mid, up:up, dn:dn };
  }
  function rsi(bars, n){
    var out = new Array(bars.length), g = 0, l = 0;
    for (var i=0;i<bars.length;i++){
      if (i === 0){ out[i] = null; continue; }
      var ch = bars[i][4] - bars[i-1][4], gain = ch > 0 ? ch : 0, loss = ch < 0 ? -ch : 0;
      if (i <= n){
        g += gain; l += loss;
        if (i < n){ out[i] = null; continue; }
        g /= n; l /= n;
      } else {
        g = (g*(n-1) + gain)/n; l = (l*(n-1) + loss)/n;
      }
      out[i] = l === 0 ? 100 : 100 - 100/(1 + g/l);
    }
    return out;
  }

  /* gộp nến ngày thành nến tuần (tuần ISO, thứ Hai → Chủ nhật) */
  function weekly(rows){
    var out = [], cur = null;
    for (var i=0;i<rows.length;i++){
      var r = rows[i], d = new Date(r[0].slice(0,10) + 'T00:00:00Z');
      var wk = Math.floor((d.getTime()/86400000 + 3) / 7);
      if (!cur || cur.wk !== wk){
        cur = { wk:wk, k:1, b:[r[0], r[1], r[2], r[3], r[4], r[5]] };
        out.push(cur);
      } else {
        var b = cur.b;
        if (r[2] > b[2]) b[2] = r[2];
        if (r[3] < b[3]) b[3] = r[3];
        b[4] = r[4]; b[5] += r[5];
        cur.k++;
      }
      cur.end = r[0];
    }
    return out.map(function(o){ var b = o.b.slice(); b[6] = o.end; b[7] = o.k; return b; });
  }

  /* ---------- định dạng ---------- */
  function fmtPrice(p, dec){
    if (dec === undefined){
      dec = p >= 1000 ? 0 : p >= 100 ? 1 : p >= 1 ? 2 : p >= 0.01 ? 4 : 6;
    }
    return p.toLocaleString('vi-VN', { minimumFractionDigits:dec, maximumFractionDigits:dec });
  }
  function fmtVol(v){
    if (v >= 1e9) return (v/1e9).toFixed(2) + ' tỷ';
    if (v >= 1e6) return (v/1e6).toFixed(2) + ' tr';
    if (v >= 1e3) return (v/1e3).toFixed(1) + ' k';
    return v.toLocaleString('vi-VN', { maximumFractionDigits:2 });
  }
  function dm(s){ return s.slice(8,10) + '/' + s.slice(5,7); }
  function dmy(s){ return s.slice(8,10) + '/' + s.slice(5,7) + '/' + s.slice(0,4); }
  function hm(s){ return s.length > 10 ? s.slice(11,16) : ''; }

  function create(opt){
    var host = opt.host, SVG = host.querySelector('svg'), READ = host.querySelector('.lab-read');
    var RAW = opt.bars || [], bars = RAW, sel = -1;
    var tf = opt.tf || 'D';                       // khoá khung thời gian hiện tại
    var intraday = false;                         // nến nhỏ hơn 1 ngày → nhãn giờ
    var ind = { ma20:false, ma50:false, ma200:false, bb:false, rsi:false };
    var zone = opt.zone || null, touch = opt.touch || 0;
    var unit = opt.unit || 'phiên';               // "phiên" (CK) / "nến" (coin)
    var dec = opt.decimals;                       // số lẻ cố định (null = tự chọn)
    var axis = opt.axis || function(p){ return fmtPrice(p, dec); };
    var price = opt.price || function(p){ return fmtPrice(p, dec); };
    var W = 720, L = 10, R = 664, PT = 26, PB = 258, VT = 288, VB = 348, TY = 370, H = 400;
    var RT = 0, RB = 0;                           // vùng RSI (nếu bật)

    host.querySelectorAll('[data-ind]').forEach(function(b){
      ind[b.getAttribute('data-ind')] = b.classList.contains('on');
      b.addEventListener('click', function(){
        var k = b.getAttribute('data-ind');
        ind[k] = !ind[k];
        b.classList.toggle('on', ind[k]);
        b.setAttribute('aria-pressed', ind[k] ? 'true' : 'false');
        draw(); readout();
      });
    });

    function layout(){
      if (ind.rsi){ RT = 392; RB = 452; TY = 474; H = 490; }
      else { RT = RB = 0; TY = 370; H = 400; }
      SVG.setAttribute('viewBox', '0 0 ' + W + ' ' + H);
    }

    function polyline(series, py, cx, color, dash, width){
      var d = '', on = false;
      for (var i=0;i<series.length;i++){
        if (series[i] === null){ on = false; continue; }
        d += (on ? 'L' : 'M') + cx(i).toFixed(1) + ' ' + py(series[i]).toFixed(1);
        on = true;
      }
      if (!d) return;
      SVG.appendChild(el('path', { d:d, fill:'none', stroke:color, 'stroke-width':width || 1.4,
        'stroke-dasharray':dash || null, 'stroke-linejoin':'round', 'pointer-events':'none' }));
    }

    function draw(){
      layout();
      while (SVG.firstChild) SVG.removeChild(SVG.firstChild);
      var n = bars.length, i;
      if (!n){
        SVG.appendChild(el('text', { x:W/2, y:H/2, 'text-anchor':'middle', class:'t-num', fill:'var(--muted)' }))
          .textContent = 'Chưa có dữ liệu';
        return;
      }
      var hi = -Infinity, lo = Infinity, vmax = 0;
      for (i=0;i<n;i++){
        if (bars[i][2] > hi) hi = bars[i][2];
        if (bars[i][3] < lo) lo = bars[i][3];
        if (bars[i][5] > vmax) vmax = bars[i][5];
      }
      var bb = ind.bb ? bollinger(bars, 20, 2) : null;
      var mas = {};
      [20,50,200].forEach(function(k){ if (ind['ma'+k]) mas[k] = sma(bars, k); });
      if (bb){ for (i=0;i<n;i++){ if (bb.up[i] !== null){ if (bb.up[i] > hi) hi = bb.up[i]; if (bb.dn[i] < lo) lo = bb.dn[i]; } } }
      var pad = (hi - lo) * 0.06 || hi * 0.01 || 1;
      hi += pad; lo -= pad;
      var py = function(p){ return PB - (p - lo) * (PB - PT) / (hi - lo); };
      var pitch = (R - L) / n;
      var cx = function(i){ return L + pitch * (i + 0.5); };
      var bw = Math.max(1.2, Math.min(13, pitch * 0.66));

      // lưới giá
      var rawStep = (hi - lo) / 6, mag = Math.pow(10, Math.floor(Math.log(rawStep)/Math.LN10));
      var nm = rawStep / mag;
      var step = (nm <= 1 ? 1 : nm <= 2 ? 2 : nm <= 2.5 ? 2.5 : nm <= 5 ? 5 : 10) * mag;
      var start = Math.ceil(lo / step) * step;
      for (var p = start; p <= hi; p += step){
        SVG.appendChild(el('line', { x1:L, y1:py(p), x2:R, y2:py(p), stroke:'var(--line-soft)' }));
        SVG.appendChild(el('text', { x:R+6, y:py(p)+4, class:'t-num', fill:'var(--muted)', 'font-size':'10' })).textContent = axis(p);
      }

      // vùng giá đang chú ý
      if (zone && zone[0] > lo && zone[1] < hi){
        SVG.appendChild(el('rect', { x:L, y:py(zone[1]), width:R-L, height:Math.max(2, py(zone[0])-py(zone[1])),
          fill:'var(--accent)', 'fill-opacity':'.11', stroke:'var(--accent)', 'stroke-opacity':'.42', 'stroke-dasharray':'5 4' }));
        var zt = el('text', { x:L+7, y:py(zone[1])-6, class:'t-num', fill:'var(--accent-ink)', 'font-size':'9.5' });
        zt.textContent = 'vùng ' + axis(zone[0]) + ' – ' + axis(zone[1]) + (touch ? ' · ' + touch + ' ' + unit + ' chạm rồi bật lên' : '');
        SVG.appendChild(zt);
      }

      // dải Bollinger
      if (bb){
        var area = '', back = '';
        for (i=0;i<n;i++){ if (bb.up[i] === null) continue;
          area += (area ? 'L' : 'M') + cx(i).toFixed(1) + ' ' + py(bb.up[i]).toFixed(1);
          back = 'L' + cx(i).toFixed(1) + ' ' + py(bb.dn[i]).toFixed(1) + back;
        }
        if (area) SVG.appendChild(el('path', { d:area + back + 'Z', fill:'var(--floor)', 'fill-opacity':'.08', 'pointer-events':'none' }));
        polyline(bb.up, py, cx, 'var(--floor)', '3 3', 1);
        polyline(bb.dn, py, cx, 'var(--floor)', '3 3', 1);
        polyline(bb.mid, py, cx, 'var(--floor)', null, 1);
      }

      // nến + khối lượng
      for (i=0;i<n;i++){
        var b = bars[i], up = b[4] >= b[1], col = up ? 'var(--up)' : 'var(--down)';
        var g = el('g', { 'data-i':i, class:'cd', style:'cursor:pointer' });
        g.appendChild(el('line', { x1:cx(i), y1:py(b[2]), x2:cx(i), y2:py(b[3]), stroke:col, 'stroke-width':Math.max(1, bw*0.16) }));
        var yo = py(b[1]), yc = py(b[4]);
        g.appendChild(el('rect', { x:cx(i)-bw/2, y:Math.min(yo,yc), width:bw, height:Math.max(Math.abs(yc-yo), 1.4), fill:col }));
        if (vmax > 0 && b[5] > 0){
          var vh = (b[5]/vmax) * (VB - VT);
          g.appendChild(el('rect', { x:cx(i)-bw/2, y:VB-vh, width:bw, height:vh, fill:col, 'fill-opacity':'.42' }));
        }
        g.appendChild(el('rect', { x:cx(i)-pitch/2, y:PT-2, width:pitch, height:(ind.rsi ? RB : VB)-PT+4, fill:'transparent' }));
        SVG.appendChild(g);
      }

      // đường trung bình
      var maCol = { 20:'var(--accent)', 50:'var(--ceil)', 200:'var(--ink)' };
      for (var k in mas) polyline(mas[k], py, cx, maCol[k], null, 1.5);

      SVG.appendChild(el('line', { x1:L, y1:VB, x2:R, y2:VB, stroke:'var(--line)' }));
      var vl = el('text', { x:L, y:VT-6, class:'t-num', fill:'var(--muted)', 'font-size':'9.5' });
      vl.textContent = 'KHỐI LƯỢNG'; SVG.appendChild(vl);

      // chú giải chỉ báo
      var lx = L + 4, legend = [];
      for (k in mas) legend.push(['MA' + k, maCol[k]]);
      if (bb) legend.push(['BB(20,2)', 'var(--floor)']);
      legend.forEach(function(it){
        SVG.appendChild(el('line', { x1:lx, y1:PT-14, x2:lx+14, y2:PT-14, stroke:it[1], 'stroke-width':2 }));
        var t = el('text', { x:lx+18, y:PT-10, class:'t-num', fill:'var(--muted)', 'font-size':'9.5' });
        t.textContent = it[0]; SVG.appendChild(t);
        lx += 18 + it[0].length * 6.2 + 12;
      });

      // RSI
      if (ind.rsi){
        var rs = rsi(bars, 14);
        var ry = function(v){ return RB - v * (RB - RT) / 100; };
        SVG.appendChild(el('rect', { x:L, y:ry(70), width:R-L, height:ry(30)-ry(70), fill:'var(--surface-2)' }));
        [30,50,70].forEach(function(v){
          SVG.appendChild(el('line', { x1:L, y1:ry(v), x2:R, y2:ry(v), stroke:'var(--line-soft)', 'stroke-dasharray': v===50 ? '2 3' : null }));
          SVG.appendChild(el('text', { x:R+6, y:ry(v)+4, class:'t-num', fill:'var(--muted)', 'font-size':'10' })).textContent = v;
        });
        polyline(rs, ry, cx, 'var(--ceil)', null, 1.5);
        var rl = el('text', { x:L, y:RT-6, class:'t-num', fill:'var(--muted)', 'font-size':'9.5' });
        rl.textContent = 'RSI 14'; SVG.appendChild(rl);
      }

      // nhãn thời gian
      var every = Math.max(1, Math.round(n / 6));
      for (i=0;i<n;i+=every){
        var ax = cx(i), an = 'middle';
        if (ax - 20 < L){ ax = L; an = 'start'; }
        else if (ax + 20 > R){ ax = R; an = 'end'; }
        var t2 = el('text', { x:ax, y:TY, class:'t-num', fill:'var(--muted)', 'text-anchor':an });
        t2.textContent = intraday ? dm(bars[i][0]) + ' ' + hm(bars[i][0]) : dm(bars[i][0]);
        SVG.appendChild(t2);
      }

      if (sel >= 0 && sel < n){
        var s = bars[sel], bottom = ind.rsi ? RB : VB;
        SVG.appendChild(el('line', { x1:cx(sel), y1:PT-2, x2:cx(sel), y2:bottom, stroke:'var(--ink)', 'stroke-opacity':'.32', 'stroke-dasharray':'3 3' }));
        SVG.appendChild(el('rect', { x:cx(sel)-Math.max(bw,7)/2-3, y:py(s[2])-4, width:Math.max(bw,7)+6, height:py(s[3])-py(s[2])+8, rx:3, fill:'none', stroke:'var(--ink)', 'stroke-opacity':'.55' }));
        SVG.appendChild(el('line', { x1:L, y1:py(s[4]), x2:R, y2:py(s[4]), stroke:'var(--ink)', 'stroke-opacity':'.3', 'stroke-dasharray':'2 4' }));
      }
    }

    function avgVol(i){
      var a = 0, k = 0;
      for (var j = Math.max(0, i-19); j <= i; j++){ if (bars[j][5] > 0){ a += bars[j][5]; k++; } }
      return { avg: k ? a/k : 0, n: k };
    }

    function readout(){
      if (!READ) return;
      if (sel < 0 || sel >= bars.length){ READ.innerHTML = '<p class="lab-empty">Chưa chọn cây nến nào — bấm vào đồ thị ở trên.</p>'; return; }
      var b = bars[sel], o=b[1], h=b[2], l=b[3], c=b[4], v=b[5];
      var rng = h - l, body = Math.abs(c-o);
      var upSh = h - Math.max(o,c), dnSh = Math.min(o,c) - l;
      var pb = rng ? body/rng*100 : 0, pu = rng ? upSh/rng*100 : 0, pd = rng ? dnSh/rng*100 : 0;
      var prev = sel > 0 ? bars[sel-1][4] : o;
      var chg = prev ? (c-prev)/prev*100 : 0;
      var up = c >= o, col = up ? 'var(--up)' : 'var(--down)';
      var av = avgVol(sel), vr = av.avg ? v/av.avg : 0;
      var partial = (tf === 'W' && b[7] && b[7] < 5);
      var last = sel === bars.length - 1 && opt.liveLast;

      var why = [];
      if (last) why.push('<b>Cây nến này chưa đóng</b> — hình dạng của nó còn thay đổi cho tới khi khung thời gian này kết thúc. Đọc một cây nến chưa đóng là lỗi phổ biến nhất khi xem dữ liệu sống.');
      if (rng === 0) why.push('Giá không dao động — gần như không có giao dịch đáng kể.');
      else if (pb > 70) why.push('<b>Thân dài (' + pb.toFixed(0) + '% biên độ)</b> — phe ' + (up?'mua':'bán') + ' kiểm soát gần như cả ' + unit + ', ít giằng co.');
      else if (pb < 12) why.push('<b>Thân rất ngắn (' + pb.toFixed(0) + '%)</b> — mở và đóng gần bằng nhau: hai phe hoà nhau, đám đông lưỡng lự.');
      else why.push('Thân vừa (' + pb.toFixed(0) + '% biên độ) — có xu hướng nhưng vẫn còn giằng co.');
      if (pd > 45) why.push('<b>Bóng dưới dài (' + pd.toFixed(0) + '%)</b> — giá từng bị dìm xuống ' + price(l) + ' rồi được mua ngược lên: có lực đỡ ở vùng đó.');
      if (pu > 45) why.push('<b>Bóng trên dài (' + pu.toFixed(0) + '%)</b> — có lúc lên tới ' + price(h) + ' nhưng bị bán ép về: có lực cản ở trên.');
      var ky = tf === 'W' ? ' tuần' : ' ' + unit;
      if (partial){
        why.push('<b>Tuần này chưa kết thúc</b> — mới có ' + b[7] + ' phiên, nên không so khối lượng với các tuần trọn vẹn được.');
      } else if (v > 0 && av.avg > 0 && av.n > 3){
        if (vr >= 2) why.push('Khối lượng <b>gấp ' + vr.toFixed(1) + ' lần</b> trung bình ' + av.n + ky + ' gần nhất — nhiều người cùng hành động, tín hiệu đáng tin hơn.');
        else if (vr <= 0.6) why.push('Khối lượng chỉ bằng ' + Math.round(vr*100) + '% trung bình ' + av.n + ky + ' gần nhất — ít người tham gia, đừng tin vội.');
      }

      // đọc chỉ báo đang bật
      var ext = [];
      if (ind.ma20 || ind.ma50 || ind.ma200){
        var parts = [];
        [20,50,200].forEach(function(k){
          if (!ind['ma'+k]) return;
          var m = sma(bars, k)[sel];
          if (m === null){ parts.push('MA' + k + ' chưa đủ ' + k + ' ' + unit + ' để tính'); return; }
          parts.push('giá ' + (c >= m ? '<b>trên</b>' : '<b>dưới</b>') + ' MA' + k + ' (' + price(m) + ')');
        });
        var m20 = ind.ma20 ? sma(bars,20)[sel] : null, m50 = ind.ma50 ? sma(bars,50)[sel] : null;
        var verdict = '';
        if (m20 !== null && m50 !== null) verdict = m20 > m50 ? ' MA20 nằm trên MA50 — cấu trúc ngắn hạn đang nghiêng về tăng.' : ' MA20 nằm dưới MA50 — cấu trúc ngắn hạn đang nghiêng về giảm.';
        ext.push('<b>Trung bình động:</b> ' + parts.join(', ') + '.' + verdict);
      }
      if (ind.bb){
        var bbv = bollinger(bars, 20, 2);
        if (bbv.up[sel] !== null){
          var w = (bbv.up[sel]-bbv.dn[sel])/bbv.mid[sel]*100;
          var pos = c > bbv.up[sel] ? 'đóng cửa <b>ngoài dải trên</b> — giá đang căng, hay gặp sau một nhịp tăng mạnh; không tự động là tín hiệu bán'
                  : c < bbv.dn[sel] ? 'đóng cửa <b>ngoài dải dưới</b> — bị bán quá đà trong ngắn hạn; không tự động là tín hiệu mua'
                  : 'nằm trong dải';
          ext.push('<b>Bollinger:</b> ' + pos + '. Độ rộng dải ' + w.toFixed(1) + '%' + (w < 6 ? ' — dải đang <b>bóp hẹp</b>, thường đi trước một cú biến động mạnh.' : '.'));
        }
      }
      if (ind.rsi){
        var rv = rsi(bars, 14)[sel];
        if (rv !== null){
          ext.push('<b>RSI 14 = ' + rv.toFixed(1) + '</b>' + (rv >= 70 ? ' — vùng quá mua. Trong xu hướng tăng mạnh RSI có thể ở đây rất lâu, đừng bán chỉ vì con số này.'
            : rv <= 30 ? ' — vùng quá bán. Trong xu hướng giảm mạnh RSI có thể ở đây rất lâu, đừng bắt đáy chỉ vì con số này.'
            : rv >= 55 ? ' — phe mua đang chiếm ưu thế nhẹ.' : rv <= 45 ? ' — phe bán đang chiếm ưu thế nhẹ.' : ' — trung tính.'));
        }
      }
      why = why.concat(ext);
      why.push('Câu hỏi cuối cùng vẫn thế: cây nến này nằm ở đâu trong xu hướng, và cách vùng giá quan trọng bao xa?');

      var per;
      if (tf === 'W') per = 'Tuần ' + dmy(b[0]) + (b[6] && b[6] !== b[0] ? ' – ' + dm(b[6]) : '');
      else if (intraday) per = dmy(b[0]) + ' ' + hm(b[0]);
      else per = dmy(b[0]);
      var cells = [['Mở', o], ['Cao', h], ['Thấp', l], ['Đóng', c]].map(function(x){
        return '<div><dt>' + x[0] + '</dt><dd>' + price(x[1]) + '</dd></div>';
      }).join('');
      cells += '<div><dt>Khối lượng</dt><dd>' + (v > 0 ? (opt.volFmt ? opt.volFmt(v) : vn(v)) : '—') + '</dd></div>';

      READ.innerHTML =
        '<div class="lab-r1"><span class="lab-date">' + per + '</span>' +
        '<span class="lab-chg" style="color:' + col + '">' + (chg>=0?'+':'−') + Math.abs(chg).toFixed(2) + '%</span>' +
        '<span class="lab-tag" style="color:' + col + ';border-color:' + col + '">' + (up ? 'nến tăng' : 'nến giảm') + '</span>' +
        (last ? '<span class="lab-tag lab-tag-live">đang chạy</span>' : '') + '</div>' +
        '<dl class="lab-ohlc">' + cells + '</dl>' +
        '<div class="lab-why">' + why.join(' ') + '</div>';
    }

    function pick(i){
      if (i < 0 || i >= bars.length) return;
      sel = i; draw(); readout();
    }
    function pickDate(d){
      for (var i=0;i<bars.length;i++) if (bars[i][0].slice(0, d.length) === d){ pick(i); return true; }
      return false;
    }
    function setTfButtons(key){
      host.querySelectorAll('[data-tf]').forEach(function(o){
        var on = o.getAttribute('data-tf') === key;
        o.classList.toggle('on', on);
        o.setAttribute('aria-pressed', on ? 'true' : 'false');
      });
    }
    /* đổi dữ liệu gốc (khi tải xong dữ liệu sống / đổi mã) */
    function setBars(rows, o){
      o = o || {};
      RAW = rows || [];
      if ('zone' in o){ zone = o.zone; touch = o.touch || 0; }
      if ('intraday' in o) intraday = !!o.intraday;
      if ('liveLast' in o) opt.liveLast = !!o.liveLast;
      bars = (tf === 'W' && o.derive !== false) ? weekly(RAW) : RAW;
      sel = bars.length ? bars.length - 1 : -1;
      draw(); readout();
    }
    function setStatus(text, kind){
      var s = host.querySelector('.lab-status');
      if (!s) return;
      s.textContent = text || '';
      s.className = 'lab-status' + (kind ? ' is-' + kind : '');
    }

    SVG.addEventListener('click', function(e){
      var g = e.target.closest ? e.target.closest('[data-i]') : null;
      if (g) pick(+g.getAttribute('data-i'));
    });
    SVG.addEventListener('keydown', function(e){
      if (e.key === 'ArrowRight'){ pick(sel < 0 ? 0 : sel+1); e.preventDefault(); }
      else if (e.key === 'ArrowLeft'){ pick(sel < 0 ? bars.length-1 : sel-1); e.preventDefault(); }
    });
    host.querySelectorAll('[data-tf]').forEach(function(btn){
      btn.addEventListener('click', function(){
        var key = btn.getAttribute('data-tf');
        if (key === tf) return;
        tf = key; setTfButtons(key);
        if (opt.onTf){
          // trang tự tải dữ liệu cho khung mới (crypto), engine chỉ chờ setBars
          opt.onTf(key);
        } else {
          bars = tf === 'W' ? weekly(RAW) : RAW;
          sel = bars.length - 1; draw(); readout();
        }
      });
    });
    host.querySelectorAll('.lab-jump').forEach(function(btn){
      btn.addEventListener('click', function(){
        var d = btn.getAttribute('data-date');
        if (tf !== 'D'){
          tf = 'D'; setTfButtons('D');
          if (opt.onTf) opt.onTf('D'); else bars = RAW;
        }
        pickDate(d);
        SVG.focus({ preventScroll:true });
      });
    });

    intraday = !!opt.intraday;
    sel = RAW.length - 1;
    draw(); readout();
    return { setBars:setBars, pick:pick, pickDate:pickDate, setStatus:setStatus,
      tf:function(){ return tf; }, bars:function(){ return bars; },
      lastClose:function(){ return bars.length ? bars[bars.length-1][4] : null; } };
  }

  window.CandleLab = { create:create, sma:sma, rsi:rsi, bollinger:bollinger, weekly:weekly, fmtPrice:fmtPrice, fmtVol:fmtVol };
})();
