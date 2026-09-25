# PolyOS for Debian

PolyOS started as an operating system built in Scratch by AndrewInput and the PIXAPoLY team
([scratch.mit.edu/users/PolyOS](https://scratch.mit.edu/users/PolyOS/)). This project makes it a
real desktop: a PolyOS session that runs on top of Debian and boots on real hardware.

Debian provides the kernel, drivers, Wi-Fi, audio and apps. PolyOS provides everything you see:
the desktop, dock, Home Menu, launcher, Files, Settings, Task Manager, Driver Manager, the
PolyMarket app store, Ask Vara, the login and lock screen, the boot splash and the PolyOS 7
installer on the live USB. This edition is presented by Cryptic Software.

**See it:** [`docs/`](docs/) is the project website, with screenshots of everything so far
(open `docs/index.html`, or publish it with GitHub Pages as described in [`docs/README.md`](docs/README.md)).

## How it fits together

```
LightDM + polyos-greeter                  PolyOS login and lock screen (WebKit)
  └─ polyos-session                      X session: env, HiDPI scale, dark/light theme, supervision
       ├─ openbox                        window manager (PolyOS theme, keybindings)
       ├─ picom                          compositor: blur, shadows, rounded corners (optional)
       ├─ xcape, polkit agent
       └─ polyos-shell                   restarted automatically if it crashes
            ├─ GTK windows + WebKit      desktop · dock · popups · Settings · Files · Task Manager ·
            │                            Driver Manager · PolyMarket · setup/installer  →  ui/
            ├─ libwnck                   tracks app windows for the dock
            ├─ Gio                       apps from .desktop files, launching, XDG autostart
            └─ 127.0.0.1 API + events    token-protected bridge between the UI and the system
                 ├─ system.py            NetworkManager, PipeWire, brightnessctl, logind
                 ├─ files.py             Files app: filesystem and freedesktop Trash
                 ├─ procs.py             Task Manager: processes and performance from /proc
                 ├─ drivers.py, store.py Driver Manager and PolyMarket catalogs
                 └─ vara.py              Ask Vara: local actions + OpenAI-compatible models
polyos-ctl                               CLI used by keybindings and scripts
polyos-admin (root, via sudo)            installer engine (installer.py), apt and Flathub installs
```

The UI is plain HTML/CSS/JS with no build step. On Debian it runs inside WebKitGTK. With
`python main.py dev` it runs in any browser against a simulated system, so design work doesn't
need a Linux machine.

## Commands

Everything goes through `main.py`, which uses only the Python standard library.

| Command | Where | What it does |
|---|---|---|
| `python main.py dev` | any OS | UI at http://127.0.0.1:8790 with fake apps, windows, Wi-Fi and battery (`--live` runs the installer on fake disks) |
| `python main.py test` | any OS | unit tests (parsers, settings, popup logic, HTTP security, .deb format) |
| `python main.py check` | any OS | syntax checks for Python/JS/XML/SVG, LF line endings |
| `python main.py deb` | any OS | builds `dist/polyos-shell_*.deb` and `dist/polyos-desktop_*.deb` |
| `sudo python3 main.py install` | Debian | builds and installs the packages, hands networking to NetworkManager, makes PolyOS your default session |
| `sudo python3 main.py uninstall` | Debian | removes the packages |
| `sudo python3 main.py iso` | Debian | builds `dist/polyos-<version>-trixie-amd64.iso`: a live USB with the Calamares installer |
| `python3 main.py nested` | Debian desktop | runs the real session in a Xephyr window for development |
| `python main.py branding` | any OS | re-renders the crystal backdrop, boot splash and installer images (needs Pillow) |

## Install on a PC or VM

1. Install **Debian 13 (trixie)** from the netinst ISO. At *Software selection*, uncheck every
   desktop and keep only **standard system utilities** (and SSH server if you want it).
   Debian 12 (bookworm) also works.
2. Sign in and get the project onto the machine:
   ```bash
   sudo apt install git python3
   git clone <your-repo-url> PolyOS && cd PolyOS
   ```
   Or copy the folder over with a USB stick or `scp`.
3. Install:
   ```bash
   sudo python3 main.py install
   ```
   This pulls in Xorg, LightDM, Openbox, picom, PipeWire, NetworkManager, fonts, icons, Firefox
   ESR, a terminal and a text editor, around 1 GB in total.
4. Reboot. The PolyOS login screen comes up; sign in.

Already have GNOME, Xfce or another desktop? Run `sudo python3 main.py install --shell-only`,
then pick **PolyOS** from the session menu on your current login screen.

**Networking note:** when Debian is installed without a desktop, it configures the network in
`/etc/network/interfaces`, and NetworkManager ignores those interfaces. `install` moves them to
NetworkManager (the old file is kept as `interfaces.polyos-backup`). If you were on Wi-Fi, enter
the password again from the PolyOS Wi-Fi menu after the reboot. Pass `--keep-ifupdown` to skip
this step.

## What's in the desktop

| Piece | What it does |
|---|---|
| **Installer** | The PolyOS 7 setup on the live USB: "Cryptic Software presents", the falling pinwheel and 7, the crystal welcome, then *Install PolyOS 7* (whole disk), *Dual boot* (next to Windows or Linux, shrinking it if needed) or *Custom*, terms, edition, account, dark/light appearance, disk choice, progress, restart. Calamares stays as the *Advanced installer* |
| **Custom install** | Choose what every drive and partition is for: erase a drive for PolyOS, your files (/home) or extra storage; or use existing partitions for PolyOS (/), /home (keeping its files), the EFI boot partition, swap, or storage at /mnt/NAME (NTFS drives too). Anything left on *Keep* isn't touched, and a summary lists every erase before you confirm. Impossible choices are refused before anything is erased |
| **Editions** | *Regular*, *Developer* or *Gaming*, picked while installing; the edition's apps are offered at first sign-in and can be added any time in Settings |
| **Gaming** | Steam, Bottles (Wine for Windows games), Heroic, Lutris, ProtonUp-Qt, GameMode, Discord; cloud gaming shortcuts (GeForce NOW, Xbox Cloud Gaming, Amazon Luna, Boosteroid) that open in Chrome/Chromium when installed; `vm.max_map_count` raised like SteamOS; **Game Mode**: while a game is full screen, the performance power mode, no idle lock or sleep, slower status polling, background helpers at low priority, and the compositor steps aside |
| **Developer** | Developer mode: files in `~/.config/polyos/ui/` replace PolyOS's built-in interface files (`css/user.css` is added to every screen), `~/PolyOS-UI` holds a copy of the originals, right-click *Inspect Element* on PolyOS screens, *Reload the interface*; Git, build tools, Python, Node.js, VS Code. `polyos-ctl dev off` (Ctrl+Alt+T) undoes a broken change |
| **Security** | Firewall (ufw) on by default, automatic security updates, a security checkup (firewall, updates, lock screen, recovery key, AppArmor, Secure Boot), lock screen slows down password guessing (a wait after 5 wrong tries, doubling each time) |
| **Speed** | Compressed RAM swap (zram), SSD trim, capped system log, no waiting for the network at startup, full-screen apps bypass the compositor, one shared event connection for all PolyOS screens |
| **First sign-in** | Welcome back, Wi-Fi, drivers, Vara API key, a quick tour |
| **Dock** | Pinwheel (Home Menu), pinned and running apps, status, clock, launcher grid; right-click an app for Close, Force close and Task Manager |
| **Home Menu** | PolyOS 7 layout: date and calendar cards, Ask Vara, Run CMD, brightness and volume sliders, pinned and recent apps, power, launcher |
| **Launcher** | Full-screen paged app grid with search and Pin Apps; technical tools are hidden (Settings > Appearance > Show all apps) |
| **Desktop** | The PolyOS 7 crystal wallpaper with app shortcuts: double-click to open (or single click, in Settings), right-click to pin or remove. Add apps by right-clicking the desktop (*Add apps to the desktop*) or any app in the launcher (*Add to desktop*) |
| **Desktop menu** | Right-click (or two-finger tap): Add apps to the desktop, Taskbar settings, Personalize, Display settings, Task Manager, Terminal, Files, PolyMarket |
| **Files** | File manager for the real disk: places, breadcrumbs, grid/list views, thumbnails, search, copy/cut/paste, rename, Trash with restore, properties |
| **Task Manager** | Apps and processes with CPU and memory, End task and Force close, live CPU/memory/disk/network graphs |
| **Driver Manager** | Finds NVIDIA, AMD and Intel graphics, Wi-Fi (including Broadcom), Bluetooth and sound hardware and installs the right drivers and firmware from Debian |
| **PolyMarket** | Curated store: Chrome, Discord, Spotify, Steam, VS Code, LibreOffice, GIMP, OBS and more from Debian and Flathub |
| **Settings** | Appearance (dark/light, accent, desktop and lock screen wallpapers), Gaming, Developer (with developer mode on), Taskbar & Desktop (floating or edge-to-edge taskbar, center/left, auto-hide, widgets button, date, pinned apps, desktop shortcuts), Wi-Fi, Sound, Display, Power & Performance (Power saver / Balanced / Performance / Maximum, screen-off and sleep timers), Account (password, recovery key, sign-in options), Privacy & Security (lock on sleep, lock screen news, camera and microphone access, activity history), Vara, About |
| **Camera** | Photos and videos from the webcam (self-timer, mirror, switch camera), saved to Pictures › Camera. Only listed on computers with a camera |
| **Ask Vara** | Assistant: runs simple requests on the PC ("open firefox", "volume 40", "turn wifi off") and answers the rest with an AI model; uses your Ollama Cloud (or other) API key |
| **Login screen** | PolyOS 7 design over the blurred amethyst crystal: big stacked clock, date, *Performance: Optimal*, news and notification tiles, *Click to Enter Password*, then your name, "Enter your password", *Forgot Password* and *Next*. Falls back to the stock greeter if it can't start |
| **Lock screen** | Same design; appears instantly (Win+L, the power menu, before sleep, when the screen turns off); unlocks with your password |
| **Forgot password** | The installer shows a recovery key once; with it you set a new password from the login or lock screen. Settings > Account makes a new key or changes your password |
| **Widgets** | Win+W or the weather button in the dock: weather (Open-Meteo), calendar, system, BBC news, to-do, notes, photos, world clocks, media controls |
| **Boot splash** | Spinning pinwheel (Plymouth) |

## Build the live USB / installer ISO

**Just want the ISO?** Download the newest release from the website's Download button or from
[GitHub Releases](https://github.com/kingxxasavan/poly-os-7/releases/latest).

**Publishing a new release:** bump `__version__` in `polyos/__init__.py` and push it to `main`.
Then on GitHub open **Actions → Build PolyOS ISO → Run workflow**, tick **Publish as a GitHub
Release**, and run it (or push a tag like `v0.6.0`). About an hour later the ISO is published with
a `SHA256SUMS` file as release `v<version>` (split into parts if it's ever over GitHub's 2 GB file
limit), and the website's Download button offers it automatically.

An ISO has to be built on Linux. Three ways:

**1. GitHub Actions (no Linux needed).** Push this folder to a GitHub repository, open
**Actions → Build PolyOS ISO → Run workflow**, and download the ISO from the finished run
(about 30–60 minutes). A public repository keeps the artifact storage free; private repositories
on the free plan only get 500 MB of artifact storage, less than one ISO.

**2. WSL on Windows.** Install Debian once (`wsl --install -d Debian` in an admin terminal, then
reboot if asked), then inside Debian:

```bash
sudo apt update && sudo apt install -y live-build python3
cd /mnt/c/Users/<you>/PolyOS
sudo python3 main.py iso
```

The build runs in `~/polyos-iso` inside WSL (a Linux chroot can't live on a Windows drive) and the
finished ISO lands in `dist\` on the Windows side.

**3. Any Debian 12/13 machine or VM** with about 20 GB free:

```bash
sudo apt install live-build
sudo python3 main.py iso            # --dist bookworm for Debian 12
```

The ISO boots into a live PolyOS session as user `polyos` (no password) and opens the PolyOS 7
installer. *Try PolyOS first* goes to the desktop; the **Install PolyOS 7** card brings the
installer back. Installing needs no internet: the GRUB packages for UEFI and legacy BIOS are on
the USB drive. Firmware for common Wi-Fi chips (Intel, Realtek, Atheros, Broadcom, Marvell for
Surface devices) is included.

**Dual boot with Windows:** turn off BitLocker and Fast Startup in Windows first (Control Panel >
Power Options > Choose what the power buttons do), and back up your files. The installer shrinks
Windows' partition for you, or uses free space you made in Windows' Disk Management. The boot menu
then offers PolyOS and Windows.

## Test the ISO

**VirtualBox.** New VM → type *Linux*, version *Debian (64-bit)*; 4 GB RAM, 2 CPUs, 25 GB disk.
Under *Display*, choose **VMSVGA** with 128 MB video memory (leave 3D off; PolyOS falls back to
software effects). Attach the ISO as the optical drive and start. Try the live session, then
**Install PolyOS**, reboot and sign in on the PolyOS login screen. The first sign-in runs setup.

**An old laptop.** Write the ISO to a USB stick with [Rufus](https://rufus.ie) (choose *DD image*
mode when asked) or [balenaEtcher](https://etcher.balena.io). Boot the laptop from USB (usually
F12, F9, F2 or Esc at power-on). If it won't boot the stick, turn off Secure Boot in the firmware
settings. The live session changes nothing on the disk until you run the installer.

## Keyboard

| Keys | Action |
|---|---|
| Tap `Super` (Windows key) · `Super+Space` | Open or close the Home Menu (type to search) |
| `Super+S` | App launcher (all apps) |
| `Super+R` | Run CMD |
| `Super+X` | Quick menu: Task Manager, Settings, Files, Driver Manager, PolyMarket, power |
| `Super+W` | Widgets |
| `Ctrl+Shift+Esc` · `Ctrl+Alt+Delete` | Task Manager |
| `Super+V` | Ask Vara |
| `Super+A` | Quick settings |
| Power key | Power Options |
| `Super+I` | Settings |
| `Super+E` / `Super+T` / `Super+B` | Files / Terminal / Browser |
| `Super+L` | Lock |
| `Ctrl+Alt+T` | Terminal (works even if the PolyOS interface is broken: `polyos-ctl dev off`) |
| `Super+D` | Show desktop |
| `Super+←` `Super+→` `Super+↑` `Super+↓` | Snap left/right, maximize, restore/minimize |
| `Alt+Tab` · `Alt+F4` | Switch · close windows |
| Volume, brightness and power keys | Work, even if the shell is down |

Touchpads: tap to click, two-finger tap to right-click, natural scrolling (like Windows).

## Where things live

| Path | Contents |
|---|---|
| `polyos/` | Python: `shell.py` (GTK/WebKit/wnck), `server.py` (API), `system.py` (hardware), `session.py`, `ctl.py`, `installer.py` + `admin.py` (root helper), `privileged.py` (sudo, jobs), `procs.py`, `drivers.py`, `store.py`, `mock.py` (dev) |
| `data/store/catalog.json` | PolyMarket's app list (also the list of what may be installed) |
| `/var/log/polyos-installer.log` | Installer log (copied to the installed system) |
| `ui/` | The interface: `js/surfaces/` (desktop, panel, popup, settings), `js/views/` (Home Menu, launcher, Run CMD, Power Options, quick settings, calendar, task menu), `css/polyos.css` |
| `data/` | Openbox config and theme, picom, GTK defaults, LightDM greeter, session file, wallpapers, entry-point scripts |
| `iso/config/` | live-build additions: package list, GRUB branding |
| `~/.config/polyos/settings.json` | Per-user settings (the Settings app writes this) |
| `~/.config/polyos/openbox/rc.xml`, `~/.config/polyos/picom.conf` | Optional per-user overrides |
| `~/.local/state/polyos/*.log` | Session, shell and helper logs |

`polyos-ctl status` prints the live shell state. `polyos-ctl restart` restarts the shell without
closing apps.

## Current limits

- Custom installs use existing partitions or whole drives; they don't create or resize single
  partitions (Dual boot does that, or use the Advanced installer). Disk encryption isn't offered yet.
- Edition apps come from Debian and Flathub, so the first sign-in needs the internet. Packages a
  Debian release doesn't have are skipped and named in the result.
- Developer-mode overrides replace whole files; after a PolyOS update, compare your copies with
  `~/PolyOS-UI` (Settings > Developer > Copy to my files).
- X11 only; Wayland would mean replacing Openbox and libwnck. The taskbar and popups use the
  primary monitor; the wallpaper stretches across every monitor.
- Full-screen apps (videos, games, F11) cover the taskbar. Maximized windows stop above it
  unless the taskbar is set to hide automatically (Settings > Taskbar & Desktop).
- Power modes use power-profiles-daemon when the computer supports it; otherwise only the
  screen and sleep timers change. Idle timers need libxss1 (installed with PolyOS).
- The Camera app uses WebKitGTK's GStreamer webcam support; recording video needs
  gstreamer1.0-plugins-good (installed with PolyOS).
- The installer, Driver Manager and PolyMarket run their root steps through `polyos-admin`; the
  partition planning is unit-tested and the steps have a dry-run test, but test installs on a
  spare disk or VM before trusting one with important data.
- Apps and drivers installed in the live session disappear at restart (it runs from RAM).
- The login screen can't read each user's settings (users' home folders are private), so it
  shows the default Amethyst background; the lock screen uses the one chosen in Settings.
- The look follows PolyOS 7: the logo is the original vector, and the palette was measured from
  the Scratch costumes (`:root` in `ui/css/polyos.css`). The two crystal photos are third-party
  images; check their license before sharing builds publicly (see `CREDITS.md`).

## Credits and license

Based on PolyOS by AndrewInput and PIXAPoLY Software, used with their blessing. Code: GNU GPL v3
or later. The logo, palette and PIXAPoLY wallpaper come from the PolyOS 7 Scratch project
(CC BY-SA 2.0). Poppins is under the SIL OFL. Details are in [CREDITS.md](CREDITS.md).
