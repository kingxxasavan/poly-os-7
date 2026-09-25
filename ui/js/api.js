// Transport to the PolyOS backend: JSON API plus a streamed event feed.

const token = (window.POLYOS && window.POLYOS.token) || '';
export const params = new URLSearchParams(location.search);
export const surface = params.get('surface') || 'desktop';

export function withToken(url) {
  if (!url) return url;
  return `${url}${url.includes('?') ? '&' : '?'}t=${encodeURIComponent(token)}`;
}

async function request(method, path, body) {
  const headers = { 'X-PolyOS-Token': token };
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  const res = await fetch(path, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
    cache: 'no-store',
  });
  let data = null;
  try { data = await res.json(); } catch { /* empty body */ }
  if (!res.ok) {
    const err = new Error((data && data.error) || `${res.status} ${res.statusText}`);
    err.status = res.status;
    throw err;
  }
  return data;
}

export const api = {
  get: (path) => request('GET', path),
  post: (path, body = {}) => request('POST', path, body),
};

// ---- events ------------------------------------------------------------------
const listeners = new Map();

export function on(type, fn) {
  if (!listeners.has(type)) listeners.set(type, new Set());
  listeners.get(type).add(fn);
  return () => listeners.get(type).delete(fn);
}

function emit(event) {
  for (const key of [event.type, '*']) {
    for (const fn of listeners.get(key) || []) {
      try { fn(event); } catch (err) { console.error(err); }
    }
  }
}

// Streamed with fetch (not EventSource) so the token can travel in a header.
export async function connectEvents() {
  let delay = 400;
  for (;;) {
    try {
      const res = await fetch('/api/events', { headers: { 'X-PolyOS-Token': token }, cache: 'no-store' });
      if (!res.ok || !res.body) throw new Error(`event stream: HTTP ${res.status}`);
      delay = 400;
      emit({ type: 'connected' });
      const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
      let buffer = '';
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += value;
        let cut;
        while ((cut = buffer.indexOf('\n\n')) >= 0) {
          const chunk = buffer.slice(0, cut);
          buffer = buffer.slice(cut + 2);
          for (const line of chunk.split('\n')) {
            if (line.startsWith('data: ')) {
              try { emit(JSON.parse(line.slice(6))); } catch (err) { console.error(err); }
            }
          }
        }
      }
    } catch (err) {
      console.warn(err.message);
    }
    emit({ type: 'disconnected' });
    await new Promise((resolve) => setTimeout(resolve, delay));
    delay = Math.min(delay * 2, 5000);
  }
}

// ---- common actions ------------------------------------------------------------
export const launch = (id) => api.post('/api/launch', { id });
export const windowAction = (xid, action) => api.post('/api/window', { xid, action });
export const closePopup = () => api.post('/api/popup', { view: null });
export const openSettings = (page) => api.post('/api/open', { app: 'settings', page });
export const power = (action) => api.post('/api/power', { action });
export const saveSettings = (patch) => api.post('/api/settings', patch);
