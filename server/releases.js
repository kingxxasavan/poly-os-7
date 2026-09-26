// PolyOS releases: the ISOs, the update packages and their signed manifest live on GitHub
// Releases of RELEASES_REPO (a public repository just for downloads, so the source can be
// private). The website's download buttons and the update check both read it through here.

const DEFAULT_REPO = 'kingxxasavan/poly-os-7-debain-receration';
const CACHE_MS = 5 * 60 * 1000;
const cache = new Map();

export function releasesRepo() {
  return process.env.RELEASES_REPO || DEFAULT_REPO;
}

export const CHANNELS = ['stable', 'beta', 'developer'];

async function github(path) {
  const hit = cache.get(path);
  if (hit && Date.now() - hit.at < CACHE_MS) return hit.data;
  const headers = { Accept: 'application/vnd.github+json', 'User-Agent': 'PolyOS-website' };
  if (process.env.GITHUB_TOKEN) headers.Authorization = `Bearer ${process.env.GITHUB_TOKEN}`;
  const res = await fetch(`https://api.github.com/repos/${releasesRepo()}${path}`, { headers });
  if (!res.ok) throw Object.assign(new Error(`Release information isn't available right now (${res.status}).`), { status: 502 });
  const data = await res.json();
  cache.set(path, { at: Date.now(), data });
  return data;
}

function summarize(release) {
  const assets = Object.fromEntries((release.assets || []).map((a) => [a.name, { url: a.browser_download_url, size: a.size }]));
  return {
    version: String(release.tag_name || '').replace(/^v/, ''),
    name: release.name || release.tag_name,
    notes: release.body || '',
    published: release.published_at,
    prerelease: Boolean(release.prerelease),
    assets,
  };
}

// stable: the newest full release; beta and developer: the newest release of any kind.
export async function latest(channel = 'stable') {
  if (channel === 'stable') return summarize(await github('/releases/latest'));
  const list = await github('/releases?per_page=10');
  const release = list.find((r) => !r.draft);
  if (!release) throw Object.assign(new Error('No releases yet.'), { status: 404 });
  return summarize(release);
}

export async function history(count = 10) {
  const list = await github(`/releases?per_page=${Math.min(30, count)}`);
  return list.filter((r) => !r.draft).map(summarize).map(({ assets, ...r }) => ({ ...r, files: Object.keys(assets) }));
}

export function versionTuple(v) {
  const m = /^v?(\d+)\.(\d+)\.(\d+)/.exec(String(v || ''));
  return m ? m.slice(1).map(Number) : [0, 0, 0];
}

export function newer(a, b) {
  const x = versionTuple(a);
  const y = versionTuple(b);
  for (let i = 0; i < 3; i += 1) if (x[i] !== y[i]) return x[i] > y[i];
  return false;
}

// What /api/v1/updates/check answers: only what the updater needs, nothing about the asker.
export async function check({ channel = 'stable', version = '0.0.0' } = {}) {
  const rel = await latest(CHANNELS.includes(channel) ? channel : 'stable');
  const manifest = rel.assets['polyos-update.json'];
  const available = newer(rel.version, version);
  return {
    update_available: available && Boolean(manifest),
    version: rel.version,
    notes: rel.notes,
    published: rel.published,
    manifest: manifest?.url || null,
    signature: rel.assets['polyos-update.json.sig']?.url || null,
    size: Object.entries(rel.assets).filter(([n]) => n.endsWith('.deb')).reduce((t, [, a]) => t + (a.size || 0), 0),
    iso_only: available && !manifest,
    mandatory: false,
  };
}
