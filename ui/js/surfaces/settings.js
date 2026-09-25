// Settings app: appearance, Wi-Fi, sound, display, power, about.

import { api, launch, on, params, power, saveSettings, withToken } from '../api.js';
import { errorText, group, row, slider, toggle, wifiPanel } from '../components.js';
import { formatBytes, h, hexToHue, hueToHex, icon, networkLabel, throttle } from '../ui.js';

const PAGES = [
  ['appearance', 'Appearance', 'palette'],
  ['network', 'Wi-Fi & Network', 'wifi'],
  ['sound', 'Sound', 'volume'],
  ['display', 'Display', 'monitor'],
  ['power', 'Power', 'power'],
  ['vara', 'Vara', 'chat'],
  ['about', 'About', 'info'],
];
// PolyOS blue first; the rest share its softness so text on them stays readable.
const ACCENTS = ['#678fd9', '#9b7fe0', '#d97fb8', '#e0906a', '#d9c46a', '#81d862', '#5fc4c4', '#b5b5b5'];
const CREDITS =
  'PolyOS began as an operating system built in Scratch by AndrewInput and PIXAPoLY Software. ' +
  'This edition, presented by Cryptic Software, brings PolyOS 7 to real hardware on top of Debian, with the team’s blessing. ' +
  'The PolyOS logo, colors and PIXAPoLY wallpaper come from the Scratch project (CC BY-SA 2.0).';

function pageHead(title, subtitle) {
  return h('header.page-head', h('h1', title), h('p', subtitle));
}

function save(patch, errEl) {
  saveSettings(patch).then(() => errEl && errorText(errEl, ''), (err) => errEl && errorText(errEl, err.message));
}

// Button that opens an installed helper app, or explains what to install.
function helperButton(store, appId, label, pkg) {
  const app = store.state.apps.find((a) => a.id === appId);
  return app
    ? h('button.btn', { onclick: () => launch(appId) }, label, icon('external'))
    : h('span.muted.small', `Install ${pkg} for more options`);
}

const pages = {
  appearance(page, store) {
    const s = () => store.state.settings;
    const err = h('div.error-text', { hidden: true });

    const swatches = h('div.swatches');
    const custom = h('input.color-input', { type: 'color', value: s().accent, title: 'Custom color' });
    custom.addEventListener('change', () => save({ accent: custom.value }, err));
    for (const color of ACCENTS) {
      swatches.append(h('button.swatch', { style: { background: color }, title: color, 'data-color': color,
        onclick: () => save({ accent: color }, err) }));
    }
    swatches.append(custom);

    const walls = h('div.wall-grid');
    api.get('/api/wallpapers').then((list) => {
      for (const w of list) {
        walls.append(h('button.wall', { 'data-id': w.id, title: w.name, style: { backgroundImage: `url("${withToken(w.url)}")` },
          onclick: () => save({ wallpaper: w.id }, err) }, h('span', w.name)));
      }
      if (!store.state.env.dev) {
        walls.append(h('button.wall.wall-add', { onclick: () => api.post('/api/pick-wallpaper').catch((e) => errorText(err, e.message)) },
          icon('plus'), h('span', 'Browse…')));
      }
      update();
    }, (e) => errorText(err, e.message));

    // PolyOS 7's accent control: one slider across the color wheel.
    const hue = h('input.range.hue-range', { type: 'range', min: 0, max: 359, value: hexToHue(s().accent), 'aria-label': 'Accent hue' });
    const sendHue = throttle((v) => save({ accent: hueToHex(v) }, err), 150);
    hue.addEventListener('input', () => {
      document.documentElement.style.setProperty('--accent', hueToHex(Number(hue.value)));
      sendHue(Number(hue.value));
    });

    const glass = slider({ min: 30, max: 100, value: s().glass, label: 'Transparency',
      onInput: (v) => { glassValue.textContent = `${v}%`; save({ glass: v }, err); } });
    const glassValue = h('span.value');

    const clock24 = toggle(s().clock24h, (v) => save({ clock24h: v }, err), '24-hour clock');
    const seconds = toggle(s().showSeconds, (v) => save({ showSeconds: v }, err), 'Show seconds');
    const deskClock = toggle(s().desktopClock, (v) => save({ desktopClock: v }, err), 'Desktop clock');
    const effects = toggle(s().effects, (v) => save({ effects: v }, err), 'Visual effects');
    const allApps = toggle(s().showAllApps, (v) => save({ showAllApps: v }, err), 'Show all apps');
    const modes = h('div.seg', { role: 'radiogroup', 'aria-label': 'Mode' },
      ['dark', 'light'].map((m) => h('button.seg-btn', { 'data-mode': m, role: 'radio', onclick: () => save({ theme: m }, err) },
        icon(m === 'dark' ? 'moon' : 'sun'), m === 'dark' ? 'Dark' : 'Light')));

    page.append(
      pageHead('Appearance', 'Customize the look and feel of PolyOS.'),
      err,
      group('Mode', row('Appearance', 'Dark or light, for PolyOS and your apps. Open apps update when you reopen them.', modes)),
      group('Accent color',
        row('Accent', 'Highlights, sliders and the active app', swatches),
        row('Custom color', 'Slide to pick any hue', h('div.slider-wrap', hue))),
      group('Wallpaper', walls),
      group('Windows and effects',
        row('Dock and menu opacity', 'Lower is more see-through', h('div.slider-wrap', glass, glassValue)),
        row('Blur, shadows and rounded corners', 'Takes effect the next time you sign in', effects)),
      group('Clock',
        row('24-hour time', null, clock24),
        row('Show seconds in the dock', null, seconds),
        row('Clock on the desktop', 'Large time, date and greeting', deskClock)),
      group('Launcher',
        row('Show all apps', 'Include system tools PolyOS normally hides, like the volume mixer and network editor', allApps)),
    );

    function update() {
      const cur = s();
      swatches.querySelectorAll('.swatch').forEach((el) => el.classList.toggle('sel', el.dataset.color === cur.accent));
      custom.classList.toggle('sel', !ACCENTS.includes(cur.accent));
      if (document.activeElement !== hue) hue.value = hexToHue(cur.accent);
      glass.set(cur.glass);
      glassValue.textContent = `${cur.glass}%`;
      walls.querySelectorAll('.wall[data-id]').forEach((el) => el.classList.toggle('sel', el.dataset.id === cur.wallpaper));
      walls.querySelector('.wall-add')?.classList.toggle('sel', !cur.wallpaper.startsWith('builtin:'));
      clock24.set(cur.clock24h);
      seconds.set(cur.showSeconds);
      deskClock.set(cur.desktopClock);
      effects.set(cur.effects);
      allApps.set(cur.showAllApps);
      modes.querySelectorAll('.seg-btn').forEach((el) => el.setAttribute('aria-checked', String(el.dataset.mode === cur.theme)));
    }
    update();
    return { update: (_st, changed) => changed.has('settings') && update() };
  },

  network(page, store) {
    const summary = h('span.muted');
    const err = h('div.error-text', { hidden: true });
    const wifiSwitch = toggle(false, (v) => {
      api.post('/api/wifi/enabled', { enabled: v }).then(() => errorText(err, ''), (e) => errorText(err, e.message));
    }, 'Wi-Fi');
    const wifi = wifiPanel(store);
    page.append(
      pageHead('Wi-Fi & Network', 'Connect to networks and manage saved ones.'),
      err,
      group(null, row('Wi-Fi', summary, wifiSwitch)),
      group('Networks', wifi.el),
      group('Advanced', row('Network connections', 'VPNs, enterprise Wi-Fi, static IP addresses',
        helperButton(store, 'nm-connection-editor.desktop', 'Open editor', 'network-manager-gnome'))),
    );
    function update() {
      const net = store.state.system.network;
      summary.textContent = networkLabel(net);
      wifiSwitch.set(net.wifiEnabled);
      wifiSwitch.disabled = !net.wifiDevice;
      wifi.update();
    }
    update();
    return { update: (_st, changed) => changed.has('system') && update() };
  },

  sound(page, store) {
    const vol = slider({ label: 'Volume', onInput: (v) => api.post('/api/volume', { level: v }) });
    const value = h('span.value');
    const mute = toggle(false, (v) => api.post('/api/volume', { muted: v }), 'Mute');
    const body = h('div');
    page.append(pageHead('Sound', 'Output volume and audio devices.'), body);
    function build() {
      body.replaceChildren(
        store.state.system.volume.available
          ? group('Output', row('Volume', null, h('div.slider-wrap', vol, value)), row('Mute', null, mute))
          : group(null, row('No audio output found', 'Check that PipeWire is running and a device is connected')),
        group('Advanced', row('Devices and per-app volume', null, helperButton(store, 'pavucontrol.desktop', 'Open mixer', 'pavucontrol'))),
      );
    }
    let available = null;
    function update() {
      const v = store.state.system.volume;
      if (v.available !== available) {
        available = v.available;
        build();
      }
      vol.set(v.level);
      value.textContent = `${v.level}%`;
      mute.set(v.muted);
    }
    update();
    return { update: (_st, changed) => changed.has('system') && update() };
  },

  display(page, store) {
    const bri = slider({ min: 5, label: 'Brightness', onInput: (v) => api.post('/api/brightness', { level: v }) });
    const value = h('span.value');
    const err = h('div.error-text', { hidden: true });
    const scale = h('select.select', { 'aria-label': 'Display scale' },
      h('option', { value: 'auto' }, 'Automatic'), h('option', { value: '1' }, '100%'), h('option', { value: '2' }, '200% (HiDPI)'));
    scale.addEventListener('change', () => save({ scale: scale.value }, err));
    const briGroup = group('Brightness', row('Screen brightness', null, h('div.slider-wrap', bri, value)));
    page.append(
      pageHead('Display', 'Brightness, scaling and screen arrangement.'),
      err,
      briGroup,
      group('Scale', row('Display scale', 'Automatic picks 200% on high-density screens. Applies at next sign-in.', scale)),
      group('Arrangement', row('Resolution and multiple displays', null, helperButton(store, 'arandr.desktop', 'Arrange displays', 'arandr'))),
    );
    function update() {
      const b = store.state.system.brightness;
      briGroup.hidden = !b.available;
      bri.set(b.level);
      value.textContent = `${b.level}%`;
      scale.value = store.state.settings.scale;
    }
    update();
    return { update: (_st, changed) => (changed.has('system') || changed.has('settings')) && update() };
  },

  power(page, store) {
    const battery = h('div');
    const actions = [
      ['lock', 'Lock', 'lock'], ['logout', 'Sign out', 'logout'], ['moon', 'Sleep', 'suspend'],
      ['restart', 'Restart', 'reboot'], ['power', 'Shut down', 'poweroff'],
    ];
    const err = h('div.error-text', { hidden: true });
    page.append(
      pageHead('Power', 'Battery status and session options.'),
      err,
      battery,
      group('Session', h('div.power-grid', actions.map(([ico, label, action]) =>
        h('button.power-tile', { onclick: () => power(action).catch((e) => errorText(err, e.message)) }, icon(ico), h('span', label))))),
    );
    function update() {
      const b = store.state.system.battery;
      battery.replaceChildren(b.present
        ? group('Battery', row(`${b.level}%`, b.charging ? 'Charging' : b.plugged ? 'Plugged in' : 'On battery',
          h('span.battery-big', icon('battery', b.level, b.charging))))
        : '');
    }
    update();
    return { update: (_st, changed) => changed.has('system') && update() };
  },

  vara(page) {
    const PRESETS = [
      ['Ollama Cloud', 'https://ollama.com/v1', 'gpt-oss:120b'],
      ['OpenAI', 'https://api.openai.com/v1', 'gpt-4o-mini'],
      ['Ollama on this PC', 'http://127.0.0.1:11434/v1', 'llama3.2'],
    ];
    const err = h('div.error-text', { hidden: true });
    const note = h('span.muted.small');
    const endpoint = h('input.input', { placeholder: 'http://127.0.0.1:11434/v1', spellcheck: 'false', 'aria-label': 'Endpoint' });
    const model = h('input.input', { placeholder: 'llama3.2', spellcheck: 'false', 'aria-label': 'Model' });
    const key = h('input.input', { type: 'password', placeholder: 'Paste your API key', autocomplete: 'off', 'aria-label': 'API key' });
    const presets = h('div.swatches', PRESETS.map(([label, url, m]) => h('button.pill-btn', {
      onclick: () => { endpoint.value = url; model.value = m; },
    }, label)));
    const saveBtn = h('button.btn.primary', 'Save');
    const testBtn = h('button.btn', 'Test connection');
    const load = () => api.get('/api/vara/config').then((c) => {
      endpoint.value = c.endpoint;
      model.value = c.model;
      key.value = '';
      key.placeholder = c.hasKey ? 'Saved (type to replace)' : 'Paste your API key';
      note.textContent = c.needsKey ? 'Add an API key so Vara can chat. Ollama Cloud keys are free at ollama.com.' : '';
    });
    saveBtn.addEventListener('click', async () => {
      errorText(err, '');
      try {
        await api.post('/api/vara/config', { endpoint: endpoint.value, model: model.value, ...(key.value ? { apiKey: key.value } : {}) });
        note.textContent = 'Saved.';
        load();
      } catch (e) {
        errorText(err, e.message);
      }
    });
    testBtn.addEventListener('click', async () => {
      errorText(err, '');
      note.textContent = 'Testing…';
      try {
        const res = await api.post('/api/vara/test', {});
        note.textContent = `Connected. The model said: ${res.reply}`;
      } catch (e) {
        note.textContent = '';
        errorText(err, e.message);
      }
    });
    page.append(
      pageHead('Vara', 'Your PolyOS assistant, powered by the AI model you choose.'),
      err,
      group('Quick setup', row('Provider', 'Fills in the address and a model; add your key for cloud services', presets)),
      group('Connection',
        row('Endpoint', 'Any OpenAI-compatible API', h('div.slider-wrap.wide', endpoint)),
        row('Model', null, h('div.slider-wrap.wide', model)),
        row('API key', 'Stored only on this computer, readable only by you', h('div.slider-wrap.wide', key))),
      h('div.btn-row', saveBtn, testBtn, note),
      group('Privacy', h('p.prose',
        'Simple requests like “open Firefox” or “volume 40” are handled on this computer. Other messages ',
        'go to the endpoint above; with a cloud provider they leave this computer, so don’t share passwords with Vara. ',
        'To keep everything on this computer instead, install Ollama (ollama.com), pull a model such as llama3.2 and choose “Ollama on this PC”.')),
    );
    load();
    return null;
  },

  about(page, store) {
    const { version, hostname } = store.state;
    const specs = h('div');
    page.append(
      h('div.about-hero',
        h('img', { src: '/img/logo.svg', alt: '' }),
        h('div', h('h1', 'PolyOS'), h('p.muted', `Version ${version}`))),
      specs,
      group('Tools',
        row('Task Manager', 'See what’s running and end apps that stopped responding (Ctrl+Shift+Esc)',
          h('button.btn', { onclick: () => api.post('/api/open', { app: 'taskmgr' }) }, 'Open', icon('external'))),
        row('Driver Manager', 'Install graphics, Wi-Fi and other drivers',
          h('button.btn', { onclick: () => api.post('/api/open', { app: 'drivers' }) }, 'Open', icon('external'))),
        row('PolyMarket', 'Get trusted apps', h('button.btn', { onclick: () => api.post('/api/open', { app: 'store' }) }, 'Open', icon('external')))),
      group('Credits', h('p.prose', CREDITS, ' ',
        h('a', { href: 'https://scratch.mit.edu/users/PolyOS/', target: '_blank', rel: 'noopener' }, 'PolyOS on Scratch'), '.')),
      group('License', h('p.prose',
        'PolyOS is free software under the GNU General Public License, version 3 or later. ',
        'It is built on Debian GNU/Linux, Openbox and many other open-source projects.')),
    );
    api.get('/api/sysinfo').then((info) => {
      const uptime = `${Math.floor(info.uptime / 3600)} h ${Math.floor((info.uptime % 3600) / 60)} min`;
      specs.replaceChildren(group('This computer',
        row('Device name', null, h('span.value', info.hostname || hostname)),
        row('Based on', null, h('span.value', info.os)),
        row('Processor', null, h('span.value', `${info.cpu}${info.cores ? ` (${info.cores} threads)` : ''}`)),
        row('Memory', null, h('span.value', formatBytes(info.memoryBytes, 1024))),
        row('Storage', null, h('span.value', `${formatBytes(info.diskFree)} free of ${formatBytes(info.diskTotal)}`)),
        row('Kernel', null, h('span.value', `${info.kernel} (${info.arch})`)),
        row('Uptime', null, h('span.value', uptime))));
    }, (e) => specs.replaceChildren(h('div.error-text', e.message)));
    return null;
  },
};

export function mount(root, store) {
  root.className = 'settings';
  const nav = h('nav.nav', { 'aria-label': 'Settings sections' });
  const page = h('main.page');
  root.append(h('aside.sidebar', h('div.brand', h('img', { src: '/img/logo.svg', alt: '' }), 'Settings'), nav), page);

  let current = null;
  let pageApi = null;
  const buttons = new Map();
  for (const [id, label, ico] of PAGES) {
    const btn = h('button.nav-item', { onclick: () => go(id) }, icon(ico), h('span', id === 'about' ? 'About PolyOS' : label));
    buttons.set(id, btn);
    if (id === 'about') nav.append(h('div.nav-spacer')); // About sits at the bottom, as in PolyOS 7
    nav.append(btn);
  }

  function go(id) {
    if (!pages[id]) id = 'appearance';
    if (id === current) return;
    current = id;
    for (const [key, btn] of buttons) btn.classList.toggle('active', key === id);
    page.replaceChildren();
    page.scrollTop = 0;
    pageApi = pages[id](page, store);
    history.replaceState(null, '', `?surface=settings&page=${id}`);
    document.title = `${PAGES.find((p) => p[0] === id)[1]} – Settings`;
  }

  store.subscribe((state, changed) => pageApi?.update?.(state, changed));
  on('navigate', (e) => { if (e.surface === 'settings' && e.page) go(e.page); });
  go(params.get('page') || 'appearance');
}
