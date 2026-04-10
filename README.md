# Android Messages Desktop

A lightweight, native Windows desktop client for [Google Messages](https://messages.google.com/web/) — built with Python and WebView2.

> **No Electron. No bloat.** Uses the same WebView2 engine already installed on Windows 10/11, keeping the app fast and small.

---

## Features

- ✅ Native Windows WebView2 rendering (full Google Sign-in support)
- ✅ System tray icon with show/hide, unread badge & red dot
- ✅ Windows 11 toast notifications with message preview
- ✅ Taskbar flash on new messages
- ✅ Menu bar with View, Tray, Notifications and App menus
- ✅ Hide menu bar (press `Alt` to bring it back)
- ✅ Minimize to tray / Close to tray
- ✅ Remember window position and size
- ✅ Single-instance enforcement
- ✅ About window
- ✅ Update checker
- ✅ Settings persisted in `%APPDATA%\android-messages\config.json`

---

## Download (No Install Required)

Head to the [**Releases**](https://github.com/PatrickHusband/android-messages/releases/latest) page and download `Android Messages Desktop.exe`.

**Requirements:**
- Windows 10 or Windows 11
- [WebView2 Runtime](https://developer.microsoft.com/en-us/microsoft-edge/webview2/) — pre-installed on Windows 11 and most updated Windows 10 systems. If missing, download it free from Microsoft.

Just double-click the `.exe` — no installation needed.

---

## Data & Privacy

All app data is stored locally on your machine:

| Location | Contents |
|---|---|
| `%APPDATA%\android-messages\config.json` | App settings (window size, tray prefs, etc.) |
| `%APPDATA%\android-messages\EBWebView\` | WebView2 session data (cookies / Google login) |

No data is sent anywhere other than to Google Messages directly.

---

## Building from Source

### Prerequisites

- **Python 3.10+** (tested on Python 3.13)
- **pip** packages:

```bash
pip install pywebview pyinstaller pystray Pillow win11toast pythonnet
```

### Clone and Build

```bash
git clone https://github.com/PatrickHusband/android-messages.git
cd android-messages

pyinstaller "Android Messages Desktop.spec" --clean
```

The standalone executable will be output to:

```
dist/Android Messages Desktop.exe
```

### Running from Source (without building)

```bash
python messages_app.py
```

### Project Structure

```
android-messages/
├── messages_app.py                  ← Main application source
├── about.html                       ← About window UI
├── about_icon.png                   ← About window hero image
├── icon.ico                         ← Application icon (exe/taskbar)
├── icon.png                         ← Tray icon source
├── Android Messages Desktop.spec    ← PyInstaller build configuration
└── README.md
```

### How the Build Works

The `.spec` file instructs PyInstaller to:
- Bundle `messages_app.py` and all dependencies into a **single `.exe`**
- Embed `icon.png`, `about.html`, and `about_icon.png` as internal resources
- Use `icon.ico` as the Windows application icon
- Output a **windowless** (no console) executable

---

## Tech Stack

| Component | Technology |
|---|---|
| UI Engine | [pywebview](https://pywebview.flowrl.com/) + WebView2 |
| Tray Icon | [pystray](https://github.com/moses-palmer/pystray) |
| Notifications | [win11toast](https://github.com/GitHub30/win11toast) |
| Images | [Pillow](https://python-pillow.org/) |
| .NET interop (menu) | [pythonnet](https://github.com/pythonnet/pythonnet) |
| Packaging | [PyInstaller](https://pyinstaller.org/) |

---

## Credits

Inspired by the original [android-messages-desktop](https://github.com/OrangeDrangon/android-messages-desktop) project by OrangeDrangon.

Not affiliated with Google LLC. Android is a trademark of Google LLC.
