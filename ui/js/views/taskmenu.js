// Taskbar right-click menu: new window, pin/unpin, add to the desktop, full screen, close.

import { api, closePopup, launch, saveSettings, windowAction, withToken } from '../api.js';
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
    const onDesktop = settings.desktopIcons.includes(app.id);
    items.push(
      h('button.menu-item', {
        onclick: () => done(saveSettings({
          desktopIcons: onDesktop ? settings.desktopIcons.filter((id) => id !== app.id) : [...settings.desktopIcons, app.id],
        })),
      }, icon(onDesktop ? 'close' : 'monitor'), onDesktop ? 'Remove from desktop' : 'Add to desktop'),
    );
  }
  if (wins.length === 1) {
    items.push(h('button.menu-item', { onclick: () => done(windowAction(wins[0].xid, 'fullscreen')) },
      icon('maximize'), wins[0].fullscreen ? 'Exit full screen' : 'Full screen'));
  }
  if (wins.length) {
    items.push(
      h('button.menu-item', { onclick: () => done(Promise.all(wins.map((w) => windowAction(w.xid, 'close')))) },
        icon('close'), wins.length > 1 ? `Close ${wins.length} windows` : 'Close window'),
      h('button.menu-item.danger', { onclick: () => done(Promise.all(wins.map((w) => windowAction(w.xid, 'kill')))) },
        icon('stop'), 'Force close'),
    );
  }
  items.push(h('button.menu-item', { onclick: () => done(api.post('/api/open', { app: 'taskmgr' })) }, icon('activity'), 'Task Manager'));
  const iconUrl = app ? app.icon : wins[0]?.icon;
  root.append(
    h('div.tm-head', iconUrl ? h('img', { src: withToken(iconUrl), alt: '' }) : null,
      h('span', app ? app.name : wins[0]?.title || 'App')),
    h('div.tm-items', items),
  );
}
