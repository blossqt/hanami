# Adding an app to the suite

Every suite app looks the same, is built the same way, folds its tray icon into
Hanami's blossom, and is published so Hanami can install and update it. Keytap
is the most recent app built this way: copy from it whenever a step says
"like Keytap".

## 1. Look like the suite

**Icon.** A rounded-square tile filling the whole canvas, corners rounded to
42/192 of its width, in blossom pink `#ffd1dc`, holding one mark in deep rose
`#c2255c`, centred and about 50-60% of the tile's width.

- Write both colours into the code as constants. Never take them from the
  system palette or accent: the icon is baked into the exe at build time, and
  this PC's accent follows the wallpaper.
- Draw each size (16, 20, 24, 32, 40, 48, 64, 128, 256) on its own so the small
  ones stay crisp.
- The exe icon, the window and tray icon, and any phone launcher icon all come
  from one drawing, `render_app_icon(size)` in `app/<app>/ui/icons.py`.

Copy the layout of Keytap's `ui/icons.py`.

**Window.** The highlight is the same pink, never Windows' accent:

- Buttons, ticks, selections and progress fill with `#ffd1dc`, and text on
  them is `#a61e4d`.
- As text or a line on the window, the pink is `#ffd1dc` on dark and `#c2255c`
  on white.
- Copy Keytap's `ui/theme.py` and call `theme.install(app)` right after making
  the `QApplication`. Its `SuiteStyle` draws check boxes, because Windows 11's
  own style loses a ticked box's fill under a style sheet.

## 2. Build it the suite way

Copy Keytap's `build\` folder and rename what's in it:

- **`bootstrap.ps1`** makes a venv in `%LOCALAPPDATA%\<App>Build\` and fetches
  any bundled tools there. Pin PySide6-Essentials and PyInstaller to the
  suite's versions.
- **`build_app.ps1`** works through these steps:
  - refuses to run while the app runs from `dist\`;
  - checks every module imports;
  - writes the icon;
  - runs PyInstaller;
  - starts the exe with `--self-test`.
- **`<app>.spec`** lists Qt's plugins explicitly. PyInstaller drops them when
  it runs inside the Claude desktop app.
- **`version_info.txt`** carries the same version as `app\<app>\__init__.py`.
  The release script checks the two agree.

The app itself:

- **`--self-test <file>`** loads what a real start loads, paints a window
  without showing it, and writes the version (first, before anything else) to
  the file. The build, the release script and Hanami's installer all start the
  exe this way before trusting it.
- **Command-line tools** start with `CREATE_NO_WINDOW`.
- **One copy at a time:** a second start brings up the first copy (a
  `QLocalServer` named `<app>-<user>`, like Keytap's).

## 3. Join the blossom

Copy `app/hanami/suitelink.py` into the app (and `suitetray.py` too, for a Qt
app). Then describe the tray menu as data:

```python
self.tray = SuiteTray('MyApp', icons.app_icon(), self)
self.tray.clicked.connect(self._tray_clicked)
self.tray.set_menu([
    {'id': 'settings', 'text': 'Settings…', 'default': True},
    {'id': 'pause', 'text': 'Pause', 'checkable': True, 'checked': False},
    {'separator': True},
    {'id': 'quit', 'text': 'Quit MyApp'},
], tooltip='MyApp')
```

- **`quit` is required.** Hanami sends it to quit an app before updating it,
  and from the app's Quit button in its window.
- **`default`** is the item a left click on the app's own icon chooses.
- **Notifications** go through `tray.notify(title, body)`. They come from the
  blossom while Hanami runs.
- **Hide option (optional):** an app that can do without the tray can offer a
  **Show … in the tray** setting, as Keytap and Dropshift do.

## 4. Make it releasable

From Hanami's `build\` folder, copy `release.py`, `release.ps1` and
`ed25519.py` into the app's `build\`. Then write `build\release.json`:

```json
{
  "app": "MyApp",
  "repo": "blossqt/myapp",
  "public_key": ""
}
```

Then, once:

```
powershell -ExecutionPolicy Bypass -File build\release.ps1 --make-key
```

This writes the signing key to `~\.myapp\release\update-signing.key` and its
public half into `release.json`. **Back the key up.** Hanami installs only
releases signed with it.

## 5. Tell Hanami about it

In Hanami:

1. **`app/hanami/catalog.py`:** add a `SuiteApp` to `SUITE`:
   - its name, as it introduces itself through `suitelink`;
   - a one-line description;
   - the exe's file name;
   - where its build lands in `Documents`;
   - its repository;
   - the public key from its `release.json`.

   An app published as a lone exe rather than a zipped folder sets
   `single_exe=True`. One without `--self-test` sets `self_test=False`.
2. **`tests/check_copies.py`:** add the app's folders to the lists its copies
   are in. Then run `python tests\check_copies.py`.
3. **`tests/test_apps.py`:** a test that starts the app from source and checks
   it joins the blossom is worth adding, like Keytap's and Dropshift's.
4. **The window** lays the apps out two to a row. A fifth app starts a third
   row by itself.

## 6. Publish

1. **Create the repository and push.** Make it public, as with Grabbit, Keytap
   and Dropshift: Hanami downloads releases without signing in to GitHub. A
   private app can keep its code in a private repository and publish to a
   public `<app>-releases` one instead, as Homework Hub does.
2. **Release:** run
   `powershell -ExecutionPolicy Bypass -File build\release.ps1 --notes "First release."`
   It builds, checks, zips (`MyApp-0.1.0-win64.zip`, holding one `MyApp\`
   folder), signs `latest.json`, and publishes `v0.1.0`.
3. **Release Hanami too.** The new catalog entry only reaches people with a
   Hanami built after it.

Later releases work the same way: raise the version in `__init__.py` and
`version_info.txt`, commit and push, then run `release.ps1`. Every Hanami that
has the app installed offers the update within 12 hours, or as soon as its
window is opened.
