// Quick settings: Wi-Fi, volume, brightness, battery, shortcuts.

import { api, closePopup, openSettings, power } from '../api.js';
import { slider, wifiPanel } from '../components.js';
import { h, icon, networkIcon, networkLabel, volumeIcon } from '../ui.js';

const WIFI_HEIGHT = 470;

// The Wi-Fi list is the same popup reopened with data.sub = 'wifi' and a taller size.
const reopen = (store, data, height) =>
  api.post('/api/popup', { view: 'quick', anchorX: store.state.popup?.anchorX ?? null, data, height })
    .catch((err) => console.warn(err.message));

export default function quick(root, store, data) {
  if (data.sub === 'wifi') return wifiList(root, store);
  const sys = () => store.state.system;
  const main = h('div.qs');
  root.append(main);

  // ---- tiles ---------------------------------------------------------------------
  const wifiTile = h('div.tile');
  const wifiToggle = h('button.tile-main', { title: 'Turn Wi-Fi on or off' });
  const wifiMore = h('button.tile-more', { title: 'Choose a network' }, icon('chevronRight'));
  wifiTile.append(wifiToggle, wifiMore);
  wifiToggle.addEventListener('click', () => {
    const net = sys().network;
    if (!net.wifiDevice) return;
    api.post('/api/wifi/enabled', { enabled: !net.wifiEnabled }).catch((err) => console.warn(err.message));
  });

  const muteTile = h('div.tile', h('button.tile-main'));
  muteTile.firstChild.addEventListener('click', () => api.post('/api/volume', { toggleMute: true }));

  // ---- sliders -------------------------------------------------------------------
  const volSlider = slider({ label: 'Volume', onInput: (v) => api.post('/api/volume', { level: v }) });
  const volBtn = h('button.icon-btn', { title: 'Mute', onclick: () => api.post('/api/volume', { toggleMute: true }) });
  const volRow = h('div.qs-slider', volBtn, volSlider);
  const briSlider = slider({ min: 5, label: 'Brightness', onInput: (v) => api.post('/api/brightness', { level: v }) });
  const briRow = h('div.qs-slider', h('span.icon-btn.static', icon('sun')), briSlider);

  // ---- footer --------------------------------------------------------------------
  const battery = h('div.qs-battery');
  const footer = h(
    'div.qs-footer',
    battery,
    h('div.footer-actions',
      h('button.icon-btn', { title: 'Settings', onclick: () => { openSettings(); closePopup(); } }, icon('settings')),
      h('button.icon-btn', { title: 'Lock', onclick: () => power('lock') }, icon('lock')),
      h('button.icon-btn', { title: 'Power options', onclick: () => api.post('/api/popup', { view: 'start' }) }, icon('power'))),
  );

  main.append(h('div.qs-tiles', wifiTile, muteTile), volRow, briRow, footer);

  wifiMore.addEventListener('click', () => reopen(store, { sub: 'wifi' }, WIFI_HEIGHT));

  function render() {
    const { network, volume, brightness, battery: bat } = sys();
    const wifiOn = network.available && network.wifiDevice && network.wifiEnabled;
    wifiTile.classList.toggle('on', !!wifiOn || network.kind === 'ethernet');
    wifiTile.classList.toggle('disabled', !network.wifiDevice);
    wifiToggle.replaceChildren(
      h('span.tile-ico', networkIcon(network)),
      h('span.tile-text', h('b', network.kind === 'ethernet' ? 'Ethernet' : 'Wi-Fi'), h('small', networkLabel(network))),
    );
    wifiMore.hidden = !network.wifiDevice;

    muteTile.classList.toggle('on', volume.available && !volume.muted);
    muteTile.classList.toggle('disabled', !volume.available);
    muteTile.firstChild.replaceChildren(
      h('span.tile-ico', volumeIcon(volume)),
      h('span.tile-text', h('b', 'Sound'), h('small', !volume.available ? 'No output' : volume.muted ? 'Muted' : 'On')),
    );

    volRow.hidden = !volume.available;
    volBtn.replaceChildren(volumeIcon(volume));
    volSlider.set(volume.muted ? 0 : volume.level);
    briRow.hidden = !brightness.available;
    briSlider.set(brightness.level);

    battery.replaceChildren(
      ...(bat.present
        ? [icon('battery', bat.level, bat.charging), h('span', `${bat.level}%`), h('small', bat.charging ? 'Charging' : bat.plugged ? 'Plugged in' : 'On battery')]
        : []),
    );
  }

  const unsubscribe = store.subscribe((_s, changed) => {
    if (changed.has('system')) render();
  });
  render();
  return unsubscribe;
}

function wifiList(root, store) {
  const wifi = wifiPanel(store, { compact: true });
  root.append(h('div.qs-sub',
    h('div.qs-sub-head',
      h('button.icon-btn', { title: 'Back', onclick: () => reopen(store, {}, null) }, icon('chevronLeft')),
      h('span', 'Wi-Fi')),
    h('div.qs-sub-body', wifi.el),
    h('div.qs-sub-foot',
      h('button.link-btn', { onclick: () => { openSettings('network'); closePopup(); } }, 'More Wi-Fi settings'))));
  return store.subscribe((_s, changed) => {
    if (changed.has('system')) wifi.update();
  });
}
