// Run CMD: start a program, or open a file, folder or website.

import { api, closePopup } from '../api.js';
import { errorText } from '../components.js';
import { h } from '../ui.js';

export default function run(root) {
  root.classList.add('run');
  const input = h('input.run-input', {
    type: 'text', placeholder: 'Type a program, folder or website', autocomplete: 'off', spellcheck: 'false',
    autofocus: true, 'aria-label': 'Command',
  });
  const error = h('div.error-text', { hidden: true });
  const go = h('button.btn.primary', 'Run');
  root.append(
    h('div.run-head', h('span.hm-code', '< >'), h('span', 'Run CMD')),
    h('label.run-field', input),
    error,
    h('div.run-actions',
      h('span.run-hint', 'e.g. firefox-esr, ~/Documents, https://scratch.mit.edu'),
      h('button.btn', { onclick: () => closePopup() }, 'Cancel'),
      go),
  );

  let busy = false;
  async function submit() {
    const command = input.value.trim();
    if (!command || busy) return;
    busy = true;
    go.disabled = true;
    try {
      await api.post('/api/run-command', { command });
      closePopup();
    } catch (err) {
      errorText(error, err.message);
      input.select();
    } finally {
      busy = false;
      go.disabled = false;
    }
  }
  go.addEventListener('click', submit);
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') submit();
  });
  input.addEventListener('input', () => errorText(error, ''));
}
