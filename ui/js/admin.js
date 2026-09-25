// Administrator access and background jobs (installing PolyOS, drivers and apps).
//
// Actions that need root answer 401 until the person enters their password; withAdmin()
// shows the PolyOS password dialog, unlocks sudo through /api/admin/auth and retries.

import { api, on } from './api.js';
import { h } from './ui.js';

export function askPassword({ title = 'Enter your password', text = 'PolyOS needs your password to install software.' } = {}) {
  return new Promise((resolve) => {
    const input = h('input.ad-input', { type: 'password', placeholder: 'Password', autocomplete: 'current-password', 'aria-label': 'Password' });
    const error = h('div.ad-error', { hidden: true });
    const ok = h('button.pill-btn.on', { type: 'submit' }, 'Continue');
    const cancel = h('button.pill-btn', { type: 'button' }, 'Cancel');
    const form = h('form.ad-card', { role: 'dialog', 'aria-modal': 'true', 'aria-label': title },
      h('img.ad-logo', { src: '/img/logo-white.svg', alt: '' }),
      h('b', title), h('p', text), input, error, h('div.ad-actions', cancel, ok));
    const backdrop = h('div.ad-backdrop', form);
    const close = (value) => {
      backdrop.remove();
      document.removeEventListener('keydown', onKey, true);
      resolve(value);
    };
    const onKey = (e) => { if (e.key === 'Escape') { e.preventDefault(); close(false); } };
    cancel.addEventListener('click', () => close(false));
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      ok.disabled = true;
      error.hidden = true;
      try {
        await api.post('/api/admin/auth', { password: input.value });
        close(true);
      } catch (err) {
        error.textContent = err.message;
        error.hidden = false;
        ok.disabled = false;
        input.select();
      }
    });
    document.addEventListener('keydown', onKey, true);
    document.body.append(backdrop);
    setTimeout(() => input.focus(), 30);
  });
}

// Run fn(); if it needs the administrator password, ask for it and try again.
export async function withAdmin(fn, prompt) {
  try {
    return await fn();
  } catch (err) {
    if (err.status !== 401) throw err;
    if (!(await askPassword(prompt))) {
      const cancelled = new Error('Cancelled.');
      cancelled.cancelled = true;
      throw cancelled;
    }
    return fn();
  }
}

// Current state of background jobs, kept up to date from the event stream.
export function watchJobs(onChange) {
  const jobs = new Map();
  const set = (job) => {
    jobs.set(job.id, job);
    onChange(job, jobs);
  };
  api.get('/api/jobs').then((res) => res.jobs.forEach(set), () => {});
  const off = on('job', (e) => set(e.job));
  return { jobs, off };
}
