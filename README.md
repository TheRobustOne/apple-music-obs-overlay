# Apple Music Now Playing Overlay for OBS

A lightweight local overlay that shows what's currently playing in Apple Music
(Windows), for use as an OBS Browser Source. Fully customizable through a
web-based settings page — no code editing required.

![status](https://img.shields.io/badge/platform-Windows-blue)

## How it works

- Reads the current track from Apple Music via the Windows System Media
  Transport Controls (SMTC) API — the same mechanism Windows uses to show
  media controls in the taskbar/lock screen.
- Runs a small local web server (`localhost:8765`) that serves:
  - `/overlay.html` — the overlay itself, added as an OBS Browser Source
  - `/settings` — a web UI for customizing colors, fonts, and layout
  - `/api/now-playing` — JSON with the current track info
  - `/api/config` — JSON with the current appearance settings

Everything runs locally on your machine. Nothing is uploaded anywhere.

## Quick start (no Python required)

Download `AppleMusicOverlay.exe` from the
[latest release](https://github.com/dougcoleman19/apple-music-obs-overlay/releases/latest)
and double-click it. A console window opens showing the overlay URL — leave
it running while you stream, and close it to stop the overlay. Then skip to
[Add it to OBS](#add-it-to-obs) below.

Windows SmartScreen may warn about an unrecognized app the first time,
since the exe isn't code-signed — click **More info -> Run anyway**.

## Requirements (running from source)

- Windows 10/11
- [Python 3.9+](https://www.python.org/downloads/) (3.9–3.12 recommended —
  see note below for 3.13)
- Apple Music for Windows
- OBS Studio

## Setup (running from source)

1. Install Python from [python.org](https://www.python.org/downloads/) if
   you don't already have it. During install, check **"Add python.exe to
   PATH"**.
2. Download/clone this project folder.
3. Open a terminal in the project folder and install dependencies:

   ```
   pip install -r requirements.txt
   ```

4. Run the overlay:

   ```
   python apple_music_overlay.py
   ```

   You should see:

   ```
   Overlay running at http://localhost:8765/overlay.html
   Customize it at   http://localhost:8765/settings
   ```

   Leave this window open while you stream — closing it stops the overlay.

### A note on Python 3.13

The `winsdk` package doesn't yet publish a prebuilt wheel for Python 3.13,
so `pip install` will try to compile it from source, which requires the
[Visual Studio Build Tools](https://visualstudio.microsoft.com/visual-cpp-build-tools/)
(the "Desktop development with C++" workload). To avoid that entirely,
use Python 3.12 or earlier, where a prebuilt wheel installs instantly.

## Add it to OBS

1. In OBS, click **+** under Sources -> **Browser**.
2. Set the URL to `http://localhost:8765/overlay.html`.
3. Set Width/Height to roughly `600 x 200` (adjust to taste — see
   "Overlay size" below if it looks too small or gets cut off).
4. **Uncheck** "Shutdown source when not visible" so it keeps polling in
   the background.
5. Play something in Apple Music. If nothing appears, hit pause/play once —
   Windows only exposes a media session once playback has started.

## Customize the look

Open **http://localhost:8765/settings** in a browser while the script is
running. You can change:

- Background color & opacity
- Progress bar color
- Title & artist text color
- Font
- Corner radius / rounding
- Max card width
- Overlay size (scales everything — art, text, progress bar — up or down)
- Show/hide album art
- Show/hide the progress bar

If you increase "Overlay size" and it gets clipped in OBS, increase the
Browser Source's Width/Height too (right-click the source -> Properties).

A live preview (showing your actual current track) updates as you save.
Settings are written to `overlay_config.json` next to the script and are
picked up by the OBS overlay automatically within a few seconds — no need
to restart OBS or the script.

## Troubleshooting

- **Nothing shows up in OBS**: Make sure Apple Music is actually playing
  (or paused with an active session). Hit pause/play once after starting
  the script.
- **Wrong app's media shows up**: If you have other media apps open
  (Spotify, a browser tab playing video, etc.), the script prefers a
  session that looks like Apple Music/iTunes but falls back to whatever
  Windows reports as the "current" session. Pause the other apps if it
  picks the wrong one.
- **`pip install winsdk` fails while building a wheel**: see the
  [Python 3.13 note](#a-note-on-python-313) above.
- **Port 8765 already in use**: another instance of the script (or
  something else) is already using that port. Close it, or edit `PORT` at
  the top of `apple_music_overlay.py`.

## Sharing this with other people

Anyone using this needs to independently install Python + `winsdk` and run
the script themselves — it reads their own PC's Apple Music session, so it
can't be hosted centrally or run from the cloud. Point them at this README
for setup.
