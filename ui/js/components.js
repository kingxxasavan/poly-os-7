// Reusable controls: switch, slider, settings rows and the Wi-Fi network list.

import { api } from './api.js';
import { h, icon, throttle, wifiLevel } from './ui.js';

export function toggle(checked, onChange, label = '') {
  const el = h('button.switch', { role: 'switch', 'aria-checked': String(!!checked), 'aria-label': label });
  el.addEventListener('click', () => {
    const next = el.getAttribute('aria-checked') !== 'true';
    el.setAttribute('aria-checked', String(next));
    onChange(next);
  });
  return Object.assign(el, { set: (v) => el.setAttribute('aria-checked', String(!!v)) });
}

let dragging = null;
window.addEventListener('pointerup', () => { dragging = null; });

// Range input that ignores external updates while the user is dragging it.
export function slider({ value = 0, min = 0, max = 100, label = '', onInput }) {
  const input = h('input.range', { type: 'range', min, max, value, 'aria-label': label });
  const paint = () => input.style.setProperty('--pct', `${((input.value - min) * 100) / (max - min)}%`);
  const send = throttle((v) => onInput(v), 80);
  input.addEventListener('pointerdown', () => { dragging = input; });
  input.addEventListener('input', () => { paint(); send(Number(input.value)); });
  paint();
  return Object.assign(input, {
    set(v) {
      if (dragging === input) return;
      input.value = v;
      paint();
    },
  });
}

// PolyOS 7 control-center slider: a rounded bar whose light fill is the value, icon inside.
export function fillSlider({ value = 0, min = 0, max = 100, label = '', icon: iconFn, onInput, onIcon }) {
  const fill = h('span.fs-fill');
  const ico = h('span.fs-ico', { title: onIcon ? `Mute ${label.toLowerCase()}` : null });
  const el = h('div.fill-slider', { role: 'slider', tabindex: '0', 'aria-label': label, 'aria-valuemin': min, 'aria-valuemax': max },
    fill, ico);
  let current = value;
  let dragging = false;
  const send = throttle((v) => onInput(v), 80);
  const paint = () => {
    fill.style.width = `${((current - min) * 100) / (max - min)}%`;
    el.setAttribute('aria-valuenow', String(current));
  };
  const setFrom = (clientX) => {
    const r = el.getBoundingClientRect();
    const v = Math.round(min + (max - min) * Math.min(1, Math.max(0, (clientX - r.left) / r.width)));
    if (v !== current) {
      current = v;
      paint();
      send(v);
    }
  };
  el.addEventListener('pointerdown', (e) => {
    if (onIcon && ico.contains(e.target)) {
      onIcon();
      return;
    }
    dragging = true;
    el.setPointerCapture(e.pointerId);
    setFrom(e.clientX);
  });
  el.addEventListener('pointermove', (e) => { if (dragging) setFrom(e.clientX); });
  el.addEventListener('pointerup', () => { dragging = false; });
  el.addEventListener('pointercancel', () => { dragging = false; });
  el.addEventListener('keydown', (e) => {
    const step = { ArrowRight: 5, ArrowUp: 5, ArrowLeft: -5, ArrowDown: -5 }[e.key];
    if (!step) return;
    e.preventDefault();
    current = Math.min(max, Math.max(min, current + step));
    paint();
    send(current);
  });
  el.set = (v) => {
    if (dragging) return;
    current = v;
    paint();
  };
  el.refreshIcon = () => ico.replaceChildren(iconFn());
  el.refreshIcon();
  paint();
  return el;
}

export function group(title, ...rows) {
  return h('section.group-wrap', title ? h('h2.group-title', title) : null, h('div.group', ...rows));
}

export function row(label, sub, ...controls) {
  return h('div.row', h('div.row-label', h('span', label), sub ? h('small', sub) : null), ...controls);
}

export function errorText(el, message) {
  el.textContent = message || '';
  el.hidden = !message;
}

// ---- Wi-Fi --------------------------------------------------------------------
export function wifiPanel(store, { compact = false } = {}) {
  const el = h('div.wifi');
  let networks = null;
  let loading = false;
  let loadError = null;
  let expanded = null;
  let password = '';
  let busy = null;
  let failure = null;
  let signature = '';

  const status = () => store.state.system.network;

  async function load() {
    const net = status();
    if (!net.available || !net.wifiDevice || !net.wifiEnabled) {
      networks = [];
      render();
      return;
    }
    loading = true;
    render();
    try {
      const res = await api.get('/api/wifi');
      networks = res.networks;
      loadError = null;
    } catch (err) {
      loadError = err.message;
    }
    loading = false;
    render();
  }

  async function connect(ssid, pass) {
    busy = ssid;
    failure = null;
    render();
    try {
      await api.post('/api/wifi/connect', { ssid, password: pass || null });
      expanded = null;
      password = '';
      busy = null;
      await load();
    } catch (err) {
      failure = { ssid, text: err.message };
      busy = null;
      render();
    }
  }

  async function forget(ssid) {
    try {
      await api.post('/api/wifi/forget', { ssid });
    } catch (err) {
      failure = { ssid, text: err.message };
    }
    await load();
  }

  function networkRow(n) {
    const isBusy = busy === n.ssid;
    const meta = n.active ? 'Connected' : isBusy ? 'Connecting…' : n.known ? 'Saved' : n.secure ? 'Secured' : 'Open';
    const main = h(
      'button.net-row',
      { class: n.active ? 'active' : '', disabled: isBusy || !!busy },
      h('span.net-signal', icon('wifi', wifiLevel(n.signal))),
      h('span.net-text', h('span.net-name', n.ssid), h('span.net-meta', meta)),
      n.secure ? h('span.net-lock', icon('lock')) : null,
    );
    main.addEventListener('click', () => {
      if (n.active) return;
      if (!n.secure || n.known) connect(n.ssid);
      else {
        expanded = expanded === n.ssid ? null : n.ssid;
        password = '';
        failure = null;
        render();
      }
    });
    const item = h('div.net', main);
    if (n.known && !compact && !isBusy) {
      item.append(h('button.net-forget', { title: `Forget ${n.ssid}`, onclick: () => forget(n.ssid) }, 'Forget'));
    }
    if (expanded === n.ssid) {
      const input = h('input.input', { type: 'password', placeholder: 'Password', value: password, autocomplete: 'off' });
      input.addEventListener('input', () => { password = input.value; });
      const go = () => connect(n.ssid, input.value);
      input.addEventListener('keydown', (e) => { if (e.key === 'Enter') go(); });
      item.append(
        h('div.net-pass', input, h('button.btn.primary', { onclick: go, disabled: isBusy }, isBusy ? 'Connecting…' : 'Connect')),
      );
      setTimeout(() => input.focus(), 0);
    }
    if (failure && failure.ssid === n.ssid) item.append(h('div.error-text', failure.text));
    return item;
  }

  function render() {
    const net = status();
    signature = JSON.stringify([net.available, net.wifiDevice, net.wifiEnabled, net.name]);
    el.replaceChildren();
    if (!net.available) {
      el.append(h('p.muted.pad', 'NetworkManager is not running.'));
      return;
    }
    if (!net.wifiDevice) {
      el.append(h('p.muted.pad', 'No Wi-Fi adapter found.'));
      return;
    }
    if (!net.wifiEnabled) {
      el.append(h('p.muted.pad', 'Wi-Fi is turned off.'));
      return;
    }
    const refresh = h('button.icon-btn', { title: 'Scan again', class: loading ? 'spinning' : '', onclick: load }, icon('refresh'));
    el.append(h('div.wifi-head', h('span', 'Available networks'), refresh));
    if (loadError) el.append(h('div.error-text.pad', loadError));
    if (networks === null || (loading && !networks.length)) {
      el.append(h('p.muted.pad', 'Scanning…'));
      return;
    }
    if (!networks.length) {
      el.append(h('p.muted.pad', 'No networks found.'));
      return;
    }
    el.append(h('div.net-list', networks.map(networkRow)));
  }

  load();
  return {
    el,
    refresh: load,
    update() {
      const net = status();
      const next = JSON.stringify([net.available, net.wifiDevice, net.wifiEnabled, net.name]);
      if (next !== signature) load();
    },
  };
}
