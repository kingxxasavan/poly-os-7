// Passwords, tokens and codes. Everything secret is stored only as a hash: passwords and recovery
// keys with scrypt (slow on purpose), random tokens and device credentials with SHA-256.

import crypto from 'node:crypto';
import { promisify } from 'node:util';

const scrypt = promisify(crypto.scrypt);
const SCRYPT = { N: 16384, r: 8, p: 1, maxmem: 64 * 1024 * 1024 };
const KEYLEN = 32;

export async function hashSecret(secret) {
  const salt = crypto.randomBytes(16);
  const key = await scrypt(secret.normalize('NFKC'), salt, KEYLEN, SCRYPT);
  return `scrypt$${SCRYPT.N}$${SCRYPT.r}$${SCRYPT.p}$${salt.toString('base64')}$${key.toString('base64')}`;
}

export async function verifySecret(secret, stored) {
  if (typeof secret !== 'string' || typeof stored !== 'string') return false;
  const [kind, n, r, p, salt, key] = stored.split('$');
  if (kind !== 'scrypt' || !salt || !key) return false;
  const expected = Buffer.from(key, 'base64');
  const got = await scrypt(secret.normalize('NFKC'), Buffer.from(salt, 'base64'), expected.length,
    { N: Number(n), r: Number(r), p: Number(p), maxmem: SCRYPT.maxmem });
  return crypto.timingSafeEqual(expected, got);
}

// A hash that makes timing the same whether or not an account exists (sign in with an unknown email).
let dummy = null;
export async function dummyVerify(secret) {
  dummy = dummy || await hashSecret('not-a-real-password');
  await verifySecret(String(secret || ''), dummy);
  return false;
}

export function token(prefix = '') {
  return prefix + crypto.randomBytes(32).toString('base64url');
}

export function sha256(text) {
  return crypto.createHash('sha256').update(String(text)).digest('hex');
}

// "482913": what a new device shows and its owner types on the website.
export function userCode() {
  return String(crypto.randomInt(0, 1_000_000)).padStart(6, '0');
}

// Recovery keys: 24 characters from an alphabet without look-alikes (≈120 bits), in groups of four.
const ALPHABET = '23456789ABCDEFGHJKLMNPQRSTUVWXYZ';
export function recoveryKey() {
  const bytes = crypto.randomBytes(24);
  const chars = [...bytes].map((b) => ALPHABET[b % ALPHABET.length]).join('');
  return chars.match(/.{4}/g).join('-');
}

export function normalizeRecoveryKey(key) {
  return String(key || '').toUpperCase().replace(/[^0-9A-Z]/g, '').match(/.{1,4}/g)?.join('-') || '';
}

export function passwordProblem(password) {
  if (typeof password !== 'string' || password.length < 10) return 'Use at least 10 characters for your password.';
  if (password.length > 200) return 'That password is too long.';
  if (/^(.)\1+$/.test(password)) return 'Choose a password that isn’t one repeated character.';
  const common = ['password12', 'password123', '1234567890', 'qwertyuiop', '0123456789', 'polyos1234'];
  if (common.includes(password.toLowerCase())) return 'That password is too easy to guess.';
  return null;
}
