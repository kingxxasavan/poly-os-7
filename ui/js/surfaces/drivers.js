// Driver Manager: finds graphics, Wi-Fi, Bluetooth and audio hardware and installs the drivers
// and firmware that make it work best (NVIDIA, AMD, Intel, Broadcom, ...).

import { watchJobs, withAdmin } from '../admin.js';
import { api, power } from '../api.js';
import { fill, h, icon } from '../ui.js';

const KIND_ICON = { graphics: 'monitor', wifi: 'wifi', bluetooth: 'bluetooth', audio: 'volume', network: 'ethernet', firmware: 'chip' };
const KIND_LABEL = { graphics: 'Graphics', wifi: 'Wi-Fi', bluetooth: 'Bluetooth', audio: 'Sound', network: 'Network', firmware: 'Firmware' };

export function mount(root) {
  root.className = 'drivers';
  document.title = 'Driver Manager';
  const list = h('div.dm-list');
  const banner = h('div.dm-banner', { hidden: true });
  const progress = h('div.dm-progress', { hidden: true });
  const scanBtn = h('button.pill-btn', { onclick: () => scan() }, icon('refresh'), 'Scan again');
  const allBtn = h('button.pill-btn.on', { disabled: true }, icon('download'), 'Install all recommended');
  root.append(
    h('header.dm-hero',
      h('img', { src: '/img/drivers.svg', alt: '' }),
      h('div', h('h1', 'Driver Manager'), h('p', 'PolyOS finds your hardware and installs the drivers that make it work best.')),
      h('div.dm-actions', scanBtn, allBtn)),
    banner, progress, list,
    h('p.dm-foot', 'Drivers come from Debian’s archive (including its non-free section for NVIDIA, Broadcom and firmware). Installing needs an internet connection.'),
  );

  let result = null;
  let busy = false;

  function card(dev) {
    const needs = dev.missing.length > 0;
    const btn = needs ? h('button.pill-btn', { disabled: busy, onclick: () => install(dev.missing) }, 'Install') : null;
    return h('article.dm-card', { class: needs ? 'needs' : '' },
      h('span.dm-ico', icon(KIND_ICON[dev.kind] || 'chip')),
      h('div.dm-text',
        h('small.dm-kind', KIND_LABEL[dev.kind] || 'Device'),
        h('b', dev.title),
        h('span.dm-state', needs ? icon('download') : icon('check'),
          needs ? 'Recommended driver available' : dev.driver ? `Working (${dev.driver} driver)` : 'Ready'),
        dev.note && needs ? h('p', dev.note) : null,
        needs ? h('div.dm-pkgs', dev.missing.map((p) => h('code', p))) : null),
      btn);
  }

  function render() {
    if (!result) return;
    const pending = [...new Set(result.devices.flatMap((d) => d.missing))];
    allBtn.disabled = busy || !pending.length;
    allBtn.onclick = () => install(pending);
    fill(list, result.devices.length ? result.devices.map(card)
      : h('div.dm-empty', icon('check'), h('b', 'Everything is ready'), h('span', 'No extra drivers are needed for this computer.')));
    if (result.secureBoot && result.devices.some((d) => d.missing.some((p) => p.startsWith('nvidia') || p.includes('dkms')))) {
      list.append(h('p.dm-note', icon('lock'), 'Secure Boot is on. After installing NVIDIA or Broadcom drivers, the next start shows a blue “MOK management” screen: choose Enroll MOK and use the password it asks you to set (or turn Secure Boot off).'));
    }
  }

  async function scan() {
    scanBtn.disabled = true;
    fill(list, h('div.dm-empty', h('img.su-spin', { src: '/img/logo-white.svg', alt: '' }), h('span', 'Checking your hardware…')));
    try {
      result = await api.get('/api/drivers');
      render();
    } catch (err) {
      fill(list, h('div.dm-empty', icon('info'), h('b', 'Couldn’t check the hardware'), h('span', err.message)));
    }
    scanBtn.disabled = false;
  }

  async function install(packages) {
    try {
      await withAdmin(() => api.post('/api/drivers/install', { packages }),
        { title: 'Install drivers', text: 'Enter your password to install drivers.' });
    } catch (err) {
      if (!err.cancelled) showError(err.message);
    }
  }

  function showError(text) {
    banner.hidden = false;
    banner.className = 'dm-banner error';
    fill(banner, icon('info'), h('span', text));
  }

  watchJobs((job) => {
    if (job.kind !== 'drivers') return;
    busy = job.state === 'running';
    progress.hidden = !busy;
    fill(progress, h('span', job.message || 'Working…'), h('div.su-progress', h('span', { style: { width: `${Math.max(3, Math.round(job.progress * 100))}%` } })));
    if (job.state === 'failed') showError(job.error);
    if (job.state === 'done') {
      banner.hidden = false;
      banner.className = 'dm-banner ok';
      fill(banner, icon('check'), h('span', job.restart ? 'Drivers installed. Restart to start using them.' : 'Drivers installed.'),
        job.restart ? h('button.pill-btn.on', { onclick: () => power('reboot') }, 'Restart now') : null);
      scan();
    }
    render();
  });
  scan();
}
