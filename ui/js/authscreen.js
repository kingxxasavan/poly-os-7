// Shared by the login screen (LightDM greeter) and the lock screen, after the PolyOS 7 Login
// design: clock over the wallpaper, then a card with your name, "Enter your password", and a
// real "Forgot password" that resets it with the recovery key saved during setup.

import { withToken } from './api.js';
import { clockTicker, fill, fmtDate, fmtTime, h, icon, networkIcon } from './ui.js';

const IDLE_AFTER = 60000;

// adapter: { kind: 'login' | 'lock', load() -> info, signIn(user, password, session),
//            recover(user, key, password), power(action), onSignedIn() }
export function mountAuth(root, store, adapter) {
  root.className = `greeter ${adapter.kind}`;
  const wall = h('div.gr-wall', { style: { backgroundImage: `url("${withToken(`/wallpaper/current?v=${encodeURIComponent(store.state.settings.wallpaper)}`)}")` } });
  const time = h('div.gr-time');
  const date = h('div.gr-date');
  const hint = h('div.gr-hint');
  const idle = h('section.gr-idle', time, date, hint);
  const card = h('section.gr-card', { role: 'dialog', 'aria-label': adapter.kind === 'lock' ? 'Unlock' : 'Sign in' });
  const status = h('div.gr-status');
  const bottom = h('div.gr-bottom');
  root.append(wall, h('div.gr-shade'), status, idle, card, bottom);

  let info = null;
  let user = null;
  let typedUser = '';
  let session = null;
  let mode = 'idle';
  let view = 'password'; // or 'recover'
  let busy = false;
  let idleTimer = 0;
  let error = null;
  let notice = null;

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
    if (adapter.kind === 'login' && info && info.sessions.length > 1) {
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

  const who = () => (user ? user.name : typedUser.trim());

  function passwordView() {
    const others = adapter.kind === 'login' && info ? info.users : [];
    const nameInput = !user ? h('input.gr-input.gr-name-input', { placeholder: 'Username', autocomplete: 'username', value: typedUser, 'aria-label': 'Username' }) : null;
    nameInput?.addEventListener('input', () => { typedUser = nameInput.value; });
    const input = h('input.gr-input', { type: 'password', placeholder: 'Password', autocomplete: 'current-password', 'aria-label': 'Password', disabled: busy });
    const next = h('button.gr-next', { disabled: busy, 'aria-label': 'Sign in' }, busy ? h('span.gr-spinner') : icon('arrowRight'));
    const submit = () => signIn(input.value);
    input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') submit();
      if (e.key === 'Escape') setMode('idle');
    });
    next.addEventListener('click', submit);
    const title = user ? displayName(user) : adapter.kind === 'lock' ? 'Locked' : 'Sign in';
    const parts = [
      others.length > 1
        ? h('div.gr-users', others.map((u) => h('button.gr-user', {
          class: u.name === user?.name ? 'on' : '',
          onclick: () => { user = u; error = null; notice = null; renderCard(); },
        }, h('span.gr-avatar.small', initials(u)), h('span', displayName(u)))))
        : null,
      h('div.gr-avatar', user ? initials(user) : icon('user')),
      h('h1.gr-name', title),
      h('p.gr-prompt', 'Enter your password'),
      notice ? h('div.gr-notice', { role: 'status' }, icon('check'), h('span', notice)) : null,
      error ? h('div.gr-error', { role: 'alert' }, h('b', 'Incorrect password'), h('span', error)) : null,
      nameInput,
      h('div.gr-field', input, next),
      h('button.gr-forgot', { onclick: () => { view = 'recover'; error = null; renderCard(); } }, 'Forgot password?'),
    ];
    return { parts, focus: nameInput || input };
  }

  function recoverView() {
    const key = h('input.gr-input.gr-key', { placeholder: 'XXXXX-XXXXX-XXXXX-XXXXX-XXXXX', spellcheck: 'false', autocomplete: 'off', 'aria-label': 'Recovery key' });
    const pass = h('input.gr-input', { type: 'password', placeholder: 'New password', autocomplete: 'new-password', 'aria-label': 'New password' });
    const again = h('input.gr-input', { type: 'password', placeholder: 'Type it again', autocomplete: 'new-password', 'aria-label': 'Confirm new password' });
    const go = h('button.gr-wide', { disabled: busy }, busy ? h('span.gr-spinner') : 'Reset password');
    key.addEventListener('input', () => { key.value = key.value.toUpperCase(); });
    go.addEventListener('click', async () => {
      if (!who()) { error = 'Enter your username first.'; return renderCard(); }
      if (!pass.value) { error = 'Choose a new password.'; return renderCard(); }
      if (pass.value !== again.value) { error = 'The passwords don’t match.'; return renderCard(); }
      busy = true;
      error = null;
      renderCard();
      try {
        await adapter.recover(who(), key.value, pass.value);
        busy = false;
        view = 'password';
        notice = adapter.kind === 'lock' ? null : 'Your password was changed. Sign in with the new one.';
        if (adapter.kind === 'lock') return setMode('welcome');
        renderCard();
      } catch (err) {
        busy = false;
        error = err.message;
        renderCard();
      }
    });
    const parts = [
      h('div.gr-avatar', icon('lock')),
      h('h1.gr-name', 'Reset your password'),
      h('p.gr-sub', `Enter the recovery key you saved when ${displayName(user) || 'this account'}'s account was set up, then choose a new password.`),
      error ? h('div.gr-error', { role: 'alert' }, h('b', 'Couldn’t reset it'), h('span', error)) : null,
      key, pass, again, go,
      h('button.gr-forgot', { onclick: () => { view = 'password'; error = null; renderCard(); } }, 'Back to sign in'),
    ];
    return { parts, focus: key };
  }

  function renderCard() {
    const { parts, focus } = view === 'recover' ? recoverView() : passwordView();
    fill(card, ...parts);
    if (mode === 'login' && !busy) requestAnimationFrame(() => focus.focus());
  }

  function setMode(next, firstKey) {
    mode = next;
    root.classList.toggle('login', mode === 'login');
    root.classList.toggle('welcome', mode === 'welcome');
    if (mode === 'login') {
      error = null;
      renderCard();
      if (firstKey) requestAnimationFrame(() => { const i = card.querySelector('input[type=password]'); if (i) i.value = firstKey; });
    }
    if (mode === 'welcome') {
      card.replaceChildren(h('img.gr-welcome-logo', { src: '/img/logo-white.svg', alt: '' }),
        h('h1', `Welcome back, ${displayName(user).split(' ')[0] || 'friend'}`));
    }
    if (mode === 'idle') view = 'password';
    poke();
  }

  async function signIn(password) {
    if (busy || !who()) return;
    busy = true;
    error = null;
    notice = null;
    renderCard();
    try {
      await adapter.signIn(who(), password, session);
      busy = false;
      setMode('welcome');
      adapter.onSignedIn?.();
    } catch (err) {
      busy = false;
      error = err.message;
      renderCard();
    }
  }

  async function doPower(action) {
    try {
      await adapter.power(action);
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

  Promise.resolve(adapter.load()).then((state) => {
    info = state;
    user = state.users.find((u) => u.name === state.selectedUser) || (state.users.length === 1 ? state.users[0] : null)
      || state.users[0] || null;
    session = state.defaultSession;
    hint.textContent = adapter.kind === 'lock' ? 'Click or press any key to unlock' : 'Click or press any key to sign in';
    root.classList.toggle('locked', adapter.kind === 'lock');
    renderStatus();
    renderBottom();
    renderCard();
  }, (err) => {
    hint.textContent = err.message;
  });
  renderStatus();
  return { setMode };
}
