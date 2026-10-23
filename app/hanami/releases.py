"""What each suite app's newest release is, and whether to believe it.

Every suite app publishes its releases on GitHub the same way (Grabbit's and
Homework Hub's arrangement, and build/release.py's): beside the Windows file,
each release carries

    latest.json        which version it is, and the file's name, size and SHA-256
    latest.json.sig    an Ed25519 signature over latest.json's exact bytes

Hanami fetches the manifest from GitHub's stable "latest release" address, and
its signature from the release the manifest names (see latest()), and believes
the manifest only when the signature checks out against the public key in the
catalog. A download is then believed only if its size and SHA-256 are the ones
the signed manifest gives. So nobody who got into a GitHub account - or between
this PC and GitHub - can get Hanami to install anything the app's own release
key didn't sign.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from . import __version__, ed25519
from .catalog import SuiteApp

MANIFEST_NAME = 'latest.json'
SIGNATURE_NAME = 'latest.json.sig'
SCHEMA = 1

_VERSION = re.compile(r'^v?(\d+)\.(\d+)\.(\d+)$')
_HEX32 = re.compile(r'^[0-9a-f]{64}$')
_FILE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]*$')

# For tests: a stand-in site and the key it signs with. The key is ignored
# unless the site is set, so nothing a user does by accident points Hanami
# anywhere but GitHub, or makes it trust another key.
ENV_SITE, ENV_KEY = 'HANAMI_RELEASE_SITE', 'HANAMI_RELEASE_KEY'


class ReleaseError(RuntimeError):
    """Why a check or an install cannot go ahead, in words fit to show."""


def parse_version(text) -> tuple | None:
    match = _VERSION.match(str(text or '').strip())
    return tuple(int(part) for part in match.groups()) if match else None


def is_newer(candidate, current) -> bool:
    """Compared as numbers, so 1.10.0 is newer than 1.9.0."""
    a, b = parse_version(candidate), parse_version(current)
    return a is not None and b is not None and a > b


def _test_site() -> str:
    return os.environ.get(ENV_SITE, '').strip().rstrip('/')


def site(app: SuiteApp) -> str:
    return f'{_test_site()}/{app.repo}' if _test_site() else f'https://github.com/{app.repo}'


def public_key(app: SuiteApp) -> str:
    override = os.environ.get(ENV_KEY, '').strip().lower()
    if _test_site() and _HEX32.match(override):
        return override
    return app.public_key


@dataclass(frozen=True)
class Asset:
    name: str
    size: int
    sha256: str
    url: str


@dataclass(frozen=True)
class Release:
    app: str
    version: str
    published_at: str
    notes: str
    asset: Asset | None         # the Windows file; None if this release has none

    def page(self, app: SuiteApp) -> str:
        return f'https://github.com/{app.repo}/releases/tag/v{self.version}'


def verify_and_parse(app: SuiteApp, manifest: bytes, signature, key: str | None = None) -> Release:
    """Check the signature first, and only then read a word of the contents."""
    key = public_key(app) if key is None else key
    if not _HEX32.match(key or ''):
        raise ReleaseError(f'Hanami has no release key for {app.name} yet.')
    try:
        raw = base64.b64decode(signature.strip() if isinstance(signature, (bytes, str)) else b'',
                               validate=True)
    except (ValueError, TypeError):
        raise ReleaseError(f'{app.name}’s release signature is unreadable.') from None
    if not ed25519.verify(bytes.fromhex(key), manifest, raw):
        raise ReleaseError(f'{app.name}’s release signature does not match, so it cannot be trusted.')
    try:
        body = json.loads(manifest.decode('utf-8'))
    except (UnicodeDecodeError, ValueError):
        raise ReleaseError(f'{app.name}’s release description is unreadable.') from None
    if not isinstance(body, dict) or body.get('schema') != SCHEMA or body.get('app') != app.manifest_app:
        raise ReleaseError(f'The release found for {app.name} is for a different app, or a newer format.')
    version = str(body.get('version') or '')
    if parse_version(version) is None:
        raise ReleaseError(f'{app.name}’s release has no usable version.')
    entry, asset = body.get('desktop'), None
    if entry is not None:
        if not isinstance(entry, dict):
            raise ReleaseError(f'{app.name}’s release is malformed.')
        name = str(entry.get('file') or '')
        sha = str(entry.get('sha256') or '').lower()
        try:
            size = int(entry.get('size'))
        except (TypeError, ValueError):
            size = -1
        if not _FILE.match(name) or not _HEX32.match(sha) or size <= 0:
            raise ReleaseError(f'{app.name}’s release is missing its file, size or hash.')
        asset = Asset(name, size, sha, f'{site(app)}/releases/download/v{version}/{name}')
    return Release(app=app.name, version=version, published_at=str(body.get('published_at') or ''),
                   notes=str(body.get('notes') or '')[:4000], asset=asset)


# ------------------------------------------------------------------- fetching

def open_url(url: str, timeout: float):
    request = urllib.request.Request(url, headers={'User-Agent': f'Hanami/{__version__}'})
    context = ssl.create_default_context() if url.startswith('https:') else None
    return urllib.request.urlopen(request, timeout=timeout, context=context)


def _fetch(url: str, timeout: float) -> bytes:
    with open_url(url, timeout) as response:
        return response.read(1 << 20)          # a manifest is a few hundred bytes


def _named_version(manifest: bytes) -> str | None:
    """The version a manifest says it is, before it is believed - only to know which release's
    signature to fetch for it, so only as plain numbers."""
    try:
        version = parse_version(json.loads(manifest.decode('utf-8')).get('version'))
    except (UnicodeDecodeError, ValueError, AttributeError):
        return None
    return '.'.join(map(str, version)) if version else None


def latest(app: SuiteApp, timeout: float = 15) -> Release:
    """The app's newest release, verified. Raises ReleaseError and nothing else.

    The signature is fetched from the release the manifest names, not from the "latest release"
    address as the manifest is: GitHub caches the two files apart, and for a few minutes after a
    release one can be the new release's and the other the last one's - a pair that would never
    match, and would look like a forgery."""
    base = f'{site(app)}/releases/latest/download'
    try:
        manifest = _fetch(f'{base}/{MANIFEST_NAME}', timeout)
        named = _named_version(manifest)
        try:
            signature = _fetch(f'{site(app)}/releases/download/v{named}/{SIGNATURE_NAME}' if named
                               else f'{base}/{SIGNATURE_NAME}', timeout)
        except urllib.error.HTTPError as error:
            if error.code != 404 or not named:
                raise
            signature = _fetch(f'{base}/{SIGNATURE_NAME}', timeout)
    except urllib.error.HTTPError as error:
        if error.code == 404:
            raise ReleaseError(f'{app.name} has no release yet.') from None
        if error.code in (403, 429):
            raise ReleaseError('GitHub is limiting how often this can be asked. Try again in an hour.') from None
        raise ReleaseError(f'GitHub answered {error.code}.') from None
    except (urllib.error.URLError, OSError, ValueError):
        raise ReleaseError("Couldn't reach GitHub. Check the internet connection.") from None
    try:
        return verify_and_parse(app, manifest, signature)
    except ReleaseError:
        raise
    except Exception as error:                  # a bug here must not take Hanami down
        raise ReleaseError(f'{app.name}’s release could not be read: {error}') from None


def file_digest(path: Path) -> tuple:
    digest, size = hashlib.sha256(), 0
    with Path(path).open('rb') as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b''):
            digest.update(chunk)
            size += len(chunk)
    return size, digest.hexdigest()


def download(asset: Asset, folder: Path, progress=None, cancel=None) -> Path:
    """Fetch a release file and prove it is the one the signed manifest
    describes - size and SHA-256 - before anything opens it."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    final = folder / asset.name
    if final.exists() and file_digest(final) == (asset.size, asset.sha256):
        return final
    part = final.with_name(final.name + '.part')
    digest, done = hashlib.sha256(), 0
    try:
        with open_url(asset.url, timeout=60) as response, part.open('wb') as out:
            for chunk in iter(lambda: response.read(1 << 16), b''):
                if cancel is not None and cancel.is_set():
                    raise ReleaseError('Cancelled.')
                done += len(chunk)
                if done > asset.size:
                    raise ReleaseError('The download is bigger than the release says.')
                out.write(chunk)
                digest.update(chunk)
                if progress:
                    progress(done, asset.size)
        if done != asset.size or digest.hexdigest() != asset.sha256:
            raise ReleaseError('The download didn’t match the release, so it wasn’t installed.')
    except ReleaseError:
        part.unlink(missing_ok=True)
        raise
    except (urllib.error.URLError, OSError) as error:
        part.unlink(missing_ok=True)
        raise ReleaseError(f'The download failed: {getattr(error, "reason", None) or error}') from None
    os.replace(part, final)
    return final
