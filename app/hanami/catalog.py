"""The suite's apps, as Hanami knows them: what each is, where it lives, and
where its releases come from.

A new app joins the suite with an entry here - docs/adding-an-app.md says what
else it needs. Each entry's public key is the one its build/release.json
records; Hanami installs only releases whose latest.json that key signed.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

_DOCUMENTS = Path.home() / 'Documents'


@dataclass(frozen=True)
class SuiteApp:
    name: str               # as the app introduces itself to Hanami (suitelink); also its folder's name
    description: str
    exe_name: str           # the program in its folder
    dev_build: Path         # where it is on a PC that builds it from source
    repo: str               # the GitHub repository its releases are published to, owner/name
    public_key: str         # Ed25519, hex
    release_name: str = ''  # the "app" its latest.json names, when that isn't `name`
    single_exe: bool = False   # its release is the exe itself, not a zip holding its folder
    self_test: bool = True     # its exe answers --self-test <file> with its version
    # What it is started with at sign-in, to stay in the background rather than open its window.
    # Only for apps that ask: Grabbit, say, takes any argument for a link to download.
    startup_args: tuple[str, ...] = ()

    @property
    def manifest_app(self) -> str:
        return self.release_name or self.name

    @property
    def releases_page(self) -> str:
        return f'https://github.com/{self.repo}/releases/latest'


SUITE = (
    SuiteApp('Keytap', 'Types your Bitwarden logins into any app.', 'Keytap.exe',
             _DOCUMENTS / 'Keytap' / 'dist' / 'Keytap' / 'Keytap.exe',
             'blossqt/keytap', '080b0717166ed42a3eca16c1ebf1d6b9229114a08479c3082691a854d2d08b05',
             startup_args=('--startup',)),
    SuiteApp('Dropshift', 'Drag a file, press a key, drop it on what it should become.', 'Dropshift.exe',
             _DOCUMENTS / 'Dropshift' / 'dist' / 'Dropshift' / 'Dropshift.exe',
             'blossqt/dropshift', '2805973de0b5ac4baf04e1712bd4143b84fd532d2e03cdec6cfa6f2d929e4f6f'),
    SuiteApp('Grabbit', 'Paste a link - video, post, magnet or file - and it downloads.', 'Grabbit.exe',
             _DOCUMENTS / 'Grabbit' / 'dist' / 'Grabbit' / 'Grabbit.exe',
             'blossqt/grabbit', '73c12e6787d3b5271ef6e3d3cca0a3e63c9c1aae998c5e390e94ef367b0e7c20'),
    SuiteApp('Homework Hub', 'Every assignment due, from every course site, in one list.', 'HomeworkHub.exe',
             _DOCUMENTS / 'homework-hub' / 'dist' / 'HomeworkHub.exe',
             'blossqt/homework-hub-releases', 'd7cfd2d285134baa76c7a45512b9d04ccb63601364bbaff1f7898c3eba479b20',
             release_name='HomeworkHub', single_exe=True, self_test=False),
)

# Hanami itself: checked for newer releases, which its window then points to.
HANAMI = SuiteApp('Hanami', 'The suite’s launcher and installer.', 'Hanami.exe',
                  _DOCUMENTS / 'Hanami' / 'dist' / 'Hanami' / 'Hanami.exe',
                  'blossqt/hanami', 'bb21c85150684fb56ecebb1d64c0862025c7f0a52e6ccb3467576e81a96afd69')

BY_NAME = {app.name: app for app in SUITE}
ORDER = {app.name: i for i, app in enumerate(SUITE)}


def programs() -> Path:
    """Where Hanami installs apps: a folder each, where Windows' own per-user installs go."""
    chosen = os.environ.get('HANAMI_PROGRAMS')
    if chosen:
        return Path(chosen)
    return Path(os.environ.get('LOCALAPPDATA', str(Path.home() / 'AppData' / 'Local'))) / 'Programs'


def install_dir(app: SuiteApp) -> Path:
    return programs() / app.name


def installed_exe(app: SuiteApp) -> Path:
    return install_dir(app) / app.exe_name
