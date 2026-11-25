(function () {
  'use strict'; // ES5 di proposito: deve girare su Safari 12 (iOS 12)

  var token = (/[?&]t=([^&]+)/.exec(location.search) || [])[1] || '';
  var cfgVersion = null, cfg = null, fails = 0, deckSig = '';

  function $(id) { return document.getElementById(id); }

  function api(method, path, body, cb) {
    var x = new XMLHttpRequest(), done = false;
    var url = path + (token ? (path.indexOf('?') > -1 ? '&' : '?') + 't=' + encodeURIComponent(token) : '');
    function end(err, data) { if (!done) { done = true; cb && cb(err, data); } }
    x.open(method, url, true);
    x.timeout = 4000;
    x.onload = function () {
      var d = null;
      try { d = JSON.parse(x.responseText); } catch (e) {}
      end(x.status >= 200 && x.status < 300 ? null : (d && d.error) || 'errore ' + x.status, d);
    };
    x.onerror = x.ontimeout = function () { end('rete'); };
    if (body) { x.setRequestHeader('Content-Type', 'application/json'); x.send(JSON.stringify(body)); }
    else { x.send(); }
  }

  /* ---- orologio ---- */
  var DAYS = ['domenica', 'lunedì', 'martedì', 'mercoledì', 'giovedì', 'venerdì', 'sabato'];
  var MONTHS = ['gennaio', 'febbraio', 'marzo', 'aprile', 'maggio', 'giugno', 'luglio', 'agosto', 'settembre', 'ottobre', 'novembre', 'dicembre'];
  function pad(n) { return n < 10 ? '0' + n : '' + n; }
  function tick() {
    var d = new Date();
    $('hm').textContent = pad(d.getHours()) + ':' + pad(d.getMinutes());
    $('ss').textContent = pad(d.getSeconds());
    $('date').textContent = DAYS[d.getDay()] + ' ' + d.getDate() + ' ' + MONTHS[d.getMonth()];
  }
  setInterval(tick, 1000); tick();

  /* ---- luminosita': tocca l'orologio per attenuare lo schermo ---- */
  var LEVELS = [0, 0.4, 0.7], level = 0;
  try { level = parseInt(localStorage.getItem('dim'), 10) || 0; } catch (e) {}
  function applyDim() { $('dim').style.opacity = LEVELS[level]; }
  $('clockcard').addEventListener('click', function () {
    level = (level + 1) % LEVELS.length; applyDim();
    try { localStorage.setItem('dim', level); } catch (e) {}
  });
  applyDim();

  /* ---- stato ---- */
  function setBar(barId, valId, pct) {
    var b = $(barId);
    b.style.width = pct + '%';
    b.className = pct >= 85 ? 'hot' : '';
    $(valId).textContent = pct + '%';
  }
  function render(s) {
    setBar('cpubar', 'cpuval', s.stats.cpu);
    setBar('rambar', 'ramval', s.stats.ram);
    var sp = s.spotify, song, artist;
    if (!sp.running) { song = 'Spotify non aperto'; artist = 'Apri Spotify sul PC'; }
    else if (!sp.playing) { song = 'In pausa'; artist = 'Spotify'; }
    else { song = sp.title; artist = sp.artist || ' '; }
    $('song').textContent = song;
    $('artist').textContent = artist;
    $('music').className = 'card' + (sp.playing ? '' : ' idle');
    $('ppbtn').innerHTML = sp.playing ? '&#9208;' : '&#9654;&#65039;';
  }
  function poll() {
    api('GET', '/api/state', null, function (err, s) {
      if (err || !s) {
        fails++;
        if (fails >= 3) { $('offline').className = 'show'; }
      } else {
        fails = 0; $('offline').className = '';
        render(s);
        if (s.version !== cfgVersion) { loadConfig(); }
      }
      setTimeout(poll, err ? 3000 : 1500);
    });
  }

  /* ---- pulsanti ---- */
  function flash(el, cls) { el.className += ' ' + cls; setTimeout(function () { el.className = el.className.replace(' ' + cls, ''); }, 600); }
  function press(el, id) {
    api('POST', '/api/press', { id: id }, function (err) { flash(el, err ? 'err' : 'ok'); });
  }
  function layoutDeck() {
    if (!cfg) { return; }
    var portrait = window.innerHeight > window.innerWidth;
    var cols = (portrait ? cfg.columnsPortrait : cfg.columns) || 4;
    var n = cfg.buttons.length, rows = Math.max(1, Math.ceil(n / cols));
    var deck = $('deck');
    deck.style.gridTemplateColumns = 'repeat(' + cols + ', 1fr)';
    deck.style.gridTemplateRows = 'repeat(' + rows + ', 1fr)';
  }
  function buildDeck() {
    var deck = $('deck');
    deck.innerHTML = '';
    cfg.buttons.forEach(function (b) {
      var el = document.createElement('button');
      el.className = 'key';
      if (b.color) { el.style.backgroundColor = b.color; }
      var ic = document.createElement('div'); ic.className = 'ic'; ic.textContent = b.icon || '';
      var lb = document.createElement('div'); lb.className = 'lb'; lb.textContent = b.label || '';
      el.appendChild(ic); el.appendChild(lb);
      el.addEventListener('click', function () { press(el, b.id); });
      deck.appendChild(el);
    });
    layoutDeck();
  }
  function loadConfig() {
    api('GET', '/api/config', null, function (err, c) {
      if (err || !c) { return; }
      cfg = c; cfgVersion = c.version; buildDeck();
    });
  }
  window.addEventListener('resize', layoutDeck);
  window.addEventListener('orientationchange', function () { setTimeout(layoutDeck, 200); });

  /* ---- controlli musica ---- */
  var ctls = document.querySelectorAll('.ctl');
  Array.prototype.forEach.call(ctls, function (b) {
    b.addEventListener('click', function () { api('POST', '/api/media', { cmd: b.getAttribute('data-cmd') }); });
  });

  /* ---- niente scroll / zoom ---- */
  document.addEventListener('touchmove', function (e) { e.preventDefault(); }, { passive: false });
  document.addEventListener('gesturestart', function (e) { e.preventDefault(); });

  loadConfig();
  poll();
})();
