// Settings app: appearance, taskbar, Wi-Fi, sound, display, power, account, privacy & security,
// Vara, about.

import { watchJobs, withAdmin } from '../admin.js';
import { api, launch, on, params, power, saveSettings, withToken } from '../api.js';
import { VARA_PROVIDERS, errorText, group, packPanel, providerFor, row, slider, toggle, wifiPanel } from '../components.js';
import { fill, formatBytes, h, hexToHue, hueToHex, icon, networkLabel, throttle } from '../ui.js';

const PAGES = [
  ['display', 'Display', 'monitor'],
  ['sound', 'Sound', 'volume'],
  ['account', 'Account', 'user'],
  ['privacy', 'Privacy & Security', 'shield'],
  ['network', 'Wi-Fi & Network', 'wifi'],
  ['appearance', 'Appearance', 'palette'],
  ['taskbar', 'Taskbar & Desktop', 'taskbar'],
  ['gaming', 'Gaming', 'gamepad'],
  ['vara', 'Vara', 'chat'],
  ['apps', 'Apps', 'apps'],
  ['power', 'Power & Performance', 'bolt'],
  ['developer', 'Developer', 'code'],
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
    const err = h('div.error-text', { hidden: true });
    const outSel = h('select.select', { 'aria-label': 'Output device' });
    const inSel = h('select.select', { 'aria-label': 'Input device' });
    const micVol = slider({ label: 'Input volume', onInput: (v) => api.post('/api/sound/input', { level: v }) });
    const micValue = h('span.value');
    const micMute = toggle(false, (v) => api.post('/api/sound/input', { muted: v }).then(show, fail), 'Mute microphone');
    const body = h('div');
    const fail = (x) => errorText(err, x.message);
    // Every section has its own "Advanced" button: the full mixer (pavucontrol, installed with PolyOS) on the matching tab.
    const advanced = (tab, label = 'Advanced') => h('button.btn', {
      onclick: () => api.post('/api/sound/mixer', { tab }).then(() => errorText(err, ''), fail),
    }, label, icon('external'));
    outSel.addEventListener('change', () => api.post('/api/sound/device', { kind: 'output', name: outSel.value }).then(show, fail));
    inSel.addEventListener('change', () => api.post('/api/sound/device', { kind: 'input', name: inSel.value }).then(show, fail));
    page.append(pageHead('Sound', 'Speakers, headphones, microphones and each app’s volume.'), err, body);

    let devices = null;
    function show(d) {
      devices = d;
      errorText(err, '');
      fill(outSel, d.outputs.map((o) => h('option', { value: o.name }, o.description)));
      outSel.value = d.defaultOutput || '';
      fill(inSel, d.inputs.length ? d.inputs.map((o) => h('option', { value: o.name }, o.description)) : h('option', { value: '' }, 'No microphone found'));
      inSel.value = d.defaultInput || '';
      inSel.disabled = !d.inputs.length;
      const mic = d.inputs.find((o) => o.name === d.defaultInput);
      micVol.disabled = !mic;
      micVol.set(mic ? mic.level : 0);
      micValue.textContent = mic ? `${mic.level}%` : '';
      micMute.set(mic ? mic.muted : false);
    }
    function build() {
      const v = store.state.system.volume;
      fill(body,
        v.available
          ? group('Output',
            row('Output device', 'Where sound plays', outSel),
            row('Volume', null, h('div.slider-wrap', vol, value)),
            row('Mute', null, mute),
            row('Output settings', 'Balance, ports and each device’s volume', advanced('output')))
          : group('Output', row('No audio output found', 'Check that PipeWire is running and a device is connected'),
            row('Output settings', 'Devices, ports and levels', advanced('output'))),
        group('Input',
          row('Input device', 'The microphone apps use', inSel),
          row('Input volume', null, h('div.slider-wrap', micVol, micValue)),
          row('Mute microphone', null, micMute),
          row('Input settings', 'Levels, ports and each microphone', advanced('input'))),
        group('Apps',
          row('Volume for each app', 'Make one app louder or quieter than the rest', advanced('playback', 'Open')),
          row('Apps using the microphone', 'See and change what records sound', advanced('recording', 'Open'))),
        group('Advanced',
          row('Sound card profiles', 'Stereo, surround 5.1/7.1, HDMI audio, headset mode', advanced('configuration')),
          row('Full sound mixer', 'Every device and app in one place', advanced('playback', 'Open mixer'))),
      );
      if (devices) show(devices);
    }
    const refresh = () => api.get('/api/sound/devices').then(show, fail);
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
    refresh();
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
    const screens = h('div');
    const confirm = h('div.keep-bar', { hidden: true, role: 'alertdialog', 'aria-live': 'assertive' });
    const graphics = h('div');
    const fail = (x) => errorText(err, x.message);
    const ROTATE = [['normal', 'Landscape'], ['left', 'Portrait'], ['right', 'Portrait (flipped)'], ['inverted', 'Landscape (flipped)']];
    const friendly = (name) => (/^(eDP|LVDS|DSI)/.test(name) ? 'Built-in screen' : name.replace(/-\d+$/, (m) => ` ${m.slice(1)}`));
    let outputs = [];
    let countdown = null;

    page.append(
      pageHead('Display', 'Resolution, refresh rate, brightness and graphics.'),
      err, confirm,
      briGroup,
      screens,
      group('Scale', row('Display scale', 'Automatic picks 200% on high-density screens. Applies at next sign-in.', scale)),
      graphics,
      group('Arrangement', row('Position multiple displays', 'Drag screens to match how they sit on your desk',
        helperButton(store, 'arandr.desktop', 'Arrange displays', 'arandr'))),
    );

    const stateOf = (o) => ({ name: o.name, size: o.mode, rate: o.rate, rotation: o.rotation, primary: o.primary });
    function stopCountdown() {
      clearInterval(countdown);
      countdown = null;
      confirm.hidden = true;
    }
    // Change a screen, then ask to keep it: if the picture is gone, it goes back by itself after 15 seconds.
    function apply(o, patch) {
      const before = stateOf(o);
      const next = { ...before, ...patch };
      if (patch.size) next.rate = o.modes.find((m) => m.size === patch.size)?.rates[0] ?? null;
      api.post('/api/displays', next).then((r) => {
        errorText(err, '');
        show(r);
        stopCountdown();
        let left = 15;
        const text = h('span');
        const tick = () => { text.textContent = `Keep these display settings? Going back in ${left} s.`; };
        tick();
        fill(confirm, icon('monitor'), text, h('div.btn-row.tight',
          h('button.btn', { onclick: () => { stopCountdown(); api.post('/api/displays', before).then(show, fail); } }, 'Revert'),
          h('button.btn.primary', { onclick: stopCountdown }, 'Keep changes')));
        confirm.hidden = false;
        countdown = setInterval(() => {
          left -= 1;
          if (left > 0) return tick();
          stopCountdown();
          api.post('/api/displays', before).then(show, fail);
        }, 1000);
      }, (x) => { fail(x); show({ outputs, graphics: null }); });
    }

    function screenGroup(o) {
      const sizeSel = h('select.select', { 'aria-label': `${friendly(o.name)} resolution` },
        o.modes.map((m) => h('option', { value: m.size }, `${m.size.replace('x', ' × ')}${m.size === o.preferred ? ' (recommended)' : ''}`)));
      sizeSel.value = o.mode || '';
      sizeSel.addEventListener('change', () => apply(o, { size: sizeSel.value }));
      const rates = o.modes.find((m) => m.size === o.mode)?.rates || [];
      const rateSel = h('select.select', { 'aria-label': `${friendly(o.name)} refresh rate` },
        rates.map((r) => h('option', { value: String(r) }, `${Math.round(r * 100) / 100} Hz`)));
      rateSel.value = String(o.rate ?? '');
      rateSel.disabled = rates.length < 2;
      rateSel.addEventListener('change', () => apply(o, { rate: Number(rateSel.value) }));
      const rotSel = h('select.select', { 'aria-label': `${friendly(o.name)} orientation` },
        ROTATE.map(([v, t]) => h('option', { value: v }, t)));
      rotSel.value = o.rotation;
      rotSel.addEventListener('change', () => apply(o, { rotation: rotSel.value }));
      const best = rates.length ? Math.max(...rates) : null;
      return group(outputs.length > 1 ? `${friendly(o.name)}${o.primary ? ' · main display' : ''}` : 'Screen',
        o.active ? [
          row('Resolution', null, sizeSel),
          row('Refresh rate', best && o.rate && best - o.rate > 1 ? `This screen can go up to ${Math.round(best)} Hz for smoother motion` : 'How many times a second the picture updates', rateSel),
          row('Orientation', null, rotSel),
          outputs.length > 1 ? row('Make this my main display', 'The taskbar and new windows go here',
            toggle(o.primary, (v) => (v ? apply(o, { primary: true }) : show({ outputs, graphics: null })), 'Main display')) : null,
        ] : row('This screen is off', 'Turn it on with Arrange displays'));
    }

    function show(r) {
      outputs = r.outputs;
      fill(screens, outputs.length ? outputs.map(screenGroup)
        : group('Screen', row('Screen settings aren’t available', 'xrandr couldn’t read your screens')));
      if (r.graphics) {
        const drivers = h('button.btn', { onclick: () => api.post('/api/open', { app: 'drivers' }).catch(fail) }, 'Driver Manager', icon('external'));
        const nvidia = store.state.apps.find((a) => a.id === 'nvidia-settings.desktop');
        fill(graphics, group('Graphics',
          r.graphics.length ? r.graphics.map((g) => row(g.name.replace(/\s*\[[0-9a-f]{4}:[0-9a-f]{4}\]/gi, ''),
            g.driver ? `Driver: ${g.driver}` : 'No driver in use')) : row('Graphics card', 'Not detected'),
          row('Graphics drivers', 'Install NVIDIA or other recommended drivers', drivers),
          nvidia ? row('NVIDIA settings', 'Clocks, G-Sync, anti-aliasing and more', h('button.btn', { onclick: () => launch(nvidia.id) }, 'Open', icon('external'))) : null,
          row('Performance mode', 'Balanced, Performance or Maximum for games and 3D',
            h('button.btn', { onclick: () => navigate('power') }, 'Power & Performance', icon('chevronRight')))));
      }
    }

    function update() {
      const b = store.state.system.brightness;
      briGroup.hidden = !b.available;
      bri.set(b.level);
      value.textContent = `${b.level}%`;
      scale.value = store.state.settings.scale;
    }
    update();
    api.get('/api/displays').then(show, fail);
    return { update: (_st, changed) => (changed.has('system') || changed.has('settings')) && update(), close: stopCountdown };
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
    const checkup = h('div.checkup');
    const firewall = toggle(false, (v) => setSecurity('firewall', v), 'Firewall');
    const updates = toggle(false, (v) => setSecurity('updates', v), 'Automatic security updates');
    const secNote = h('p.muted.small.pad', { hidden: true });
    async function setSecurity(what, on) {
      errorText(err, '');
      try {
        await withAdmin(() => api.post('/api/security', { what, on }),
          { title: 'Security', text: 'Enter your password to change this.' });
        secNote.hidden = false;
        secNote.textContent = 'Working on it…';
      } catch (e) {
        if (!e.cancelled) errorText(err, e.message);
        loadSecurity();
      }
    }
    function loadSecurity() {
      api.get('/api/security').then((st) => {
        const item = (ok, title, good, bad, unknown) => h('div.check-item', { class: ok === null || ok === undefined ? 'unknown' : ok ? 'ok' : 'warn' },
          icon(ok ? 'check' : ok === false ? 'info' : 'shield'), h('span', h('b', title), h('small', ok === null || ok === undefined ? unknown : ok ? good : bad)));
        checkup.replaceChildren(
          item(st.firewall, 'Firewall', 'On: other computers can’t connect in', 'Off: turn it on below', 'Not installed'),
          item(st.updates, 'Security updates', 'Installed automatically', 'Off: turn them on below', 'Not set up'),
          item(st.lockOnSleep, 'Lock screen', 'Your password is needed after sleep', 'Off: anyone can use the computer after sleep', ''),
          item(st.recoveryKey, 'Recovery key', 'Set: you can reset a forgotten password', 'None: make one in Account', 'Made while installing'),
          item(st.apparmor, 'App protection (AppArmor)', 'On: apps are kept to what they need', 'Off', 'Not available'),
          item(st.secureBoot, 'Secure Boot', 'On: only signed software starts the computer', 'Off in your firmware settings', 'Not available on this computer'));
        firewall.set(!!st.firewall);
        updates.set(!!st.updates);
      }, (e) => errorText(err, e.message));
    }
    loadSecurity();
    const offSecurity = on('security', () => { secNote.hidden = true; loadSecurity(); });
    const offJob = on('job', (e) => {
      if (e.job.kind !== 'security') return;
      secNote.hidden = e.job.state === 'done';
      secNote.textContent = e.job.state === 'failed' ? e.job.error : e.job.message;
    });
    page.append(
      pageHead('Privacy & Security', 'Choose what PolyOS remembers, shows and lets apps use.'),
      err,
      group('Security checkup', checkup),
      group('Protection',
        row('Firewall', 'Blocks other computers from connecting to this one. Your apps still reach the internet.', firewall),
        row('Automatic security updates', 'Installs Debian’s security fixes in the background every day', updates),
        secNote),
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
    return { update: (_st, changed) => changed.has('settings') && update(), close: () => { offSecurity(); offJob(); } };
  },

  apps(page) {
    const err = h('div.error-text', { hidden: true });
    const startupBox = h('div');
    const listBox = h('div.app-list');
    const search = h('input.input', { placeholder: 'Search apps', spellcheck: 'false', 'aria-label': 'Search apps' });
    const addSel = h('select.select', { 'aria-label': 'App to start when you sign in' });
    const status = new Map(); // app id -> "Removing…" / error
    let data = null;
    let confirmFor = null;

    const setStartup = (r) => { data.startup = r.startup; renderStartup(); };
    function renderStartup() {
      const inList = new Set(data.startup.map((e) => e.id));
      fill(addSel, data.apps.filter((a) => !inList.has(a.id)).map((a) => h('option', { value: a.id }, a.name)));
      fill(startupBox,
        data.startup.length ? data.startup.map((e) => row(e.name, e.comment || (e.own ? 'Added by you' : ''),
          e.locked ? h('span.muted.small', 'PolyOS needs this') : toggle(e.enabled, (v) => api.post('/api/apps/startup', { id: e.id, enabled: v })
            .then(setStartup, (x) => errorText(err, x.message)), e.name),
          e.own ? h('button.icon-btn', { title: `Remove ${e.name} from startup`, 'aria-label': `Remove ${e.name} from startup`,
            onclick: () => api.post('/api/apps/startup/remove', { id: e.id }).then(setStartup, (x) => errorText(err, x.message)) }, icon('close')) : null))
          : h('p.prose', 'Nothing starts automatically when you sign in.'),
        row('Add an app', 'Start it every time you sign in', addSel, h('button.btn', {
          onclick: () => addSel.value && api.post('/api/apps/startup/add', { id: addSel.value }).then(setStartup, (x) => errorText(err, x.message)),
        }, icon('plus'), 'Add')));
    }
    const source = (a) => ({ debian: `Debian package ${a.package || ''}`.trim(), flatpak: 'Flathub', local: 'Added in your home folder' }[a.kind] || '');
    function renderApps() {
      const q = search.value.trim().toLowerCase();
      const list = data.apps.filter((a) => !q || a.name.toLowerCase().includes(q));
      fill(listBox, list.length ? list.map((a) => {
        let action;
        if (status.has(a.id)) action = h('span.muted.small', status.get(a.id));
        else if (!a.removable) action = h('span.muted.small', 'Part of PolyOS');
        else if (confirmFor === a.id) {
          action = h('div.btn-row.tight',
            h('button.btn', { onclick: () => { confirmFor = null; renderApps(); } }, 'Cancel'),
            h('button.btn.danger.solid', { onclick: () => uninstall(a) }, 'Uninstall'));
        } else action = h('button.btn', { onclick: () => { confirmFor = a.id; renderApps(); } }, 'Uninstall');
        return h('div.row.app-row', h('img.app-row-icon', { src: withToken(a.icon), alt: '' }),
          h('div.row-label', h('span', a.name), h('small', source(a))), action);
      }) : h('p.prose', 'No app matches.'));
    }
    async function uninstall(a) {
      confirmFor = null;
      status.set(a.id, 'Removing…');
      renderApps();
      try {
        const job = await withAdmin(() => api.post('/api/apps/uninstall', { id: a.id }),
          { title: `Uninstall ${a.name}`, text: 'Enter your password to remove this app.' });
        if (job && job.removed) { status.delete(a.id); load(); }
      } catch (x) {
        status.delete(a.id);
        if (!x.cancelled) errorText(err, x.message);
        renderApps();
      }
    }
    const offJobs = watchJobs((job) => {
      if (job.kind !== 'app' || !status.has(job.target)) return;
      if (job.state === 'running') status.set(job.target, job.message || 'Removing…');
      else {
        status.delete(job.target);
        if (job.state === 'failed') errorText(err, job.error || 'That app couldn’t be removed.');
        load();
      }
      renderApps();
    }).off;
    function load() {
      return api.get('/api/apps/manage').then((d) => { data = d; renderStartup(); renderApps(); }, (x) => errorText(err, x.message));
    }
    search.addEventListener('input', () => data && renderApps());
    page.append(
      pageHead('Apps', 'Uninstall apps, and choose what starts when you sign in.'),
      err,
      group('Startup apps', startupBox),
      group('Installed apps', h('div.slider-wrap.wide.app-search', search), listBox),
    );
    load();
    return { update: (_st, changed) => changed.has('apps') && load(), close: offJobs };
  },

  gaming(page, store) {
    const s = () => store.state.settings;
    const err = h('div.error-text', { hidden: true });
    const gameMode = toggle(s().gameMode, (v) => save({ gameMode: v }, err), 'Game Mode');
    const cloud = h('div.cloud-list', h('p.muted.small.pad', 'Loading…'));
    const loadCloud = () => api.get('/api/gaming/cloud').then(({ services, installed }) => {
      cloud.replaceChildren(...services.map((svc) => {
        const on = toggle(installed.includes(svc.id), (v) => {
          const next = v ? [...new Set([...installed, svc.id])] : installed.filter((i) => i !== svc.id);
          api.post('/api/gaming/cloud', { services: next }).then(loadCloud, (e) => errorText(err, e.message));
        }, svc.name);
        return row(svc.name, svc.summary, on);
      }));
    }, (e) => errorText(err, e.message));
    loadCloud();
    page.append(
      pageHead('Gaming', 'Games from Steam, Windows games with Wine, cloud gaming and Game Mode.'),
      err,
      group('Game Mode',
        row('Game Mode', 'When a game is full screen: the performance power mode, no sleeping or locking, and PolyOS’s background work steps back until you close it.', gameMode)),
      group('Cloud gaming', h('p.muted.small.pad', 'Stream games from the cloud: no downloads, and they run well on any computer. '
        + 'These come with PolyOS; switch one on to show it in your apps. They open in Chromium, which PolyOS includes.'), cloud),
      group('Gaming apps', row('Steam, Heroic, Lutris and more', 'Get them from PolyMarket’s Games section.',
        h('button.btn', { onclick: () => api.post('/api/open', { app: 'store' }).catch((e) => errorText(err, e.message)) }, 'Open PolyMarket'))),
      group('Tips', h('p.prose',
        'Windows games in Steam: Steam > Settings > Compatibility > “Enable Steam Play for all other titles” (Proton). ',
        'Add “gamemoderun %command%” to a game’s Launch Options for GameMode. ',
        'Other Windows games and apps: open Bottles and create a “Gaming” bottle. ',
        'Graphics drivers: Settings > About > Driver Manager.')),
    );
    return { update: (_st, changed) => changed.has('settings') && gameMode.set(s().gameMode) };
  },

  developer(page, store) {
    const s = () => store.state.settings;
    const err = h('div.error-text', { hidden: true });
    const note = h('span.muted.small');
    const devMode = toggle(s().developerMode, (v) => save({ developerMode: v }, err), 'Developer mode');
    const inspector = toggle(s().devInspector, (v) => save({ devInspector: v }, err), 'Inspect element');
    const act = (action, label, ico) => h('button.btn', {
      onclick: () => api.post('/api/dev', { action }).then((r) => {
        note.textContent = action === 'reset' ? (r.path ? `Your changes were moved to ${r.path}.` : 'Nothing to reset.') : '';
      }, (e) => errorText(err, e.message)),
    }, icon(ico), label);
    const reload = h('button.btn.primary', { onclick: () => api.post('/api/shell/restart', {}).catch((e) => errorText(err, e.message)) },
      icon('refresh'), 'Reload the interface');
    page.append(
      pageHead('Developer', 'Change PolyOS itself: its look, its screens and its code.'),
      err,
      group(null,
        row('Developer mode', 'Files in your interface folder replace PolyOS’s built-in ones, on every screen', devMode),
        row('Inspect element', 'Right-click any PolyOS screen to open the web inspector (after reloading the interface)', inspector)),
      group('Change the interface',
        row('Your interface folder', 'css/user.css is added to every screen. Copy any other file here, with the same path, to replace it.',
          act('folder', 'Open folder', 'folder')),
        row('PolyOS’s interface', 'A fresh copy of the built-in files in ~/PolyOS-UI, to read and copy from', act('source', 'Copy to my files', 'download')),
        row('Apply your changes', 'Reloads the taskbar, desktop and menus. Your apps keep running.', reload),
        row('Undo everything', 'Moves your interface folder aside (nothing is deleted)', act('reset', 'Reset', 'restart'))),
      h('div.btn-row', note),
      group('Coding tools', packPanel('developer')),
      group('If something breaks', h('p.prose',
        'Press Ctrl+Alt+T for a terminal and run ', h('code', 'polyos-ctl dev off'),
        '. PolyOS goes back to its built-in interface; your files stay in ~/.config/polyos/ui.')),
    );
    const update = () => { devMode.set(s().developerMode); inspector.set(s().devInspector); };
    update();
    return { update: (_st, changed) => changed.has('settings') && update() };
  },

  vara(page) {
    const PRESETS = VARA_PROVIDERS;
    const err = h('div.error-text', { hidden: true });
    const note = h('span.muted.small');
    const endpoint = h('input.input', { placeholder: 'https://ollama.com/v1', spellcheck: 'false', 'aria-label': 'Endpoint' });
    const model = h('input.input', { placeholder: 'gpt-oss:120b', spellcheck: 'false', 'aria-label': 'Model' });
    const key = h('input.input', { type: 'password', placeholder: 'Paste your API key', autocomplete: 'off', 'aria-label': 'API key' });
    const presets = h('div.swatches', PRESETS.map((p) => h('button.pill-btn', {
      onclick: () => { endpoint.value = p.endpoint; model.value = p.model; note.textContent = p.keyHint; },
    }, p.label)));
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
        await api.post('/api/vara/config', { endpoint: endpoint.value, model: model.value, provider: providerFor(endpoint.value),
          ...(key.value ? { apiKey: key.value } : {}) });
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
    // ---- the agent: workspace, approvals, tools, skills, memory ----
    const agentNote = h('p.prose.small', { hidden: true });
    const workspace = h('input.input', { placeholder: '~/Projects', spellcheck: 'false', 'aria-label': 'Workspace folder' });
    const saveAgent = async (patch) => {
      errorText(err, '');
      try {
        const c = await api.post('/api/vara/config', patch);
        approval.set(c.approval);
        workspace.value = c.workspace;
        agentNote.textContent = c.approval === 'auto'
          ? 'Vara now changes files and runs programs without asking. Use this only on a computer you can set up again.' : '';
        agentNote.hidden = !agentNote.textContent;
      } catch (e) {
        errorText(err, e.message);
      }
    };
    const approval = seg('When Vara asks first', [
      ['ask', 'Always'], ['workspace', 'Only outside the workspace'], ['auto', 'Never']], (v) => saveAgent({ approval: v }));
    workspace.addEventListener('change', () => saveAgent({ workspace: workspace.value }));
    const agentGroup = group('Agent',
      row('Workspace', 'Where Vara puts new projects and runs commands', h('div.slider-wrap.wide', workspace)),
      row('Ask before changes', 'Looking never needs a yes. Running programs always does, unless you choose Never', approval),
      agentNote);
    const toolsBody = h('div');
    const toolsGroup = group('Tools', toolsBody);
    const skillsBody = h('div');
    const skillsGroup = group('Skills', skillsBody);
    const memoryBody = h('div');
    const memoryGroup = group('Memory', memoryBody);

    function showMemory(notes) {
      fill(memoryBody,
        notes.length
          ? notes.map((n, i) => row(n.note, `Saved ${n.added || ''}`.trim(), h('button.btn', {
            onclick: () => api.post('/api/vara/forget', { index: i }).then((r) => showMemory(r.memory), (e) => errorText(err, e.message)),
          }, 'Forget')))
          : h('p.prose', 'Nothing yet. Vara saves short notes when it learns something lasting, like your board, your printer or where your projects are.'),
        notes.length ? h('div.btn-row', h('button.btn', {
          onclick: () => api.post('/api/vara/forget', {}).then((r) => showMemory(r.memory), (e) => errorText(err, e.message)),
        }, 'Forget everything')) : null);
    }

    function loadAgent() {
      api.get('/api/vara/config').then((c) => { workspace.value = c.workspace; approval.set(c.approval); }, () => {});
      api.get('/api/vara/tools').then((t) => {
        const { installed, missing } = t.programs;
        fill(toolsBody,
          h('p.prose', 'Vara reads and writes files, runs commands and git, measures 3D models and reads web pages',
            installed.length ? `, and uses ${installed.join(', ')} on this computer.` : '.'),
          missing.length ? row('Not installed', missing.join(', '), h('button.btn', {
            onclick: () => api.post('/api/open', { app: 'store' }).catch((e) => errorText(err, e.message)),
          }, 'Open PolyMarket')) : null);
        fill(skillsBody,
          t.skills.map((sk) => row(sk.own ? `${sk.name} (yours)` : sk.name, sk.description, null)),
          h('p.prose.small', 'Skills are step-by-step know-how Vara reads before a task. Add your own as Markdown files in ',
            h('code', t.skillsFolder.replace(/^\/home\/[^/]+/, '~')), ', or ask Vara to save one after it works something out.'));
        showMemory(t.memory);
      }, (e) => errorText(err, e.message));
    }

    page.append(
      pageHead('Vara', 'Your PolyOS agent for code, 3D models and robots, powered by the AI model you choose.'),
      err,
      group('Quick setup', row('Provider', 'Fills in the address and a model; then add your key from that service', presets)),
      group('Connection',
        row('Endpoint', 'Any OpenAI-compatible API', h('div.slider-wrap.wide', endpoint)),
        row('Model', null, h('div.slider-wrap.wide', model)),
        row('API key', 'Stored only on this computer, readable only by you', h('div.slider-wrap.wide', key))),
      h('div.btn-row', saveBtn, testBtn, note),
      agentGroup,
      toolsGroup,
      skillsGroup,
      memoryGroup,
      group('Privacy', h('p.prose',
        'Simple requests like “open Firefox” or “volume 40” are handled on this computer. Other messages, and what Vara ',
        'reads while working (files, command output), go to the endpoint above; with a cloud provider they leave this computer, ',
        'so don’t share passwords with Vara. Vara never opens SSH keys, saved passwords, browser data or its own API key.')),
    );
    load();
    loadAgent();
    return null;
  },

  about(page, store) {
    const { version, hostname } = store.state;
    const specs = h('div');
    const devMode = toggle(store.state.settings.developerMode, (v) => save({ developerMode: v }), 'Developer mode');
    const edition = { regular: 'Regular', developer: 'Developer', gaming: 'Gaming' }[store.state.settings.edition] || 'Regular';
    page.append(
      h('div.about-hero',
        h('img', { src: '/img/logo.svg', alt: '' }),
        h('div', h('h1', 'PolyOS'), h('p.muted', `Version ${version} · ${edition} edition`))),
      specs,
      group('Tools',
        row('Task Manager', 'See what’s running and end apps that stopped responding (Ctrl+Shift+Esc)',
          h('button.btn', { onclick: () => api.post('/api/open', { app: 'taskmgr' }) }, 'Open', icon('external'))),
        row('Driver Manager', 'Install graphics, Wi-Fi and other drivers',
          h('button.btn', { onclick: () => api.post('/api/open', { app: 'drivers' }) }, 'Open', icon('external'))),
        row('PolyMarket', 'Get trusted apps', h('button.btn', { onclick: () => api.post('/api/open', { app: 'store' }) }, 'Open', icon('external'))),
        row('Developer mode', 'Change PolyOS’s own interface. Adds the Developer page to Settings.', devMode)),
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

  const syncNav = () => { buttons.get('developer').hidden = !store.state.settings.developerMode; };
  syncNav();
  store.subscribe((_st, changed) => { if (changed.has('settings')) syncNav(); });

  function go(id) {
    if (!pages[id]) id = PAGES[0][0];
    if (id === current) return;
    pageApi?.close?.();
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
  go(params.get('page') || PAGES[0][0]);
}
