// The website and Poly Account on this computer: npm install && npm run dev (http://localhost:8792).
// Like Vercel: docs/ as the site (with clean URLs, so /account is account.html), /api/… to the API.
// The database is PGlite in memory, or in the folder named by POLY_DEV_DB.

import fs from 'node:fs';
import http from 'node:http';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { handle } from './app.js';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', 'docs');
const port = Number(process.env.PORT || 8792);
const types = { '.html': 'text/html; charset=utf-8', '.css': 'text/css', '.js': 'text/javascript', '.svg': 'image/svg+xml',
  '.png': 'image/png', '.jpg': 'image/jpeg', '.ttf': 'font/ttf', '.json': 'application/json', '.webp': 'image/webp' };

function serveFile(res, file) {
  res.writeHead(200, { 'Content-Type': types[path.extname(file)] || 'application/octet-stream' });
  fs.createReadStream(file).pipe(res);
}

http.createServer((req, res) => {
  const url = new URL(req.url, 'http://localhost');
  if (url.pathname.startsWith('/api/')) return handle(req, res);
  const dl = /^\/download\/([a-z0-9]+)$/.exec(url.pathname);
  if (dl) {
    req.url = `/api/download/${dl[1]}`;
    return handle(req, res);
  }
  let rel = decodeURIComponent(url.pathname);
  if (rel.endsWith('/')) rel += 'index.html';
  const file = path.join(root, rel);
  if (!file.startsWith(root)) { res.writeHead(403); return res.end(); }
  for (const candidate of [file, `${file}.html`]) {
    if (fs.existsSync(candidate) && fs.statSync(candidate).isFile()) return serveFile(res, candidate);
  }
  res.writeHead(404, { 'Content-Type': 'text/html' });
  return fs.existsSync(path.join(root, '404.html')) ? fs.createReadStream(path.join(root, '404.html')).pipe(res) : res.end('Not found');
}).listen(port, () => console.log(`PolyOS website and Poly Account: http://localhost:${port}`));
