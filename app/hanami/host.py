"""The other end of suitelink: suite apps folding their tray menus into Hanami's icon."""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass, field

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtNetwork import QLocalServer, QLocalSocket

from .suitelink import PIPE_NAME

MAX_LINE = 1 << 20          # an app's message is never anywhere near this


@dataclass
class Member:
    name: str
    pid: int
    icon: QIcon
    socket: QLocalSocket
    items: list = field(default_factory=list)
    tooltip: str = ''


class TrayHost(QObject):
    changed = Signal()
    notified = Signal(str, str, str)         # app, title, body

    def __init__(self, parent=None):
        super().__init__(parent)
        self.members: dict[str, Member] = {}
        self._buffers: dict[QLocalSocket, bytes] = {}
        self._names: dict[QLocalSocket, str] = {}
        self.server = QLocalServer(self)
        self.server.setSocketOptions(QLocalServer.UserAccessOption)
        QLocalServer.removeServer(PIPE_NAME)
        self.listening = self.server.listen(PIPE_NAME)
        self.server.newConnection.connect(self._connected)

    def click(self, name: str, item_id: str) -> bool:
        member = self.members.get(name)
        if member is None:
            return False
        member.socket.write((json.dumps({'t': 'click', 'id': item_id}) + '\n').encode('utf-8'))
        member.socket.flush()
        return True

    def close(self) -> None:
        for member in list(self.members.values()):
            member.socket.disconnectFromServer()
        self.server.close()

    # ------------------------------------------------------------------ connections

    def _connected(self) -> None:
        while self.server.hasPendingConnections():
            socket = self.server.nextPendingConnection()
            self._buffers[socket] = b''
            socket.readyRead.connect(lambda s=socket: self._read(s))
            socket.disconnected.connect(lambda s=socket: self._gone(s))

    def _read(self, socket: QLocalSocket) -> None:
        data = self._buffers.get(socket, b'') + bytes(socket.readAll())
        if len(data) > MAX_LINE and b'\n' not in data:
            socket.abort()
            return
        lines = data.split(b'\n')
        self._buffers[socket] = lines.pop()
        for line in lines:
            try:
                message = json.loads(line.decode('utf-8'))
            except (ValueError, UnicodeDecodeError):
                continue
            if isinstance(message, dict):
                self._handle(socket, message)

    def _handle(self, socket: QLocalSocket, message: dict) -> None:
        kind = message.get('t')
        if kind == 'hello':
            name = str(message.get('app') or '')[:60]
            if not name:
                return
            old = self.members.get(name)
            if old is not None and old.socket is not socket:
                old.socket.abort()          # a copy that went away without saying so
            pixmap = QPixmap()
            try:
                pixmap.loadFromData(base64.b64decode(message.get('icon') or ''), 'PNG')
            except ValueError:
                pass
            self._names[socket] = name
            self.members[name] = Member(name, int(message.get('pid') or 0),
                                        QIcon(pixmap) if not pixmap.isNull() else QIcon(), socket)
            self.changed.emit()
            return
        member = self.members.get(self._names.get(socket, ''))
        if member is None or member.socket is not socket:
            return
        if kind == 'menu':
            items = message.get('items')
            member.items = [i for i in items if isinstance(i, dict)] if isinstance(items, list) else []
            member.tooltip = str(message.get('tooltip') or member.name)[:300]
            self.changed.emit()
        elif kind == 'notify':
            self.notified.emit(member.name, str(message.get('title') or '')[:200],
                               str(message.get('body') or '')[:500])

    def _gone(self, socket: QLocalSocket) -> None:
        name = self._names.pop(socket, '')
        self._buffers.pop(socket, None)
        member = self.members.get(name)
        if member is not None and member.socket is socket:
            del self.members[name]
            self.changed.emit()
        socket.deleteLater()
