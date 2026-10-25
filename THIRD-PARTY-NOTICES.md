# Third-party software in Hanami

| Component | Licence | Use |
|-----------|---------|-----|
| Qt 6 / PySide6 | LGPL-3.0 | the window, the tray icon, drawing |

Qt and PySide6 are used unchanged, as the libraries in `_internal\`; their
source is at https://code.qt.io. Hanami's own Ed25519 check is plain Python,
written from RFC 8032.

## Hanami Sensors (`sensors\`)

The small service that reads the processor's temperature carries these, unchanged, as the DLLs in
`sensors\service\`:

| Component | Licence | Source |
|-----------|---------|--------|
| LibreHardwareMonitorLib 0.9.6 | MPL-2.0 | https://github.com/LibreHardwareMonitor/LibreHardwareMonitor |
| BlackSharp.Core 1.0.7 | MPL-2.0 | https://github.com/Blacktempel/BlackSharp |
| DiskInfoToolkit 1.1.2 | MPL-2.0 | https://github.com/Blacktempel/DiskInfoToolkit |
| RAMSPDToolkit-NDD 1.4.2 | MPL-2.0 | https://github.com/Blacktempel/RAMSPDToolkit |
| HidSharp 2.6.4 | Apache-2.0 | https://software.seekye.com/hidsharp |
| Mono.Posix.NETStandard 1.0.0 | MIT | https://github.com/mono/mono |
| System.Management, System.IO.Ports, System.CodeDom, System.Diagnostics.EventLog, System.ServiceProcess.ServiceController | MIT | https://github.com/dotnet/dotnet |

The MPL-2.0 components' source is at the addresses above; Hanami changes none of them. It reads
the temperature through PawnIO (https://pawnio.eu), which is installed separately.

The apps Hanami installs carry their own notices.
