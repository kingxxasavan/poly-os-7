// Taskbar right-click menu: new window, pin/unpin, close.

import { closePopup, launch, saveSettings, windowAction, withToken } from '../api.js';
import { h, icon } from '../ui.js';

export default function taskmenu(root, store, data) {
  const { apps, windows, settings } = store.state;
  const app = apps.find((a) => a.id === data.appId);
  const wins = windows.filter((w) => (data.xids || []).includes(w.xid));
  const pinned = app && settings.pinned.includes(app.id);
  const done = (promise) => {
    promise.catch((err) => console.warn(err.message));
    closePopup();
  };

  const items = [];
  if (app) {
    items.push(h('button.menu-item', { onclick: () => done(launch(app.id)) }, icon('plus'), 'New window'));
    items.push(
      h('button.menu-item', {
        onclick: () => done(saveSettings({
          pinned: pinned ? settings.pinned.filter((id) => id !== app.id) : [...settings.pinned, app.id],
        })),
      }, icon(pinned ? 'unpin' : 'pin'), pinned ? 'Unpin from dock' : 'Pin to dock'),
    );
  }
  if (wins.length) {
    items.push(
      h('button.menu-item.danger', { onclick: () => done(Promise.all(wins.map((w) => windowAction(w.xid, 'close')))) },
        icon('close'), wins.length > 1 ? `Close ${wins.length} windows` : 'Close window'),
    );
  }
  const iconUrl = app ? app.icon : wins[0]?.icon;
  root.append(
    h('div.tm-head', iconUrl ? h('img', { src: withToken(iconUrl), alt: '' }) : null,
      h('span', app ? app.name : wins[0]?.title || 'App')),
    h('div.tm-items', items),
  );
}
