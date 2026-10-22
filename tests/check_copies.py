"""Are the suite's shared files the same everywhere?

    python tests\\check_copies.py          say which copies differ from Hanami's
    python tests\\check_copies.py --sync   copy Hanami's over them

Written once, here in Hanami, and copied into each app:

    suitelink.py    every app: its tray menu, folded into Hanami's blossom
    suitetray.py    the Qt apps: suitelink, plus their own icon when Hanami isn't there
    suitetheme.py   the Qt apps, in ui\\: the pink, check boxes, colours, fonts and cards;
                    each app's ui\\theme.py imports it and adds its own colours
    suitelog.py     the Qt apps and Homework Hub: a windowed exe's prints, tracebacks and
                    native crashes, in a log
    release kit     build\\release.py, release.ps1 and ed25519.py: publishing a
                    release Hanami will install (apps without a release
                    process of their own - Grabbit and Homework Hub have theirs)

docs/adding-an-app.md says where a new app's copies go.
"""

import filecmp
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCUMENTS = Path.home() / 'Documents'

QT_APPS = [DOCUMENTS / 'Keytap' / 'app' / 'keytap', DOCUMENTS / 'Dropshift' / 'app' / 'dropshift',
           DOCUMENTS / 'Grabbit' / 'app' / 'grabbit']
RELEASED_BY_THE_KIT = [DOCUMENTS / 'Keytap' / 'build', DOCUMENTS / 'Dropshift' / 'build']

COPIES = {
    ROOT / 'app' / 'hanami' / 'suitelink.py': QT_APPS + [DOCUMENTS / 'homework-hub'],
    ROOT / 'app' / 'hanami' / 'suitetray.py': QT_APPS,
    ROOT / 'app' / 'hanami' / 'ui' / 'suitetheme.py': [app / 'ui' for app in QT_APPS],
    ROOT / 'app' / 'hanami' / 'suitelog.py': QT_APPS + [DOCUMENTS / 'homework-hub'],
    ROOT / 'app' / 'hanami' / 'ed25519.py': [ROOT / 'build'] + RELEASED_BY_THE_KIT,
    ROOT / 'build' / 'release.py': RELEASED_BY_THE_KIT,
    ROOT / 'build' / 'release.ps1': RELEASED_BY_THE_KIT,
}


def main() -> int:
    sync = '--sync' in sys.argv
    stale = 0
    for original, folders in COPIES.items():
        for folder in folders:
            copy = folder / original.name
            same = copy.is_file() and filecmp.cmp(original, copy, shallow=False)
            if same:
                print(f'same     {copy}')
            elif sync:
                shutil.copyfile(original, copy)
                print(f'copied   {copy}')
            else:
                stale += 1
                print(f'DIFFERS  {copy}' if copy.exists() else f'MISSING  {copy}')
    return 1 if stale else 0


if __name__ == '__main__':
    sys.exit(main())
