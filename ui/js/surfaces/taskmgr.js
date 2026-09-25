// Task Manager: running apps and processes (End task / Force close) and live performance graphs.

import { api, params, withToken } from '../api.js';
import { fill, formatBytes, h, icon } from '../ui.js';

const POLL_MS = 1500;
const HISTORY = 60;
const PAGES = [['processes', 'Processes', 'apps'], ['performance', 'Performance', 'activity']];

const mb = (bytes) => (bytes >= 1024 ** 3 ? `${(bytes / 1024 ** 3).toFixed(1)} GB` : `${(bytes / 1024 ** 2).toFixed(1)} MB`);
const rate = (bps) => `${formatBytes(bps)}/s`;
const heat = (value, max) => `color-mix(in srgb, var(--accent) ${Math.round(Math.min(1, value / max) * 55)}%, transparent)`;

function uptimeText(seconds) {
  const d = Math.floor(seconds / 86400);
  const hrs = Math.floor((seconds % 86400) / 3600);
  const min = Math.floor((seconds % 3600) / 60);
  return `${d ? `${d}:` : ''}${String(hrs).padStart(2, '0')}:${String(min).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`;
}

// Line chart on a canvas, drawn in the accent color.
function chart(values, max, canvas, color) {
  const dpr = window.devicePixelRatio || 1;
  const w = canvas.clientWidth;
  const hgt = canvas.clientHeight;
  if (!w || !hgt) return;
  if (canvas.width !== Math.round(w * dpr)) {
    canvas.width = Math.round(w * dpr);
    canvas.height = Math.round(hgt * dpr);
  }
  const ctx = canvas.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, w, hgt);
  const style = getComputedStyle(document.documentElement);
  ctx.strokeStyle = style.getPropertyValue('--line').trim() || 'rgba(255,255,255,.08)';
  ctx.lineWidth = 1;
  for (let i = 1; i < 4; i++) {
    const y = Math.round((hgt * i) / 4) + 0.5;
    ctx.beginPath();
    ctx.moveTo(0, y);
    ctx.lineTo(w, y);
    ctx.stroke();
  }
  if (values.length < 2) return;
  const accent = color || style.getPropertyValue('--accent').trim() || '#678fd9';
  const step = w / (HISTORY - 1);
  const x0 = w - (values.length - 1) * step;
  const y = (v) => hgt - (Math.min(max, v) / max) * (hgt - 4) - 2;
  ctx.beginPath();
  values.forEach((v, i) => (i ? ctx.lineTo(x0 + i * step, y(v)) : ctx.moveTo(x0, y(v))));
  ctx.strokeStyle = accent;
  ctx.lineWidth = 2;
  ctx.lineJoin = 'round';
  ctx.stroke();
  ctx.lineTo(x0 + (values.length - 1) * step, hgt);
  ctx.lineTo(x0, hgt);
  ctx.closePath();
  const grad = ctx.createLinearGradient(0, 0, 0, hgt);
  grad.addColorStop(0, `${accent}55`);
  grad.addColorStop(1, `${accent}05`);
  ctx.fillStyle = grad;
  ctx.fill();
}

export function mount(root, store) {
  root.className = 'taskmgr';
  document.title = 'Task Manager';
  const nav = h('nav.nav', { 'aria-label': 'Task Manager sections' });
  const page = h('main.tk-page');
  root.append(h('aside.sidebar', h('div.brand', h('img', { src: '/img/taskmgr.svg', alt: '' }), 'Task Manager'), nav), page);

  let current = null;
  let data = null;
  let selected = null;
  let query = '';
  let menu = null;
  const hist = { cpu: [], mem: [], disk: [], net: [] };
  const buttons = new Map();
  for (const [id, label, ico] of PAGES) {
    const btn = h('button.nav-item', { onclick: () => go(id) }, icon(ico), h('span', label));
    buttons.set(id, btn);
    nav.append(btn);
  }

  // ---- processes --------------------------------------------------------------------------
  const search = h('input.tk-search-input', { type: 'search', placeholder: 'Search by name', 'aria-label': 'Search processes' });
  const endBtn = h('button.pill-btn', { disabled: true }, icon('stop'), 'End task');
  const status = h('span.tk-status');
  const table = h('div.tk-table', { role: 'grid' });
  search.addEventListener('input', () => { query = search.value.trim().toLowerCase(); renderProcesses(); });
  endBtn.addEventListener('click', () => endTask(false));

  const toast = (text) => {
    status.textContent = text;
    clearTimeout(toast.t);
    toast.t = setTimeout(() => { status.textContent = ''; }, 4000);
  };

  async function endTask(force, pid = selected) {
    if (!pid) return;
    closeMenu();
    try {
      await api.post('/api/procs/end', { pid, force });
      toast(force ? 'Force closed.' : 'Ended.');
      selected = null;
      setTimeout(poll, 400);
    } catch (err) {
      toast(err.message);
    }
  }

  function closeMenu() {
    menu?.remove();
    menu = null;
  }

  function openMenu(e, row) {
    e.preventDefault();
    closeMenu();
    selected = row.pid;
    renderProcesses();
    if (row.protected) return;
    menu = h('div.menu.fx-menu', { role: 'menu' },
      h('button.menu-item', { onclick: () => endTask(false, row.pid) }, icon('stop'), 'End task'),
      h('button.menu-item.danger', { onclick: () => endTask(true, row.pid) }, icon('close'), 'Force close'));
    document.body.append(menu);
    const r = menu.getBoundingClientRect();
    menu.style.left = `${Math.min(e.clientX, innerWidth - r.width - 8)}px`;
    menu.style.top = `${Math.min(e.clientY, innerHeight - r.height - 8)}px`;
  }
  document.addEventListener('pointerdown', (e) => { if (menu && !menu.contains(e.target)) closeMenu(); });
  window.addEventListener('blur', closeMenu);

  function rowEl(row, kind) {
    const cpuMax = 25;
    const img = kind === 'apps' && row.icon ? h('img', { src: withToken(row.icon), alt: '' })
      : h('span.tk-gen', icon(kind === 'desktop' ? 'settings' : 'window'));
    const el = h('div.tk-row', {
      role: 'row', tabindex: '-1', class: [selected === row.pid ? 'sel' : '', row.protected ? 'locked' : ''].join(' '),
      title: row.cmdline || row.title || row.name,
      onclick: () => { selected = row.pid; renderProcesses(); },
      ondblclick: () => kind === 'apps' && !row.protected && endTask(false, row.pid),
      oncontextmenu: (e) => openMenu(e, row),
    },
    h('span.tk-name', h('span.tk-ico', img), h('span.tk-label', row.name), row.count > 1 ? h('small', `(${row.count})`) : null),
    h('span.tk-cell.tk-state', row.status === 'Running' ? '' : row.status),
    h('span.tk-cell.num', { style: { background: heat(row.cpu, cpuMax) } }, `${row.cpu.toFixed(1)}%`),
    h('span.tk-cell.num', { style: { background: heat(row.memory, 1.5 * 1024 ** 3) } }, mb(row.memory)));
    return el;
  }

  function renderProcesses() {
    if (current !== 'processes' || !data) return;
    const match = (r) => !query || r.name.toLowerCase().includes(query) || (r.title || '').toLowerCase().includes(query);
    const groups = [['apps', 'Apps', data.apps], ['background', 'Background processes', data.background], ['desktop', 'PolyOS', data.desktop]];
    const perf = data.perf;
    const rows = [h('div.tk-row.tk-head', { role: 'row' },
      h('span', 'Name'), h('span.tk-cell', 'Status'),
      h('span.tk-cell.num', h('b', `${Math.round(perf.cpu)}%`), h('small', 'CPU')),
      h('span.tk-cell.num', h('b', `${Math.round((perf.memUsed / perf.memTotal) * 100)}%`), h('small', 'Memory')))];
    for (const [kind, title, list] of groups) {
      const shown = list.filter(match);
      if (!shown.length) continue;
      rows.push(h('div.tk-group', `${title} (${shown.length})`));
      rows.push(...shown.map((r) => rowEl(r, kind)));
    }
    if (rows.length === 1) rows.push(h('p.tk-empty', 'Nothing matches your search.'));
    const scroll = table.scrollTop;
    fill(table, ...rows);
    table.scrollTop = scroll;
    const sel = [...data.apps, ...data.background, ...data.desktop].find((r) => r.pid === selected);
    endBtn.disabled = !sel || sel.protected;
  }

  function processesPage() {
    page.append(h('header.tk-top', h('h1', 'Processes'), h('div.tk-tools', h('label.tk-search', icon('search'), search), endBtn)),
      table, h('footer.tk-foot', status, h('span.muted', 'Right-click a process to force close it.')));
    renderProcesses();
  }

  // ---- performance --------------------------------------------------------------------------
  let perfEls = null;
  let resource = 'cpu';
  function performancePage() {
    const tiles = {};
    const side = h('div.tk-res');
    for (const [id, label] of [['cpu', 'CPU'], ['mem', 'Memory'], ['disk', 'Disk'], ['net', 'Network']]) {
      const canvas = h('canvas.tk-spark');
      const value = h('small');
      const tile = h('button.tk-res-tile', { onclick: () => { resource = id; paintPerf(); } }, canvas, h('span', h('b', label), value));
      tiles[id] = { tile, canvas, value };
      side.append(tile);
    }
    const title = h('h2');
    const subtitle = h('span.muted');
    const big = h('canvas.tk-chart');
    const stats = h('div.tk-stats');
    page.append(h('header.tk-top', h('h1', 'Performance')),
      h('div.tk-perf', side, h('section.tk-detail', h('div.tk-detail-head', title, subtitle), big, stats)));
    perfEls = { tiles, title, subtitle, big, stats };
    paintPerf();
  }

  function stat(label, value) {
    return h('div.tk-stat', h('small', label), h('b', value));
  }

  function paintPerf() {
    if (current !== 'performance' || !perfEls || !data) return;
    const p = data.perf;
    const netMax = Math.max(128 * 1024, ...hist.net);
    const diskMax = Math.max(1024 * 1024, ...hist.disk);
    const t = perfEls.tiles;
    chart(hist.cpu, 100, t.cpu.canvas);
    chart(hist.mem, 100, t.mem.canvas, '#9b7fe0');
    chart(hist.disk, diskMax, t.disk.canvas, '#81d862');
    chart(hist.net, netMax, t.net.canvas, '#e0906a');
    t.cpu.value.textContent = `${Math.round(p.cpu)}%`;
    t.mem.value.textContent = `${mb(p.memUsed)} / ${mb(p.memTotal)}`;
    t.disk.value.textContent = rate(p.diskRead + p.diskWrite);
    t.net.value.textContent = `↓ ${rate(p.netDown)}`;
    for (const [id, el] of Object.entries(t)) el.tile.classList.toggle('on', id === resource);
    const { title, subtitle, big, stats } = perfEls;
    if (resource === 'cpu') {
      title.textContent = 'CPU';
      subtitle.textContent = p.cpuModel;
      chart(hist.cpu, 100, big);
      fill(stats, stat('Utilization', `${Math.round(p.cpu)}%`), stat('Cores', String(p.cores.length)),
        stat('Processes', String(p.processes)), stat('Threads', String(p.threads)), stat('Up time', uptimeText(p.uptime)),
        h('div.tk-cores', p.cores.map((c, i) => h('span', { title: `Core ${i + 1}: ${c}%`, style: { '--v': `${c}%` } }))));
    } else if (resource === 'mem') {
      title.textContent = 'Memory';
      subtitle.textContent = `${mb(p.memTotal)} installed`;
      chart(hist.mem, 100, big, '#9b7fe0');
      fill(stats, stat('In use', mb(p.memUsed)), stat('Available', mb(p.memTotal - p.memUsed)), stat('Cached', mb(p.memCached)),
        stat('Swap', p.swapTotal ? `${mb(p.swapUsed)} / ${mb(p.swapTotal)}` : 'Off'));
    } else if (resource === 'disk') {
      title.textContent = 'Disk';
      subtitle.textContent = 'All disks';
      chart(hist.disk, diskMax, big, '#81d862');
      fill(stats, stat('Read speed', rate(p.diskRead)), stat('Write speed', rate(p.diskWrite)));
    } else {
      title.textContent = 'Network';
      subtitle.textContent = store.state.system.network.name || 'All connections';
      chart(hist.net, netMax, big, '#e0906a');
      fill(stats, stat('Receive', rate(p.netDown)), stat('Send', rate(p.netUp)));
    }
  }

  // ---- data -------------------------------------------------------------------------------
  let timer = 0;
  async function poll() {
    clearTimeout(timer);
    try {
      data = await api.get('/api/procs');
      const p = data.perf;
      const push = (key, v) => { hist[key].push(v); if (hist[key].length > HISTORY) hist[key].shift(); };
      push('cpu', p.cpu);
      push('mem', (p.memUsed / p.memTotal) * 100);
      push('disk', p.diskRead + p.diskWrite);
      push('net', p.netDown + p.netUp);
      renderProcesses();
      paintPerf();
    } catch (err) {
      toast(err.message);
    }
    timer = setTimeout(poll, document.hidden ? POLL_MS * 4 : POLL_MS);
  }

  function go(id) {
    if (!PAGES.some((p) => p[0] === id)) id = 'processes';
    current = id;
    perfEls = null;
    for (const [key, btn] of buttons) btn.classList.toggle('active', key === id);
    page.replaceChildren();
    if (id === 'processes') processesPage();
    else performancePage();
    window.history.replaceState(null, '', `?surface=taskmgr&page=${id}`);
  }

  document.addEventListener('keydown', (e) => {
    if (e.key === 'Delete' && current === 'processes' && selected && !(e.target instanceof HTMLInputElement)) endTask(e.shiftKey);
    if (e.key === 'Escape') closeMenu();
  });
  window.addEventListener('resize', paintPerf);
  go(params.get('page') || 'processes');
  poll();
}
