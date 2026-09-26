// Account emails through Resend (resend.com: RESEND_API_KEY and EMAIL_FROM in Vercel's settings).
// Without them, accounts still work; emails are skipped and the site says email isn't set up.

export function emailEnabled() {
  return Boolean(process.env.RESEND_API_KEY && process.env.EMAIL_FROM);
}

export const outbox = []; // what would have been sent, when email isn't set up (dev and tests)

function layout(title, body, button) {
  const btn = button ? `<p style="margin:28px 0"><a href="${button.url}" style="background:#678fd9;color:#fff;padding:12px 22px;border-radius:999px;text-decoration:none;font-weight:600">${button.label}</a></p>
    <p style="color:#888;font-size:13px">Or open this link: ${button.url}</p>` : '';
  return `<div style="font-family:Segoe UI,system-ui,sans-serif;max-width:520px;margin:auto;padding:24px;color:#1d1d21">
    <p style="font-weight:700;font-size:18px">Poly Account</p><h1 style="font-size:22px">${title}</h1>${body}${btn}
    <p style="color:#888;font-size:12px;margin-top:32px">You're getting this because of your Poly Account. Poly never asks for your password by email.</p></div>`;
}

export async function sendEmail(to, subject, { title, body, button, text }) {
  const message = { to, subject, text: text || `${title}\n\n${button ? button.url : ''}` };
  if (!emailEnabled()) {
    outbox.push({ ...message, button });
    if (outbox.length > 50) outbox.shift();
    return { sent: false };
  }
  const res = await fetch('https://api.resend.com/emails', {
    method: 'POST',
    headers: { Authorization: `Bearer ${process.env.RESEND_API_KEY}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({ from: process.env.EMAIL_FROM, to: [to], subject, html: layout(title, body, button), text: message.text }),
  });
  if (!res.ok) console.error('email failed', res.status, await res.text().catch(() => ''));
  return { sent: res.ok };
}
