// Gallery filters and a keyboard-friendly lightbox. The page works without this script.

const figures = [...document.querySelectorAll('.gallery figure')];
const tabs = [...document.querySelectorAll('.filters button')];
let visible = figures;

for (const tab of tabs) {
  tab.addEventListener('click', () => {
    const cat = tab.dataset.filter;
    tabs.forEach((t) => t.setAttribute('aria-selected', String(t === tab)));
    figures.forEach((f) => { f.hidden = cat !== 'all' && f.dataset.cat !== cat; });
    visible = figures.filter((f) => !f.hidden);
  });
}

const box = document.querySelector('.lightbox');
const boxImg = box.querySelector('img');
const boxCap = box.querySelector('figcaption');
let current = 0;
let opener = null;

function show(index) {
  current = (index + visible.length) % visible.length;
  const fig = visible[current];
  boxImg.src = fig.dataset.full;
  boxImg.alt = fig.querySelector('b').textContent;
  boxCap.innerHTML = fig.querySelector('figcaption').innerHTML;
}

function open(fig) {
  opener = fig;
  show(visible.indexOf(fig));
  box.hidden = false;
  document.body.style.overflow = 'hidden';
  box.querySelector('.lb-close').focus();
}

function close() {
  box.hidden = true;
  document.body.style.overflow = '';
  opener?.focus();
}

for (const fig of figures) {
  fig.tabIndex = 0;
  fig.setAttribute('role', 'button');
  fig.setAttribute('aria-label', `Open screenshot: ${fig.querySelector('b').textContent}`);
  fig.addEventListener('click', () => open(fig));
  fig.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); open(fig); } });
}
box.querySelector('.lb-close').addEventListener('click', close);
box.querySelector('.lb-prev').addEventListener('click', () => show(current - 1));
box.querySelector('.lb-next').addEventListener('click', () => show(current + 1));
box.addEventListener('click', (e) => { if (e.target === box) close(); });
document.addEventListener('keydown', (e) => {
  if (box.hidden) return;
  if (e.key === 'Escape') close();
  if (e.key === 'ArrowLeft') show(current - 1);
  if (e.key === 'ArrowRight') show(current + 1);
});
