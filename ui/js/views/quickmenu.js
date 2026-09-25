// Win+X quick link menu (like Windows' power-user menu), bottom-left above the dock.

import { api, closePopup, openSettings, power } from '../api.js';
import { h, icon } from '../ui.js';

const open = (app, page) => api.post('/api/open', { app, page });
const popup = (view) => api.post('/api/popup', { view });

export default function quickmenu(root) {
  const items = [
    ['apps', 'All apps', () => popup('launcher'), 'Win+S'],
    ['activity', 'Task Manager', () => open('taskmgr'), 'Ctrl+Shift+Esc'],
    ['settings', 'Settings', () => openSettings(), 'Win+I'],
    ['folder', 'Files', () => api.post('/api/run', { what: 'files' }), 'Win+E'],
    ['terminal', 'Terminal', () => api.post('/api/run', { what: 'terminal' }), 'Win+T'],
    ['chip', 'Driver Manager', () => open('drivers')],
    ['bag', 'PolyMarket', () => open('store')],
    ['arrowRight', 'Run', () => popup('run'), 'Win+R'],
    null,
    ['lock', 'Lock', () => power('lock'), 'Win+L'],
    ['logout', 'Sign out', () => power('logout')],
    ['restart', 'Restart', () => power('reboot')],
    ['power', 'Shut down', () => power('poweroff')],
  ];
  root.classList.add('qm');
  root.append(...items.map((it) => (it
    ? h('button.menu-item', {
      onclick: () => {
        const keepsPopup = it[1] === 'All apps' || it[1] === 'Run';
        it[2]().catch((err) => console.warn(err.message));
        if (!keepsPopup) closePopup();
      },
    }, icon(it[0]), it[1], it[3] ? h('span.menu-hint', it[3]) : null)
    : h('div.menu-sep'))));
  root.querySelector('.menu-item')?.setAttribute('autofocus', '');
  const onKey = (e) => {
    const list = [...root.querySelectorAll('.menu-item')];
    const idx = list.indexOf(document.activeElement);
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      const next = list[(idx + (e.key === 'ArrowDown' ? 1 : -1) + list.length) % list.length];
      next.focus();
    }
  };
  document.addEventListener('keydown', onKey);
  return () => document.removeEventListener('keydown', onKey);
}
