// Ask Vara: the PolyOS assistant (chat popup from the Home Menu).

import { api, closePopup, openSettings } from '../api.js';
import { fill, h, icon } from '../ui.js';

const SUGGESTIONS = ['Open Firefox', 'Set volume to 40', 'What’s the time?', 'How do I install new apps?'];

export default function vara(root) {
  root.classList.add('vara');
  const log = h('div.va-log', { role: 'log', 'aria-live': 'polite' });
  const input = h('textarea.va-input', { rows: 1, placeholder: 'Ask Vara anything', autofocus: true, 'aria-label': 'Message Vara' });
  const send = h('button.va-send', { title: 'Send', 'aria-label': 'Send' }, icon('arrowRight'));
  root.append(
    h('header.va-head',
      h('img.va-logo', { src: '/img/vara.png', alt: '' }),
      h('div.va-title', h('b', 'Vara'), h('small', 'Your PolyOS assistant')),
      h('button.icon-btn.round', { title: 'New chat', onclick: reset }, icon('refresh')),
      h('button.icon-btn.round', { title: 'Vara settings', onclick: () => { openSettings('vara'); closePopup(); } }, icon('settings'))),
    log,
    h('div.va-compose', input, send),
  );

  let history = [];
  let busy = false;

  function render() {
    if (!history.length && !busy) {
      fill(log, h('div.va-empty',
        h('img', { src: '/img/vara.png', alt: '' }),
        h('b', 'Hi, I’m Vara.'),
        h('p', 'I can open apps, change the volume or brightness, turn Wi-Fi on and off, and answer questions.'),
        h('div.va-chips', SUGGESTIONS.map((s) => h('button.va-chip', { onclick: () => ask(s) }, s)))));
      return;
    }
    fill(log,
      ...history.map((m) => h(`div.va-msg.${m.role === 'user' ? 'me' : 'vara'}`, { class: m.error ? 'error' : '' }, m.content)),
      busy ? h('div.va-msg.vara.typing', h('span'), h('span'), h('span')) : null);
    log.scrollTop = log.scrollHeight;
  }

  async function ask(text) {
    const message = (text ?? input.value).trim();
    if (!message || busy) return;
    input.value = '';
    autosize();
    busy = true;
    history = [...history, { role: 'user', content: message }];
    render();
    try {
      const res = await api.post('/api/vara/chat', { message });
      history = res.history;
    } catch (err) {
      history = [...history, { role: 'assistant', content: err.message, error: true }];
    }
    busy = false;
    render();
    input.focus();
  }

  async function reset() {
    await api.post('/api/vara/reset', {}).catch(() => {});
    history = [];
    render();
    input.focus();
  }

  function autosize() {
    input.style.height = 'auto';
    input.style.height = `${Math.min(input.scrollHeight, 120)}px`;
  }

  input.addEventListener('input', autosize);
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      ask();
    }
  });
  send.addEventListener('click', () => ask());

  api.get('/api/vara/history').then((res) => { history = res.history; render(); }, () => render());
  render();
}
