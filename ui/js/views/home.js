// PolyOS Home Menu (the "start" popup), following the PolyOS 7 layout:
//   date card | calendar card
//   Ask Vara  | brightness (or Wi-Fi)
//   Run CMD   | volume
//   pinned apps
//   power · settings · Launcher (All Apps)

import { api, closePopup, launch, openSettings, withToken } from '../api.js';
import { fillSlider } from '../components.js';
import { greeting, h, icon, networkIcon, networkLabel, volumeIcon } from '../ui.js';

function ordinal(n) {
  const tens = n % 100;
  if (tens >= 11 && tens <= 13) return `${n}th`;
  return `${n}${{ 1: 'st', 2: 'nd', 3: 'rd' }[n % 10] || 'th'}`;
}

const popup = (view, data, extra = {}) => api.post('/api/popup', { view, data, ...extra }).catch((err) => console.warn(err.message));

export default function home(root, store) {
  root.classList.add('home');
  const now = new Date();
  const { user } = store.state;
  const first = (user.fullName || user.name).split(' ')[0];

  // ---- row 1: date + calendar ---------------------------------------------------
  const dateCard = h('button.hm-card.hm-date', { title: 'Open the calendar', onclick: () => popup('calendar') },
    h('span.hm-date-main', `${now.toLocaleDateString([], { month: 'long' })} ${ordinal(now.getDate())}`),
    h('span.hm-date-year', String(now.getFullYear())),
    h('span.hm-date-sub', store.state.env.live ? 'Welcome to PolyOS 7' : `${greeting(now)}, ${first}`));
  const calCard = h('button.hm-card.hm-cal', { title: 'Open the calendar', onclick: () => popup('calendar') },
    h('span.hm-cal-day', String(now.getDate())),
    h('span.hm-cal-meta', now.toLocaleDateString([], { weekday: 'long' }), h('br'), now.toLocaleDateString([], { month: 'short', year: 'numeric' })));

  // ---- rows 2-3: actions + sliders ----------------------------------------------
  const askVara = h('button.hm-card.hm-action', { onclick: () => popup('vara') },
    h('img.hm-vara', { src: '/img/vara.png', alt: '' }), h('span', 'Ask Vara'));
  const runCmd = h('button.hm-card.hm-action', { onclick: () => popup('run') },
    h('span.hm-code', '< >'), h('span', 'Run CMD'));

  const brightness = fillSlider({ min: 5, label: 'Brightness', icon: () => icon('sun'),
    onInput: (v) => api.post('/api/brightness', { level: v }) });
  const volume = fillSlider({ label: 'Volume', icon: () => volumeIcon(store.state.system.volume),
    onIcon: () => api.post('/api/volume', { toggleMute: true }),
    onInput: (v) => api.post('/api/volume', { level: v }) });
  // Desktops without a backlight get a Wi-Fi tile in the brightness slot.
  const wifi = h('button.hm-card.hm-wifi', { onclick: () => popup('quick', { sub: 'wifi' }, { height: 470 }) });

  // ---- row 4: pinned apps -------------------------------------------------------
  const pinned = h('div.hm-card.hm-pinned');

  // ---- footer -------------------------------------------------------------------
  const footer = h('div.hm-footer',
    h('button.hm-round', { title: 'Power options', onclick: () => popup('power') }, icon('power')),
    h('button.hm-round', { title: 'Settings', onclick: () => { openSettings(); closePopup(); } }, icon('settings')),
    h('button.hm-card.hm-launcher', { onclick: () => popup('launcher') },
      icon('apps'), h('span.hm-launcher-text', h('b', 'Launcher'), h('small', '(All Apps)'))));

  const grid = h('div.hm-grid', dateCard, calCard, askVara, h('div.hm-slot-top'), runCmd, volume);
  root.append(grid, pinned, footer);
  const topSlot = grid.querySelector('.hm-slot-top');

  function renderSystem() {
    const { brightness: bri, volume: vol, network } = store.state.system;
    const want = bri.available ? brightness : wifi;
    if (topSlot.firstChild !== want) topSlot.replaceChildren(want);
    brightness.set(bri.level);
    volume.set(vol.muted ? 0 : vol.level);
    volume.refreshIcon();
    volume.classList.toggle('disabled', !vol.available);
    wifi.replaceChildren(h('span.hm-wifi-ico', networkIcon(network)),
      h('span.hm-wifi-text', h('b', network.kind === 'ethernet' ? 'Ethernet' : 'Wi-Fi'), h('small', networkLabel(network))));
  }

  const appButton = (app) => h('button.hm-app', {
    title: app.name,
    onclick: () => { launch(app.id).catch((err) => console.warn(err.message)); closePopup(); },
  }, h('img', { src: withToken(app.icon), alt: '', draggable: 'false' }), h('span', app.name));

  // Pinned apps, then recently opened ones that aren't pinned.
  function renderPinned() {
    const { apps: all, settings } = store.state;
    const byId = new Map(all.filter((a) => settings.showAllApps || !a.hidden).map((a) => [a.id, a]));
    const pins = settings.pinned.map((id) => byId.get(id)).filter(Boolean).slice(0, 5);
    const recent = settings.recent.filter((id) => !settings.pinned.includes(id))
      .map((id) => byId.get(id)).filter(Boolean).slice(0, 5);
    const items = pins.map(appButton);
    if (recent.length) items.push(h('span.hm-caption', 'Recent'), ...recent.map(appButton));
    pinned.replaceChildren(...(items.length ? items : [h('p.hm-empty', 'Pin apps from the Launcher to see them here.')]));
  }

  // Typing anywhere starts a search in the launcher, like PolyOS's search bar.
  const onKey = (e) => {
    if (e.key.length === 1 && !e.ctrlKey && !e.altKey && !e.metaKey && e.key.trim()) {
      e.preventDefault();
      popup('launcher', { focus: true, q: e.key });
    }
  };
  document.addEventListener('keydown', onKey);

  const unsubscribe = store.subscribe((_s, changed) => {
    if (changed.has('system')) renderSystem();
    if (changed.has('apps') || changed.has('settings')) renderPinned();
  });
  renderSystem();
  renderPinned();
  return () => {
    unsubscribe();
    document.removeEventListener('keydown', onKey);
  };
}
