// Widgets board (Win+W, or the weather button in the dock), like Windows 11's widgets:
// weather, calendar, system, news, to-do, notes, photos, world clocks and media controls.

import { api, closePopup, saveSettings, withToken } from '../api.js';
import { clockTicker, fill, fmtTime, formatBytes, greeting, h, icon } from '../ui.js';

const INFO = {
  weather: ['Weather', 'sun', true], calendar: ['Calendar', 'grid', false], system: ['System', 'activity', false],
  news: ['News', 'globe', true], todo: ['To Do', 'check', false], notes: ['Notes', 'chat', false],
  photos: ['Photos', 'image', false], clocks: ['World clock', 'globe', false], media: ['Now playing', 'music', false],
};

// WMO weather codes (Open-Meteo) -> [description, icon]
export function weatherLook(code, day = true) {
  if (code === 0) return ['Clear', day ? 'sun' : 'moon'];
  if (code === 1 || code === 2) return [code === 1 ? 'Mostly clear' : 'Partly cloudy', day ? 'cloudSun' : 'cloud'];
  if (code === 3) return ['Cloudy', 'cloud'];
  if (code === 45 || code === 48) return ['Fog', 'fog'];
  if (code >= 51 && code <= 57) return ['Drizzle', 'rain'];
  if ((code >= 61 && code <= 67) || (code >= 80 && code <= 82)) return [code >= 80 ? 'Showers' : 'Rain', 'rain'];
  if ((code >= 71 && code <= 77) || code === 85 || code === 86) return ['Snow', 'snow'];
  if (code >= 95) return ['Thunderstorms', 'storm'];
  return ['—', 'cloud'];
}

const deg = (v) => (v == null ? '--' : `${Math.round(v)}°`);
const timeAgo = (text) => {
  const t = Date.parse(text);
  if (!t) return '';
  const min = Math.round((Date.now() - t) / 60000);
  return min < 60 ? `${Math.max(1, min)}m ago` : min < 1440 ? `${Math.round(min / 60)}h ago` : `${Math.round(min / 1440)}d ago`;
};

export default function widgets(root, store) {
  root.classList.add('widgets');
  const clock = h('div.wg-time');
  const greet = h('div.wg-greet');
  const addBtn = h('button.pill-btn', { title: 'Add widgets' }, icon('plus'), 'Add widgets');
  const grid = h('div.wg-grid');
  const menuLayer = h('div.wg-layer');
  root.append(h('header.wg-head', h('div', clock, greet), h('div.wg-head-actions', addBtn,
    h('button.icon-btn.round', { title: 'Close', onclick: () => closePopup() }, icon('close')))), grid, menuLayer);

  let data = null; // widgets.json
  const timers = [];
  const every = (ms, fn) => { fn(); timers.push(setInterval(fn, ms)); };
  const save = (patch) => api.post('/api/widgets/data', patch).then((d) => { data = d; return d; });
  const shown = () => store.state.settings.widgets;

  function menu(anchor, items) {
    const el = h('div.menu.wg-menu', items.map(([label, fn, cls]) => h('button.menu-item', {
      class: cls || '', onclick: () => { fill(menuLayer); fn(); },
    }, label)));
    fill(menuLayer, el);
    const r = anchor.getBoundingClientRect();
    el.style.top = `${r.bottom + 4}px`;
    el.style.left = `${Math.max(8, Math.min(r.right - 200, innerWidth - 220))}px`;
  }
  root.addEventListener('pointerdown', (e) => { if (!menuLayer.contains(e.target) && !e.target.closest('.wg-more')) fill(menuLayer); });

  function card(id, body, extra = []) {
    const [title, ico, wide] = INFO[id];
    const list = shown();
    const i = list.indexOf(id);
    const more = h('button.icon-btn.wg-more', { title: 'Widget options' }, icon('settings'));
    more.addEventListener('click', () => menu(more, [
      ...extra,
      ...(i > 0 ? [['Move up', () => saveSettings({ widgets: swap(list, i, i - 1) })]] : []),
      ...(i < list.length - 1 ? [['Move down', () => saveSettings({ widgets: swap(list, i, i + 1) })]] : []),
      ['Remove widget', () => saveSettings({ widgets: list.filter((w) => w !== id) }), 'danger'],
    ]));
    return h('section.wg-card', { class: wide ? 'wide' : '', 'data-id': id },
      h('div.wg-card-head', icon(ico), h('b', title), more), body);
  }
  const swap = (list, a, b) => { const out = [...list]; [out[a], out[b]] = [out[b], out[a]]; return out; };

  // ---- weather --------------------------------------------------------------------------
  function weatherWidget() {
    const body = h('div.wg-weather', h('p.wg-muted', 'Loading the forecast…'));
    const setup = () => {
      const input = h('input.input', { placeholder: 'Search for your city', 'aria-label': 'City' });
      const results = h('div.wg-results');
      let t = 0;
      input.addEventListener('input', () => {
        clearTimeout(t);
        t = setTimeout(async () => {
          try {
            const res = await api.get(`/api/widgets/geocode?q=${encodeURIComponent(input.value)}`);
            fill(results, res.results.map((r) => h('button.wg-result', {
              onclick: async () => { await save({ weather: { place: r } }); load(); },
            }, h('b', r.name), h('small', [r.region, r.country].filter(Boolean).join(', ')))));
          } catch (err) { fill(results, h('p.wg-muted', err.message)); }
        }, 350);
      });
      fill(body, h('p.wg-muted', 'Choose a city to see its weather.'), input, results);
      setTimeout(() => input.focus(), 50);
    };
    const load = async () => {
      try {
        const w = await api.get('/api/widgets/weather');
        if (!w.place) return setup();
        const [desc, ico] = weatherLook(w.code, w.day);
        const unit = w.units === 'celsius' ? 'C' : 'F';
        fill(body,
          h('div.wg-now', h('span.wg-big-ico', icon(ico)), h('span.wg-temp', `${Math.round(w.temp)}°${unit}`),
            h('div.wg-now-text', h('b', desc), h('small', `${w.place.name}${w.place.region ? `, ${w.place.region}` : ''}`),
              h('small', `Feels like ${deg(w.feels)} · Humidity ${w.humidity ?? '--'}% · Wind ${Math.round(w.wind ?? 0)} ${unit === 'F' ? 'mph' : 'km/h'}`))),
          h('div.wg-days', w.days.map((d, i) => {
            const [dDesc, dIco] = weatherLook(d.code, true);
            const name = i === 0 ? 'Today' : new Date(`${d.date}T12:00`).toLocaleDateString([], { weekday: 'short' });
            return h('div.wg-day', { title: dDesc }, h('small', name), icon(dIco), h('b', deg(d.high)), h('small', deg(d.low)));
          })));
      } catch (err) {
        fill(body, h('p.wg-muted', err.message));
      }
    };
    every(10 * 60000, load);
    return card('weather', body, [
      ['Change city', setup],
      ['Use °F', async () => { await save({ weather: { units: 'fahrenheit' } }); load(); }],
      ['Use °C', async () => { await save({ weather: { units: 'celsius' } }); load(); }],
    ]);
  }

  // ---- calendar -------------------------------------------------------------------------
  function calendarWidget() {
    const now = new Date();
    const first = new Date(now.getFullYear(), now.getMonth(), 1);
    const days = new Date(now.getFullYear(), now.getMonth() + 1, 0).getDate();
    const cells = ['S', 'M', 'T', 'W', 'T', 'F', 'S'].map((d) => h('span.wg-wd', d));
    for (let i = 0; i < first.getDay(); i++) cells.push(h('span'));
    for (let d = 1; d <= days; d++) cells.push(h('span.wg-cal-day', { class: d === now.getDate() ? 'today' : '' }, String(d)));
    return card('calendar', h('div.wg-cal',
      h('div.wg-cal-head', h('b', now.toLocaleDateString([], { month: 'long' })), h('small', String(now.getFullYear()))),
      h('div.wg-cal-grid', cells)));
  }

  // ---- system ---------------------------------------------------------------------------
  function systemWidget() {
    const body = h('div.wg-system');
    const bar = (label, pct, text) => h('div.wg-meter', h('div.wg-meter-top', h('span', label), h('b', text)),
      h('div.wg-meter-bar', h('span', { style: { width: `${Math.max(2, Math.min(100, pct))}%` } })));
    let disk = null;
    api.get('/api/sysinfo').then((s) => { disk = s; }, () => {});
    every(3000, async () => {
      try {
        const { perf } = await api.get('/api/procs');
        const bat = store.state.system.battery;
        fill(body,
          bar('CPU', perf.cpu, `${Math.round(perf.cpu)}%`),
          bar('Memory', (perf.memUsed / perf.memTotal) * 100, `${formatBytes(perf.memUsed, 1024)} of ${formatBytes(perf.memTotal, 1024)}`),
          disk ? bar('Storage', ((disk.diskTotal - disk.diskFree) / disk.diskTotal) * 100, `${formatBytes(disk.diskFree)} free`) : null,
          bat.present ? bar('Battery', bat.level, `${bat.level}%${bat.charging ? ' · charging' : ''}`) : null,
          h('button.link-btn', { onclick: () => { api.post('/api/open', { app: 'taskmgr' }); closePopup(); } }, 'Open Task Manager'));
      } catch { /* keep the last numbers */ }
    });
    return card('system', body);
  }

  // ---- news -----------------------------------------------------------------------------
  function newsWidget() {
    const body = h('div.wg-news', h('p.wg-muted', 'Loading headlines…'));
    const load = async (topic) => {
      try {
        const n = await api.get(`/api/widgets/news${topic ? `?topic=${topic}` : ''}`);
        fill(body,
          h('div.wg-chips', n.topics.map(([id, label]) => h('button.wg-chip', {
            class: id === n.topic ? 'on' : '',
            onclick: async () => { await save({ news: { topic: id } }); load(id); },
          }, label))),
          h('div.wg-headlines', n.items.slice(0, 7).map((it) => h('a.wg-headline', { href: it.link, target: '_blank', rel: 'noopener' },
            h('b', it.title), h('small', `${n.source} · ${timeAgo(it.published)}`)))));
      } catch (err) {
        fill(body, h('p.wg-muted', err.message));
      }
    };
    every(15 * 60000, () => load());
    return card('news', body);
  }

  // ---- to do ----------------------------------------------------------------------------
  function todoWidget() {
    const body = h('div.wg-todo');
    const render = () => {
      const items = data.todo;
      const input = h('input.input', { placeholder: 'Add a task', 'aria-label': 'New task', maxlength: 200 });
      input.addEventListener('keydown', async (e) => {
        if (e.key === 'Enter' && input.value.trim()) {
          await save({ todo: [...items, { text: input.value.trim(), done: false }] });
          render();
          body.querySelector('input.input')?.focus();
        }
      });
      fill(body, input, h('div.wg-tasks', items.length ? items.map((t, i) => h('div.wg-task', { class: t.done ? 'done' : '' },
        h('button.wg-check', { 'aria-label': t.done ? 'Mark not done' : 'Mark done',
          onclick: async () => { await save({ todo: items.map((x, j) => (j === i ? { ...x, done: !x.done } : x)) }); render(); } },
        t.done ? icon('check') : null),
        h('span', t.text),
        h('button.icon-btn.wg-del', { title: 'Delete', onclick: async () => { await save({ todo: items.filter((_, j) => j !== i) }); render(); } }, icon('close'))))
        : h('p.wg-muted', 'Nothing to do. Nice.')));
    };
    render();
    return card('todo', body, [['Clear completed', async () => { await save({ todo: data.todo.filter((t) => !t.done) }); refresh(); }]]);
  }

  // ---- notes ----------------------------------------------------------------------------
  function notesWidget() {
    const area = h('textarea.wg-notes', { placeholder: 'Write something down…', 'aria-label': 'Notes', maxlength: 20000 });
    area.value = data.notes;
    let t = 0;
    area.addEventListener('input', () => { clearTimeout(t); t = setTimeout(() => save({ notes: area.value }), 500); });
    return card('notes', area);
  }

  // ---- photos ---------------------------------------------------------------------------
  function photosWidget() {
    const img = h('img.wg-photo', { alt: '' });
    const openPictures = async () => {
      const { home } = await api.get('/api/files/places');
      await api.post('/api/open', { app: 'files', page: `${home}/Pictures` });
      closePopup();
    };
    const body = h('button.wg-photos', { title: 'Open Pictures', onclick: () => openPictures().catch(() => {}) }, img);
    api.get('/api/widgets/photos').then(({ photos }) => {
      if (!photos.length) return fill(body, h('p.wg-muted', 'Add pictures to your Pictures folder to see them here.'));
      let i = Math.floor(Math.random() * photos.length);
      const show = () => { img.src = withToken(`/files/raw?path=${encodeURIComponent(photos[i % photos.length])}`); i += 1; };
      show();
      timers.push(setInterval(show, 8000));
    }, (err) => fill(body, h('p.wg-muted', err.message)));
    return card('photos', body);
  }

  // ---- world clock ----------------------------------------------------------------------
  function clocksWidget() {
    const body = h('div.wg-clocks');
    const zones = () => [Intl.DateTimeFormat().resolvedOptions().timeZone, ...data.clocks];
    const tick = () => fill(body, zones().map((z, i) => h('div.wg-zone',
      h('span', i === 0 ? 'Here' : z.split('/').pop().replace(/_/g, ' ')),
      h('b', new Date().toLocaleTimeString([], { timeZone: z, hour: 'numeric', minute: '2-digit', hour12: !store.state.settings.clock24h })),
      h('small', new Date().toLocaleDateString([], { timeZone: z, weekday: 'short' })))));
    every(20000, tick);
    const choices = ['America/New_York', 'America/Los_Angeles', 'America/Chicago', 'Europe/London', 'Europe/Paris',
      'Asia/Kolkata', 'Asia/Tokyo', 'Asia/Shanghai', 'Australia/Sydney', 'America/Sao_Paulo'];
    return card('clocks', body, choices.filter((z) => !data.clocks.includes(z)).slice(0, 5).map((z) => [
      `Add ${z.split('/').pop().replace(/_/g, ' ')}`,
      async () => { await save({ clocks: [...data.clocks, z].slice(-3) }); refresh(); },
    ]).concat(data.clocks.length ? [['Remove last city', async () => { await save({ clocks: data.clocks.slice(0, -1) }); refresh(); }]] : []));
  }

  // ---- media ----------------------------------------------------------------------------
  function mediaWidget() {
    const body = h('div.wg-media');
    const render = (m) => {
      if (!m.available) return fill(body, h('p.wg-muted', 'Install playerctl to control music and videos from here.'));
      if (!m.playing) return fill(body, h('p.wg-muted', 'Play music or a video in any app to control it here.'));
      const act = async (action) => render(await api.post('/api/widgets/media', { action }));
      fill(body, h('div.wg-track', h('b', m.playing.title || 'Unknown'), h('small', [m.playing.artist, m.playing.player].filter(Boolean).join(' · '))),
        h('div.wg-controls',
          h('button.icon-btn.round', { title: 'Previous', onclick: () => act('previous') }, icon('chevronLeft')),
          h('button.icon-btn.round.big', { title: m.playing.status === 'Playing' ? 'Pause' : 'Play', onclick: () => act('play-pause') },
            icon(m.playing.status === 'Playing' ? 'pause' : 'play')),
          h('button.icon-btn.round', { title: 'Next', onclick: () => act('next') }, icon('chevronRight'))));
    };
    every(5000, async () => { try { render(await api.get('/api/widgets/media')); } catch { /* ignore */ } });
    return card('media', body);
  }

  const makers = { weather: weatherWidget, calendar: calendarWidget, system: systemWidget, news: newsWidget,
    todo: todoWidget, notes: notesWidget, photos: photosWidget, clocks: clocksWidget, media: mediaWidget };

  function refresh() {
    timers.splice(0).forEach(clearInterval);
    const list = shown();
    fill(grid, list.length ? list.map((id) => makers[id]()) : h('div.wg-empty', icon('sparkle'), h('b', 'No widgets yet'),
      h('span', 'Use Add widgets to pick some.')));
    addBtn.disabled = list.length === Object.keys(INFO).length;
  }

  addBtn.addEventListener('click', () => {
    const missing = Object.keys(INFO).filter((id) => !shown().includes(id));
    menu(addBtn, missing.map((id) => [INFO[id][0], () => saveSettings({ widgets: [...shown(), id] })]));
  });

  const stopClock = clockTicker((now) => {
    clock.textContent = fmtTime(now, store.state.settings, false);
    const first = (store.state.user.fullName || store.state.user.name).split(' ')[0];
    greet.textContent = `${greeting(now)}, ${first}`;
  }, () => false);

  const unsubscribe = store.subscribe((_s, changed) => {
    if (changed.has('settings') && data) {
      const key = JSON.stringify(store.state.settings.widgets);
      if (key !== refresh.key) { refresh.key = key; refresh(); }
    }
  });
  api.get('/api/widgets/data').then((d) => {
    data = d;
    refresh.key = JSON.stringify(shown());
    refresh();
  }, (err) => fill(grid, h('p.wg-muted', err.message)));

  return () => {
    timers.splice(0).forEach(clearInterval);
    stopClock();
    unsubscribe();
  };
}
