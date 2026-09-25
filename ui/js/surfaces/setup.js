// PolyOS 7 setup, after the Scratch original: "Cryptic Software presents", the pinwheel falls
// into place, the striped 7 slides in, and the crystal backdrop says welcome. Then:
//   live USB:      It's time to get started (install / dual boot / custom) → Terms → Edition
//                  → Account → Appearance → Where to install → installing → restart
//   first sign-in: Wi-Fi → Drivers → your edition's apps → Vara → Tour → done

import { withAdmin, watchJobs } from '../admin.js';
import { api, launch, saveSettings, withToken } from '../api.js';
import { VARA_PROVIDERS, packPanel, providerFor, wifiPanel } from '../components.js';
import { fill, formatBytes, h, hexToHue, hueToHex, icon, networkLabel, throttle } from '../ui.js';

const GB = 1000 ** 3;
const TERMS =
  'BY CLICKING “I AGREE”, YOU AGREE TO THE FOLLOWING TERMS AND CONDITIONS: PolyOS 7 for Debian is presented by ' +
  'Cryptic Software and based on PolyOS, created in Scratch by AndrewInput and PIXAPoLY Software. PolyOS is free ' +
  'software: you may use, copy, change and share it under the GNU General Public License, version 3 or later. It is ' +
  'built on Debian GNU/Linux and includes software from many open-source projects, each under its own license; some ' +
  'drivers and firmware are non-free and are covered by their makers’ licenses. The PolyOS logo, colors and PIXAPoLY ' +
  'artwork come from the PolyOS 7 Scratch project and are shared under CC BY-SA 2.0. “Scratch” is a trademark of the ' +
  'Scratch Foundation; PolyOS is not affiliated with or sponsored by the Scratch Foundation, Debian or any app maker. ' +
  'Installing an operating system changes your disk: back up anything important first. THIS SOFTWARE COMES WITH ' +
  'ABSOLUTELY NO WARRANTY, TO THE EXTENT PERMITTED BY APPLICABLE LAW.';
const TOUR = [
  ['Home Menu', 'Click the pinwheel in the dock or tap the Windows key. Tap it again to close.'],
  ['Right-click', 'Right-click (or tap with two fingers) the desktop to personalize PolyOS or open Task Manager.'],
  ['PolyMarket', 'Get Chrome, Discord, Spotify, Steam and more from PolyOS’s store of trusted apps.'],
  ['Shortcuts', 'Win+S all apps · Win+E Files · Win+X quick menu · Ctrl+Shift+Esc Task Manager · Win+L lock.'],
];
const FALLBACK_ZONES = ['America/New_York', 'America/Chicago', 'America/Denver', 'America/Los_Angeles', 'America/Phoenix',
  'America/Anchorage', 'Pacific/Honolulu', 'America/Toronto', 'America/Mexico_City', 'America/Sao_Paulo', 'Europe/London',
  'Europe/Paris', 'Europe/Berlin', 'Europe/Madrid', 'Africa/Lagos', 'Africa/Johannesburg', 'Asia/Dubai', 'Asia/Kolkata',
  'Asia/Shanghai', 'Asia/Tokyo', 'Asia/Seoul', 'Australia/Sydney', 'UTC'];

// PolyOS editions, chosen while installing. Each one's apps are added at first sign-in (online).
export const EDITIONS = [
  ['regular', 'Regular', 'Everything most people need: the PolyOS desktop, Firefox, Files and PolyMarket.', 'star'],
  ['developer', 'Developer', 'Change PolyOS itself, and get coding tools: Git, Python and its libraries, Node.js, VS Code, Docker and Blender.', 'code'],
  ['gaming', 'Gaming', 'Steam, Wine for Windows games, Heroic, Lutris, cloud gaming, drivers and Game Mode, set up for play.', 'gamepad'],
];
// Custom install: what an existing partition can become (value -> [label, mount, erase]).
const ROLES = {
  keep: ['Keep as it is', null, false],
  root: ['PolyOS (/) · erase', '/', true],
  'home-keep': ['Your files (/home) · keep what’s on it', '/home', false],
  'home-format': ['Your files (/home) · erase', '/home', true],
  'storage-keep': ['Extra storage · keep what’s on it', 'storage', false],
  'storage-format': ['Extra storage · erase', 'storage', true],
  efi: ['EFI boot partition (/boot/efi)', '/boot/efi', false],
  swap: ['Swap · erase', 'swap', true],
};
const LINUX_FS = ['ext4', 'ext3', 'ext2', 'btrfs', 'xfs', 'f2fs'];
// partition types the drive screen names (GPT type GUIDs, lowercase as lsblk prints them)
const MSR_GUID = 'e3c9e316-0b5c-4db8-817d-f92df00215ae';
const WINRE_GUID = 'de94bba4-06d1-4d40-a16a-bfd50179d6ac';
const BIOS_BOOT_GUID = '21686148-6449-6e6f-744e-656564454649';
const READABLE_FS = [...LINUX_FS, 'ntfs', 'vfat', 'exfat'];

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const reduceMotion = () => window.matchMedia('(prefers-reduced-motion: reduce)').matches;

function timeZones() {
  try {
    const list = Intl.supportedValuesOf('timeZone');
    if (list && list.length) return list;
  } catch { /* older engines */ }
  return FALLBACK_ZONES;
}

function guessZone() {
  const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
  return tz && tz !== 'UTC' && tz !== 'Etc/UTC' ? tz : 'America/New_York';
}

// 25 Crockford base32 characters (125 bits), the format polyos/recovery.py expects.
function recoveryKey() {
  const alphabet = '0123456789ABCDEFGHJKMNPQRSTVWXYZ';
  const bytes = crypto.getRandomValues(new Uint8Array(25));
  const raw = [...bytes].map((b) => alphabet[b % 32]).join('');
  return raw.match(/.{5}/g).join('-');
}

function usernameFrom(name) {
  const first = (name.trim().split(/\s+/)[0] || '').normalize('NFKD').replace(/[^\w]/g, '').toLowerCase().replace(/_/g, '');
  const clean = first.replace(/[^a-z0-9]/g, '').slice(0, 24);
  return clean ? (/^[a-z]/.test(clean) ? clean : `u${clean}`) : '';
}

export function mount(root, store) {
  const live = !!store.state.env.live;
  root.className = 'setup';
  const bg = h('div.su-bg');
  const scrim = h('div.su-scrim');
  const intro = h('div.su-intro');
  const card = h('section.su-card');
  const pills = h('div.su-pills');
  const stage = h('div.su-stage', card);
  root.append(bg, scrim, intro, stage, pills);
  bg.style.backgroundImage = `url("${withToken('/wallpaper/builtin/polyos-crystal.jpg')}")`;

  const plan = {
    mode: 'pick', disk: null, size: null, hostname: '', timezone: guessZone(), edition: 'regular',
    pick: null, // the drive screen: { kind: 'part' | 'space', disk, device | start }
    wipe: {}, roles: {}, // custom mode: drive -> what it's erased for; partition -> ROLES key
    user: { fullName: '', username: '', password: '' },
    appearance: { theme: store.state.settings.theme || 'dark', accent: store.state.settings.accent },
  };
  let probe = null;        // disks from /api/install/probe (fetched while the person fills in the rest)
  let probeError = null;
  let usernameEdited = false;
  let hostnameEdited = false;
  let installJob = null;
  let progressEls = null; // the install progress screen, updated in place
  let wifi = null;

  // ---- intro ---------------------------------------------------------------------------
  async function playIntro() {
    const skip = { done: false };
    const skipper = (e) => {
      if (e.type === 'keydown' && !['Enter', ' ', 'Escape'].includes(e.key)) return;
      skip.done = true;
    };
    root.addEventListener('pointerdown', skipper);
    document.addEventListener('keydown', skipper);
    const wait = async (ms) => {
      const end = Date.now() + (reduceMotion() ? ms / 4 : ms);
      while (Date.now() < end && !skip.done) await sleep(40);
    };
    const name = (store.state.user.fullName || '').split(' ')[0];
    const presents = h('div.in-presents', h('span', 'Cryptic Software'), h('small', 'presents'));
    const logo = h('img.in-logo', { src: '/img/logo-white.svg', alt: '' });
    const seven = h('img.in-seven', { src: '/img/seven.svg', alt: '' });
    const mark = h('div.in-mark', logo, seven);
    const hello = h('div.in-hello', h('h1', 'Welcome to PolyOS 7'),
      h('p', live ? 'We’re glad you’re here.' : `We’re glad you’re here${name ? `, ${name}` : ''}.`));
    fill(intro, presents, mark, hello);
    root.classList.add('intro');
    if (live) {
      presents.classList.add('show');
      await wait(2300);
      presents.classList.remove('show');
      await wait(700);
    }
    mark.classList.add('fall');
    await wait(1100);
    mark.classList.add('landed', 'seven');
    await wait(1300);
    root.classList.add('crystal');
    mark.classList.add('up');
    await wait(900);
    hello.classList.add('show');
    await wait(1400);
    hello.classList.add('second');
    await wait(1700);
    root.removeEventListener('pointerdown', skipper);
    document.removeEventListener('keydown', skipper);
    root.classList.add('crystal');
    root.classList.remove('intro');
    intro.classList.add('gone');
    setTimeout(() => intro.remove(), 700);
  }

  // ---- steps ---------------------------------------------------------------------------
  const installSteps = [start, terms, edition, account, appearance, target, installing];
  const welcomeSteps = [connect, drivers, editionApps, vara, tour, done];
  const steps = live ? installSteps : welcomeSteps;
  let step = 0;

  function go(n) {
    step = Math.max(0, Math.min(steps.length - 1, n));
    wifi = null;
    progressEls = null;
    card.classList.remove('enter', 'light');
    void card.offsetWidth;
    card.classList.add('enter');
    card.classList.toggle('light', live && plan.appearance.theme === 'light' && steps[step] === appearance);
    fill(card, ...steps[step](), h('img.su-seven', { src: '/img/seven.svg', alt: '' }));
    const count = live ? installSteps.length - 1 : steps.length;
    fill(pills, ...Array.from({ length: count }, (_, i) => h('span', { class: i < step ? 'done' : i === step ? 'on' : '' })));
    pills.hidden = live && step >= count;
    card.querySelector('[autofocus]')?.focus();
  }

  const head = (title, sub) => [h('h1', title), sub ? h('p.su-sub', sub) : null];
  const back = () => h('button.su-back', { onclick: () => go(step - 1), title: 'Back' }, icon('chevronLeft'), 'Back');
  const next = (label = 'Next', onclick = () => go(step + 1), opts = {}) =>
    h('button.su-next', { onclick, disabled: opts.disabled, class: opts.primary ? 'primary' : '' }, label);
  const nav = (...right) => h('div.su-nav', step > 0 ? back() : h('span'), h('div.su-nav-right', ...right));
  const option = (title, sub, trailing, onclick) => h('button.su-option', { onclick },
    h('span.su-option-text', h('b', title), h('small', sub)), trailing);

  // live USB --------------------------------------------------------------------------
  function start() {
    const extra = [];
    extra.push(h('button.su-link', { onclick: tryFirst }, 'Try PolyOS first'));
    if (store.state.env.installer) {
      extra.push(h('span.su-dot', '·'), h('button.su-link', { onclick: () => launch(store.state.env.installer) }, 'Advanced installer'));
    }
    return [
      ...head('It’s time to get started.', 'Pick an option to continue installation or dual boot.'),
      h('div.su-options',
        option('Install PolyOS 7', 'Choose a drive or partition, like Windows Setup.', h('img', { src: '/img/logo-white.svg', alt: '' }),
          () => { plan.mode = 'pick'; go(1); }),
        option('Dual boot', 'Next to Windows or Linux: PolyOS makes room by itself.', h('span.su-dual', icon('window'), icon('window')),
          () => { plan.mode = 'alongside'; go(1); })),
      h('div.su-foot', ...extra),
    ];
  }

  function terms() {
    return [
      ...head('Terms and conditions', 'Agree to the terms and conditions to continue installation.'),
      h('div.su-terms', { tabindex: '0' }, h('p', TERMS),
        h('small', '*PolyOS™ is a trademark of PIXAPoLY Software. The full license texts are in /usr/share/common-licenses on the installed system.')),
      nav(next('I Agree', () => go(step + 1), { primary: true })),
    ];
  }

  function edition() {
    const cards = EDITIONS.map(([id, name, text, ico]) => h('button.su-edition', {
      class: plan.edition === id ? 'on' : '', role: 'radio', 'aria-checked': String(plan.edition === id),
      onclick: () => { plan.edition = id; go(step); },
    }, h('span.su-edition-ico', icon(ico)), h('b', name), h('small', text), plan.edition === id ? h('span.su-edition-check', icon('check')) : null));
    return [
      ...head('How will you use PolyOS?', 'Pick an edition. You can add the others later in Settings.'),
      h('div.su-editions', { role: 'radiogroup', 'aria-label': 'Edition' }, cards),
      plan.edition === 'regular' ? null : h('p.su-note', icon('info'),
        'Its apps are downloaded the first time you sign in, so connect to the internet then.'),
      nav(next()),
    ];
  }

  function account() {
    const err = h('div.su-error', { hidden: true });
    const name = h('input.su-input', { value: plan.user.fullName, placeholder: 'Your name', autocomplete: 'name', autofocus: true, maxlength: 80 });
    const user = h('input.su-input', { value: plan.user.username, placeholder: 'username', autocomplete: 'username', spellcheck: 'false', maxlength: 32 });
    const pass = h('input.su-input', { type: 'password', value: plan.user.password, placeholder: 'Type a password', autocomplete: 'new-password' });
    const confirm = h('input.su-input', { type: 'password', value: plan.user.password, placeholder: 'Type it again', autocomplete: 'new-password' });
    const host = h('input.su-input', { value: plan.hostname, placeholder: 'computer-name', spellcheck: 'false', maxlength: 63 });
    const zone = h('select.su-input', timeZones().map((z) => h('option', { value: z, selected: z === plan.timezone }, z.replace(/_/g, ' '))));
    name.addEventListener('input', () => {
      plan.user.fullName = name.value;
      if (!usernameEdited) user.value = plan.user.username = usernameFrom(name.value);
      if (!hostnameEdited) host.value = plan.hostname = user.value ? `${user.value}-polyos` : '';
    });
    user.addEventListener('input', () => {
      usernameEdited = true;
      user.value = user.value.toLowerCase().replace(/[^a-z0-9_-]/g, '');
      plan.user.username = user.value;
      if (!hostnameEdited) host.value = plan.hostname = user.value ? `${user.value}-polyos` : '';
    });
    host.addEventListener('input', () => {
      hostnameEdited = true;
      host.value = host.value.toLowerCase().replace(/[^a-z0-9-]/g, '');
      plan.hostname = host.value;
    });
    zone.addEventListener('change', () => { plan.timezone = zone.value; });
    const nextBtn = next('Next', () => {
      const problem = !plan.user.fullName.trim() ? 'Enter your name.'
        : !/^[a-z_][a-z0-9_-]{0,31}$/.test(plan.user.username) ? 'Usernames start with a letter and use lowercase letters, numbers, - and _.'
          : pass.value !== confirm.value ? 'The passwords don’t match.'
            : !/^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$/.test(plan.hostname) ? 'Computer names use letters, numbers and hyphens.' : null;
      if (problem) {
        err.textContent = problem;
        err.hidden = false;
        return;
      }
      plan.user.password = pass.value;
      go(step + 1);
    });
    const blank = h('p.su-note', { hidden: !!plan.user.password }, icon('info'),
      'With no password, PolyOS signs you in automatically and anyone using this computer can change it.');
    pass.addEventListener('input', () => { blank.hidden = !!pass.value; });
    const field = (label, input, hint) => h('label.su-field', h('span', label), input, hint ? h('small', hint) : null);
    return [
      ...head('Create your account', 'Choose a name and a password for your desktop. If you want, you can leave the password blank.'),
      h('div.su-form',
        field('Your name', name),
        field('Username', user, 'For signing in. Lowercase, no spaces.'),
        field('Password', pass),
        field('Confirm password', confirm),
        field('Computer name', host),
        field('Time zone', zone)),
      blank, err,
      nav(nextBtn),
    ];
  }

  function appearance() {
    const pick = async (theme) => {
      plan.appearance.theme = theme;
      card.classList.toggle('light', theme === 'light');
      darkBtn.classList.toggle('on', theme === 'dark');
      lightBtn.classList.toggle('on', theme === 'light');
      await saveSettings({ theme }).catch(() => {});
    };
    const darkBtn = h('button.su-theme.dark', { class: plan.appearance.theme === 'dark' ? 'on' : '', onclick: () => pick('dark'), 'aria-label': 'Dark' }, icon('moon'), h('span', 'Dark'));
    const lightBtn = h('button.su-theme.light', { class: plan.appearance.theme === 'light' ? 'on' : '', onclick: () => pick('light'), 'aria-label': 'Light' }, icon('sun'), h('span', 'Light'));
    const hue = h('input.range.hue-range.su-hue', { type: 'range', min: 0, max: 359, value: hexToHue(plan.appearance.accent), 'aria-label': 'Accent color' });
    const send = throttle((v) => saveSettings({ accent: v }).catch(() => {}), 200);
    hue.addEventListener('input', () => {
      plan.appearance.accent = hueToHex(Number(hue.value));
      document.documentElement.style.setProperty('--accent', plan.appearance.accent);
      send(plan.appearance.accent);
    });
    return [
      ...head('Appearance', 'Customize whether dark or light theme should be used, and UI accent color. This can be changed anytime.'),
      h('div.su-themes', darkBtn, lightBtn),
      h('div.su-accent', h('span', 'Accent color'), hue),
      nav(next()),
    ];
  }

  function loadProbe() {
    if (probe || probeError === 'loading') return;
    probeError = 'loading';
    api.get('/api/install/probe').then((res) => {
      probe = res;
      probeError = null;
      if (steps[step] === target) go(step);
    }, (err) => {
      probeError = err.message;
      if (steps[step] === target) go(step);
    });
  }

  function target() {
    const erase = plan.mode === 'erase';
    const title = erase ? 'Where should PolyOS go?' : 'Make room for PolyOS';
    const sub = erase ? 'Choose the disk to install PolyOS on. Everything on it will be replaced.'
      : 'PolyOS will sit next to your other system. You’ll pick which one to start each time you turn on the computer.';
    if (!probe) {
      if (probeError && probeError !== 'loading') {
        return [...head(title, sub), h('div.su-error', probeError),
          nav(next('Try again', () => { probeError = null; loadProbe(); go(step); }))];
      }
      loadProbe();
      return [...head(title, sub), h('div.su-wait', h('img.su-spin', { src: '/img/logo-white.svg', alt: '' }), 'Looking at your disks…'), nav(h('span'))];
    }
    if (plan.mode === 'custom') return customTarget();
    if (plan.mode === 'pick') return drivesScreen();
    const usable = probe.disks.filter((d) => (erase ? d.canErase : d.alongside.possible));
    if (!usable.length) {
      const reasons = probe.disks.filter((d) => !d.isLive).map((d) => h('li', h('b', `${d.model} (${formatBytes(d.size)})`), ': ',
        erase ? 'too small or read-only.' : d.alongside.reason));
      return [...head(title, erase ? 'PolyOS couldn’t find a disk to install on.' : 'PolyOS can’t fit next to your other system yet.'),
        h('ul.su-reasons', reasons.length ? reasons : [h('li', 'No internal disk was found.')]),
        nav(erase ? h('span') : next('Fresh install instead', () => { plan.mode = 'erase'; go(step); }))];
    }
    if (!usable.some((d) => d.path === plan.disk)) {
      const internal = usable.filter((d) => !d.removable);
      plan.disk = (erase ? (internal[0] || usable[0]) : usable[0]).path;
      plan.size = null;
    }
    const disk = () => usable.find((d) => d.path === plan.disk);
    const understood = h('input', { type: 'checkbox' });
    const install = next('Install', () => startInstall(), { primary: true, disabled: true });
    understood.addEventListener('change', () => { install.disabled = !understood.checked; });
    const list = h('div.su-disks', usable.map((d) => h('button.su-disk', {
      class: d.path === plan.disk ? 'on' : '',
      onclick: () => { plan.disk = d.path; plan.size = null; go(step); },
    }, h('span.su-disk-ico', icon(d.transport === 'usb' || d.removable ? 'download' : 'disk')),
    h('span.su-disk-text', h('b', d.model), h('small', `${formatBytes(d.size)} · ${d.transport ? d.transport.toUpperCase() : 'disk'}${d.oses.length ? ` · ${d.oses.join(', ')}` : ''}`)),
    d.path === plan.disk ? icon('check') : null)));
    const body = [list];
    const d = disk();
    if (erase) {
      body.push(h('p.su-warn', icon('info'), d.oses.length
        ? `${d.oses.join(' and ')} and all files on ${d.model} will be erased.`
        : `All files on ${d.model} will be erased.`));
      body.push(h('label.su-check', understood, h('span', 'I understand that this disk will be erased.')));
    } else {
      const opt = d.alongside;
      plan.size = plan.size || opt.suggested;
      const other = d.oses[0] || 'Your other system';
      const range = h('input.range.su-size', { type: 'range', min: opt.minBytes, max: opt.maxBytes, step: GB, value: plan.size, 'aria-label': 'Space for PolyOS' });
      const labels = h('div.su-split-labels');
      const bar = h('div.su-split-bar', h('span.su-split-other'), h('span.su-split-poly'));
      const total = opt.kind === 'shrink' ? (d.partitions.find((p) => p.path === opt.partition)?.size || opt.maxBytes) : opt.maxBytes;
      const paint = () => {
        plan.size = Number(range.value);
        const pct = Math.max(8, Math.min(92, (plan.size / total) * 100));
        bar.style.setProperty('--poly', `${pct}%`);
        range.style.setProperty('--pct', `${((plan.size - opt.minBytes) * 100) / Math.max(1, opt.maxBytes - opt.minBytes)}%`);
        fill(labels,
          h('span', h('b', other), opt.kind === 'shrink' ? ` keeps ${formatBytes(total - plan.size)}` : ' stays as it is'),
          h('span', h('b', 'PolyOS'), ` gets ${formatBytes(plan.size)}`));
      };
      range.addEventListener('input', paint);
      paint();
      body.push(h('div.su-split', bar, labels, range));
      body.push(h('label.su-check', understood, h('span', 'I’ve backed up my important files.')));
      if (opt.kind === 'shrink') body.push(h('p.su-note', icon('info'), `${other} will be shrunk to make room. This can take a while.`));
    }
    if (probe.uefi && probe.secureBoot) body.push(h('p.su-note', icon('lock'), 'Secure Boot is on. PolyOS supports it.'));
    return [...head(title, sub), ...body, nav(install)];
  }

  // ---- "Where do you want to install PolyOS?": every drive's partitions and unallocated space,
  // with Delete and New (applied right away, like Windows Setup); pick one and install there.
  let driveBusy = null;   // "Deleting…" while a change is being made
  let driveError = null;
  let newFormFor = null;  // the unallocated space whose "New" size form is open
  let confirm = null;     // { text, detail, action, label }: the delete / erase question

  function partType(p) {
    if (p.esp) return 'System (EFI)';
    if (p.parttype === MSR_GUID) return 'Microsoft reserved';
    if (p.parttype === WINRE_GUID) return 'Recovery';
    if (p.parttype === BIOS_BOOT_GUID) return 'BIOS boot';
    if (p.fstype === 'swap') return 'Swap';
    const fs = { ntfs: 'NTFS', vfat: 'FAT32', exfat: 'exFAT' }[p.fstype] || p.fstype || 'Unformatted';
    return p.os ? `${p.os} · ${fs}` : fs;
  }

  function driveRows() {
    const drives = probe.disks.filter((d) => !d.isLive);
    return drives.map((d, n) => {
      const items = [
        ...d.partitions.map((p) => ({ kind: 'part', key: p.path, disk: d, n, p, start: p.start ?? 0, bytes: p.size,
          name: `Drive ${n} Partition ${p.number}${p.label || p.os ? `: ${p.label || p.os}` : ''}`, type: partType(p), install: p.install })),
        ...d.free.map((r) => ({ kind: 'space', key: `${d.path}@${r.start}`, disk: d, n, start: r.start, bytes: r.bytes,
          name: `Drive ${n} Unallocated Space`, type: '', install: r.install })),
      ].sort((a, b) => a.start - b.start);
      return { d, n, items };
    });
  }

  function pickedItem(groups) {
    const all = groups.flatMap((g) => g.items);
    const pk = plan.pick;
    if (pk) {
      const found = all.find((it) => it.disk.path === pk.disk && (pk.kind === 'part'
        ? (pk.device ? it.p?.path === pk.device : it.kind === 'part' && it.start >= pk.start && !it.p.esp)
        : it.kind === 'space' && it.start <= pk.start && pk.start < it.start + it.bytes / (it.disk.sector || 512) + 1));
      if (found) return found;
    }
    // nothing chosen yet: the biggest unallocated space PolyOS fits in, preferring internal drives
    const spaces = all.filter((it) => it.kind === 'space' && it.install?.possible)
      .sort((a, b) => (a.disk.removable - b.disk.removable) || (b.bytes - a.bytes));
    return spaces[0] || null;
  }

  async function changeDrive(label, body, hint) {
    driveBusy = label;
    driveError = null;
    newFormFor = null;
    confirm = null;
    go(step);
    try {
      await withAdmin(() => api.post('/api/install/disk', body),
        { title: 'Change your drives', text: 'Enter the password to change partitions.' });
      plan.pick = hint;
    } catch (err) {
      if (!err.cancelled) driveError = err.message;
    }
    driveBusy = null;
    probe = null;
    loadProbe();
    go(step);
  }

  function drivesScreen() {
    const title = 'Where do you want to install PolyOS?';
    const sub = 'Choose a partition or unallocated space. Delete and New change your drives right away.';
    if (driveBusy) {
      return [...head(title, sub), h('div.su-wait', h('img.su-spin', { src: '/img/logo-white.svg', alt: '' }), driveBusy), nav(h('span'))];
    }
    const groups = driveRows();
    const sel = pickedItem(groups);
    if (sel) plan.pick = sel.kind === 'part' ? { kind: 'part', disk: sel.disk.path, device: sel.p.path } : { kind: 'space', disk: sel.disk.path, start: sel.start };
    const select = (it) => { plan.pick = it.kind === 'part' ? { kind: 'part', disk: it.disk.path, device: it.p.path } : { kind: 'space', disk: it.disk.path, start: it.start }; newFormFor = null; driveError = null; go(step); };

    const table = h('div.su-ptable', { role: 'listbox', 'aria-label': 'Drives and partitions' },
      h('div.su-prow.su-phead', { 'aria-hidden': 'true' }, h('span', 'Name'), h('span', 'Total size'), h('span', 'Type')),
      groups.length ? groups.flatMap(({ d, n, items }) => [
        h('div.su-pdrive', icon(d.transport === 'usb' || d.removable ? 'usb' : 'disk'),
          h('b', `Drive ${n}`), h('span', `${d.model} · ${formatBytes(d.size)}${d.oses.length ? ` · ${d.oses.join(', ')}` : ''}`)),
        ...items.map((it) => h('button.su-prow', {
          role: 'option', 'aria-selected': String(it === sel), class: [it === sel ? 'on' : '', it.kind, it.install?.possible ? '' : 'no'].join(' '),
          onclick: () => select(it), ondblclick: () => { select(it); if (it.install?.possible) installHere(it); },
        }, h('span.su-pname', icon(it.kind === 'space' ? 'plus' : 'disk'), it.name), h('span', formatBytes(it.bytes)), h('span', it.type))),
      ]) : h('p.su-note', 'No drive was found. Connect one, then press Refresh.'));

    const canDelete = sel && sel.kind === 'part';
    const canNew = sel && sel.kind === 'space' && !sel.install?.reason?.includes('running from');
    const tools = h('div.su-ptools',
      h('button.su-ptool', { onclick: () => { probe = null; loadProbe(); go(step); } }, icon('refresh'), 'Refresh'),
      h('button.su-ptool', { disabled: !canDelete, onclick: () => askDelete(sel) }, icon('trash'), 'Delete'),
      h('button.su-ptool', { disabled: !canNew, onclick: () => { newFormFor = sel.key; go(step); } }, icon('plus'), 'New'),
      h('button.su-link.su-padv', { onclick: () => { plan.mode = 'custom'; go(step); } }, 'Advanced setup'));

    let form = null;
    if (sel && newFormFor === sel.key) {
      const maxGb = Math.max(1, Math.floor(sel.bytes / GB));
      const size = h('input.su-input.su-psize', { type: 'number', min: 1, max: maxGb, value: maxGb, 'aria-label': 'Size in GB' });
      form = h('div.su-pnew', h('span', 'Size:'), size, h('span', `GB of ${maxGb} GB`),
        h('button.su-next.primary', { onclick: () => {
          const gb = Math.min(maxGb, Math.max(1, Number(size.value) || maxGb));
          changeDrive('Creating the partition…', { action: 'new', disk: sel.disk.path, start: sel.start, size: gb === maxGb ? sel.bytes : gb * GB },
            { kind: 'part', disk: sel.disk.path, start: sel.start });
        } }, 'Apply'),
        h('button.su-link', { onclick: () => { newFormFor = null; go(step); } }, 'Cancel'));
    }

    let status;
    if (driveError) status = h('div.su-error', driveError);
    else if (!sel) status = h('p.su-note', icon('info'), 'Select a partition or unallocated space for PolyOS.');
    else if (!sel.install?.possible) status = h('p.su-warn', icon('info'), sel.install?.reason || 'PolyOS can’t be installed here.');
    else if (sel.kind === 'space') {
      status = h('p.su-note.ok', icon('check'), sel.disk.partitions.length
        ? `PolyOS will use this unallocated space (${formatBytes(sel.bytes)}). Nothing else on the drive changes.${sel.install.newEsp ? ' It also adds a 512 MB EFI system partition.' : ''}`
        : `PolyOS will set up this whole drive (${formatBytes(sel.bytes)}).`);
    } else {
      status = h('p.su-warn', icon('info'), `Everything on this partition will be erased${sel.p.os ? `, including ${sel.p.os}` : ''}.`);
    }

    const overlay = confirm ? h('div.su-confirm', { role: 'alertdialog', 'aria-label': confirm.text },
      h('div.su-confirm-box', h('b', confirm.text), h('p', confirm.detail),
        h('div.su-confirm-btns', h('button.su-link', { onclick: () => { confirm = null; go(step); } }, 'Cancel'),
          h('button.su-next.primary.danger', { onclick: confirm.action }, confirm.label)))) : null;

    const install = next('Next', () => sel && installHere(sel), { primary: true, disabled: !sel?.install?.possible });
    setTimeout(() => table.querySelector('.su-prow.on')?.scrollIntoView({ block: 'nearest' }), 0); // the chosen row stays in sight
    if (probe.uefi && probe.secureBoot) tools.append(h('span.su-psb', icon('lock'), 'Secure Boot is on. PolyOS supports it.'));
    return [...head(title, sub), table, tools, form, status, nav(install), overlay];
  }

  function askDelete(it) {
    const what = it.p.os ? ` This deletes ${it.p.os}.` : '';
    const system = it.p.esp ? ' Other systems on this computer may stop starting.' : '';
    confirm = { text: `Delete ${it.name}?`, label: 'Delete',
      detail: `Everything stored on this partition (${formatBytes(it.bytes)}) will be lost.${what}${system}`,
      action: () => changeDrive('Deleting the partition…', { action: 'delete', disk: it.disk.path, number: it.p.number },
        { kind: 'space', disk: it.disk.path, start: it.start }) };
    go(step);
  }

  function installHere(it) {
    if (it.kind === 'part') {
      confirm = { text: `Erase ${it.name} and install PolyOS there?`, label: 'Erase and install',
        detail: `Everything on it (${formatBytes(it.bytes)}${it.p.os ? `, including ${it.p.os}` : ''}) will be erased. Other partitions stay as they are.`,
        action: () => { confirm = null; startInstall(); } };
      go(step);
      return;
    }
    startInstall();
  }

  // what the drive screen's choice means for the installer
  function pickPayload() {
    const pk = plan.pick;
    const d = probe.disks.find((x) => x.path === pk.disk);
    if (pk.kind === 'part') return { mode: 'custom', disk: pk.disk, wipe: {}, mounts: [{ device: pk.device, mount: '/', format: true }] };
    if (!d || !d.partitions.length) return { mode: 'erase', disk: pk.disk };
    return { mode: 'space', disk: pk.disk, start: pk.start };
  }

  // Custom: every drive and partition, and what each one becomes.
  function customLayout() {
    const wipe = {};
    const mounts = [];
    const names = new Set();
    const storageName = (label) => {
      const base = (label || 'data').toLowerCase().replace(/[^a-z0-9_-]+/g, '-').replace(/^[-_]+|[-_]+$/g, '').slice(0, 24) || 'data';
      let name = base;
      for (let i = 2; names.has(name); i += 1) name = `${base}-${i}`;
      names.add(name);
      return `/mnt/${name}`;
    };
    for (const d of probe.disks) {
      const use = plan.wipe[d.path];
      if (use) wipe[d.path] = use === 'storage' ? storageName(d.model) : use;
    }
    for (const d of probe.disks) {
      if (plan.wipe[d.path]) continue;
      for (const p of d.partitions) {
        const role = plan.roles[p.path];
        if (!role || role === 'keep') continue;
        const [, where, erase] = ROLES[role];
        mounts.push({ device: p.path, mount: where === 'storage' ? storageName(p.label || p.os) : where, format: erase });
      }
    }
    return { wipe, mounts };
  }

  function customProblem({ wipe, mounts }) {
    const targets = [...Object.values(wipe), ...mounts.filter((m) => m.mount !== 'swap').map((m) => m.mount)];
    const roots = targets.filter((t) => t === '/').length;
    if (!roots) return 'Choose a drive or partition for PolyOS itself.';
    if (roots > 1) return 'Only one drive or partition can hold PolyOS.';
    const twice = targets.find((t, i) => targets.indexOf(t) !== i);
    if (twice) return `Two places are set to ${twice}.`;
    if (mounts.filter((m) => m.mount === 'swap').length > 1) return 'Choose at most one swap partition.';
    if (probe.uefi && !Object.values(wipe).includes('/') && !mounts.some((m) => m.mount === '/boot/efi')
        && !probe.disks.some((d) => !wipe[d.path] && d.partitions.some((p) => p.esp))) {
      return 'This computer needs an EFI boot partition. Choose one, or erase a whole drive for PolyOS.';
    }
    return null;
  }

  function customTarget() {
    const disks = probe.disks.filter((d) => !d.isLive && !d.readonly);
    const summary = h('ul.su-summary');
    const err = h('div.su-error', { hidden: true });
    const understood = h('input', { type: 'checkbox' });
    const install = next('Install', () => startInstall(), { primary: true, disabled: true });
    const refresh = () => {
      const layout = customLayout();
      const problem = customProblem(layout);
      err.textContent = problem || '';
      err.hidden = !problem;
      const lines = [];
      for (const d of disks) {
        const use = layout.wipe[d.path];
        if (use) lines.push(h('li.erase', icon('trash'), `Erase ${d.model} (${formatBytes(d.size)}) for ${use === '/' ? 'PolyOS' : use}`));
        for (const p of d.partitions) {
          const m = layout.mounts.find((x) => x.device === p.path);
          const name = `${p.label || p.os || p.path.replace('/dev/', '')} (${formatBytes(p.size)})`;
          if (m) lines.push(h('li', { class: m.format ? 'erase' : 'use' }, icon(m.format ? 'trash' : 'check'),
            `${m.format ? 'Erase' : 'Use'} ${name} as ${m.mount === '/' ? 'PolyOS (/)' : m.mount}`));
          else if (!use && (p.os || p.fstype)) lines.push(h('li.keep', icon('lock'), `Keep ${name}${p.os ? `: ${p.os}` : ''}`));
        }
      }
      const rank = (li) => (li.classList.contains('erase') ? 0 : li.classList.contains('use') ? 1 : 2);
      lines.sort((x, y) => rank(x) - rank(y)); // erasing first, so it can't be missed
      fill(summary, lines.length ? lines : h('li.keep', 'Nothing is chosen yet.'));
      install.disabled = !!problem || !understood.checked;
    };
    understood.addEventListener('change', refresh);
    const cards = disks.map((d) => {
      const whole = h('select.su-input.su-role', { 'aria-label': `Use ${d.model} for` },
        [['', d.partitions.length ? 'Choose per partition' : 'Don’t use'], ['/', 'Erase · install PolyOS here'],
          ['/home', 'Erase · your files (/home)'], ['storage', 'Erase · extra storage']]
          .map(([v, t]) => h('option', { value: v, selected: (plan.wipe[d.path] || '') === v, disabled: v === '/' && !d.canErase }, t)));
      whole.addEventListener('change', () => {
        if (whole.value) plan.wipe[d.path] = whole.value;
        else delete plan.wipe[d.path];
        go(step);
      });
      const parts = plan.wipe[d.path] ? [] : d.partitions.map((p) => {
        const fs = p.fstype || '';
        const allowed = Object.keys(ROLES).filter((r) => r === 'keep'
          || (r === 'root' && p.size >= probe.minBytes && !p.esp)
          || (r === 'home-keep' && LINUX_FS.includes(fs))
          || (r === 'home-format' && !p.esp)
          || (r === 'storage-keep' && READABLE_FS.includes(fs) && !p.esp)
          || (r === 'storage-format' && !p.esp)
          || (r === 'efi' && p.esp)
          || (r === 'swap' && !p.esp && p.size <= 64 * GB));
        const select = h('select.su-input.su-role', { 'aria-label': `Use ${p.path} for` },
          allowed.map((r) => h('option', { value: r, selected: (plan.roles[p.path] || 'keep') === r }, ROLES[r][0])));
        select.addEventListener('change', () => { plan.roles[p.path] = select.value; refresh(); });
        return h('div.su-part',
          h('span.su-part-text', h('b', p.label || p.os || p.path.replace('/dev/', '')),
            h('small', [formatBytes(p.size), fs || 'empty', p.os, p.esp ? 'EFI' : null].filter(Boolean).join(' · '))),
          select);
      });
      return h('div.su-drive',
        h('div.su-drive-head', h('span.su-disk-ico', icon(d.transport === 'usb' || d.removable ? 'download' : 'disk')),
          h('span.su-disk-text', h('b', d.model), h('small', `${formatBytes(d.size)}${d.oses.length ? ` · ${d.oses.join(', ')}` : ''}`)),
          whole),
        ...parts);
    });
    refresh();
    return [
      ...head('Choose drives and partitions', 'Decide what each drive is for. Anything you leave as “Keep” isn’t touched.'),
      h('div.su-drives', cards),
      h('div.su-plan', h('b', 'What will happen'), summary),
      err,
      h('label.su-check', understood, h('span', 'I’ve backed up my files and checked the list above.')),
      nav(install),
    ];
  }

  async function startInstall() {
    plan.user.recoveryKey = plan.user.recoveryKey || recoveryKey();
    const payload = { mode: plan.mode, disk: plan.disk, hostname: plan.hostname, timezone: plan.timezone,
      user: plan.user, appearance: plan.appearance, edition: plan.edition,
      ...(plan.mode === 'alongside' ? { size: plan.size } : {}),
      ...(plan.mode === 'custom' ? customLayout() : {}),
      ...(plan.mode === 'pick' ? pickPayload() : {}) };
    installJob = { state: 'running', progress: 0, message: 'Getting ready for installation…' };
    go(steps.indexOf(installing));
    try {
      installJob = await withAdmin(() => api.post('/api/install/start', { plan: payload }));
    } catch (err) {
      installJob = { state: 'failed', error: err.message };
    }
    go(steps.indexOf(installing));
  }

  function installing() {
    const job = installJob || { state: 'running', progress: 0, message: 'Getting ready for installation…' };
    if (job.state === 'done') {
      const saved = h('input', { type: 'checkbox' });
      const restart = h('button.su-next.primary', { disabled: !!plan.user.recoveryKey,
        onclick: () => api.post('/api/install/restart', {}).catch((err) => { restart.textContent = err.message; }) }, 'Restart now');
      saved.addEventListener('change', () => { restart.disabled = !saved.checked; });
      const removeUsb = h('div.su-remove', { role: 'status' }, icon('usb'),
        h('span', h('b', 'Please remove the USB drive now.'),
          h('small', 'PolyOS has been installed on your computer. Then click Restart now to start using it.')));
      return [
        h('div.su-center',
          h('img.su-done-logo', { src: '/img/logo-white.svg', alt: '' }),
          h('h1', 'PolyOS 7 has been installed.'),
          plan.user.recoveryKey ? [
            h('p.su-sub', 'This is your recovery key. If you ever forget your password, it lets you set a new one from the sign-in screen. Write it down or take a photo of it. You won’t see it again.'),
            h('div.su-key', plan.user.recoveryKey),
            h('label.su-check', saved, h('span', 'I’ve saved my recovery key.')),
          ] : null,
          removeUsb,
          restart),
      ];
    }
    if (job.state === 'failed') {
      return [
        ...head('The installation didn’t finish', 'Nothing was changed if PolyOS stopped before formatting. Your USB drive still works.'),
        h('div.su-error', job.error || 'Something went wrong.'),
        h('p.su-note', icon('info'), 'Details are in /var/log/polyos-installer.log.'),
        h('div.su-nav', h('button.su-back', { onclick: () => { installJob = null; go(steps.indexOf(target)); } }, icon('chevronLeft'), 'Back'),
          h('div.su-nav-right', next('Try again', startInstall, { primary: true }))),
      ];
    }
    const els = { title: h('h1'), msg: h('p.su-sub.su-live'), bar: h('span'), pct: h('small.su-pct') };
    setTimeout(() => { progressEls = els; paintProgress(job); }, 0);
    paintProgress(job, els);
    return [
      h('div.su-center',
        h('img.su-spin.big', { src: '/img/logo-white.svg', alt: '' }),
        els.title, els.msg, h('div.su-progress', els.bar), els.pct,
        h('p.su-note', 'Keep the computer plugged in and don’t remove the USB drive.')),
    ];
  }

  function paintProgress(job, els = progressEls) {
    if (!els) return;
    const pct = Math.round((job.progress || 0) * 100);
    els.title.textContent = pct < 3 ? 'Getting ready for installation…' : 'Installing PolyOS 7…';
    els.msg.textContent = job.message || '';
    els.bar.style.width = `${Math.max(2, pct)}%`;
    els.pct.textContent = `${pct}%`;
  }

  async function tryFirst() {
    root.classList.add('leaving');
    await api.post('/api/setup/done', {}).catch(() => root.classList.remove('leaving'));
  }

  // first sign-in -----------------------------------------------------------------------
  function connect() {
    const net = store.state.system.network;
    let body;
    if (net.kind === 'ethernet' || (net.kind === 'wifi' && net.name)) {
      body = h('div.su-status', icon('check'), h('span', `You’re online: ${networkLabel(net)}.`));
    } else if (net.available && net.wifiDevice) {
      wifi = wifiPanel(store);
      body = h('div.su-wifi', wifi.el);
    } else {
      body = h('div.su-status', icon('wifiOff'), h('span', 'No network adapter was found. The Driver Manager (next) can help.'));
    }
    return [...head('Get connected', 'Connect to the internet for drivers, apps and updates.'), body,
      nav(h('button.su-link', { onclick: () => go(step + 1) }, 'Skip'), next())];
  }

  function drivers() {
    const list = h('div.su-drivers', h('div.su-wait', h('img.su-spin', { src: '/img/logo-white.svg', alt: '' }), 'Checking your hardware…'));
    const status = h('p.su-note', { hidden: true });
    const installBtn = next('Install drivers', null, { primary: true, disabled: true });
    let missing = [];
    api.get('/api/drivers').then((res) => {
      missing = [...new Set(res.devices.flatMap((d) => d.missing))];
      fill(list, ...res.devices.map((d) => h('div.su-driver',
        h('span.su-driver-ico', icon({ graphics: 'monitor', wifi: 'wifi', bluetooth: 'bluetooth', audio: 'volume' }[d.kind] || 'chip')),
        h('span.su-driver-text', h('b', d.title), h('small', d.missing.length ? `Recommended: ${d.missing.join(', ')}` : 'Ready')),
        d.missing.length ? h('span.su-badge', 'Update') : h('span.su-ok', icon('check')))));
      if (!res.devices.length) fill(list, h('div.su-status', icon('check'), h('span', 'Everything is ready. No extra drivers needed.')));
      installBtn.disabled = !missing.length;
      if (!missing.length) installBtn.textContent = 'All set';
    }, (err) => fill(list, h('div.su-error', err.message)));
    installBtn.addEventListener('click', async () => {
      installBtn.disabled = true;
      status.hidden = false;
      status.textContent = 'Starting…';
      try {
        await withAdmin(() => api.post('/api/drivers/install', { packages: missing }),
          { title: 'Install drivers', text: 'Enter your password to install drivers.' });
        const { off } = watchJobs((job) => {
          if (job.kind !== 'drivers') return;
          status.textContent = job.state === 'running' ? `${job.message} ${Math.round(job.progress * 100)}%`
            : job.state === 'done' ? `Drivers installed.${job.restart ? ' Restart when you’re done setting up.' : ''}`
              : job.error;
          if (job.state !== 'running') {
            off();
            installBtn.textContent = job.state === 'done' ? 'Installed' : 'Try again';
            installBtn.disabled = job.state === 'done';
          }
        });
      } catch (err) {
        status.textContent = err.cancelled ? '' : err.message;
        installBtn.disabled = false;
      }
    });
    return [...head('Drivers', 'PolyOS checks your graphics, Wi-Fi and other hardware and installs what works best.'),
      list, status, nav(h('button.su-link', { onclick: () => go(step + 1) }, 'Skip'), installBtn, next())];
  }

  // The edition chosen while installing: offer its apps now that PolyOS is online.
  function editionApps() {
    const chosen = store.state.settings.edition;
    const pack = chosen === 'regular' ? null : chosen;
    const [, name, text] = EDITIONS.find((e) => e[0] === chosen) || EDITIONS[0];
    if (!pack) {
      const more = (id, title, sub, ico) => h('button.su-option', { onclick: () => { extra = id; go(step); } },
        h('span.su-option-text', h('b', title), h('small', sub)), h('span.su-dual', icon(ico)));
      if (extra) {
        const panel = packPanel(extra, { compact: true, external: true });
        return [...head(extra === 'gaming' ? 'Gaming apps' : 'Developer tools', 'Pick what to install. You can add more in Settings anytime.'),
          panel, nav(h('button.su-link', { onclick: () => { extra = null; go(step); } }, 'Back to choices'),
            installAndContinue(panel, extra))];
      }
      return [...head('Add more to PolyOS?', 'Optional: set up gaming or coding now. Both are in Settings later too.'),
        h('div.su-options', more('gaming', 'Gaming', 'Steam, Wine, Heroic and cloud gaming', 'gamepad'),
          more('developer', 'Developer', 'Git, Python libraries, Node.js, VS Code and Docker', 'code')),
        nav(next('Skip'))];
    }
    const online = store.state.system.network.kind && store.state.system.network.kind !== 'none';
    const panel = packPanel(pack, { compact: true, external: true, onDone: () => saveSettings({ editionSetup: true }).catch(() => {}) });
    return [
      ...head(`Your ${name} edition`, text),
      online ? null : h('p.su-note', icon('wifiOff'), 'You’re offline. Go back to connect, or set this up later in Settings.'),
      panel,
      h('p.su-note', icon('info'), 'The apps download while you finish setting up, and appear on your desktop when they’re ready.'),
      nav(h('button.su-link', { onclick: () => go(step + 1) }, 'Later'), installAndContinue(panel, pack)),
    ];
  }
  let extra = null;
  let varaProvider = VARA_PROVIDERS[0];
  let packJob = null; // the edition's apps, installing in the background while setup carries on

  // "Install and continue": start installing what's ticked, then go on (nothing ticked just goes on)
  function installAndContinue(panel, pack) {
    const button = next('Install and continue', async () => {
      button.disabled = true;
      button.textContent = 'Starting…';
      const started = await panel.start();
      if (started) {
        packJob = packJob || { kind: 'pack', target: pack, state: 'running', progress: 0, message: 'Starting…' };
        go(step + 1);
      } else {
        button.disabled = false;
        button.textContent = 'Install and continue';
      }
    }, { primary: true });
    return button;
  }

  function vara() {
    const key = h('input.su-input', { type: 'password', placeholder: 'Paste your API key', autocomplete: 'off', 'aria-label': 'API key' });
    const status = h('p.su-note', { hidden: true });
    const save = async () => {
      if (!key.value.trim()) return go(step + 1);
      status.hidden = false;
      status.textContent = 'Checking the key…';
      try {
        await api.post('/api/vara/config', { apiKey: key.value.trim(), endpoint: varaProvider.endpoint, model: varaProvider.model,
          provider: providerFor(varaProvider.endpoint) });
        const res = await api.post('/api/vara/test', {});
        status.textContent = `Vara is ready: “${res.reply}”`;
        setTimeout(() => go(step + 1), 900);
      } catch (err) {
        status.textContent = err.message;
      }
    };
    const label = h('span');
    const hint = h('small');
    const pick = (p) => {
      varaProvider = p;
      label.textContent = `${p.label} API key`;
      hint.textContent = `${p.keyHint} Other providers are in Settings > Vara.`;
      chips.querySelectorAll('button').forEach((b) => b.classList.toggle('on', b.textContent === p.label));
    };
    const chips = h('div.su-chips', VARA_PROVIDERS.map((p) => h('button.su-chip', { onclick: () => pick(p) }, p.label)));
    pick(varaProvider);
    return [
      h('div.su-vara-head', h('img', { src: '/img/vara.png', alt: '' }), h('div', ...head('Meet Vara', 'Vara is the PolyOS agent: it opens apps and changes settings, and builds code, 3D models and robot projects with you.'))),
      chips,
      h('label.su-field.wide', label, key, hint),
      status,
      nav(h('button.su-link', { onclick: () => go(step + 1) }, 'Later'), next('Next', save)),
    ];
  }

  function tour() {
    return [...head('A quick tour', 'A few things to know about PolyOS.'),
      h('div.su-tour', TOUR.map(([t, text]) => h('div.su-tip', h('b', t), h('p', text)))), nav(next())];
  }

  function done() {
    const apps = packJob ? h('div.su-apps', { role: 'status' },
      h('span', packJob.state === 'running' ? packJob.message || 'Installing your apps…'
        : packJob.state === 'done' ? 'Your apps are installed and on your desktop.' : packJob.error || 'Some apps didn’t install. Try again in Settings.'),
      packJob.state === 'running' ? h('div.su-progress', h('span', { style: { width: `${Math.max(3, Math.round((packJob.progress || 0) * 100))}%` } })) : null,
      packJob.state === 'running' ? h('small', 'They keep installing after you start using PolyOS.') : null) : null;
    return [
      h('div.su-center',
        h('img.su-done-logo', { src: '/img/logo-white.svg', alt: '' }),
        h('h1', 'You’re all set.'),
        h('p.su-sub', 'Enjoy PolyOS 7. Everything you chose here is in Settings.'),
        apps,
        h('button.su-next.primary', { onclick: finish }, 'Start using PolyOS')),
    ];
  }

  async function finish() {
    root.classList.add('leaving');
    try {
      await api.post('/api/setup/done', {});
    } catch (err) {
      root.classList.remove('leaving');
      console.warn(err.message);
    }
  }

  // ---- live updates ---------------------------------------------------------------------
  watchJobs((job) => {
    if (job.kind === 'pack' && packJob) {
      packJob = job;
      if (steps[step] === done) go(step);
      return;
    }
    if (job.kind !== 'install') return;
    installJob = job;
    if (steps[step] !== installing) return;
    if (job.state === 'running' && progressEls) paintProgress(job);
    else go(step);
  });
  store.subscribe((_s, changed) => {
    if (changed.has('system')) wifi?.update();
  });

  if (live) loadProbe();
  playIntro().then(() => go(0));
}
