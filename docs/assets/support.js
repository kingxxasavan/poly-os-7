// Help & Support: the contact form posts to /api/support.
const form = document.getElementById('support-form');
if (form) {
  const topic = new URLSearchParams(location.search).get('topic');
  if (topic) form.topic.value = topic;
  const err = form.querySelector('.af-error');
  const ok = form.querySelector('.af-ok');
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    err.hidden = true;
    const button = form.querySelector('button');
    button.disabled = true;
    try {
      const res = await fetch('/api/support', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ topic: form.topic.value, email: form.email.value || undefined, message: form.message.value }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.error || 'That didn’t send. Try again.');
      form.reset();
      ok.hidden = false;
    } catch (x) {
      err.textContent = x.message;
      err.hidden = false;
    } finally {
      button.disabled = false;
    }
  });
}
