// Poly Account (account.html and link.html). Signs in against /api/… on this site; every change
// sends X-Poly: 1, which the API requires (other sites can't send it). Text goes in with
// textContent only, never as HTML.

const app = document.getElementById('app');
const START = document.body.dataset.start || 'dashboard';
let me = null;          // { user, devices, email } from /api/me
let countries = null;

// ---- small helpers ---------------------------------------------------------------------------
function h(tag, attrs, ...kids) {
  const [name, ...classes] = tag.split('.');
  const el = document.createElement(name || 'div');
  if (classes.length) el.className = classes.join(' ');
  if (attrs && (typeof attrs !== 'object' || attrs instanceof Node || Array.isArray(attrs))) { kids.unshift(attrs); attrs = null; }
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === undefined || v === null || v === false) continue;
    if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
    else if (k === 'class') el.className += ` ${v}`;
    else if (v === true) el.setAttribute(k, '');
    else el.setAttribute(k, v);
  }
  for (const kid of kids.flat(Infinity)) {
    if (kid === null || kid === undefined || kid === false) continue;
    el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
  return el;
}
const icon = (name) => {
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('class', 'ico');
  const use = document.createElementNS('http://www.w3.org/2000/svg', 'use');
  use.setAttribute('href', `#i-${name}`);
  svg.append(use);
  return svg;
};

async function api(method, path, body) {
  const res = await fetch(path, {
    method,
    headers: { 'Content-Type': 'application/json', 'X-Poly': '1' },
    body: body === undefined ? undefined : JSON.stringify(body),
    credentials: 'same-origin',
  });
  let data = {};
  try { data = await res.json(); } catch { /* empty */ }
  if (!res.ok) throw Object.assign(new Error(data.error || `Something went wrong (${res.status}).`), { status: res.status, data });
  return data;
}

const when = (iso) => {
  if (!iso) return 'never';
  const d = new Date(iso);
  const mins = Math.round((Date.now() - d.getTime()) / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins} minute${mins === 1 ? '' : 's'} ago`;
  if (mins < 60 * 24) return `${Math.round(mins / 60)} hour${Math.round(mins / 60) === 1 ? '' : 's'} ago`;
  return d.toLocaleDateString([], { year: 'numeric', month: 'short', day: 'numeric' });
};
const date = (iso) => (iso ? new Date(iso).toLocaleDateString([], { year: 'numeric', month: 'long', day: 'numeric' }) : '');
const gb = (bytes) => (bytes ? `${Math.round(bytes / 1e9)} GB` : '');

function field(label, input, hint, aside) {
  // aside: a link next to the label, like "Forgot password?"
  const head = aside ? h('span.af-label-row', h('span', label), aside) : h('span', label);
  return h('label.af-field', head, input, hint ? h('small', hint) : null);
}
// A password box with a show/hide button, like most sign-in pages.
function passwordInput(name, attrs = {}) {
  const box = input('password', name, attrs);
  const eye = h('button.af-eye', { type: 'button', 'aria-label': 'Show password', title: 'Show password' }, icon('eye'));
  eye.addEventListener('click', (e) => {
    e.preventDefault();
    const show = box.type === 'password';
    box.type = show ? 'text' : 'password';
    eye.setAttribute('aria-label', show ? 'Hide password' : 'Show password');
    eye.title = eye.getAttribute('aria-label');
    eye.classList.toggle('on', show);
    box.focus();
  });
  return h('span.af-pass', box, eye);
}
function input(type, name, attrs = {}) {
  return h('input.af-input', { type, name, ...attrs });
}
function errorBox() {
  const el = h('p.af-error', { role: 'alert', hidden: true });
  return Object.assign(el, { show(msg) { el.textContent = msg || ''; el.hidden = !msg; } });
}
function busy(button, fn) {
  return async (e) => {
    e?.preventDefault?.();
    if (button.disabled) return;
    const label = button.textContent;
    button.disabled = true;
    button.textContent = 'One moment…';
    try { await fn(); } finally { button.disabled = false; button.textContent = label; }
  };
}
function form(onSubmit, ...kids) {
  const f = h('form.af-form', { novalidate: true }, ...kids);
  f.addEventListener('submit', (e) => { e.preventDefault(); onSubmit(new FormData(f)); });
  return f;
}
const go = (hash) => { if (location.hash !== `#${hash}`) location.hash = hash; else route(); };

// ---- signed out: sign in, create, forgot, recover ----------------------------------------------
function authCard(title, sub, ...kids) {
  return h('section.auth-card',
    h('header.auth-head', h('span.auth-logo', h('img', { src: '/assets/logo-white.svg', alt: '', width: 30, height: 30 })),
      h('h1', title), sub ? h('p.auth-sub', sub) : null),
    ...kids);
}
const orLine = () => h('div.auth-or', h('span', 'or'));
const authFoot = (...kids) => h('p.auth-foot', ...kids);

function signIn(note) {
  const err = errorBox();
  const btn = h('button.btn.primary.wide', { type: 'submit' }, 'Sign in');
  const f = form(async (data) => {
    err.show('');
    await busy(btn, async () => {
      try {
        await api('POST', '/api/auth/login', { email: data.get('email'), password: data.get('password') });
        await loadMe();
        go(START === 'link' ? 'link' : 'dashboard');
      } catch (x) { err.show(x.message); }
    })();
  },
  field('Email', input('email', 'email', { autocomplete: 'email', required: true, autofocus: true, placeholder: 'you@example.com' })),
  field('Password', passwordInput('password', { autocomplete: 'current-password', required: true, placeholder: 'Your password' }), null,
    h('a.af-aside', { href: '#forgot' }, 'Forgot password?')),
  err, btn);
  return authCard('Sign in', note || 'to your Poly Account', f,
    orLine(),
    h('a.btn.wide', { href: '#recover' }, icon('key'), 'Sign in with a recovery key'),
    authFoot('New to Poly? ', h('a', { href: '#create' }, 'Create an account')),
    h('p.auth-note', 'PolyOS never needs an account. It works fully offline and updates without one.'));
}

async function createAccount() {
  countries = countries || (await api('GET', '/api/countries').catch(() => ({ countries: ['United States', 'Other'] }))).countries;
  const err = errorBox();
  const btn = h('button.btn.primary.wide', { type: 'submit' }, 'Create account');
  const guess = Intl.DateTimeFormat().resolvedOptions().timeZone?.startsWith('America/') ? 'United States' : '';
  const country = h('select.af-input', { name: 'country', required: true },
    h('option', { value: '' }, 'Choose…'), countries.map((c) => h('option', { value: c, selected: c === guess }, c)));
  const f = form(async (data) => {
    err.show('');
    if (data.get('password') !== data.get('confirm')) return err.show('The passwords don’t match.');
    if (!data.get('terms') || !data.get('privacy')) return err.show('Agree to the Terms of Service and acknowledge the Privacy Policy to continue.');
    await busy(btn, async () => {
      try {
        const r = await api('POST', '/api/auth/register', {
          name: data.get('name'), email: data.get('email'), password: data.get('password'), country: data.get('country'), acceptTerms: true,
        });
        await loadMe();
        showRecoveryKey(r.recoveryKey, START === 'link' ? 'link' : 'dashboard', r.emailSent
          ? `We sent a link to ${r.user.email}. Open it to verify your email.` : null);
      } catch (x) { err.show(x.message); }
    })();
  },
  field('Name', input('text', 'name', { autocomplete: 'name', required: true, maxlength: 80, autofocus: true, placeholder: 'Your name' })),
  field('Email', input('email', 'email', { autocomplete: 'email', required: true, placeholder: 'you@example.com' })),
  h('div.af-pair',
    h('div.af-two',
      field('Password', passwordInput('password', { autocomplete: 'new-password', required: true, minlength: 10 })),
      field('Confirm password', passwordInput('confirm', { autocomplete: 'new-password', required: true }))),
    h('small.af-hint', 'Use at least 10 characters. A few words together work well.')),
  field('Country or region', country),
  h('div.af-checks',
    h('label.af-check', input('checkbox', 'terms'), h('span', 'I agree to the ', h('a', { href: '/terms', target: '_blank' }, 'Terms of Service'))),
    h('label.af-check', input('checkbox', 'privacy'), h('span', 'I’ve read the ', h('a', { href: '/privacy', target: '_blank' }, 'Privacy Policy')))),
  err, btn);
  return authCard('Create your account', 'Only your name, email, password and country. Nothing else.', f,
    authFoot('Already have an account? ', h('a', { href: '#signin' }, 'Sign in')));
}

function showRecoveryKey(key, next, extra) {
  const saved = input('checkbox', 'saved');
  const cont = h('button.btn.primary.wide', { disabled: true, onclick: () => go(next) }, 'Continue');
  saved.addEventListener('change', () => { cont.disabled = !saved.checked; });
  const download = () => {
    const blob = new Blob([`Poly Account recovery key\n\n${key}\n\nKeep this somewhere safe. With your email, it resets your password.\n`], { type: 'text/plain' });
    const a = h('a', { href: URL.createObjectURL(blob), download: 'poly-recovery-key.txt' });
    a.click();
  };
  app.replaceChildren(authCard('Save your recovery key', 'If you forget your password, this key and your email get you back in. '
    + 'Poly keeps only a scrambled copy, so we can’t show it to you again.',
  h('div.recovery-key', { tabindex: 0 }, key),
  h('div.btn-row', h('button.btn', { onclick: () => navigator.clipboard?.writeText(key) }, 'Copy'), h('button.btn', { onclick: download }, 'Download')),
  extra ? h('p.auth-note', extra) : null,
  h('label.af-check', saved, h('span', 'I saved my recovery key somewhere safe')), cont));
}

function forgot() {
  const err = errorBox();
  const done = h('p.af-ok', { hidden: true });
  const btn = h('button.btn.primary.wide', { type: 'submit' }, 'Send reset link');
  const f = form(async (data) => {
    err.show('');
    await busy(btn, async () => {
      try {
        const r = await api('POST', '/api/auth/forgot', { email: data.get('email') });
        done.textContent = r.emailSent
          ? 'If a verified Poly Account uses that email, a reset link is on its way. It works for an hour.'
          : 'Email isn’t set up on this site yet, so no link can be sent. Use your recovery key instead.';
        done.hidden = false;
      } catch (x) { err.show(x.message); }
    })();
  }, field('Email', input('email', 'email', { autocomplete: 'email', required: true, autofocus: true, placeholder: 'you@example.com' })), err, done, btn);
  return authCard('Forgot your password?', 'Enter your email and we’ll send you a link to choose a new one.', f,
    orLine(),
    h('a.btn.wide', { href: '#recover' }, icon('key'), 'Use your recovery key instead'),
    authFoot(h('a', { href: '#signin' }, '← Back to sign in')));
}

function recover() {
  const err = errorBox();
  const btn = h('button.btn.primary.wide', { type: 'submit' }, 'Reset password');
  const f = form(async (data) => {
    err.show('');
    if (data.get('password') !== data.get('confirm')) return err.show('The passwords don’t match.');
    await busy(btn, async () => {
      try {
        const r = await api('POST', '/api/auth/recover', { email: data.get('email'), recoveryKey: data.get('key'), password: data.get('password') });
        await loadMe();
        showRecoveryKey(r.recoveryKey, 'dashboard', 'Your old recovery key was used up. This new one replaces it.');
      } catch (x) { err.show(x.message); }
    })();
  },
  field('Email', input('email', 'email', { autocomplete: 'email', required: true, autofocus: true, placeholder: 'you@example.com' })),
  field('Recovery key', input('text', 'key', { autocomplete: 'off', spellcheck: 'false', placeholder: 'XXXX-XXXX-XXXX-XXXX-XXXX-XXXX', required: true, class: 'mono' })),
  h('div.af-pair',
    h('div.af-two',
      field('New password', passwordInput('password', { autocomplete: 'new-password', required: true })),
      field('Confirm', passwordInput('confirm', { autocomplete: 'new-password', required: true }))),
    h('small.af-hint', 'At least 10 characters.')),
  err, btn);
  return authCard('Use your recovery key', 'The key you saved when you created your account, and a new password.', f,
    authFoot(h('a', { href: '#signin' }, '← Back to sign in')));
}

function resetWithToken(tokenValue) {
  const err = errorBox();
  const btn = h('button.btn.primary.wide', { type: 'submit' }, 'Save new password');
  const f = form(async (data) => {
    if (data.get('password') !== data.get('confirm')) return err.show('The passwords don’t match.');
    await busy(btn, async () => {
      try {
        await api('POST', '/api/auth/reset', { token: tokenValue, password: data.get('password') });
        await loadMe();
        go('dashboard');
      } catch (x) { err.show(x.message); }
    })();
  },
  field('New password', passwordInput('password', { autocomplete: 'new-password', required: true, autofocus: true }), 'At least 10 characters.'),
  field('Confirm new password', passwordInput('confirm', { autocomplete: 'new-password', required: true })), err, btn);
  return authCard('Choose a new password', 'Every browser signed in to your account will be signed out.', f);
}

async function verifyEmail(tokenValue) {
  try {
    await api('POST', '/api/auth/verify', { token: tokenValue });
    await loadMe();
    return authCard('Email verified', 'Thanks! Poly can now send you security alerts and help you recover your account.',
      h('button.btn.primary.wide', { onclick: () => go(me ? 'dashboard' : 'signin') }, me ? 'Go to your account' : 'Sign in'));
  } catch (x) {
    return authCard('That link didn’t work', x.message, h('button.btn.primary.wide', { onclick: () => go('dashboard') }, 'Go to your account'));
  }
}

// ---- signed in ---------------------------------------------------------------------------------
const SECTIONS = [
  ['dashboard', 'Dashboard', 'grid'], ['devices', 'Devices', 'desktop'], ['updates', 'Updates', 'download'], ['sync', 'Sync', 'sync'],
  ['security', 'Security', 'shield'], ['privacy', 'Privacy', 'eye'], ['recovery', 'Recovery', 'key'],
  ['notifications', 'Notifications', 'bell'], ['account', 'Account', 'user'],
];

function shell(active, ...content) {
  const u = me.user;
  const nav = h('nav.acct-nav', { 'aria-label': 'Poly Account' },
    SECTIONS.map(([id, label, ico]) => h('a', { href: `#${id}`, 'aria-current': id === active ? 'page' : null }, icon(ico), label)));
  const foot = h('div.acct-foot',
    h('a', { href: 'support' }, icon('help'), 'Help & Support'),
    h('a', { href: 'docs' }, icon('book'), 'Documentation'),
    h('a', { href: 'security' }, icon('shield'), 'Security Center'),
    h('button', { onclick: signOut }, icon('logout'), 'Sign out'));
  const banners = [];
  if (u.terms.outdated) {
    banners.push(h('div.acct-banner', h('div', h('b', 'Poly’s terms have changed'), h('span', ' Here’s what changed, and you can review them before accepting.')),
      h('div.btn-row', h('a.btn', { href: 'terms', target: '_blank' }, 'Review changes'),
        h('button.btn.primary', { onclick: async () => { await api('POST', '/api/terms/accept'); await loadMe(); route(); } }, 'Accept'))));
  }
  if (!u.emailVerified) {
    const resend = h('button.btn', {}, 'Send the link again');
    resend.addEventListener('click', busy(resend, async () => {
      const r = await api('POST', '/api/account/resend-verification').catch((x) => ({ error: x.message }));
      resend.textContent = r.error || (r.emailSent ? 'Sent' : 'Email isn’t set up yet');
    }));
    banners.push(h('div.acct-banner.soft', h('div', h('b', 'Verify your email'), h('span', ` Open the link we sent to ${u.email} so we can reach you about security.`)), resend));
  }
  return h('div.acct',
    h('aside.acct-side', h('div.acct-me', h('span.acct-avatar', (u.name || '?').trim()[0].toUpperCase()), h('div', h('b', u.name), h('small', u.email))), nav, foot),
    h('section.acct-main', banners, ...content));
}

function head(title, sub, ...actions) {
  return h('header.acct-head', h('div', h('h1', title), sub ? h('p', sub) : null), actions.length ? h('div.btn-row', actions) : null);
}
function card(title, ...kids) {
  return h('section.acct-card', title ? h('h2', title) : null, ...kids);
}
function kv(label, value) {
  return h('div.kv', h('span', label), h('b', value ?? '—'));
}

async function signOut() {
  await api('POST', '/api/auth/logout').catch(() => {});
  me = null;
  go('signin');
}

function greeting() {
  const hour = new Date().getHours();
  return hour < 12 ? 'Good morning' : hour < 18 ? 'Good afternoon' : 'Good evening';
}

function deviceCard(d) {
  return h('article.dev-card',
    h('div.dev-top', icon(d.info?.kind === 'laptop' ? 'laptop' : 'desktop'), h('div', h('b', d.name), h('small', `PolyOS ${d.version || '?'}`)),
      h('span', { class: `dot ${d.online ? 'on' : ''}` }, d.online ? 'Online' : 'Offline')),
    h('p.dev-meta', d.online ? `Last check-in ${when(d.lastSeen)}` : `Last seen ${when(d.lastSeen)}`),
    h('a.btn', { href: `#device=${d.id}` }, 'Manage device'));
}

async function dashboard() {
  const { devices } = await api('GET', '/api/devices');
  const u = me.user;
  const checks = [
    [u.emailVerified, u.emailVerified ? 'Email verified' : 'Email not verified yet'],
    [Boolean(u.recoveryCreatedAt), 'Recovery key configured'],
    [devices.length > 0, `${devices.length} device${devices.length === 1 ? '' : 's'} connected`],
  ];
  return shell('dashboard',
    head(`${greeting()}, ${u.name.split(' ')[0]}`, 'Your Poly ecosystem', h('a.btn.primary', { href: '#link' }, icon('plus'), 'Connect a computer')),
    devices.length ? h('div.dev-grid', devices.map(deviceCard))
      : card(null, h('p', 'No computers are connected yet. In PolyOS, open Settings › Poly Account › Connect, or connect one while setting it up.'),
        h('a.btn.primary', { href: '#link' }, 'I have a code')),
    card('Account', h('ul.checks', checks.map(([ok, text]) => h('li', { class: ok ? 'ok' : 'todo' }, icon(ok ? 'check' : 'info'), text)))));
}

async function devicesPage() {
  const { devices } = await api('GET', '/api/devices');
  return shell('devices', head('Devices', 'The PolyOS computers connected to your account.', h('a.btn.primary', { href: '#link' }, icon('plus'), 'Connect a computer')),
    devices.length ? h('div.dev-grid', devices.map(deviceCard)) : card(null, h('p', 'No computers yet.')));
}

const COMMAND_LABEL = { 'check-updates': 'Check for updates', update: 'Install updates', restart: 'Restart', lock: 'Lock' };
async function devicePage(id) {
  const { device: d, commands } = await api('GET', `/api/devices/${id}`);
  const err = errorBox();
  const run = (kind) => async (e) => {
    err.show('');
    await busy(e.currentTarget, async () => {
      try { await api('POST', `/api/devices/${id}/commands`, { kind }); route(); } catch (x) { err.show(x.message); }
    })();
  };
  const remote = d.remoteManagement;
  const name = input('text', 'name', { value: d.name, maxlength: 60 });
  const channel = h('select.af-input', { name: 'channel' }, ['stable', 'beta', 'developer'].map((c) => h('option', { value: c, selected: c === d.channel }, c[0].toUpperCase() + c.slice(1))));
  const save = h('button.btn', {}, 'Save');
  save.addEventListener('click', busy(save, async () => {
    try { await api('PATCH', `/api/devices/${id}`, { name: name.value, channel: channel.value }); route(); } catch (x) { err.show(x.message); }
  }));
  const remove = h('button.btn.danger', {}, 'Remove device');
  remove.addEventListener('click', async () => {
    if (!confirm(`Remove “${d.name}” from your Poly Account? It stops syncing and can’t be managed from here until you connect it again. PolyOS keeps working on it.`)) return;
    await api('DELETE', `/api/devices/${id}`);
    go('devices');
  });
  const i = d.info || {};
  return shell('devices',
    head(d.name, d.online ? 'Online now' : `Offline · last seen ${when(d.lastSeen)}`, h('a.btn', { href: '#devices' }, 'All devices')),
    err,
    h('div.acct-cols',
      card('Status', kv('Status', d.online ? '● Online' : '○ Offline'), kv('Last check-in', when(d.lastSeen)), kv('Where', d.place || '—'), kv('Connected', date(d.createdAt))),
      card('PolyOS', kv('Version', d.version || '—'), kv('Channel', d.channel), kv('Architecture', d.arch || '—'), kv('Edition', i.edition || '—'))),
    h('div.acct-cols',
      card('Hardware', kv('Computer', [i.maker, i.model].filter(Boolean).join(' ') || '—'), kv('Processor', i.cpu), kv('Memory', gb(i.ram)),
        kv('Storage', i.storage ? `${gb(i.storageFree)} free of ${gb(i.storage)}` : '—'), kv('Graphics', i.gpu)),
      card('Security', h('ul.checks',
        h('li', { class: 'ok' }, icon('check'), 'Device authenticated with its own key'),
        h('li', { class: i.secureBoot ? 'ok' : 'todo' }, icon(i.secureBoot ? 'check' : 'info'), i.secureBoot ? 'Secure Boot on' : 'Secure Boot off or unknown'),
        h('li', { class: d.policy?.autoDownload ? 'ok' : 'todo' }, icon(d.policy?.autoDownload ? 'check' : 'info'), d.policy?.autoDownload ? 'Updates download automatically' : 'Automatic updates off'),
        h('li', { class: remote ? 'ok' : 'todo' }, icon(remote ? 'check' : 'info'), remote ? 'Remote management on' : 'Remote management off (turn it on at the computer: Settings › Poly Account)')))),
    card('Actions',
      h('div.btn-row.wrap',
        h('button.btn.primary', { onclick: run('check-updates') }, 'Check for updates'),
        h('button.btn', { onclick: run('update'), disabled: !remote }, 'Install updates'),
        h('button.btn', { onclick: run('restart'), disabled: !remote }, 'Restart'),
        h('button.btn', { onclick: run('lock'), disabled: !remote }, 'Lock')),
      remote ? null : h('p.muted', 'Install updates, restart and lock work once Remote management is turned on at the computer. Actions reach it at its next check-in (within 15 minutes).'),
      commands.length ? h('ul.history', commands.map((c) => h('li', h('b', COMMAND_LABEL[c.kind] || c.kind), h('span', ` · ${c.status}${c.detail ? `: ${c.detail}` : ''} · ${when(c.created_at)}`)))) : null),
    card('Settings', field('Device name', name), field('Update channel', channel, 'Stable for most people. Beta and Developer get new versions sooner.'), save),
    card('Remove', h('p', 'Removing it signs this computer out of your Poly Account. Its own account and files are untouched.'), remove));
}

function linkPage() {
  const err = errorBox();
  const code = input('text', 'code', { inputmode: 'numeric', autocomplete: 'one-time-code', placeholder: '482 913', maxlength: 7, autofocus: true, class: 'code-input' });
  const btn = h('button.btn.primary', { type: 'submit' }, 'Continue');
  const box = h('div');
  const f = form(async () => {
    err.show('');
    await busy(btn, async () => {
      try {
        const { device } = await api('POST', '/api/link/lookup', { code: code.value });
        const add = h('button.btn.primary', {}, 'Add device');
        add.addEventListener('click', busy(add, async () => {
          try {
            await api('POST', '/api/link/approve', { code: code.value });
            box.replaceChildren(card('Connected', h('p', `“${device.name}” is now part of your Poly Account. It finishes connecting on its own in a few seconds.`),
              h('a.btn.primary', { href: '#devices' }, 'See your devices')));
            f.hidden = true;
          } catch (x) { err.show(x.message); }
        }));
        const i = device.info || {};
        box.replaceChildren(card('New device detected',
          kv('Name', device.name), kv('Computer', [i.maker, i.model].filter(Boolean).join(' ') || 'PolyOS computer'),
          kv('PolyOS', device.version || '—'), kv('Where', device.place || 'Unknown'),
          h('p.muted', 'Only add it if this is the computer in front of you.'),
          h('div.btn-row', add, h('button.btn', { onclick: () => { box.replaceChildren(); code.value = ''; } }, 'Cancel'))));
      } catch (x) { err.show(x.message); }
    })();
  }, field('Code', code, 'Shown on your computer in PolyOS setup or Settings › Poly Account.'), err, btn);
  return shell('devices', head('Connect a computer', 'Enter the 6-digit code shown on your computer.'), card(null, f), box);
}

async function updatesPage() {
  const data = await api('GET', '/api/updates');
  const stable = data.latest.stable || {};
  const eligible = data.devices.filter((d) => d.updateAvailable && d.remoteManagement);
  const all = h('button.btn.primary', { disabled: !eligible.length }, 'Update all eligible devices');
  all.addEventListener('click', busy(all, async () => {
    const r = await api('POST', '/api/updates/all');
    all.textContent = `Sent to ${r.queued} device${r.queued === 1 ? '' : 's'}`;
  }));
  return shell('updates', head('Updates', 'PolyOS versions across your computers.'),
    card('Latest stable', stable.error ? h('p.muted', stable.error) : [kv('Version', `PolyOS ${stable.version}`), stable.published ? kv('Released', date(stable.published)) : null,
      stable.notes ? h('details.notes', h('summary', 'What’s new'), h('pre', stable.notes.slice(0, 3000))) : null]),
    card('Devices', data.devices.length ? h('table.acct-table', h('thead', h('tr', h('th', 'Device'), h('th', 'Version'), h('th', 'Channel'), h('th', 'Status'))),
      h('tbody', data.devices.map((d) => h('tr', h('td', h('a', { href: `#device=${d.id}` }, d.name)), h('td', d.version || '—'), h('td', d.channel),
        h('td', d.updateAvailable ? 'Update available' : 'Up to date'))))) : h('p.muted', 'No computers connected.'),
    h('div.btn-row', all), h('p.muted', 'Updating from here works on computers with Remote management on. Each computer’s own schedule (Settings › Updates) decides when updates download and install; PolyOS always asks before restarting unless you told it not to.')));
}

async function prefsSave(patch) {
  const r = await api('PUT', '/api/preferences', patch);
  me.user = r.user;
}
function toggleRow(label, sub, checked, onChange, disabled) {
  const box = input('checkbox', label, { checked, disabled, role: 'switch' });
  box.addEventListener('change', () => onChange(box.checked).catch(() => { box.checked = !box.checked; }));
  return h('label.toggle-row', h('div', h('b', label), sub ? h('small', sub) : null), box);
}

function syncPage() {
  const s = me.user.prefs.sync;
  const items = [['settings', 'Settings', 'Taskbar, clock, desktop and power choices'], ['themes', 'Themes', 'Dark or light, accent color'],
    ['wallpapers', 'Wallpapers', 'Your desktop and lock screen pictures (built-in ones)'], ['wifi', 'Wi-Fi networks', 'Coming later'],
    ['browser', 'Browser settings', 'Coming later'], ['apps', 'Installed-app preferences', 'Your pinned apps and desktop shortcuts'],
    ['accessibility', 'Accessibility', 'Scale and motion settings']];
  return shell('sync', head('Poly Sync', 'Keep your PolyOS the same on every computer.'),
    card('What syncs', items.map(([key, label, sub]) => toggleRow(label, sub, s[key], (v) => prefsSave({ sync: { [key]: v } }), key === 'browser' || key === 'wifi')),
      h('p.muted', 'Syncing is also switched on or off on each computer (Settings › Poly Account). Personal files aren’t synced; Poly Sync is for settings only.')));
}

const EVENT_LABEL = {
  'account-created': 'Account created', 'signed-in': 'Signed in', 'sign-in-failed': 'Wrong password entered', 'password-changed': 'Password changed',
  'email-verified': 'Email verified', 'email-change-requested': 'Email change requested', 'recovery-key-created': 'New recovery key made',
  'recovery-used': 'Recovery key used', 'device-added': 'New device connected', 'device-removed': 'Device removed', 'device-renamed': 'Device renamed',
  'device-link-approved': 'Device link approved', 'sessions-revoked': 'Signed out everywhere else', 'session-ended': 'A browser was signed out',
  'remote-command': 'Remote action sent', 'terms-accepted': 'Terms accepted', 'profile-updated': 'Profile updated', 'preferences-updated': 'Preferences changed',
};

async function securityPage() {
  const [{ sessions }, { events }, { devices }] = await Promise.all([api('GET', '/api/sessions'), api('GET', '/api/security/events'), api('GET', '/api/devices')]);
  const err = errorBox();
  const pw = form(async (data) => {
    err.show('');
    if (data.get('password') !== data.get('confirm')) return err.show('The new passwords don’t match.');
    try {
      await api('POST', '/api/account/password', { current: data.get('current'), password: data.get('password') });
      await loadMe();
      route();
    } catch (x) { err.show(x.message); }
  },
  field('Current password', input('password', 'current', { autocomplete: 'current-password' })),
  field('New password', input('password', 'password', { autocomplete: 'new-password' }), 'At least 10 characters. Every other browser is signed out.'),
  field('Confirm new password', input('password', 'confirm', { autocomplete: 'new-password' })), err, h('button.btn.primary', { type: 'submit' }, 'Change password'));
  const others = sessions.filter((s) => !s.current).length;
  return shell('security', head('Security', 'Sign-in, sessions and what’s happened on your account.'),
    card('Login security', h('ul.checks', h('li', { class: me.user.emailVerified ? 'ok' : 'todo' }, icon(me.user.emailVerified ? 'check' : 'info'), me.user.emailVerified ? 'Email verified' : 'Email not verified'),
      h('li', { class: 'ok' }, icon('check'), `Password last changed ${when(me.user.passwordChangedAt)}`)), h('details', h('summary', 'Change password'), pw)),
    card('Active sessions', h('ul.sessions', sessions.map((s) => h('li', h('div', h('b', s.agent || 'Browser'), h('small', `${s.place || 'Unknown place'} · ${s.current ? 'this browser' : `active ${when(s.lastSeen)}`}`)),
      s.current ? h('span.muted', 'Current') : h('button.btn', { onclick: async () => { await api('DELETE', `/api/sessions/${s.id}`); route(); } }, 'Sign out')))),
    others ? h('button.btn', { onclick: async () => { await api('POST', '/api/sessions/others/revoke'); route(); } }, 'Sign out all other sessions') : null),
    card('Connected devices', h('p', `${devices.length} computer${devices.length === 1 ? '' : 's'}. Each has its own key; removing one doesn’t affect the others.`), h('a.btn', { href: '#devices' }, 'Manage devices')),
    card('Recent security activity', events.length ? h('ul.history', events.map((e) => h('li', h('b', EVENT_LABEL[e.kind] || e.kind),
      h('span', ` · ${date(e.at)}${e.place ? ` · ${e.place}` : ''}${e.detail?.device ? ` · ${e.detail.device}` : ''}`)))) : h('p.muted', 'Nothing yet.')));
}

function privacyPage() {
  const u = me.user;
  const radios = [['minimal', 'Minimal', 'Version and whether the computer is online. The default.'],
    ['standard', 'Standard', 'Also the computer’s model, memory and storage, shown on your Devices page.'],
    ['diagnostic', 'Diagnostic', 'Also error reports, to help fix problems you report.']];
  const group = h('div.radio-list', radios.map(([v, label, sub]) => {
    const r = input('radio', 'telemetry', { value: v, checked: u.prefs.telemetry === v });
    r.addEventListener('change', () => prefsSave({ telemetry: v }));
    return h('label.radio-row', r, h('div', h('b', label), h('small', sub)));
  }));
  return shell('privacy', head('Privacy', 'Poly does not require an online account to use PolyOS.'),
    card('Account information', kv('Name', u.name), kv('Email', u.email), kv('Country', u.country), h('p.muted', 'That’s everything we ask for. Change it on the Account page.')),
    card('Device information', group),
    card('Your data', h('p', 'Download everything your Poly Account holds: your details, devices, sessions, activity and synced settings.'),
      h('a.btn', { href: '/api/account/export', download: 'poly-account.json' }, 'Download your data'),
      h('p.muted', 'No ads, no selling data. Read the ', h('a', { href: 'privacy' }, 'Privacy Policy'), '.')));
}

function recoveryPage() {
  const u = me.user;
  const err = errorBox();
  const f = form(async (data) => {
    err.show('');
    try {
      const r = await api('POST', '/api/recovery/regenerate', { password: data.get('password') });
      showRecoveryKey(r.recoveryKey, 'recovery', 'Your old recovery key no longer works.');
    } catch (x) { err.show(x.message); }
  }, field('Your password', input('password', 'password', { autocomplete: 'current-password' })), err, h('button.btn.primary', { type: 'submit' }, 'Generate new recovery key'));
  return shell('recovery', head('Recovery', 'Ways back into your account if you forget your password.'),
    card('Recovery email', kv('Email', u.email), kv('Status', u.emailVerified ? 'Verified' : 'Not verified yet'), h('p.muted', 'Password reset links go here.')),
    card('Recovery key', h('div.recovery-key.masked', '████-████-████-████-████-████'),
      h('p', u.recoveryCreatedAt ? `Made ${date(u.recoveryCreatedAt)}. Poly stores only a scrambled copy, so it can’t be shown again; make a new one if you’ve lost it.` : 'No recovery key yet.'),
      h('details', h('summary', 'Generate a new recovery key'), f)));
}

function notificationsPage() {
  const c = me.user.prefs.communications;
  const rows = [['security', 'Important security alerts', 'New devices, password changes and sign-ins. Always on.', true],
    ['account', 'Account notifications', 'Email verification and account changes'], ['updates', 'PolyOS update notifications', 'When a new version is out'],
    ['announcements', 'Product announcements', 'News about PolyOS, now and then'], ['promotions', 'Promotional emails', 'Poly doesn’t send these today']];
  return shell('notifications', head('Notifications', 'Choose what Poly emails you about.'),
    card('Email', rows.map(([key, label, sub, locked]) => toggleRow(label, sub, c[key], (v) => prefsSave({ communications: { [key]: v } }), locked)),
      h('p.muted', 'Legally important notices, like changes to the Terms or Privacy Policy, are sent even with these off.')));
}

async function accountPage() {
  countries = countries || (await api('GET', '/api/countries')).countries;
  const u = me.user;
  const err = errorBox();
  const name = input('text', 'name', { value: u.name, maxlength: 80 });
  const country = h('select.af-input', { name: 'country' }, countries.map((c) => h('option', { value: c, selected: c === u.country }, c)));
  const save = h('button.btn.primary', {}, 'Save');
  save.addEventListener('click', busy(save, async () => {
    try { await api('PATCH', '/api/account', { name: name.value, country: country.value }); await loadMe(); route(); } catch (x) { err.show(x.message); }
  }));
  const emailErr = errorBox();
  const emailForm = form(async (data) => {
    emailErr.show('');
    try {
      const r = await api('POST', '/api/account/email', { email: data.get('email'), password: data.get('password') });
      emailErr.show(r.emailSent ? `Open the link we sent to ${r.pending} to finish the change.` : 'Email isn’t set up on this site yet, so the change can’t be confirmed.');
    } catch (x) { emailErr.show(x.message); }
  }, field('New email', input('email', 'email', { autocomplete: 'email' })), field('Password', input('password', 'password', { autocomplete: 'current-password' })),
  emailErr, h('button.btn', { type: 'submit' }, 'Change email'));
  const delErr = errorBox();
  const del = form(async (data) => {
    delErr.show('');
    if (data.get('confirm') !== 'DELETE') return delErr.show('Type DELETE to confirm.');
    try {
      await api('POST', '/api/account/delete', { password: data.get('password') });
      me = null;
      app.replaceChildren(authCard('Your Poly Account is deleted', 'Your details, devices and synced settings are gone. PolyOS keeps working on your computers.',
        h('a.btn.primary.wide', { href: './' }, 'Back to PolyOS')));
    } catch (x) { delErr.show(x.message); }
  }, h('p', 'This deletes your account, disconnects every computer and erases your synced settings. It can’t be undone. PolyOS keeps working.'),
  field('Password', input('password', 'password', { autocomplete: 'current-password' })), field('Type DELETE', input('text', 'confirm', { autocomplete: 'off' })),
  delErr, h('button.btn.danger', { type: 'submit' }, 'Delete Poly Account'));
  return shell('account', head('Account', null),
    card('Your details', err, field('Name', name), kv('Email', u.email), field('Country', country), save),
    card('Email', h('details', h('summary', 'Change email'), emailForm)),
    card('Password', h('p', `Changed ${when(u.passwordChangedAt)}.`), h('a.btn', { href: '#security' }, 'Change password')),
    card('About your account', kv('Account created', date(u.createdAt)), kv('Terms version', u.terms.version || '—'), kv('Accepted', date(u.terms.acceptedAt))),
    card('Delete account', h('details.danger-zone', h('summary', 'Delete your Poly Account'), del)));
}

// ---- routing -----------------------------------------------------------------------------------
async function loadMe() {
  try {
    me = await api('GET', '/api/me');
  } catch (x) {
    me = null;
    if (x.status === 503 || x.status >= 500) throw x;
  }
  return me;
}

async function route() {
  const hash = location.hash.slice(1);
  const [key, value] = hash.split('=');
  let view;
  try {
    if (key === 'verify') view = await verifyEmail(value);
    else if (key === 'reset') view = resetWithToken(value);
    else if (!me) {
      view = { create: createAccount, forgot, recover }[key]?.() || signIn(START === 'link' ? 'Sign in to connect your computer.' : null);
      if (view instanceof Promise) view = await view;
    } else if (key === 'device') view = await devicePage(value);
    else {
      const page = { dashboard, devices: devicesPage, link: linkPage, updates: updatesPage, sync: syncPage, security: securityPage,
        privacy: privacyPage, recovery: recoveryPage, notifications: notificationsPage, account: accountPage }[key || START];
      view = page ? await page() : await dashboard();
    }
  } catch (x) {
    if (x.status === 401) { me = null; return route(); }
    view = authCard('Something went wrong', x.message, h('button.btn.primary.wide', { onclick: () => location.reload() }, 'Try again'));
  }
  app.replaceChildren(view);
  document.title = `${me ? (SECTIONS.find((s) => s[0] === (key || START))?.[1] || 'Poly Account')
    : ({ create: 'Create account', forgot: 'Forgot password', recover: 'Recovery key' }[key] || 'Sign in')} · Poly Account`;
  window.scrollTo(0, 0);
}

window.addEventListener('hashchange', route);
(async () => {
  try {
    await loadMe();
  } catch (x) {
    app.replaceChildren(authCard('Poly Account is getting ready', x.status === 503 ? x.message : 'We can’t reach Poly Account right now. Try again in a moment.',
      h('p.auth-note', 'PolyOS works without an account. You can download it and use it fully offline.'), h('a.btn.primary.wide', { href: './' }, 'Back to PolyOS')));
    return;
  }
  route();
})();
