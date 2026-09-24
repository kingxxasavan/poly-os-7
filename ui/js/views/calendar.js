// Clock and month calendar.

import { clockTicker, fmtDate, fmtTime, h, icon } from '../ui.js';

export default function calendar(root, store) {
  const today = new Date();
  const view = new Date(today.getFullYear(), today.getMonth(), 1);
  const time = h('div.cal-time');
  const date = h('div.cal-date');
  const label = h('button.cal-label', { title: 'Back to today' });
  const grid = h('div.cal-grid');
  const nav = (delta) => () => {
    view.setMonth(view.getMonth() + delta);
    renderGrid();
  };
  label.addEventListener('click', () => {
    view.setFullYear(today.getFullYear(), today.getMonth(), 1);
    renderGrid();
  });
  root.append(
    h('div.cal',
      time,
      date,
      h('div.cal-head', label, h('div.cal-nav',
        h('button.icon-btn', { title: 'Previous month', onclick: nav(-1) }, icon('chevronLeft')),
        h('button.icon-btn', { title: 'Next month', onclick: nav(1) }, icon('chevronRight')))),
      grid),
  );

  // Weekday names from a known Sunday (2023-01-01) so they follow the locale.
  const weekdays = Array.from({ length: 7 }, (_, i) =>
    new Date(2023, 0, 1 + i).toLocaleDateString([], { weekday: 'narrow' }));

  function renderGrid() {
    label.textContent = view.toLocaleDateString([], { month: 'long', year: 'numeric' });
    const year = view.getFullYear();
    const month = view.getMonth();
    const first = new Date(year, month, 1).getDay();
    const cells = weekdays.map((d) => h('span.cal-wd', d));
    for (let i = 0; i < 42; i += 1) {
      const day = new Date(year, month, 1 - first + i);
      const isToday = day.toDateString() === today.toDateString();
      cells.push(h('span.cal-day', { class: `${day.getMonth() !== month ? 'other' : ''} ${isToday ? 'today' : ''}` },
        String(day.getDate())));
    }
    grid.replaceChildren(...cells);
  }

  const stop = clockTicker((now) => {
    time.textContent = fmtTime(now, store.state.settings, true);
    date.textContent = fmtDate(now, { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' });
  }, () => true);
  renderGrid();
  return stop;
}
