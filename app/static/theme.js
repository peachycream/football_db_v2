/* ===========================================================================
   theme.js — runtime bridge from theme.css to the JS charting libraries.

   Chart.js, Plotly and html2canvas cannot resolve a CSS var(), so they need
   real colour strings. Rather than duplicate the palette here (which would
   immediately become a second source of truth and drift), this reads the
   LIVE custom properties off :root. theme.css stays the only place a colour
   is defined.

   NEVER hard-code a hex in this file.

     TOKENS.get('wr')        -> "#22d3ee"
     TOKENS.rgba('wr', .16)  -> "rgba(34,211,238,0.16)"   (a hex works too)
     TOKENS.pos('CB')        -> the DB-group hue
     TOKENS.refresh()        -> drop the cache (after a theme swap)
   =========================================================================== */
(function () {
  'use strict';

  var cache = {};

  function read(name) {
    try {
      return getComputedStyle(document.documentElement)
               .getPropertyValue('--' + name).trim();
    } catch (e) { return ''; }
  }

  // theme.css stores every colour as CHANNELS ("0 229 160") with the colour
  // itself derived, so Tailwind's /alpha modifiers work off the same
  // definition. Read the channels here too: it gives exact alpha, and the
  // comma form below is what Chart.js and Plotly accept most reliably.
  function channels(name) {
    var raw = read(name + '-rgb');
    if (raw) {
      var p = raw.split(/[\s,]+/).filter(Boolean).map(Number);
      if (p.length === 3 && p.every(function (n) { return !isNaN(n); })) return p;
    }
    return toRgb(read(name));
  }

  // Lazy, and an empty read is never cached: if this runs before the
  // stylesheet has applied, a later call still gets the real value.
  function get(name, fallback) {
    if (cache[name]) return cache[name];
    var c = channels(name);
    if (!c) return fallback || '#808080';
    var v = 'rgb(' + c[0] + ', ' + c[1] + ', ' + c[2] + ')';
    cache[name] = v;
    return v;
  }

  function toRgb(color) {
    if (!color) return null;
    var m = color.match(/rgba?\(([^)]+)\)/);
    if (m) {
      var p = m[1].split(/[\s,\/]+/).filter(Boolean).map(Number);
      if (p.length >= 3 && p.slice(0, 3).every(function (n) { return !isNaN(n); }))
        return p.slice(0, 3);
      return null;
    }
    if (color.charAt(0) !== '#') return null;
    var h = color.slice(1);
    if (h.length === 3) h = h[0] + h[0] + h[1] + h[1] + h[2] + h[2];
    if (h.length !== 6) return null;
    var n = parseInt(h, 16);
    if (isNaN(n)) return null;
    return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
  }

  // Accepts a token name ('wr') or an already-resolved colour string, so it
  // can also replace hex-alpha concatenation like clr + '28'.
  function rgba(nameOrHex, alpha) {
    var s = String(nameOrHex || '');
    var c = (s.charAt(0) === '#' || s.indexOf('rgb') === 0) ? toRgb(s) : channels(s);
    return c ? 'rgba(' + c[0] + ', ' + c[1] + ', ' + c[2] + ', ' + alpha + ')'
             : get(nameOrHex);
  }

  // Finer position codes fold onto their group hue; DT and S have their own
  // lighter shades so a stacked bar keeps every segment tellable apart.
  var POS = {
    QB: 'qb', RB: 'rb', WR: 'wr', TE: 'te',
    DL: 'dl', DE: 'dl', DT: 'dt',
    LB: 'lb',
    DB: 'db', CB: 'db', S: 's', SAF: 's'
  };

  function pos(code, fallback) {
    var k = POS[String(code || '').toUpperCase()];
    return k ? get(k) : (fallback || get('tx-mut'));
  }

  window.TOKENS = {
    get: get,
    rgba: rgba,
    pos: pos,
    refresh: function () { cache = {}; }
  };
})();
