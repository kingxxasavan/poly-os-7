# Credits

## PolyOS

PolyOS was created in Scratch by **AndrewInput** and the **PIXAPoLY Software** team
([scratch.mit.edu/users/PolyOS](https://scratch.mit.edu/users/PolyOS/)). PolyOS for Debian follows
PolyOS 7 (project 1192877121) with the team's permission. Scratch projects are shared under
[CC BY-SA 2.0](https://creativecommons.org/licenses/by-sa/2.0/); material taken from them stays
under that license:

| File | Source |
|---|---|
| `ui/img/vara.png` | The Vara assistant mark (PolyOS 7 "VaraLogo" costume) |
| `ui/img/logo.svg`, `ui/img/logo-white.svg` | PolyOS pinwheel logo, the vector from the PolyOS 7 dock ("PolyOS Home Menu Button" costume) |
| `ui/img/seven.svg` | The striped "7" from the PolyOS 7 setup screens ("Setup" costumes) |
| Setup layout and text (`ui/js/surfaces/setup.js`) | Follows the PolyOS 7 setup: "It's time to get started", Terms and conditions, password, Appearance |
| The name "PolyMarket" | The PolyOS 7 app store |
| `ui/css/polyos.css` palette (`:root` tokens), `data/themes/PolyOS/openbox-3/themerc` colors | Measured from the PolyOS 7 UI costumes: dock, home menu, search, Settings, setup |
| `data/wallpapers/pixapoly.jpg` | Recreation of the "PIXAPoLY Software" wallpaper (PolyOS branding) |
| `data/plymouth/polyos/logo.png`, `data/calamares/branding/polyos/*.png` | Rendered from the PolyOS logo by `main.py branding` |
| `data/wallpapers/polyos-dusk.jpg`, `polyos-violet.jpg`, `polyos-night.jpg` | Original renders using the color palettes of PolyOS 7's default wallpapers |
| `data/wallpapers/polyos-crystal.jpg` | Original low-poly render (`main.py branding`) standing in for PolyOS 7's crystal setup backdrop |

This edition is presented by **Cryptic Software**.

Several PolyOS 7 wallpapers are third-party photographs (stock and wallpaper-site images), which
the Scratch license can't cover. Two of them were added at the project owner's request, as the
defaults PolyOS 7 uses:

| File | Source |
|---|---|
| `data/wallpapers/polyos-prism.jpg` ("Crystal", the default desktop) | PolyOS 7's blue crystal wallpaper, supplied by the project owner |
| `data/wallpapers/polyos-amethyst.jpg` ("Amethyst", the login and lock screen) | PolyOS 7's amethyst crystal wallpaper, supplied by the project owner |

**Before distributing PolyOS images or packages publicly**, confirm where these two photos come from
and that their license allows redistribution (many stock sites forbid sharing images as-is in
wallpaper packs). If it doesn't, delete the two files: PolyOS falls back to its own wallpapers.

## Other assets

- **Poppins** font (`ui/fonts/*.ttf`): The Poppins Project Authors, SIL Open Font License 1.1 (`ui/fonts/OFL.txt`).
- App icons in PolyMarket come from the installed icon theme (Papirus) or the apps themselves.
- `ui/img/apps/*.svg`: app icons from the [Papirus icon theme](https://github.com/PapirusDevelopmentTeam/papirus-icon-theme)
  by the Papirus Development Team, GNU GPL v3; used when the installed theme has no icon for an app
  and in the dev preview.
- Code: GNU GPL v3 or later (`LICENSE`).
