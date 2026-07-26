"""
Apple Music Now Playing overlay for OBS.

How it works:
- Reads the current track from Apple Music (Windows) via the Windows
  System Media Transport Controls (SMTC) API, the same mechanism Windows
  uses to show media controls in the taskbar/lock screen.
- Runs a tiny local web server that serves an HTML overlay page and a
  JSON endpoint with the current track info.
- Add the overlay page as a Browser Source in OBS.
- Serves a web-based settings page for customizing colors, fonts, and
  layout without editing any code.

Setup:
    pip install winsdk

Run:
    python apple_music_overlay.py

Then in OBS:
    Add Source -> Browser -> URL: http://localhost:8765/overlay.html
    Width: 500, Height: 150 (adjust to taste)
    Check "Shutdown source when not visible" OFF so it keeps polling.

Customize the look:
    Open http://localhost:8765/settings in a browser. Changes are saved
    to overlay_config.json next to this script and picked up by the
    overlay automatically within a few seconds (no OBS restart needed).

Notes:
- Apple Music must actually be playing (or paused with an active session)
  for Windows to expose it via SMTC. If nothing shows up, play a track,
  hit pause/play once, and check again.
- If you have other media apps open (browser tabs, Spotify, etc.), the
  script prefers a session whose app id looks like Apple Music/iTunes,
  falling back to whatever the "current" system session is.
"""

import asyncio
import base64
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

try:
    from winsdk.windows.media.control import (
        GlobalSystemMediaTransportControlsSessionManager as MediaManager,
        GlobalSystemMediaTransportControlsSessionPlaybackStatus as PlaybackStatus,
    )
    from winsdk.windows.storage.streams import Buffer, DataReader, InputStreamOptions
except ImportError as e:
    raise SystemExit(
        "Missing dependency 'winsdk'. Install it with:\n\n    pip install winsdk\n\n"
        f"(original error: {e})"
    )

HOST = "localhost"
PORT = 8765
POLL_SECONDS = 1.0
if getattr(sys, "frozen", False):
    APP_DIR = Path(sys.executable).resolve().parent
else:
    APP_DIR = Path(__file__).resolve().parent
CONFIG_PATH = APP_DIR / "overlay_config.json"

STATE = {
    "title": "",
    "artist": "",
    "album": "",
    "artwork": "",  # data: URI, or "" if none
    "position": 0.0,
    "duration": 0.0,
    "playing": False,
}
STATE_LOCK = threading.Lock()

DEFAULT_CONFIG = {
    "bg_color": "#141418",
    "bg_opacity": 0.75,
    "accent_color": "#1ed760",
    "title_color": "#ffffff",
    "artist_color": "#cccccc",
    "font_family": "Segoe UI, Helvetica, Arial, sans-serif",
    "corner_radius": 14,
    "card_max_width": 460,
    "show_artwork": True,
    "show_progress_bar": True,
}
CONFIG_LOCK = threading.Lock()


def load_config():
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                saved = json.load(f)
            merged = dict(DEFAULT_CONFIG)
            merged.update({k: v for k, v in saved.items() if k in DEFAULT_CONFIG})
            return merged
        except Exception:
            pass
    return dict(DEFAULT_CONFIG)


def save_config(config):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)


CONFIG = load_config()


async def read_thumbnail(thumb_ref):
    if thumb_ref is None:
        return ""
    try:
        stream = await thumb_ref.open_read_async()
        size = stream.size
        if size == 0:
            return ""
        buffer = Buffer(size)
        await stream.read_async(buffer, size, InputStreamOptions.READ_AHEAD)
        reader = DataReader.from_buffer(buffer)
        data = bytearray(size)
        reader.read_bytes(data)
        b64 = base64.b64encode(bytes(data)).decode("ascii")
        return f"data:image/png;base64,{b64}"
    except Exception:
        return ""


def pick_session(manager):
    sessions = list(manager.get_sessions())
    for session in sessions:
        aumid = (session.source_app_user_model_id or "").lower()
        if "music" in aumid or "itunes" in aumid or "apple" in aumid:
            return session
    try:
        return manager.get_current_session()
    except Exception:
        return None


async def poll_loop():
    manager = await MediaManager.request_async()
    while True:
        try:
            session = pick_session(manager)
            if session is not None:
                info = await session.try_get_media_properties_async()
                timeline = session.get_timeline_properties()
                playback = session.get_playback_info()
                artwork = await read_thumbnail(info.thumbnail)

                with STATE_LOCK:
                    STATE["title"] = info.title or ""
                    STATE["artist"] = info.artist or ""
                    STATE["album"] = info.album_title or ""
                    STATE["artwork"] = artwork
                    STATE["position"] = timeline.position.total_seconds()
                    STATE["duration"] = timeline.end_time.total_seconds()
                    STATE["playing"] = playback.playback_status == PlaybackStatus.PLAYING
            else:
                with STATE_LOCK:
                    STATE["title"] = ""
                    STATE["playing"] = False
        except Exception as e:
            print(f"[poll error] {e}")
        await asyncio.sleep(POLL_SECONDS)


def start_poll_thread():
    def run():
        asyncio.run(poll_loop())

    t = threading.Thread(target=run, daemon=True)
    t.start()


OVERLAY_HTML = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  html, body {
    margin: 0; padding: 0; background: transparent;
    overflow: hidden;
  }
  #card {
    display: flex;
    align-items: center;
    gap: 14px;
    padding: 12px 18px;
    width: fit-content;
    opacity: 0;
    transform: translateY(8px);
    transition: opacity 0.4s ease, transform 0.4s ease,
      background-color 0.2s ease, border-radius 0.2s ease, max-width 0.2s ease;
  }
  #card.visible { opacity: 1; transform: translateY(0); }
  #art {
    width: 56px; height: 56px;
    border-radius: 8px;
    background: #333 center/cover no-repeat;
    flex-shrink: 0;
  }
  #text { min-width: 0; }
  #title {
    font-size: 16px; font-weight: 600;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
    transition: color 0.2s ease;
  }
  #artist {
    font-size: 13px; margin-top: 2px;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
    transition: color 0.2s ease;
  }
  #bar-bg {
    margin-top: 6px; width: 220px; height: 4px;
    background: rgba(255,255,255,0.2); border-radius: 2px; overflow: hidden;
  }
  #bar-fill {
    height: 100%; width: 0%;
    transition: width 0.9s linear, background-color 0.2s ease;
  }
</style>
</head>
<body>
  <div id="card">
    <div id="art"></div>
    <div id="text">
      <div id="title"></div>
      <div id="artist"></div>
      <div id="bar-bg"><div id="bar-fill"></div></div>
    </div>
  </div>

<script>
function hexToRgba(hex, alpha) {
  const h = hex.replace('#', '');
  const r = parseInt(h.substring(0, 2), 16);
  const g = parseInt(h.substring(2, 4), 16);
  const b = parseInt(h.substring(4, 6), 16);
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

function applyConfig(cfg) {
  const card = document.getElementById('card');
  card.style.backgroundColor = hexToRgba(cfg.bg_color, cfg.bg_opacity);
  card.style.borderRadius = cfg.corner_radius + 'px';
  card.style.maxWidth = cfg.card_max_width + 'px';
  card.style.fontFamily = cfg.font_family;
  document.getElementById('title').style.color = cfg.title_color;
  document.getElementById('artist').style.color = cfg.artist_color;
  document.getElementById('bar-fill').style.backgroundColor = cfg.accent_color;
  document.getElementById('art').style.display = cfg.show_artwork ? 'block' : 'none';
  document.getElementById('bar-bg').style.display = cfg.show_progress_bar ? 'block' : 'none';
}

async function fetchConfig() {
  try {
    const res = await fetch('/api/config', { cache: 'no-store' });
    applyConfig(await res.json());
  } catch (e) {
    // server not reachable yet; keep last applied config
  }
}

async function tick() {
  try {
    const res = await fetch('/api/now-playing', { cache: 'no-store' });
    const data = await res.json();
    const card = document.getElementById('card');

    if (!data.playing || !data.title) {
      card.classList.remove('visible');
      return;
    }

    document.getElementById('title').textContent = data.title;
    document.getElementById('artist').textContent = data.artist;
    document.getElementById('art').style.backgroundImage =
      data.artwork ? `url("${data.artwork}")` : 'none';

    const pct = data.duration > 0 ? Math.min(100, (data.position / data.duration) * 100) : 0;
    document.getElementById('bar-fill').style.width = pct + '%';

    card.classList.add('visible');
  } catch (e) {
    // server not reachable yet; keep last frame
  }
}

fetchConfig();
tick();
setInterval(tick, 1000);
setInterval(fetchConfig, 5000);
</script>
</body>
</html>
"""

SETTINGS_HTML = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Overlay Settings</title>
<style>
  body {
    margin: 0; padding: 24px;
    background: #1a1a1f; color: #eee;
    font-family: 'Segoe UI', Helvetica, Arial, sans-serif;
  }
  h1 { font-size: 20px; margin: 0 0 4px; }
  p.hint { color: #999; font-size: 13px; margin: 0 0 24px; }
  .layout { display: flex; gap: 32px; flex-wrap: wrap; align-items: flex-start; }
  form {
    display: grid; grid-template-columns: 160px 1fr; gap: 12px 16px;
    align-items: center; max-width: 480px; flex: 1 1 400px;
  }
  label { font-size: 13px; color: #ccc; }
  input[type="color"] { width: 48px; height: 32px; border: none; background: none; padding: 0; }
  input[type="number"], input[type="text"] {
    background: #26262e; border: 1px solid #3a3a44; color: #eee;
    border-radius: 6px; padding: 6px 8px; font-size: 13px; width: 100%; box-sizing: border-box;
  }
  input[type="range"] { width: 100%; }
  input[type="checkbox"] { width: 18px; height: 18px; }
  .actions { grid-column: 1 / -1; display: flex; gap: 10px; margin-top: 8px; }
  button {
    border: none; border-radius: 8px; padding: 10px 18px; font-size: 13px;
    cursor: pointer; font-weight: 600;
  }
  #save { background: #1ed760; color: #06210f; }
  #reset { background: #3a3a44; color: #eee; }
  #status { font-size: 12px; color: #1ed760; margin-left: 4px; align-self: center; }
  .preview-wrap {
    flex: 1 1 320px; position: sticky; top: 24px;
    background:
      linear-gradient(45deg, #2a2a30 25%, transparent 25%) -10px 0/ 20px 20px,
      linear-gradient(-45deg, #2a2a30 25%, transparent 25%) -10px 0/ 20px 20px,
      linear-gradient(45deg, transparent 75%, #2a2a30 75%) -10px 0/ 20px 20px,
      linear-gradient(-45deg, transparent 75%, #2a2a30 75%) -10px 0/ 20px 20px,
      #202026;
    border-radius: 10px; padding: 16px;
  }
  .preview-wrap p { font-size: 12px; color: #999; margin: 0 0 10px; }
  iframe { width: 100%; height: 160px; border: none; background: transparent; }
</style>
</head>
<body>
  <h1>Now Playing Overlay Settings</h1>
  <p class="hint">Changes save to overlay_config.json and apply to the OBS overlay automatically (no restart needed).</p>
  <div class="layout">
    <form id="cfg-form">
      <label for="bg_color">Background color</label>
      <input type="color" id="bg_color" name="bg_color">

      <label for="bg_opacity">Background opacity</label>
      <input type="range" id="bg_opacity" name="bg_opacity" min="0" max="1" step="0.05">

      <label for="accent_color">Progress bar color</label>
      <input type="color" id="accent_color" name="accent_color">

      <label for="title_color">Title text color</label>
      <input type="color" id="title_color" name="title_color">

      <label for="artist_color">Artist text color</label>
      <input type="color" id="artist_color" name="artist_color">

      <label for="font_family">Font family</label>
      <input type="text" id="font_family" name="font_family">

      <label for="corner_radius">Corner radius (px)</label>
      <input type="number" id="corner_radius" name="corner_radius" min="0" max="60">

      <label for="card_max_width">Max width (px)</label>
      <input type="number" id="card_max_width" name="card_max_width" min="200" max="1000">

      <label for="show_artwork">Show album art</label>
      <input type="checkbox" id="show_artwork" name="show_artwork">

      <label for="show_progress_bar">Show progress bar</label>
      <input type="checkbox" id="show_progress_bar" name="show_progress_bar">

      <div class="actions">
        <button type="submit" id="save">Save</button>
        <button type="button" id="reset">Reset to defaults</button>
        <span id="status"></span>
      </div>
    </form>

    <div class="preview-wrap">
      <p>Live preview (reflects your current track if Apple Music is playing)</p>
      <iframe id="preview" src="/overlay.html"></iframe>
    </div>
  </div>

<script>
const form = document.getElementById('cfg-form');
const status = document.getElementById('status');
const preview = document.getElementById('preview');

function fill(cfg) {
  form.bg_color.value = cfg.bg_color;
  form.bg_opacity.value = cfg.bg_opacity;
  form.accent_color.value = cfg.accent_color;
  form.title_color.value = cfg.title_color;
  form.artist_color.value = cfg.artist_color;
  form.font_family.value = cfg.font_family;
  form.corner_radius.value = cfg.corner_radius;
  form.card_max_width.value = cfg.card_max_width;
  form.show_artwork.checked = cfg.show_artwork;
  form.show_progress_bar.checked = cfg.show_progress_bar;
}

function readForm() {
  return {
    bg_color: form.bg_color.value,
    bg_opacity: parseFloat(form.bg_opacity.value),
    accent_color: form.accent_color.value,
    title_color: form.title_color.value,
    artist_color: form.artist_color.value,
    font_family: form.font_family.value,
    corner_radius: parseInt(form.corner_radius.value, 10),
    card_max_width: parseInt(form.card_max_width.value, 10),
    show_artwork: form.show_artwork.checked,
    show_progress_bar: form.show_progress_bar.checked,
  };
}

async function loadConfig() {
  const res = await fetch('/api/config', { cache: 'no-store' });
  fill(await res.json());
}

async function saveConfig(cfg) {
  await fetch('/api/config', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(cfg),
  });
  status.textContent = 'Saved';
  preview.src = preview.src;
  setTimeout(() => { status.textContent = ''; }, 1500);
}

form.addEventListener('submit', (e) => {
  e.preventDefault();
  saveConfig(readForm());
});

document.getElementById('reset').addEventListener('click', async () => {
  const res = await fetch('/api/config/reset', { method: 'POST' });
  fill(await res.json());
  status.textContent = 'Reset to defaults';
  preview.src = preview.src;
  setTimeout(() => { status.textContent = ''; }, 1500);
});

loadConfig();
</script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # silence default request logging

    def _send_json(self, obj, status=200):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, html, status=200):
        body = html.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path in ("/", "/overlay.html"):
            self._send_html(OVERLAY_HTML)
        elif self.path == "/settings":
            self._send_html(SETTINGS_HTML)
        elif self.path == "/api/now-playing":
            with STATE_LOCK:
                self._send_json(dict(STATE))
        elif self.path == "/api/config":
            with CONFIG_LOCK:
                self._send_json(dict(CONFIG))
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path == "/api/config":
            length = int(self.headers.get("Content-Length", 0))
            try:
                incoming = json.loads(self.rfile.read(length) or b"{}")
                with CONFIG_LOCK:
                    for key in DEFAULT_CONFIG:
                        if key in incoming:
                            CONFIG[key] = incoming[key]
                    save_config(CONFIG)
                    result = dict(CONFIG)
                self._send_json(result)
            except Exception as e:
                self._send_json({"error": str(e)}, status=400)
        elif self.path == "/api/config/reset":
            with CONFIG_LOCK:
                CONFIG.clear()
                CONFIG.update(DEFAULT_CONFIG)
                save_config(CONFIG)
                result = dict(CONFIG)
            self._send_json(result)
        else:
            self.send_response(404)
            self.end_headers()


def main():
    start_poll_thread()
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Overlay running at http://{HOST}:{PORT}/overlay.html")
    print(f"Customize it at   http://{HOST}:{PORT}/settings")
    print("Add the overlay URL as an OBS Browser Source. Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
