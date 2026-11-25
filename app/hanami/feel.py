r"""How quickly Hanami answers: from a press to its first frame on screen, written down.

    %LOCALAPPDATA%\Hanami\feel.log

Each line is one answer - the edge panel coming out, the window or Settings opening,
the sound pop-up, the frozen screens for copying text:

    2026-11-25 08:01:12  panel        34 ms   (first frame)

and, for the few seconds after each, any time the windows' thread was held up long
enough to drop frames:

    2026-11-25 08:01:12  held up      120 ms  (after panel)

So what feels slow is measured on the PC it runs on, not guessed at. Hanami-only (not
a shared file). The log is kept small: past LIMIT it starts afresh.

A press's time is taken when Hanami hears of it; for a hotkey, from when Windows
queued it (GetMessageTime). The first frame is the window's first paint after: what
the screen shows a frame or so later.
"""

from __future__ import annotations

import ctypes
import os
import time
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, QTimer

LIMIT = 200_000            # bytes: a log past this at a write starts afresh
HELD_UP = 0.05             # s: a gap in the windows' thread this long (3 frames at 60 Hz) is written down
WATCH_FOR = 3.0            # s after a press that the thread is watched for gaps
WATCH_EVERY = 16           # ms between looks, while watched

_path: Path | None = None
_last = ''                 # the latest press's name, for the gaps after it


def path() -> Path:
    chosen = os.environ.get('HANAMI_FEEL_LOG')      # (the tests' own)
    if chosen:
        return Path(chosen)
    return Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'Hanami' / 'feel.log'


def write(what: str, seconds: float, note: str = '') -> None:
    """One line in the log - never raised: the log is a help, not a need."""
    line = f'{time.strftime("%Y-%m-%d %H:%M:%S")}  {what:<11} {seconds * 1000:5.0f} ms' + (f'   ({note})' if note else '')
    try:
        file = path()
        file.parent.mkdir(parents=True, exist_ok=True)
        mode = 'w' if file.is_file() and file.stat().st_size > LIMIT else 'a'
        with open(file, mode, encoding='utf-8') as log:
            log.write(line + '\n')
    except OSError:
        pass


def hotkey_waited() -> float:
    """How long the hotkey being handled now waited in Windows' queue, in s (0 when unknown)."""
    try:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        waited = (kernel32.GetTickCount() - user32.GetMessageTime()) & 0xFFFFFFFF
        return waited / 1000 if waited < 5000 else 0.0
    except (AttributeError, OSError):
        return 0.0


class _FirstFrame(QObject):
    """Writes down the time to a window's first paint after a press, then lets go."""

    def __init__(self, what: str, window, started: float):
        super().__init__(window)
        self.what, self.window, self.started = what, window, started
        window.installEventFilter(self)
        QTimer.singleShot(5000, self, self._give_up)       # never painted (hidden again at once): no line

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Paint:
            elapsed = time.perf_counter() - self.started
            # after the paint, once Qt has handed the frame on: one turn of the loop later
            QTimer.singleShot(0, self, lambda: self._done(elapsed, time.perf_counter() - self.started))
            self.window.removeEventFilter(self)
        return False

    def _done(self, painted: float, handed_on: float) -> None:
        write(self.what, handed_on, f'painted at {painted * 1000:.0f} ms')
        self.deleteLater()

    def _give_up(self) -> None:
        try:
            self.window.removeEventFilter(self)
        except RuntimeError:
            pass
        self.deleteLater()


class _Watch(QObject):
    """The windows' thread, looked at every frame for a few seconds after a press: a gap between
    looks is a time it was held up - frames dropped in whatever moved."""

    def __init__(self):
        super().__init__()
        self._timer = QTimer(self, interval=WATCH_EVERY)
        self._timer.timeout.connect(self._look)
        self._at = 0.0
        self._until = 0.0

    def start(self) -> None:
        self._until = time.perf_counter() + WATCH_FOR
        if not self._timer.isActive():
            self._at = time.perf_counter()
            self._timer.start()

    def _look(self) -> None:
        now = time.perf_counter()
        gap = now - self._at - WATCH_EVERY / 1000
        self._at = now
        if gap >= HELD_UP:
            write('held up', gap, f'after {_last}')
        if now >= self._until:
            self._timer.stop()


_watch: _Watch | None = None


def pressed(what: str, window, waited: float = 0.0) -> None:
    """A press that brings up window: its first frame is timed from now (less waited, the time
    the press waited before Hanami heard of it), and the thread watched meanwhile."""
    global _watch, _last
    _last = what
    if window is None:
        return
    try:
        _FirstFrame(what, window, time.perf_counter() - waited)
        if _watch is None:
            _watch = _Watch()
        _watch.start()
    except RuntimeError:                    # the window is gone
        pass
