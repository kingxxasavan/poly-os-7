// PolyOS login and lock screen (LightDM greeter), after the PolyOS 7 Login design.

import { api, withToken } from '../api.js';
import { clockTicker, fill, fmtDate, fmtTime, h, icon, networkIcon } from '../ui.js';

const IDLE_AFTER = 60000;

export function mount(root, store) {
  root.className = 'greeter';
  const wall = h('div.gr-wall', { style: { backgroundImage: `url("${withToken(`/wallpaper/current?v=${encodeURIComponent(store.state.settings.wallpaper)}`)}")` } });
  const time = h('div.gr-time');
  const date = h('div.gr-date');
  const hint = h('div.gr-hint');
  const idle = h('section.gr-idle', time, date, hint);
  const card = h('section.gr-card', { role: 'dialog', 'aria-label': 'Sign in' });
  const status = h('div.gr-status');
  const bottom = h('div.gr-bottom');
  root.append(wall, h('div.gr-shade'), status, idle, card, bottom);

  let info = null;
  let user = null;
  let session = null;
  let mode = 'idle';
  let busy = false;
  let idleTimer = 0;
  let showHelp = false;
  let error = null;

  const displayName = (u) => (u ? u.displayName || u.name : '');
  const initials = (u) => displayName(u).split(/\s+/).map((p) => p[0]).join('').slice(0, 2).toUpperCase() || '?';

  function renderStatus() {
    const { battery, network } = store.state.system;
    fill(status,
      info?.hostname ? h('span.gr-host', info.hostname) : null,
      h('span.gr-ico', networkIcon(network)),
      battery.present ? h('span.gr-bat', icon('battery', battery.level, battery.charging), `${battery.level}%`) : null,
    );
  }

  function renderBottom() {
    const items = [];
    if (info && !info.lock && info.sessions.length > 1) {
      const select = h('select.gr-session', { 'aria-label': 'Desktop session' },
        info.sessions.map((s) => h('option', { value: s.key, selected: s.key === session }, s.name)));
      select.addEventListener('change', () => { session = select.value; });
      items.push(h('label.gr-session-wrap', icon('monitor'), select));
    } else {
      items.push(h('span'));
    }
    const powerBtn = (action, ico, label) => (info?.can[action]
      ? h('button.gr-round', { title: label, 'aria-label': label, onclick: (e) => { e.stopPropagation(); doPower(action); } }, icon(ico))
      : null);
    items.push(h('div.gr-power', powerBtn('suspend', 'moon', 'Sleep'), powerBtn('restart', 'restart', 'Restart'),
      powerBtn('shutdown', 'power', 'Shut down')));
    fill(bottom, ...items);
  }

  function renderCard() {
    const others = info && !info.lock && !info.hideUsers ? info.users : [];
    const input = h('input.gr-input', {
      type: 'password', placeholder: 'Password', autocomplete: 'current-password', 'aria-label': 'Password', disabled: busy,
    });
    const next = h('button.gr-next', { disabled: busy }, busy ? h('span.gr-spinner') : 'Next');
    const submit = () => login(input.value);
    input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') submit();
      if (e.key === 'Escape') setMode('idle');
    });
    next.addEventListener('click', submit);
    fill(card,
      others.length > 1
        ? h('div.gr-users', others.map((u) => h('button.gr-user', {
          class: u.name === user?.name ? 'on' : '',
          onclick: () => { user = u; error = null; renderCard(); },
        }, h('span.gr-avatar.small', initials(u)), h('span', displayName(u)))))
        : null,
      h('div.gr-avatar', initials(user)),
      h('h1', info?.lock ? 'Unlock' : 'Log In'),
      h('p.gr-sub', info?.lock
        ? `${displayName(user)}, enter your password to unlock the desktop.`
        : `Please enter the password for ${displayName(user) || 'your account'} to log in to the desktop.`),
      error
        ? h('div.gr-error', { role: 'alert' }, h('b', 'Incorrect Password'), h('span', error))
        : null,
      h('div.gr-field', input, next),
      h('button.gr-forgot', { onclick: () => { showHelp = !showHelp; renderCard(); } }, 'Forgot Password'),
      showHelp
        ? h('p.gr-help', 'Ask the computer’s administrator to reset it by running ',
          h('code', `sudo passwd ${user?.name || 'USERNAME'}`), ' in a terminal. On a single-user PC, boot into recovery mode to do it yourself.')
        : null,
    );
    if (mode === 'login') requestAnimationFrame(() => input.focus());
  }

  function setMode(next, firstKey) {
    mode = next;
    root.classList.toggle('login', mode === 'login');
    root.classList.toggle('welcome', mode === 'welcome');
    if (mode === 'login') {
      error = null;
      renderCard();
      if (firstKey) requestAnimationFrame(() => { const i = card.querySelector('input'); if (i) i.value = firstKey; });
    }
    if (mode === 'welcome') {
      card.replaceChildren(h('img.gr-welcome-logo', { src: '/img/logo-white.svg', alt: '' }),
        h('h1', info?.lock ? 'Unlocking…' : `Welcome, ${displayName(user).split(' ')[0]}`));
    }
    poke();
  }

  async function login(password) {
    if (busy || !user) return;
    busy = true;
    error = null;
    renderCard();
    try {
      await api.post('/api/greeter/login', { user: user.name, password, session: info?.lock ? null : session });
      busy = false;
      setMode('welcome'); // LightDM closes this screen once the desktop starts
    } catch (err) {
      busy = false;
      error = err.message;
      renderCard();
    }
  }

  async function doPower(action) {
    try {
      await api.post('/api/greeter/power', { action });
    } catch (err) {
      setMode('login'); // (clears old errors, so set this one after)
      error = err.message;
      renderCard();
    }
  }

  function poke() {
    clearTimeout(idleTimer);
    if (mode === 'login' && !busy) idleTimer = setTimeout(() => setMode('idle'), IDLE_AFTER);
  }

  root.addEventListener('pointerdown', (e) => {
    if (mode === 'idle' && !e.target.closest('.gr-bottom')) setMode('login');
    poke();
  });
  document.addEventListener('keydown', (e) => {
    poke();
    if (mode !== 'idle') return;
    const printable = e.key.length === 1 && !e.ctrlKey && !e.altKey && !e.metaKey;
    setMode('login', printable ? e.key : '');
    if (printable) e.preventDefault();
  });

  clockTicker((now) => {
    time.textContent = fmtTime(now, store.state.settings, false);
    date.textContent = fmtDate(now);
  }, () => false);
  store.subscribe((_s, changed) => { if (changed.has('system')) renderStatus(); });

  api.get('/api/greeter/state').then((state) => {
    info = state;
    user = state.users.find((u) => u.name === state.selectedUser) || state.users[0] || null;
    session = state.defaultSession;
    hint.textContent = state.lock ? 'Click or press any key to unlock' : 'Click to Enter Password';
    root.classList.toggle('locked', state.lock);
    renderStatus();
    renderBottom();
    renderCard();
  }, (err) => {
    hint.textContent = err.message;
  });
  renderStatus();
}
