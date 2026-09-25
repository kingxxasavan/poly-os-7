// Settings app: appearance, taskbar, Wi-Fi, sound, display, power, account, privacy & security,
// Vara, about.

import { withAdmin } from '../admin.js';
import { api, launch, on, params, power, saveSettings, withToken } from '../api.js';
import { errorText, group, row, slider, toggle, wifiPanel } from '../components.js';
import { formatBytes, h, hexToHue, hueToHex, icon, networkLabel, throttle } from '../ui.js';

const PAGES = [
  ['appearance', 'Appearance', 'palette'],
  ['taskbar', 'Taskbar & Desktop', 'taskbar'],
  ['network', 'Wi-Fi & Network', 'wifi'],
  ['sound', 'Sound', 'volume'],
  ['display', 'Display', 'monitor'],
  ['power', 'Power & Performance', 'bolt'],
  ['account', 'Account', 'user'],
  ['privacy', 'Privacy & Security', 'shield'],
  ['vara', 'Vara', 'chat'],
  ['about', 'About', 'info'],
];
// PolyOS blue first; the rest share its softness so text on them stays readable.
const ACCENTS = ['#678fd9', '#9b7fe0', '#d97fb8', '#e0906a', '#d9c46a', '#81d862', '#5fc4c4', '#b5b5b5'];
const MINUTES = (n) => (n === 0 ? 'Never' : n < 60 ? `${n} minute${n === 1 ? '' : 's'}` : `${n / 60} hour${n === 60 ? '' : 's'}`);
const SCREEN_OFF = [1, 2, 3, 5, 10, 15, 30, 60, 0];
const SLEEP_AFTER = [5, 10, 15, 30, 60, 120, 240, 0];
const MODE_ICONS = { saver: 'leaf', balanced: 'activity', performance: 'bolt', maximum: 'sparkle' };
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

// Segmented control (radio pills): options = [[value, label, icon?], ...]
function seg(label, options, onPick) {
  const el = h('div.seg', { role: 'radiogroup', 'aria-label': label },
    options.map(([value, text, ico]) => h('button.seg-btn', { role: 'radio', 'data-value': String(value), onclick: () => onPick(value) },
      ico ? icon(ico) : null, text)));
  return Object.assign(el, {
    set: (v) => el.querySelectorAll('.seg-btn').forEach((b) => b.setAttribute('aria-checked', String(b.dataset.value === String(v)))),
  });
}

// Drop-down of numbers: options = [[value, label], ...]
function choose(label, options, onPick) {
  const el = h('select.select', { 'aria-label': label }, options.map(([value, text]) => h('option', { value }, text)));
  el.addEventListener('change', () => onPick(Number(el.value)));
  return Object.assign(el, { set: (v) => { el.value = String(v); } });
}

// Built-in wallpapers for a setting ("wallpaper" or "lockWallpaper"); browse adds any picture.
function wallGrid(store, key, err, browse) {
  const grid = h('div.wall-grid');
  const update = () => {
    const cur = store.state.settings[key];
    grid.querySelectorAll('.wall[data-id]').forEach((el) => el.classList.toggle('sel', el.dataset.id === cur));
    grid.querySelector('.wall-add')?.classList.toggle('sel', !cur.startsWith('builtin:'));
  };
  api.get('/api/wallpapers').then((list) => {
    for (const w of list) {
      grid.append(h('button.wall', { 'data-id': w.id, title: w.name, style: { backgroundImage: `url("${withToken(w.url)}")` },
        onclick: () => save({ [key]: w.id }, err) }, h('span', w.name)));
    }
    if (browse && !store.state.env.dev) {
      grid.append(h('button.wall.wall-add', { onclick: () => api.post('/api/pick-wallpaper').catch((e) => errorText(err, e.message)) },
        icon('plus'), h('span', 'Browse…')));
    }
    update();
  }, (e) => errorText(err, e.message));
  return Object.assign(grid, { update });
}

// A list of apps (dock pins or desktop shortcuts) with remove buttons.
function appList(store, key, empty) {
  const list = h('div.app-list');
  const update = () => {
    const { settings, apps } = store.state;
    const byId = new Map(apps.map((a) => [a.id, a]));
    const items = settings[key].map((id) => byId.get(id)).filter(Boolean);
    list.replaceChildren(...(items.length ? items.map((app, i) => h('div.app-row',
      h('img', { src: withToken(app.icon), alt: '' }), h('span', app.name),
      h('button.icon-btn.flip-up', { title: 'Move up', 'aria-label': `Move ${app.name} up`, disabled: i === 0, onclick: () => {
        const ids = items.map((a) => a.id);
        [ids[i - 1], ids[i]] = [ids[i], ids[i - 1]];
        save({ [key]: ids });
      } }, icon('chevronDown')),
      h('button.icon-btn', { title: 'Remove', 'aria-label': `Remove ${app.name}`,
        onclick: () => save({ [key]: settings[key].filter((id) => id !== app.id) }) }, icon('close'))))
      : [h('p.muted.small.pad', empty)]));
  };
  update();
  return Object.assign(list, { update });
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

    const walls = wallGrid(store, 'wallpaper', err, true);
    const lockWalls = wallGrid(store, 'lockWallpaper', err, false);

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
      group('Sign-in and lock screen background', h('p.muted.small.pad', 'Shown softly blurred behind the clock, like PolyOS 7.'), lockWalls),
      group('Windows and effects',
        row('Dock and menu opacity', 'Lower is more see-through', h('div.slider-wrap', glass, glassValue)),
        row('Blur, shadows and rounded corners', 'Takes effect the next time you sign in', effects)),
      group('Clock',
        row('24-hour time', null, clock24),
        row('Show seconds in the taskbar', null, seconds)),
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
      walls.update();
      lockWalls.update();
      clock24.set(cur.clock24h);
      seconds.set(cur.showSeconds);
      effects.set(cur.effects);
      allApps.set(cur.showAllApps);
      modes.querySelectorAll('.seg-btn').forEach((el) => el.setAttribute('aria-checked', String(el.dataset.mode === cur.theme)));
    }
    update();
    return { update: (_st, changed) => changed.has('settings') && update() };
  },

  taskbar(page, store) {
    const s = () => store.state.settings;
    const err = h('div.error-text', { hidden: true });
    const style = seg('Taskbar style', [['floating', 'Floating'], ['full', 'Edge to edge']], (v) => save({ taskbarStyle: v }, err));
    const align = seg('Taskbar alignment', [['center', 'Center'], ['left', 'Left']], (v) => save({ taskbarAlign: v }, err));
    const autoHide = toggle(s().taskbarAutoHide, (v) => save({ taskbarAutoHide: v }, err), 'Automatically hide the taskbar');
    const widgets = toggle(s().taskbarWidgets, (v) => save({ taskbarWidgets: v }, err), 'Widgets button');
    const date = toggle(s().taskbarDate, (v) => save({ taskbarDate: v }, err), 'Show the date');
    const seconds = toggle(s().showSeconds, (v) => save({ showSeconds: v }, err), 'Show seconds');
    const open = seg('Open desktop shortcuts with', [['double', 'Double-click'], ['single', 'Single click']], (v) => save({ desktopOpen: v }, err));
    const deskClock = toggle(s().desktopClock, (v) => save({ desktopClock: v }, err), 'Desktop clock');
    const pins = appList(store, 'pinned', 'Nothing is pinned. Pin apps from the launcher.');
    const shortcuts = appList(store, 'desktopIcons', 'No shortcuts on the desktop yet.');
    const launcher = (target) => h('button.btn', {
      onclick: () => api.post('/api/popup', { view: 'launcher', data: target ? { target } : {} }).catch((e) => errorText(err, e.message)),
    }, icon('plus'), target ? 'Add apps to the desktop' : 'Pin more apps');
    page.append(
      pageHead('Taskbar & Desktop', 'Layout, behaviors and the apps on your taskbar and desktop.'),
      err,
      group('Taskbar layout',
        row('Style', 'Floating is the PolyOS capsule. Edge to edge fills the bottom of the screen, so maximized apps meet it with no gap.', style),
        row('Alignment', 'Where your apps sit on the taskbar', align)),
      group('Taskbar behaviors',
        row('Automatically hide the taskbar', 'Maximized and full-screen apps use the whole screen. Touch the bottom edge to bring the taskbar back.', autoHide),
        row('Widgets button', 'Weather and the widgets board (Win+W)', widgets),
        row('Show the date', 'Under the time', date),
        row('Show seconds', null, seconds)),
      group('Pinned apps', pins, h('div.pad', launcher(null))),
      group('Desktop',
        row('Open shortcuts with', 'Right-click the desktop or any app in the launcher to add shortcuts', open),
        row('Clock on the desktop', 'Large time, date and greeting', deskClock)),
      group('Desktop shortcuts', shortcuts, h('div.pad', launcher('desktop'))),
    );
    function update() {
      const cur = s();
      style.set(cur.taskbarStyle);
      align.set(cur.taskbarAlign);
      autoHide.set(cur.taskbarAutoHide);
      widgets.set(cur.taskbarWidgets);
      date.set(cur.taskbarDate);
      seconds.set(cur.showSeconds);
      open.set(cur.desktopOpen);
      deskClock.set(cur.desktopClock);
      pins.update();
      shortcuts.update();
    }
    update();
    return { update: (_st, changed) => (changed.has('settings') || changed.has('apps')) && update() };
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
    const s = () => store.state.settings;
    const err = h('div.error-text', { hidden: true });
    const battery = h('div');
    const modes = h('div.mode-grid', { role: 'radiogroup', 'aria-label': 'Power mode' });
    const modeNote = h('p.muted.small.pad', { hidden: true });
    api.get('/api/power/modes').then((info) => {
      modes.replaceChildren(...info.modes.map((m) => h('button.mode-card', { role: 'radio', 'data-mode': m.id, onclick: () => save({ powerMode: m.id }, err) },
        h('span.mode-ico', icon(MODE_ICONS[m.id] || 'bolt')), h('b', m.name), h('small', m.description))));
      if (!info.switchable) {
        modeNote.textContent = 'This computer doesn’t offer processor power profiles (install power-profiles-daemon). Screen and sleep timers still follow your mode.';
        modeNote.hidden = false;
      }
      update();
    }, (e) => errorText(err, e.message));
    const screenOff = choose('Turn off the screen after', SCREEN_OFF.map((n) => [n, MINUTES(n)]), (v) => save({ screenOff: v }, err));
    const sleep = choose('Sleep after', SLEEP_AFTER.map((n) => [n, MINUTES(n)]), (v) => save({ sleepAfter: v }, err));
    const timers = group('Screen and sleep',
      row('Turn off the screen after', 'When you haven’t used the keyboard or mouse', screenOff),
      row('Put the computer to sleep after', null, sleep));
    const maxNote = h('p.muted.small.pad', 'Maximum keeps the screen on and never sleeps on its own. Choose another mode to use these timers.');
    const actions = [
      ['lock', 'Lock', 'lock'], ['logout', 'Sign out', 'logout'], ['moon', 'Sleep', 'suspend'],
      ['restart', 'Restart', 'reboot'], ['power', 'Shut down', 'poweroff'],
    ];
    page.append(
      pageHead('Power & Performance', 'Power modes, battery, screen and sleep.'),
      err,
      battery,
      group('Power mode', modes, modeNote),
      timers,
      maxNote,
      group('Session', h('div.power-grid', actions.map(([ico, label, action]) =>
        h('button.power-tile', { onclick: () => power(action).catch((e) => errorText(err, e.message)) }, icon(ico), h('span', label))))),
    );
    function update() {
      const cur = s();
      const b = store.state.system.battery;
      battery.replaceChildren(b.present
        ? group('Battery', row(`${b.level}%`, b.charging ? 'Charging' : b.plugged ? 'Plugged in' : 'On battery',
          h('span.battery-big', icon('battery', b.level, b.charging))))
        : '');
      modes.querySelectorAll('.mode-card').forEach((el) => el.setAttribute('aria-checked', String(el.dataset.mode === cur.powerMode)));
      screenOff.set(cur.screenOff);
      sleep.set(cur.sleepAfter);
      const max = cur.powerMode === 'maximum';
      timers.classList.toggle('disabled', max);
      screenOff.disabled = sleep.disabled = max;
      maxNote.hidden = !max;
    }
    update();
    return { update: (_st, changed) => (changed.has('system') || changed.has('settings')) && update() };
  },

  account(page, store) {
    const { user } = store.state;
    const err = h('div.error-text', { hidden: true });
    const note = h('span.muted.small');
    const current = h('input.input', { type: 'password', placeholder: 'Current password', autocomplete: 'current-password', 'aria-label': 'Current password' });
    const next = h('input.input', { type: 'password', placeholder: 'New password', autocomplete: 'new-password', 'aria-label': 'New password' });
    const again = h('input.input', { type: 'password', placeholder: 'Type it again', autocomplete: 'new-password', 'aria-label': 'Confirm new password' });
    const change = h('button.btn.primary', 'Change password');
    change.addEventListener('click', async () => {
      errorText(err, '');
      if (!next.value) return errorText(err, 'Choose a new password.');
      if (next.value !== again.value) return errorText(err, 'The new passwords don’t match.');
      change.disabled = true;
      try {
        await api.post('/api/account/password', { current: current.value, password: next.value });
        note.textContent = 'Password changed.';
        current.value = next.value = again.value = '';
      } catch (e) {
        errorText(err, e.message);
      }
      change.disabled = false;
    });
    const keyBox = h('div');
    const makeKey = h('button.btn', 'Create a new recovery key');
    makeKey.addEventListener('click', async () => {
      errorText(err, '');
      try {
        const { key } = await withAdmin(() => api.post('/api/account/recovery-key', {}),
          { title: 'New recovery key', text: 'Enter your password to create a new recovery key.' });
        keyBox.replaceChildren(h('div.su-key.small', key),
          h('p.muted.small', 'Write it down or take a photo. Your old recovery key no longer works.'));
      } catch (e) {
        if (!e.cancelled) errorText(err, e.message);
      }
    });
    const lockSleep = toggle(store.state.settings.lockOnSleep, (v) => save({ lockOnSleep: v }, err), 'Require sign-in on wake');
    page.append(
      pageHead('Account', 'Your sign-in details.'),
      err,
      group(null, row(user.fullName || user.name, `Username: ${user.name}`, h('span.gr-avatar.small.acct', (user.fullName || user.name).slice(0, 1).toUpperCase()))),
      group('Password',
        row('Current password', null, h('div.slider-wrap.wide', current)),
        row('New password', null, h('div.slider-wrap.wide', next)),
        row('Confirm new password', null, h('div.slider-wrap.wide', again))),
      h('div.btn-row', change, note),
      group('Recovery key', row('Forgot your password?', 'A recovery key lets you set a new password from the sign-in or lock screen. Creating a new one replaces the old one.', makeKey), keyBox),
      group('Sign-in options',
        row('Require your password after sleep', 'Also when the screen turns off on its own', lockSleep),
        row('Lock now', 'Win+L', h('button.btn', { onclick: () => power('lock').catch((e) => errorText(err, e.message)) }, icon('lock'), 'Lock'))),
    );
    return { update: (_st, changed) => changed.has('settings') && lockSleep.set(store.state.settings.lockOnSleep) };
  },

  privacy(page, store) {
    const s = () => store.state.settings;
    const err = h('div.error-text', { hidden: true });
    const note = h('span.muted.small');
    const lockSleep = toggle(s().lockOnSleep, (v) => save({ lockOnSleep: v }, err), 'Lock on sleep');
    const lockNews = toggle(s().lockNews, (v) => save({ lockNews: v }, err), 'Show news on the lock screen');
    const camera = toggle(s().cameraAccess, (v) => save({ cameraAccess: v }, err), 'Camera access');
    const mic = toggle(s().micAccess, (v) => save({ micAccess: v }, err), 'Microphone access');
    const recent = toggle(s().keepRecent, (v) => save({ keepRecent: v }, err), 'Remember recent apps');
    const camInfo = h('small', 'Checking for a camera…');
    api.get('/api/camera').then((c) => {
      camInfo.textContent = c.camera ? 'The Camera app can use your webcam. Photos go to Pictures › Camera.'
        : 'No camera is connected. The Camera app appears when one is.';
    }, () => { camInfo.textContent = ''; });
    const clear = h('button.btn', 'Clear activity history');
    clear.addEventListener('click', () => saveSettings({ recent: [] })
      .then(() => { note.textContent = 'Cleared.'; }, (e) => errorText(err, e.message)));
    page.append(
      pageHead('Privacy & Security', 'Choose what PolyOS remembers, shows and lets apps use.'),
      err,
      group('Lock screen',
        row('Lock when the computer sleeps', 'And when the screen turns off on its own. Your password is needed to get back in.', lockSleep),
        row('Show news and performance on the lock screen', 'Anyone who sees the screen can read them', lockNews)),
      group('App permissions',
        h('div.row', h('div.row-label', h('span', 'Camera'), camInfo), camera),
        row('Microphone', 'Sound in Camera videos', mic)),
      group('Activity history',
        row('Remember recently opened apps', 'Shown in the Home Menu. Turning this off also clears the list.', recent),
        row('Clear activity history', null, h('div.btn-row.inline', clear, note))),
      group('Account security',
        row('Password and recovery key', 'Change your password, or make a new recovery key for “Forgot Password”',
          h('button.btn', { onclick: () => navigate('account') }, 'Open Account', icon('chevronRight')))),
      group('Vara', h('p.prose',
        'Simple requests to Vara are handled on this computer. Chat messages go to the AI service chosen in Vara settings. ',
        h('a', { href: '#', onclick: (e) => { e.preventDefault(); navigate('vara'); } }, 'Vara settings'), '.')),
    );
    function update() {
      const cur = s();
      lockSleep.set(cur.lockOnSleep);
      lockNews.set(cur.lockNews);
      camera.set(cur.cameraAccess);
      mic.set(cur.micAccess);
      recent.set(cur.keepRecent);
    }
    update();
    return { update: (_st, changed) => changed.has('settings') && update() };
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

let navigate = () => {};

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

  navigate = go;
  store.subscribe((state, changed) => pageApi?.update?.(state, changed));
  on('navigate', (e) => { if (e.surface === 'settings' && e.page) go(e.page); });
  go(params.get('page') || 'appearance');
}
