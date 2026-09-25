# PolyOS 7 for Debian: project showcase

This folder is the PolyOS website: a single page that shows everything built so far, with
real screenshots. Open `index.html` in a browser to see it, or publish it with GitHub Pages
(below) to get a link like `https://kingxxasavan.github.io/poly-os-7/`.

![The PolyOS 7 desktop](screenshots/desktop.jpg)

PolyOS started as an operating system built in Scratch by **AndrewInput** and the
**PIXAPoLY Software** team. This project, presented by **Cryptic Software**, turns PolyOS 7
into a real desktop that installs and boots on a PC, on top of Debian.

## What's been built

| | |
|---|---|
| **Login and lock screen** | The PolyOS 7 design: stacked clock, date, *Performance: Optimal*, news and notification tiles over the blurred amethyst crystal; "Enter your password", Forgot Password (recovery key) and Next |
| **Desktop and dock** | Crystal wallpaper, app shortcuts, the capsule dock, a right-click menu; the taskbar can float, stretch edge to edge, align left or hide |
| **Home Menu and launcher** | Calendar, Ask Vara, Run CMD, sliders, pinned and recent apps; a full-screen app grid with search |
| **Widgets** | Weather, calendar, system, news, to-do, notes, photos, world clocks, media |
| **Apps** | Files, Task Manager, Driver Manager, PolyMarket (43 apps from Debian and Flathub), Camera, Ask Vara |
| **Settings** | Appearance, Taskbar & Desktop, Wi-Fi, Sound, Display, Power & Performance, Account, Privacy & Security, Gaming, Developer, Vara, About |
| **Installer** | The PolyOS 7 setup: whole disk, dual boot next to Windows, or Custom (choose every drive and partition) |
| **Editions** | Regular, Developer (change PolyOS's own interface) and Gaming (Steam, Wine, Heroic, Lutris, cloud gaming, Game Mode) |
| **Security and speed** | Firewall and security updates on by default, a security checkup, lock screen guessing protection; zram, SSD trim, faster startup |

## Download

The website's **Download** button always offers the newest
[release](https://github.com/kingxxasavan/poly-os-7/releases/latest): it asks GitHub for the
latest release when the page loads, so publishing a release (push a tag like `v0.6.0`, see the
main README) updates the site with no changes here.

## Screenshots

| Login | Sign in | Lock screen |
|---|---|---|
| ![](screenshots/thumbs/login.jpg) | ![](screenshots/thumbs/login-password.jpg) | ![](screenshots/thumbs/lock.jpg) |

| Home Menu | Launcher | Widgets |
|---|---|---|
| ![](screenshots/thumbs/home-menu.jpg) | ![](screenshots/thumbs/launcher.jpg) | ![](screenshots/thumbs/widgets.jpg) |

| Files | Task Manager | PolyMarket |
|---|---|---|
| ![](screenshots/thumbs/files.jpg) | ![](screenshots/thumbs/task-manager.jpg) | ![](screenshots/thumbs/polymarket.jpg) |

| Taskbar settings | Power & Performance | Privacy & Security |
|---|---|---|
| ![](screenshots/thumbs/settings-taskbar.jpg) | ![](screenshots/thumbs/settings-power.jpg) | ![](screenshots/thumbs/settings-privacy.jpg) |

| Gaming | Developer | Driver Manager |
|---|---|---|
| ![](screenshots/thumbs/settings-gaming.jpg) | ![](screenshots/thumbs/settings-developer.jpg) | ![](screenshots/thumbs/driver-manager.jpg) |

| Installer: start | Installer: editions | Installer: custom drives |
|---|---|---|
| ![](screenshots/thumbs/installer-start.jpg) | ![](screenshots/thumbs/installer-edition.jpg) | ![](screenshots/thumbs/installer-custom.jpg) |

All screenshots are full size in [`screenshots/`](screenshots/) (1440×900) with small copies in
[`screenshots/thumbs/`](screenshots/thumbs/).

## Timeline

| Date | What changed |
|---|---|
| Sep 24, 2026 | PolyOS 7 comes to Debian: desktop shell, dock, Home Menu, launcher, Files, Settings, Ask Vara, login screen, boot splash, live USB |
| Sep 24, 2026 | The PolyOS 7 installer, Task Manager, Driver Manager, PolyMarket, dark and light mode |
| Sep 24, 2026 | Windows key opens and closes the Home Menu; the live USB keeps its install card |
| Sep 24, 2026 | Instant lock screen, password recovery keys, widgets board |
| Sep 25, 2026 | PolyOS 7 login and lock screens, crystal wallpapers, Camera, desktop shortcuts, new Settings pages |
| Sep 25, 2026 | Custom installs, Regular / Developer / Gaming editions, security and speed defaults |

## Put the website online

### Vercel (set up)

`vercel.json` in the project root tells Vercel to serve this folder as it is (no build step).

1. Sign in at [vercel.com](https://vercel.com) with your GitHub account.
2. **Add New… → Project**, then **Import** `kingxxasavan/poly-os-7`.
3. Leave the settings as they are (Framework Preset: *Other*; `vercel.json` fills in the rest)
   and click **Deploy**.
4. You get an address like `https://poly-os-7.vercel.app`. Every push to `main` updates the site,
   and other branches get their own preview links. Add your own domain under **Settings → Domains**.

From a terminal instead: `npm i -g vercel`, then `vercel --prod` in the project folder.

### GitHub Pages (another option)

1. Merge this branch into `main` (or keep it on its branch, both work).
2. On GitHub, open the repository's **Settings → Pages**.
3. Under **Build and deployment**, choose **Source: Deploy from a branch**, then the branch
   (`main`) and the folder **`/docs`**, and click **Save**.
4. After a minute or two the page shows your site's address, usually
   `https://kingxxasavan.github.io/poly-os-7/`.

GitHub Pages is free for public repositories. For a private repository it needs a paid GitHub plan.

## Editing the site

It's plain HTML, CSS and JavaScript with no build step:

| File | What it holds |
|---|---|
| `index.html` | All the text and sections: hero, features, gallery, editions, installer, security, how it's built, install steps, timeline, credits |
| `assets/site.css` | The look (the same colors as PolyOS) |
| `assets/site.js` | Gallery filters and the full-size screenshot viewer |
| `screenshots/` | Screenshots; add one to the gallery by copying a `<figure>` in `index.html` |

To take new screenshots, run `python main.py dev` from the project folder and open
http://127.0.0.1:8790 in a browser (`--live` shows the installer).

## Credits

PolyOS was created in Scratch by AndrewInput and PIXAPoLY Software
([scratch.mit.edu/users/PolyOS](https://scratch.mit.edu/users/PolyOS/)); this edition is
presented by Cryptic Software. The PolyOS logo, colors and PIXAPoLY artwork are CC BY-SA 2.0.
The Crystal and Amethyst wallpapers visible in the screenshots are third-party photos (see
`CREDITS.md` in the project root). Poppins font: SIL Open Font License (`assets/fonts/OFL.txt`).
