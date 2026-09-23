/* Lớp lấy dữ liệu thị trường sống, gọi thẳng từ trình duyệt — không có backend.
   Crypto: Binance public REST (CORS mở).
   Chứng khoán VN: dchart-api.vndirect.com.vn (CORS mở, chỉ có khung ngày trở lên).
   Mọi hàm trả về Promise của mảng nến [[time,o,h,l,c,v],...], thời gian là chuỗi giờ Việt Nam. */
(function(){
  'use strict';

  var CACHE_MS = 60 * 1000;
  var mem = {};

  function jget(url, ttl){
    var now = Date.now(), hit = mem[url];
    if (hit && now - hit.t < (ttl === undefined ? CACHE_MS : ttl)) return Promise.resolve(hit.v);
    var ctrl = typeof AbortController !== 'undefined' ? new AbortController() : null;
    var timer = ctrl ? setTimeout(function(){ ctrl.abort(); }, 12000) : null;
    return fetch(url, { cache:'no-store', signal: ctrl ? ctrl.signal : undefined })
      .then(function(r){
        if (timer) clearTimeout(timer);
        if (!r.ok) throw new Error('HTTP ' + r.status);
        return r.json();
      })
      .then(function(v){ mem[url] = { t:now, v:v }; return v; });
  }

  /* ---------- thời gian ---------- */
  function pad(n){ return n < 10 ? '0' + n : '' + n; }
  /* mốc mili giây UTC → chuỗi giờ Việt Nam (UTC+7) */
  function vnStamp(ms, withTime){
    var d = new Date(ms + 7 * 3600 * 1000);
    var s = d.getUTCFullYear() + '-' + pad(d.getUTCMonth()+1) + '-' + pad(d.getUTCDate());
    return withTime ? s + 'T' + pad(d.getUTCHours()) + ':' + pad(d.getUTCMinutes()) : s;
  }

  /* ---------- crypto: Binance ---------- */
  var BINANCE = ['https://api.binance.com', 'https://data-api.binance.vision'];

  function binance(path, query){
    var qs = [];
    for (var k in query) if (query[k] !== undefined && query[k] !== null) qs.push(k + '=' + encodeURIComponent(query[k]));
    var tail = path + (qs.length ? '?' + qs.join('&') : '');
    return jget(BINANCE[0] + tail).catch(function(){ return jget(BINANCE[1] + tail); });
  }

  /* interval của Binance: 15m, 1h, 4h, 1d, 1w */
  function cryptoKlines(symbol, interval, limit){
    var intraday = /m$|h$/.test(interval);
    return binance('/api/v3/klines', { symbol:symbol, interval:interval, limit:limit || 150 })
      .then(function(rows){
        return rows.map(function(r){
          return [vnStamp(r[0], intraday), +r[1], +r[2], +r[3], +r[4], Math.round(+r[5] * 100) / 100];
        });
      });
  }

  /* giá + biến động 24h của nhiều mã một lần */
  function cryptoTickers(symbols){
    return binance('/api/v3/ticker/24hr', { symbols: JSON.stringify(symbols) })
      .then(function(rows){
        var out = {};
        (Array.isArray(rows) ? rows : [rows]).forEach(function(r){
          out[r.symbol] = {
            price: +r.lastPrice,
            changePct: +r.priceChangePercent,
            high: +r.highPrice,
            low: +r.lowPrice,
            open: +r.openPrice,
            quoteVolume: +r.quoteVolume
          };
        });
        return out;
      });
  }

  /* funding rate hợp đồng vĩnh cửu — thước đo đám đông đang nghiêng về bên nào */
  function cryptoFunding(symbol){
    return jget('https://fapi.binance.com/fapi/v1/premiumIndex?symbol=' + encodeURIComponent(symbol))
      .then(function(d){
        return {
          markPrice: +d.markPrice,
          rate: +d.lastFundingRate,
          nextTime: +d.nextFundingTime
        };
      });
  }

  /* ---------- chứng khoán VN: VNDirect dchart ---------- */
  /* Chỉ số không phải giá cổ phiếu: dchart trả đúng điểm số, không quy đổi nghìn đồng. */
  var VN_INDEX = /^(VNINDEX|VN30|VN100|VNXALL|VNALL|HNX|HNXINDEX|HNX30|UPCOM|UPCOMINDEX)$/;
  function isVnIndex(sym){ return VN_INDEX.test(String(sym || '').toUpperCase()); }

  function vnHistory(symbol, fromSec, toSec){
    var url = 'https://dchart-api.vndirect.com.vn/dchart/history?resolution=D&symbol=' +
      encodeURIComponent(symbol) + '&from=' + fromSec + '&to=' + toSec;
    return jget(url).then(function(d){
      if (!d || d.s === 'no_data' || !d.t || !d.t.length) throw new Error('Không có dữ liệu cho ' + symbol);
      var out = [], idx = isVnIndex(symbol);
      // cổ phiếu: dchart trả giá theo nghìn đồng, quy về đồng cho khớp cách đọc bảng điện
      var conv = idx ? function(x){ return Math.round(x * 100) / 100; }
                     : function(x){ return Math.round(x * 1000); };
      for (var i=0;i<d.t.length;i++){
        out.push([vnStamp(d.t[i] * 1000, false),
          conv(d.o[i]), conv(d.h[i]), conv(d.l[i]), conv(d.c[i]), +d.v[i] || 0]);
      }
      return out;
    });
  }

  function vnStock(symbol, days){
    var to = Math.floor(Date.now()/1000) + 86400;
    var from = to - (days || 200) * 86400;
    return vnHistory(symbol.toUpperCase(), from, to);
  }

  /* giá mới nhất của nhiều mã (dùng chính history, cache 60s) */
  function vnQuotes(symbols){
    var to = Math.floor(Date.now()/1000) + 86400, from = to - 20 * 86400;
    return Promise.all(symbols.map(function(s){
      return vnHistory(s.toUpperCase(), from, to)
        .then(function(rows){
          var n = rows.length, last = rows[n-1], prev = n > 1 ? rows[n-2] : last;
          return { symbol:s.toUpperCase(), price:last[4], prevClose:prev[4],
            changePct: prev[4] ? (last[4]-prev[4])/prev[4]*100 : 0,
            high:last[2], low:last[3], volume:last[5], date:last[0] };
        })
        .catch(function(){ return { symbol:s.toUpperCase(), error:true }; });
    }));
  }

  window.Market = {
    cryptoKlines: cryptoKlines,
    cryptoTickers: cryptoTickers,
    cryptoFunding: cryptoFunding,
    vnStock: vnStock,
    vnQuotes: vnQuotes,
    isVnIndex: isVnIndex,
    vnStamp: vnStamp
  };
})();
