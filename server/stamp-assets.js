// Vercel's build step (vercel.json "buildCommand"): gives every stylesheet and script link in
// docs/*.html a ?v=<checksum> of that file, so browsers fetch a changed file right away instead
// of reusing an older copy they kept. Run on each deploy; the pages in git stay unstamped.
import { createHash } from 'node:crypto';
import { readdirSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const DOCS = join(dirname(fileURLToPath(import.meta.url)), '..', 'docs');
const LINK = /((?:href|src)=")(\/?assets\/[\w.-]+\.(?:css|js))(?:\?v=\w+)?"/g;
const sums = new Map();
const sum = (file) => {
  if (!sums.has(file)) sums.set(file, createHash('sha256').update(readFileSync(join(DOCS, file))).digest('hex').slice(0, 10));
  return sums.get(file);
};

let stamped = 0;
for (const name of readdirSync(DOCS).filter((n) => n.endsWith('.html'))) {
  const path = join(DOCS, name);
  const before = readFileSync(path, 'utf8');
  const after = before.replace(LINK, (_m, attr, url) => { stamped += 1; return `${attr}${url}?v=${sum(url.replace(/^\//, ''))}"`; });
  if (after !== before) writeFileSync(path, after);
}
console.log(`PolyOS website: ${stamped} stylesheet and script links stamped (${[...sums].map(([f, v]) => `${f}=${v}`).join(', ')})`);
