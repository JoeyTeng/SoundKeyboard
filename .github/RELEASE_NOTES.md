Packaged builds include Python and the application dependencies.

| Asset | Platform |
| --- | --- |
| `SoundKeyboard-windows-x86_64.exe` | Windows, Intel/AMD 64-bit |
| `SoundKeyboard-macos-arm64.app.zip` | macOS, Apple Silicon (M-series) |
| `SoundKeyboard-macos-x86_64.app.zip` | macOS, Intel |

On Windows, save the executable in a writable folder and run it. On macOS, extract the matching archive, move `SoundKeyboard.app` to Applications, and open it. The Windows executable is not code-signed. The macOS app is ad-hoc signed, but is not Developer ID signed or notarized.

If macOS blocks the app, first try **System Settings → Privacy & Security → Open Anyway** after attempting to open it. If needed, remove quarantine from this app bundle only:

```bash
xattr -dr com.apple.quarantine "/Applications/SoundKeyboard.app"
open "/Applications/SoundKeyboard.app"
```

Grant **Input Monitoring** and **Accessibility** access in System Settings before using global keyboard features, then quit and reopen the app. Removing quarantine does not grant these permissions.

The default sound pack is empty. Add your audio files and rules, or import a sound pack, before expecting keyboard sounds.

Original project by [Pizzadark](https://space.bilibili.com/6297797). Distributed under CC BY-NC-SA 4.0; see the accompanying `LICENSE` file.
