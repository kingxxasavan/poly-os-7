// Updates page: every release from /api/releases, newest first. Notes are shown as plain text.
const list = document.getElementById('releases');

function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
}

// Release notes are Markdown; show them as readable text without running any of it as HTML.
function notes(text) {
  const box = el('div', 'release-notes');
  for (const line of String(text || '').split('\n')) {
    const t = line.trim();
    if (!t || /^\|?-{3,}/.test(t) || /^\|.*\|$/.test(t) || /^\*\*Full Changelog/.test(t)) continue;
    const bullet = /^[-*•]\s+/.test(t);
    box.append(el(bullet ? 'li' : 'p', null, t.replace(/^[-*•]\s+/, '').replace(/\*\*(.+?)\*\*/g, '$1').replace(/`([^`]+)`/g, '$1')
      .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1').replace(/^#+\s*/, '')));
  }
  return box;
}

fetch('/api/releases').then((r) => (r.ok ? r.json() : Promise.reject(new Error(r.status)))).then(({ releases }) => {
  list.replaceChildren(...releases.map((r, i) => {
    const item = el('article', 'release');
    const head = el('div', 'release-head');
    head.append(el('h2', null, `PolyOS ${r.version}`));
    if (i === 0) head.append(el('span', 'news-tag', 'Latest'));
    if (r.prerelease) head.append(el('span', 'news-tag beta', 'Beta'));
    head.append(el('time', 'muted', new Date(r.published).toLocaleDateString([], { year: 'numeric', month: 'long', day: 'numeric' })));
    item.append(head, notes(r.notes));
    return item;
  }));
}).catch(() => {
  list.replaceChildren(el('p', 'muted', 'The release list isn’t available right now. The newest version is always on the download page.'));
});
