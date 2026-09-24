# PolyOS for Debian

PolyOS started as an operating system built in Scratch by AndrewInput and the PIXAPoLY team
([scratch.mit.edu/users/PolyOS](https://scratch.mit.edu/users/PolyOS/)). This project makes it a
real desktop: a PolyOS session that runs on top of Debian and boots on real hardware.

Debian provides the kernel, drivers, Wi-Fi, audio and apps. PolyOS provides everything you see:
the desktop, dock, Home Menu, launcher, Files, Settings, Ask Vara, the login and lock screen, the
boot splash and the installable live ISO.

## How it fits together

```
LightDM + polyos-greeter                  PolyOS login and lock screen (WebKit)
  └─ polyos-session                      X session: env, HiDPI scale, helpers, supervision
       ├─ openbox                        window manager (PolyOS theme, keybindings)
       ├─ picom                          compositor: blur, shadows, rounded corners (optional)
       ├─ xcape, polkit agent
       └─ polyos-shell                   restarted automatically if it crashes
            ├─ GTK windows + WebKit      desktop · dock · popups · Settings · Files · setup  →  ui/
            ├─ libwnck                   tracks app windows for the dock
            ├─ Gio                       apps from .desktop files, launching, XDG autostart
            └─ 127.0.0.1 API + events    token-protected bridge between the UI and the system
                 ├─ system.py            NetworkManager, PipeWire, brightnessctl, logind
                 ├─ files.py             Files app: filesystem and freedesktop Trash
                 └─ vara.py              Ask Vara: local actions + OpenAI-compatible models
polyos-ctl                               CLI used by keybindings and scripts
```

The UI is plain HTML/CSS/JS with no build step. On Debian it runs inside WebKitGTK. With
`python main.py dev` it runs in any browser against a simulated system, so design work doesn't
need a Linux machine.

## Commands

Everything goes through `main.py`, which uses only the Python standard library.

| Command | Where | What it does |
|---|---|---|
| `python main.py dev` | any OS | UI at http://127.0.0.1:8790 with fake apps, windows, Wi-Fi and battery (`--live` shows the installer card) |
| `python main.py test` | any OS | unit tests (parsers, settings, popup logic, HTTP security, .deb format) |
| `python main.py check` | any OS | syntax checks for Python/JS/XML/SVG, LF line endings |
| `python main.py deb` | any OS | builds `dist/polyos-shell_*.deb` and `dist/polyos-desktop_*.deb` |
| `sudo python3 main.py install` | Debian | builds and installs the packages, hands networking to NetworkManager, makes PolyOS your default session |
| `sudo python3 main.py uninstall` | Debian | removes the packages |
| `sudo python3 main.py iso` | Debian | builds `dist/polyos-<version>-trixie-amd64.iso`: a live USB with the Calamares installer |
| `python3 main.py nested` | Debian desktop | runs the real session in a Xephyr window for development |
| `python main.py branding` | any OS | re-renders the boot splash and installer images (needs Pillow) |

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
| **Dock** | Pinwheel (Home Menu), pinned and running apps, status, clock, launcher grid |
| **Home Menu** | PolyOS 7 layout: date and calendar cards, Ask Vara, Run CMD, brightness and volume sliders, pinned and recent apps, power, launcher |
| **Launcher** | Full-screen paged app grid with search and Pin Apps |
| **Files** | File manager for the real disk: places, breadcrumbs, grid/list views, thumbnails, search, copy/cut/paste, rename, Trash with restore, properties |
| **Settings** | Appearance, Wi-Fi, Sound, Display, Power, Vara, About |
| **Ask Vara** | Assistant: runs simple requests on the PC ("open firefox", "volume 40", "turn wifi off") and answers the rest with a local (Ollama) or cloud AI model |
| **Login and lock screen** | PolyOS LightDM greeter; falls back to the stock greeter if it can't start |
| **First-run setup** | "It's time to get started": look, Wi-Fi, a tour; runs once on first sign-in |
| **Boot splash and installer** | Spinning pinwheel (Plymouth) and PolyOS-branded Calamares |

## Build the live USB / installer ISO

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

The ISO boots into a live PolyOS session as user `polyos` (no password). The **Install PolyOS**
card on the desktop starts the Calamares installer. Firmware for common Wi-Fi chips (Intel,
Realtek, Atheros, Broadcom, Marvell for Surface devices) is included.

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
| Tap `Super` · `Super+Space` | Home Menu (type to search) |
| `Super+S` | App launcher (all apps) |
| `Super+R` | Run CMD |
| `Super+V` | Ask Vara |
| `Super+A` | Quick settings |
| Power key | Power Options |
| `Super+I` | Settings |
| `Super+E` / `Super+T` / `Super+B` | Files / Terminal / Browser |
| `Super+L` | Lock |
| `Super+D` | Show desktop |
| `Super+←` `Super+→` `Super+↑` `Super+↓` | Snap left/right, maximize, restore/minimize |
| `Alt+Tab` · `Alt+F4` | Switch · close windows |
| Volume, brightness and power keys | Work, even if the shell is down |

## Where things live

| Path | Contents |
|---|---|
| `polyos/` | Python: `shell.py` (GTK/WebKit/wnck), `server.py` (API), `system.py` (hardware), `session.py`, `ctl.py`, `mock.py` (dev) |
| `ui/` | The interface: `js/surfaces/` (desktop, panel, popup, settings), `js/views/` (Home Menu, launcher, Run CMD, Power Options, quick settings, calendar, task menu), `css/polyos.css` |
| `data/` | Openbox config and theme, picom, GTK defaults, LightDM greeter, session file, wallpapers, entry-point scripts |
| `iso/config/` | live-build additions: package list, GRUB branding |
| `~/.config/polyos/settings.json` | Per-user settings (the Settings app writes this) |
| `~/.config/polyos/openbox/rc.xml`, `~/.config/polyos/picom.conf` | Optional per-user overrides |
| `~/.local/state/polyos/*.log` | Session, shell and helper logs |

`polyos-ctl status` prints the live shell state. `polyos-ctl restart` restarts the shell without
closing apps.

## Current limits

- X11 only; Wayland would mean replacing Openbox and libwnck. The taskbar and popups use the
  primary monitor; other monitors show the wallpaper color.
- Nothing that runs on Linux (shell, greeter, Plymouth theme, ISO build) has been run on real
  Debian yet; the web UI and the Python backend are tested on Windows with the mock system.
- The login screen can't read each user's wallpaper (users' home folders are private), so it
  shows the PolyOS default.
- The look follows PolyOS 7: the logo is the original vector, and the palette was measured from
  the Scratch costumes (`:root` in `ui/css/polyos.css`). Third-party photos from PolyOS 7's
  wallpaper set are not shipped; see `CREDITS.md`.

## Credits and license

Based on PolyOS by AndrewInput and PIXAPoLY Software, used with their blessing. Code: GNU GPL v3
or later. The logo, palette and PIXAPoLY wallpaper come from the PolyOS 7 Scratch project
(CC BY-SA 2.0). Poppins is under the SIL OFL. Details are in [CREDITS.md](CREDITS.md).
