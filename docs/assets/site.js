// Gallery filters and a keyboard-friendly lightbox. The page works without this script.

const figures = [...document.querySelectorAll('.gallery figure')];
const tabs = [...document.querySelectorAll('.filters button')];
let visible = figures;

for (const tab of tabs) {
  tab.addEventListener('click', () => {
    const cat = tab.dataset.filter;
    tabs.forEach((t) => t.setAttribute('aria-selected', String(t === tab)));
    figures.forEach((f) => { f.hidden = cat !== 'all' && f.dataset.cat !== cat; });
    visible = figures.filter((f) => !f.hidden);
  });
}

const box = document.querySelector('.lightbox');
const boxImg = box.querySelector('img');
const boxCap = box.querySelector('figcaption');
let current = 0;
let opener = null;

function show(index) {
  current = (index + visible.length) % visible.length;
  const fig = visible[current];
  boxImg.src = fig.dataset.full;
  boxImg.alt = fig.querySelector('b').textContent;
  boxCap.innerHTML = fig.querySelector('figcaption').innerHTML;
}

function open(fig) {
  opener = fig;
  show(visible.indexOf(fig));
  box.hidden = false;
  document.body.style.overflow = 'hidden';
  box.querySelector('.lb-close').focus();
}

function close() {
  box.hidden = true;
  document.body.style.overflow = '';
  opener?.focus();
}

for (const fig of figures) {
  fig.tabIndex = 0;
  fig.setAttribute('role', 'button');
  fig.setAttribute('aria-label', `Open screenshot: ${fig.querySelector('b').textContent}`);
  fig.addEventListener('click', () => open(fig));
  fig.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); open(fig); } });
}
box.querySelector('.lb-close').addEventListener('click', close);
box.querySelector('.lb-prev').addEventListener('click', () => show(current - 1));
box.querySelector('.lb-next').addEventListener('click', () => show(current + 1));
box.addEventListener('click', (e) => { if (e.target === box) close(); });
document.addEventListener('keydown', (e) => {
  if (box.hidden) return;
  if (e.key === 'Escape') close();
  if (e.key === 'ArrowLeft') show(current - 1);
  if (e.key === 'ArrowRight') show(current + 1);
});

// ---- Download: the newest GitHub release, so the button always offers the current ISO ----
// Without a release (or if GitHub can't be reached) the button keeps pointing to the releases page.
const REPO = 'kingxxasavan/poly-os-7';

function gb(bytes) {
  return `${(bytes / 1e9).toFixed(bytes >= 1e10 ? 0 : 1)} GB`;
}

function downloadButton(href, text, primary) {
  const a = document.createElement('a');
  a.className = primary ? 'btn primary big' : 'btn big';
  a.href = href;
  a.innerHTML = '<svg class="ico"><use href="#i-download"/></svg>';
  a.append(text);
  return a;
}

async function showRelease() {
  const buttons = document.querySelector('[data-release-buttons]');
  if (!buttons) return;
  let release;
  try {
    const res = await fetch(`https://api.github.com/repos/${REPO}/releases/latest`, { headers: { Accept: 'application/vnd.github+json' } });
    if (!res.ok) return;
    release = await res.json();
  } catch {
    return;
  }
  const assets = release.assets || [];
  const iso = assets.find((a) => a.name.endsWith('.iso'));
  const parts = assets.filter((a) => /\.iso\.part\d+$/.test(a.name)).sort((a, b) => a.name.localeCompare(b.name));
  const sums = assets.find((a) => a.name === 'SHA256SUMS');
  if (!iso && !parts.length) return;
  const date = new Date(release.published_at).toLocaleDateString([], { year: 'numeric', month: 'long', day: 'numeric' });
  const total = iso ? iso.size : parts.reduce((n, p) => n + p.size, 0);
  document.querySelector('[data-release-version]').textContent = release.tag_name;
  document.querySelector('[data-release-meta]').textContent =
    `Live USB and installer · 64-bit PC · ${gb(total)} · released ${date}`;
  buttons.replaceChildren(...(iso
    ? [downloadButton(iso.browser_download_url, 'Download the ISO', true)]
    : parts.map((p, i) => downloadButton(p.browser_download_url, `Part ${i + 1} of ${parts.length}`, i === 0))));
  const note = document.querySelector('[data-release-note]');
  if (!iso) {
    note.innerHTML = 'This release comes in parts. Download them all, then join them: <code>cat polyos-*.part* &gt; polyos.iso</code> '
      + '(Linux, macOS) or <code>copy /b part0+part1 polyos.iso</code> (Windows).';
  }
  const link = document.querySelector('[data-release-sums]');
  if (sums) link.href = sums.browser_download_url;
  link.textContent = sums ? 'SHA256 checksums' : 'All versions';
  const all = document.createElement('a');
  all.href = release.html_url;
  all.textContent = 'Release notes';
  link.after(' · ', all);
}
showRelease();
