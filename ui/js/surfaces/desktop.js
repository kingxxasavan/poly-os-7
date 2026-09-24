// Desktop: wallpaper, clock widget, installer card on live media, right-click menu.

import { api, launch, openSettings, withToken } from '../api.js';
import { clockTicker, fmtDate, fmtTime, greeting, h, icon } from '../ui.js';

export function mount(root, store) {
  root.className = 'desktop';
  const wall = h('div.wallpaper');
  const clock = h('div.desk-clock');
  root.append(wall, clock);

  let wallpaperKey = null;
  function renderWallpaper() {
    const key = store.state.settings.wallpaper;
    if (key === wallpaperKey) return;
    wallpaperKey = key;
    const url = withToken(`/wallpaper/current?v=${encodeURIComponent(key)}`);
    const img = new Image();
    img.onload = () => {
      wall.style.backgroundImage = `url("${url}")`;
      wall.classList.add('ready');
      hideSplash();
    };
    img.onerror = () => {
      wall.classList.add('ready');
      hideSplash();
    };
    img.src = url;
  }

  function renderClock(now = new Date()) {
    const { settings, user } = store.state;
    clock.hidden = !settings.desktopClock;
    if (clock.hidden) return;
    const first = (user.fullName || user.name).split(' ')[0];
    clock.replaceChildren(
      h('div.desk-time', fmtTime(now, settings, false)),
      h('div.desk-date', fmtDate(now)),
      h('div.desk-greet', `${greeting(now)}, ${first}`),
    );
  }

  // Startup splash, as PolyOS shows while it finishes setting up.
  const splash = h('div.splash', h('img.splash-logo', { src: '/img/logo-white.svg', alt: '' }), h('div.splash-text', 'Finishing up…'));
  root.append(splash);
  const started = Date.now();
  const hideSplash = () => {
    setTimeout(() => {
      splash.classList.add('done');
      splash.addEventListener('transitionend', () => splash.remove(), { once: true });
    }, Math.max(0, 1400 - (Date.now() - started)));
  };

  // Live USB: the PolyOS "It's time to get started" card.
  const { env } = store.state;
  if (env.live && env.installer) {
    const card = h('div.welcome',
      h('div.welcome-main',
        h('h2', 'It’s time to get started.'),
        h('p', 'Install PolyOS on this computer, or keep exploring first. Nothing is saved until you install.'),
        h('button.choice', { onclick: () => launch(env.installer) },
          h('span.choice-text', h('b', 'Install PolyOS'), h('small', 'Start a fresh install')),
          h('img', { src: '/img/logo-white.svg', alt: '' })),
        h('button.choice.secondary', { onclick: () => card.remove() },
          h('span.choice-text', h('b', 'Keep exploring'), h('small', 'Try PolyOS from this USB drive')),
          icon('arrowRight'))),
      h('img.welcome-mark', { src: '/img/logo.svg', alt: '' }));
    root.append(card);
  }

  // ---- context menu ------------------------------------------------------------
  let menu = null;
  const closeMenu = () => {
    menu?.remove();
    menu = null;
  };
  const items = [
    ['image', 'Change wallpaper', () => openSettings('appearance')],
    ['terminal', 'Open Terminal', () => api.post('/api/run', { what: 'terminal' })],
    ['folder', 'Open Files', () => api.post('/api/run', { what: 'files' })],
    null,
    ['settings', 'Settings', () => openSettings()],
    ['info', 'About PolyOS', () => openSettings('about')],
  ];
  root.addEventListener('contextmenu', (e) => {
    e.preventDefault();
    closeMenu();
    menu = h(
      'div.menu',
      { role: 'menu' },
      items.map((it) =>
        it
          ? h('button.menu-item', { role: 'menuitem', onclick: () => { closeMenu(); it[2]().catch?.((err) => console.warn(err.message)); } },
            icon(it[0]), it[1])
          : h('div.menu-sep'),
      ),
    );
    root.append(menu);
    const { innerWidth: w, innerHeight: hgt } = window;
    const r = menu.getBoundingClientRect();
    menu.style.left = `${Math.min(e.clientX, w - r.width - 8)}px`;
    menu.style.top = `${Math.min(e.clientY, hgt - r.height - 8)}px`;
  });
  root.addEventListener('pointerdown', (e) => {
    if (menu && !menu.contains(e.target)) closeMenu();
  });
  window.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeMenu(); });
  window.addEventListener('blur', closeMenu);

  store.subscribe((_s, changed) => {
    if (changed.has('settings')) {
      renderWallpaper();
      renderClock();
    }
  });
  renderWallpaper();
  clockTicker(renderClock, () => false);
}
