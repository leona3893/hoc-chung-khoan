/* Dùng chung cho mọi trang: tiến độ học, hiệu ứng hình, scrollspy mục lục. */
(function(){
  'use strict';
  var boxes = document.querySelectorAll('.mark input[data-level]');
  var links = document.querySelectorAll('#toc a');
  var KEY = 'ck-tien-do';

  function load(){
    try { return JSON.parse(localStorage.getItem(KEY) || '{}') || {}; }
    catch(e){ return {}; }
  }
  function save(state){
    try { localStorage.setItem(KEY, JSON.stringify(state)); } catch(e){}
  }
  function paint(state){
    links.forEach(function(a){
      var href = a.getAttribute('href') || '';
      var id = href.charAt(0) === '#' ? href.slice(1) : '';
      if (id) a.classList.toggle('done', !!state[id]);
    });
  }

  var state = load();
  boxes.forEach(function(box){
    var id = box.getAttribute('data-level');
    box.checked = !!state[id];
    box.addEventListener('change', function(){
      state[id] = box.checked;
      if (!box.checked) { delete state[id]; }
      save(state);
      paint(state);
    });
  });
  paint(state);

  var figs = Array.prototype.slice.call(document.querySelectorAll('.fig'));
  var reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  if (figs.length && !reduce && 'IntersectionObserver' in window) {
    figs.forEach(function(f){ f.classList.add('anim'); });
    var io = new IntersectionObserver(function(entries){
      entries.forEach(function(e){
        if (e.isIntersecting) { e.target.classList.add('in'); io.unobserve(e.target); }
      });
    }, { rootMargin: '0px 0px -12% 0px', threshold: 0.18 });
    figs.forEach(function(f){ io.observe(f); });
  }

  var sections = Array.prototype.slice.call(document.querySelectorAll('section[id]'));
  function spy(){
    var best = null, bestTop = -Infinity;
    var mark = window.scrollY + window.innerHeight * 0.3;
    sections.forEach(function(s){
      var top = s.offsetTop;
      if (top <= mark && top > bestTop) { bestTop = top; best = s.id; }
    });
    if (best === null && sections.length) best = sections[0].id;
    links.forEach(function(a){
      a.classList.toggle('on', a.getAttribute('href') === '#' + best);
    });
  }
  if (sections.length && links.length){
    var ticking = false;
    window.addEventListener('scroll', function(){
      if (ticking) return;
      ticking = true;
      requestAnimationFrame(function(){ spy(); ticking = false; });
    }, { passive: true });
    spy();
  }
})();
