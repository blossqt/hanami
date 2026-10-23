"""Colours for Hanami's window, following Windows' light or dark mode.

They are the suite's, from suitetheme.py - the shared file kept in step by
tests/check_copies.py - and Hanami adds none of its own. An app that needs
more colours subclasses Colors here, as Keytap and Dropshift do.
"""

from pathlib import Path

from .suitetheme import *  # noqa: F401,F403 - the suite's look, used as theme.<name>

BACKDROP = str(Path(__file__).with_name('backdrop.jpg'))     # Mi Min's blossom, on Unsplash, faint behind the windows
