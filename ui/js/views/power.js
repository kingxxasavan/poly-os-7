// Full-screen Power Options, after the PolyOS 7 design.

import { closePopup, power, withToken } from '../api.js';
import { h, icon } from '../ui.js';

const ACTIONS = [
  ['power', 'Shut Down', 'poweroff'],
  ['restart', 'Restart', 'reboot'],
  ['moon', 'Sleep', 'suspend'],
  ['lock', 'Lock', 'lock'],
  ['logout', 'Sign Out', 'logout'],
];
const FEEDBACK_URL = 'https://scratch.mit.edu/projects/1260782002/';

export default function powerOptions(root, store) {
  root.classList.add('power-screen');
  const wallpaper = withToken(`/wallpaper/current?v=${encodeURIComponent(store.state.settings.wallpaper)}`);
  const status = h('div.pw-status', { role: 'status' });
  const list = h('div.pw-list', ACTIONS.map(([ico, label, action], i) => {
    const btn = h('button.pw-action', { autofocus: i === 0 }, icon(ico), h('span', label));
    btn.addEventListener('click', async (e) => {
      e.stopPropagation();
      status.textContent = '';
      try {
        await power(action);
      } catch (err) {
        status.textContent = err.message;
      }
    });
    return btn;
  }));

  root.append(
    h('div.lp-backdrop', { style: { backgroundImage: `url("${wallpaper}")` } }),
    h('h1.pw-title', 'Power Options'),
    h('div.pw-body',
      list,
      h('section.pw-note',
        h('h2', 'Before you go:'),
        h('div.pw-cards',
          h('div.pw-card', h('b', 'Save your work.'),
            h('p', 'Shutting down or restarting closes every app. Anything you haven’t saved will be lost.')),
          h('a.pw-card', { href: FEEDBACK_URL, target: '_blank', rel: 'noopener' }, h('b', 'We want to hear from you!'),
            h('p', 'Found a bug or have an idea? Tell the PolyOS team on the PolyOS bug report project.'))))),
    status,
    h('p.pw-cancel', 'Click anywhere to cancel.'),
  );

  root.addEventListener('click', (e) => {
    if (!e.target.closest('.pw-action, .pw-card')) closePopup();
  });
}
