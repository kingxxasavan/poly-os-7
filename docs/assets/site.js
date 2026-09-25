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

// ---- Download ------------------------------------------------------------------------------
// The buttons link to this site's own /download/pc and /download/arm64 (vercel.json sends them to
// the newest release file), so downloading starts right here. The newest release's details
// (version, sizes) come from GitHub's API; where the site's links don't exist (another host, an
// older release with different file names) the buttons use the release files directly.
const REPO = 'kingxxasavan/poly-os-7-debain-receration';
const ARCHES = { amd64: ['pc', 'PC (Intel/AMD)'], arm64: ['arm64', 'ARM64'] };

function gb(bytes) {
  return `${(bytes / 1e9).toFixed(bytes >= 1e10 ? 0 : 1)} GB`;
}

function downloadButton(href, arch, text, primary, detail) {
  const a = document.createElement('a');
  a.className = primary ? 'btn primary big' : 'btn big';
  a.href = href;
  a.dataset.arch = arch;
  a.innerHTML = '<svg class="ico"><use href="#i-download"/></svg>';
  a.append(text);
  if (detail) {
    const small = document.createElement('small');
    small.textContent = detail;
    a.append(small);
  }
  return a;
}

async function visitorOnArm() {
  try {
    const hints = await navigator.userAgentData?.getHighEntropyValues(['architecture']);
    return hints?.architecture === 'arm';
  } catch {
    return false;
  }
}

// True when this site forwards /download/... (hosted on Vercel with vercel.json).
async function siteLinks() {
  try {
    const res = await fetch('download/checksums', { method: 'HEAD', redirect: 'manual', cache: 'no-store' });
    return res.type === 'opaqueredirect' || (res.status >= 300 && res.status < 400);
  } catch {
    return false;
  }
}

async function showRelease() {
  const buttons = document.querySelector('[data-release-buttons]');
  if (!buttons) return;
  const [release, local, onArm] = await Promise.all([
    fetch(`https://api.github.com/repos/${REPO}/releases/latest`, { headers: { Accept: 'application/vnd.github+json' } })
      .then((r) => (r.ok ? r.json() : null), () => null),
    siteLinks(),
    visitorOnArm(),
  ]);
  if (!release) {
    if (onArm) buttons.prepend(buttons.querySelector('[data-arch="arm64"]'));
    return;
  }
  const assets = release.assets || [];
  const builds = Object.entries(ARCHES).map(([arch, [slug, label]]) => {
    const iso = assets.find((a) => a.name.endsWith(`-${arch}.iso`));
    const parts = assets.filter((a) => a.name.includes(`-${arch}.iso.part`)).sort((a, b) => a.name.localeCompare(b.name));
    // the site's own link works when the release uses the fixed name it forwards to
    const href = iso && local && iso.name === `polyos-${arch}.iso` ? `download/${slug}` : iso?.browser_download_url;
    return { arch, label, iso, parts, href, size: iso ? iso.size : parts.reduce((n, p) => n + p.size, 0) };
  }).filter((b) => b.iso || b.parts.length);
  if (!builds.length) return;
  if (builds.length > 1 && onArm) builds.reverse(); // ARM64 first on ARM computers
  const date = new Date(release.published_at).toLocaleDateString([], { year: 'numeric', month: 'long', day: 'numeric' });
  document.querySelector('[data-release-version]').textContent = release.tag_name;
  document.querySelector('[data-release-meta]').textContent =
    `Live USB and installer · ${builds.map((b) => b.label).join(' and ')} · released ${date}`;
  buttons.replaceChildren(...builds.flatMap((b, i) => (b.iso
    ? [downloadButton(b.href, b.arch, `Download for ${b.label}`, i === 0, gb(b.size))]
    : b.parts.map((p, n) => downloadButton(p.browser_download_url, b.arch, `${b.label}, part ${n + 1} of ${b.parts.length}`,
      i === 0 && n === 0, gb(p.size))))));
  if (builds.length < 2) document.querySelector('.dl-which')?.setAttribute('hidden', '');
  if (builds.some((b) => !b.iso)) {
    document.querySelector('[data-release-note]').innerHTML = 'Some downloads come in parts. Download them all, then join them: '
      + '<code>cat polyos-*.part* &gt; polyos.iso</code> (Linux, macOS) or <code>copy /b part0+part1 polyos.iso</code> (Windows).';
  }
  const sums = assets.find((a) => a.name === 'SHA256SUMS');
  const link = document.querySelector('[data-release-sums]');
  if (sums && !local) link.href = sums.browser_download_url;
  if (!sums) link.hidden = true;
}
showRelease();

// ---- the install guide, shown when a download starts ------------------------------------------
const guide = document.querySelector('.guide');
let lastDownload = null;

function openGuide(button) {
  lastDownload = button;
  const label = ARCHES[button.dataset.arch]?.[1] || '';
  const size = button.querySelector('small')?.textContent;
  guide.querySelector('[data-guide-file]').textContent = `PolyOS 7 for ${label}${size ? ` · ${size}` : ''}`;
  guide.querySelectorAll('[data-vm]').forEach((li) => { li.hidden = li.dataset.vm !== button.dataset.arch; });
  showTab(button.dataset.arch === 'arm64' ? 'vm' : 'usb');
  guide.showModal();
}

function showTab(name) {
  guide.querySelectorAll('[data-guide-tab]').forEach((t) => t.setAttribute('aria-selected', String(t.dataset.guideTab === name)));
  guide.querySelectorAll('[data-guide-panel]').forEach((p) => { p.hidden = p.dataset.guidePanel !== name; });
}

if (guide) {
  document.querySelector('[data-release-buttons]')?.addEventListener('click', (e) => {
    const button = e.target.closest('a[data-arch]');
    if (button) openGuide(button); // the link itself carries on and starts the download
  });
  guide.querySelectorAll('[data-guide-tab]').forEach((t) => t.addEventListener('click', () => showTab(t.dataset.guideTab)));
  guide.querySelector('.guide-close').addEventListener('click', () => guide.close());
  guide.addEventListener('click', (e) => { if (e.target === guide) guide.close(); });
  guide.querySelector('[data-guide-retry]').addEventListener('click', (e) => {
    e.preventDefault();
    if (lastDownload) window.location.href = lastDownload.href;
  });
}
