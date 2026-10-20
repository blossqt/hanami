# Third-party software in Hanami

| Component | Licence | Use |
|-----------|---------|-----|
| Qt 6 / PySide6 | LGPL-3.0 | the window, the tray icon, drawing |

Qt and PySide6 are used unchanged, as the libraries in `_internal\`; their
source is at https://code.qt.io. Hanami's own Ed25519 check is plain Python,
written from RFC 8032.

The apps Hanami installs carry their own notices.
