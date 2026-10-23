# Hanami

The suite's launcher and installer, and the one tray icon its apps share.
Hanami (花見) is the custom of gathering under the cherry blossoms; this gathers
Keytap, Dropshift, Grabbit and Homework Hub under one.

## Getting started

Download `Hanami-<version>-win64.zip` from the
[latest release](https://github.com/blossqt/hanami/releases/latest), unzip it
somewhere of your own, and run `Hanami.exe`. Its window lists every suite app:
click **Install** on the ones you want. On its first start Hanami adds itself
to the Start menu.

## Installing and updating

Hanami installs each app from its newest GitHub release into a folder of its
own under `%LOCALAPPDATA%\Programs`, adds it to the Start menu, and starts it.
It doesn't need an administrator.

Every release carries a `latest.json` naming its file, size and SHA-256, signed
with that app's release key. Hanami installs a download only if all of these
hold:

- the signature matches the key Hanami carries for that app (`catalog.py`);
- the file is the size and SHA-256 the signed manifest gives;
- the program in it is the version promised;
- it starts (`--self-test`).

So a broken or tampered download never replaces a copy that works.

Hanami checks for newer releases when it starts, twice a day, and when its
window opens. When an app it installed has an update, the blossom says so and
the app's card shows **Update to …**. Updating quits the app, swaps the new
version in and starts it again. If anything fails part-way, the old version is
put back.

Updating and removing touch only the files a release put in the app's folder.
Anything else kept there stays where it is, and so does each app's own data
and settings. Apps found elsewhere, like a build in `Documents` or a copy you
pointed Hanami to, are started and quit but never changed. Grabbit and Homework
Hub keep updating themselves too.

## The tray

While Hanami runs, the suite's apps don't put icons of their own in the tray.
Each one's menu becomes a submenu of Hanami's cherry blossom, so the tray
holds one icon however many of them are running:

    Keytap        ▸  Locked · Unlock… · Sync now · Pop up in login boxes · …
    Dropshift     ▸  Settings… · How it works · Pause · Quit Dropshift
    Grabbit       ▸  Show Grabbit · Add link… · Exit
    Homework Hub  ▸  Open dashboard · Copy pairing token · …
    Start         ▸  the suite apps that aren't running
    Open Hanami
    Quit Hanami

Their notifications come from the blossom too. Quit Hanami (or don't start it)
and each app shows its own icon again; start Hanami later and they fold back in.

Keytap and Dropshift can also leave the tray altogether: untick **Show … in
the tray** in their settings. Opening the app again - from Start, or Hanami's
**Open** - brings up its settings, which then have Lock/Sync/Pause/Quit.

## The window

Click the blossom (or open Hanami from Start) for every suite app on one page:

- whether it's installed and running;
- **Install**, **Start** / **Open**, **Update to …**, and **Quit** for those in
  the blossom;
- under **⋯**: its release notes, **Find it on this PC…** for a copy Hanami
  doesn't know about, and **Uninstall** for one Hanami installed.

**Start Hanami when I sign in to Windows, and with it:** one sign-in entry for
the whole suite - Hanami starts, then starts the apps ticked there.

## Colours

The suite is blossom pink. Every app's icon is a `#ffd1dc` tile with a deep
rose `#c2255c` mark, and every window uses the same pink for its buttons,
ticks and highlights, never Windows' accent colour, which here follows the
wallpaper.

## How the apps talk to it

Hanami listens on a named pipe, `\\.\pipe\hanami-tray-<user>`, open to this
Windows user only. Each app connects with `suitelink.py`, sending one JSON
object per line:

- its name and icon;
- its menu, as data;
- notifications.

Hanami sends back which menu item was clicked. The Qt apps use `suitetray.py`
on top, which also keeps their own tray icon for when Hanami isn't there.

These files, and the release kit, are written here and copied into each app.
`tests/check_copies.py` says whether the copies match, and `--sync` copies them
over.

| App | Its copies |
|-----|------------|
| Keytap | `app/keytap/suitelink.py`, `suitetray.py`; `build/release.py`, `release.ps1`, `ed25519.py` |
| Dropshift | `app/dropshift/suitelink.py`, `suitetray.py`; `build/release.py`, `release.ps1`, `ed25519.py` |
| Grabbit | `app/grabbit/suitelink.py`, `suitetray.py` (its own release process) |
| Homework Hub | `suitelink.py` (pystray, no Qt; its own release process) |

## Adding an app

[docs/adding-an-app.md](docs/adding-an-app.md) walks through it:

- the icon and colours;
- the build;
- joining the blossom;
- signing releases;
- the catalog entry;
- publishing.

## Building and releasing

```
powershell -ExecutionPolicy Bypass -File build\bootstrap.ps1
powershell -ExecutionPolicy Bypass -File build\build_app.ps1
powershell -ExecutionPolicy Bypass -File build\release.ps1 --notes "What's new"
```

`release.ps1` builds, checks and zips Hanami, signs its `latest.json` with the
key in `~\.hanami\release\`, and publishes the release on GitHub. The top of
`build\release.py` describes each step. **Back up the keys** in
`~\.hanami\`, `~\.keytap\` and `~\.dropshift\`: installed copies only accept
releases signed with them.

Tests, none of which show anything on screen or touch a real Hanami (they use
pipe and instance names of their own):

- `tests\test_link.py` - the pipe protocol: joining, menus, clicks, leaving, rejoining
- `tests\test_suitetray.py` - the Qt tray: folding in and out, hiding, falling back
- `tests\test_apps.py` - Keytap and Dropshift from source, folding into Hanami
- `tests\test_install.py` - checking, installing, updating and removing, against a
  stand-in GitHub on this PC with releases signed by a test key

## Photo

The cherry blossom faintly behind Hanami's windows is a photo by Mi Min on Unsplash
(https://unsplash.com/photos/pkpqoBp11Jc), used under the Unsplash License.
