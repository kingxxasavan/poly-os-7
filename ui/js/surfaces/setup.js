// First-run setup ("It's time to get started"), after the PolyOS 7 installer and Welcome Guide.

import { api, saveSettings, withToken } from '../api.js';
import { wifiPanel } from '../components.js';
import { fill, h, icon, networkLabel } from '../ui.js';

const ACCENTS = ['#678fd9', '#9b7fe0', '#d97fb8', '#e0906a', '#d9c46a', '#81d862', '#5fc4c4', '#b5b5b5'];
const TOUR = [
  ['Home Menu', 'Click the PolyOS logo in the dock (or tap the Super key) to open the Home Menu. Your quick apps, settings and power options live here.'],
  ['Launcher', 'Want to see all of your installed apps? The launcher button opens a multi-page menu of every app. Use Pin Apps to add them to the dock.'],
  ['Files', 'Files browses everything on your computer. Deleted items go to the Trash first, so you can always restore them.'],
  ['Shortcuts', 'Super+S opens the launcher, Super+R runs a command, Super+E opens Files and Super+L locks the screen.'],
];

export function mount(root, store) {
  root.className = 'setup';
  const wall = h('div.su-wall');
  const card = h('section.su-card');
  const dots = h('div.su-dots');
  root.append(wall, card, dots);

  let step = 0;
  let wifi = null;
  const steps = [welcome, look, connect, tour, done];

  function setWall() {
    wall.style.backgroundImage = `url("${withToken(`/wallpaper/current?v=${encodeURIComponent(store.state.settings.wallpaper)}`)}")`;
  }

  function go(n) {
    step = Math.max(0, Math.min(steps.length - 1, n));
    wifi = null;
    card.classList.remove('enter');
    void card.offsetWidth;
    card.classList.add('enter');
    fill(card, ...steps[step]());
    fill(dots, ...steps.map((_, i) => h('span', { class: i === step ? 'on' : i < step ? 'done' : '' })));
  }

  const nav = (nextLabel = 'Next', { skip = false } = {}) => h('div.su-nav',
    step > 0 ? h('button.pill-btn', { onclick: () => go(step - 1) }, icon('chevronLeft'), 'Back') : h('span'),
    h('div.su-nav-right',
      skip ? h('button.pill-btn.ghost', { onclick: () => go(step + 1) }, 'Skip') : null,
      h('button.pill-btn.on', { onclick: () => go(step + 1) }, nextLabel, icon('chevronRight'))));

  const choice = (title, sub, trailing, onclick, secondary = false) => h('button.su-choice', { class: secondary ? 'secondary' : '', onclick },
    h('span.su-choice-text', h('b', title), h('small', sub)), trailing);

  function welcome() {
    return [
      h('div.su-split',
        h('div.su-main',
          h('h1', 'It’s time to get started.'),
          h('p.su-sub', 'Pick an option to set up PolyOS, or skip ahead with the defaults. You can change everything later in Settings.'),
          choice('Set up PolyOS', 'Choose your look and connect to Wi-Fi',
            h('img', { src: '/img/logo-white.svg', alt: '' }), () => go(1)),
          choice('Use the defaults', 'Jump straight to the desktop', icon('arrowRight'), finish, true)),
        h('img.su-mark', { src: '/img/logo-white.svg', alt: '' })),
    ];
  }

  function look() {
    const s = store.state.settings;
    const walls = h('div.su-walls');
    api.get('/api/wallpapers').then((list) => {
      fill(walls, ...list.map((w) => h('button.su-wall', {
        class: w.id === store.state.settings.wallpaper ? 'on' : '',
        style: { backgroundImage: `url("${withToken(w.url)}")` },
        onclick: async (e) => {
          const picked = e.currentTarget; // (null again after the await)
          await saveSettings({ wallpaper: w.id });
          walls.querySelectorAll('.su-wall').forEach((el) => el.classList.toggle('on', el === picked));
        },
      }, h('span', w.name))));
    });
    const swatches = h('div.su-swatches', ACCENTS.map((c) => h('button.swatch', {
      class: c === s.accent ? 'sel' : '', style: { background: c }, title: c,
      onclick: async (e) => {
        const picked = e.currentTarget;
        await saveSettings({ accent: c });
        swatches.querySelectorAll('.swatch').forEach((el) => el.classList.toggle('sel', el === picked));
      },
    })));
    return [
      h('h1', 'Make it yours'),
      h('p.su-sub', 'Choose a wallpaper and an accent color. They apply right away.'),
      walls,
      h('div.su-row', h('b', 'Accent color'), swatches),
      nav(),
    ];
  }

  function connect() {
    const net = store.state.system.network;
    let body;
    if (net.kind === 'ethernet' || (net.kind === 'wifi' && !net.wifiDevice)) {
      body = h('div.su-status', icon('check'), h('span', `You’re online: ${networkLabel(net)}.`));
    } else if (net.available && net.wifiDevice) {
      wifi = wifiPanel(store);
      body = h('div.su-wifi', wifi.el);
    } else {
      body = h('div.su-status', icon('wifiOff'), h('span', 'No network adapter was found. You can connect later from quick settings.'));
    }
    return [h('h1', 'Get connected'), h('p.su-sub', 'Connect to Wi-Fi to get updates and use the web.'), body, nav('Next', { skip: true })];
  }

  function tour() {
    return [
      h('h1', 'Welcome to PolyOS'),
      h('p.su-sub', 'A quick tour of the PolyOS desktop.'),
      h('div.su-tour', TOUR.map(([title, text]) => h('div.su-tip', h('b', title), h('p', text)))),
      nav(),
    ];
  }

  function done() {
    return [
      h('div.su-done',
        h('img.su-done-logo', { src: '/img/logo-white.svg', alt: '' }),
        h('h1', 'You’re all set.'),
        h('p.su-sub', 'Enjoy PolyOS. Settings has everything you chose here, whenever you want to change it.'),
        h('button.pill-btn.on.big', { onclick: finish }, 'Start using PolyOS', icon('arrowRight'))),
      h('div.su-nav', h('button.pill-btn', { onclick: () => go(step - 1) }, icon('chevronLeft'), 'Back'), h('span')),
    ];
  }

  async function finish() {
    root.classList.add('leaving');
    try {
      await api.post('/api/setup/done', {});
    } catch (err) {
      root.classList.remove('leaving');
      console.warn(err.message);
    }
  }

  store.subscribe((_s, changed) => {
    if (changed.has('settings')) setWall();
    if (changed.has('system')) wifi?.update();
  });
  setWall();
  go(0);
}
