#!/usr/bin/python3
"""Pause-on-mute companion for deej (or any volume source).

Watches PipeWire sink-input volumes via `pactl subscribe`. When a stream's
volume drops to ~0, finds the owning app's MPRIS player and pauses it; when
the volume comes back up, resumes it — but only if we were the ones who
paused it. Apps without MPRIS (games etc.) are silently ignored.

Generic by design: it matches any audio stream to any MPRIS player, so it
works with High Tide, Firefox, Stremio, mpv, VLC, Spotify, etc. — and with any
volume source, not just deej (the GNOME volume menu and media keys trigger it
too). Stdlib only: shells out to `pactl` and `gdbus`, no Python dependencies.

Part of this deej fork. Licensed under the MIT License (see LICENSE).
"""

import json
import re
import select
import subprocess
import sys
import time

PAUSE_BELOW = 0.005   # consider "at zero" below 0.5%
RESUME_ABOVE = 0.02   # hysteresis: resume only above 2% (pot jitter guard)
MIN_SCAN_GAP = 0.04   # act at most every 40ms during a burst (responsive, cheap)

# sink-input index -> mpris bus name we paused
paused_by_us = {}


def log(*args):
    print(*args, flush=True)


def gdbus_call(dest, method, *args):
    cmd = ["gdbus", "call", "--session", "--dest", dest,
           "--object-path", "/org/mpris/MediaPlayer2", "--method", method] + list(args)
    return subprocess.run(cmd, capture_output=True, text=True, timeout=5)


_player_cache = {"at": 0.0, "players": {}}
PLAYER_TTL = 2.0  # gdbus player enumeration is slow; cache it briefly


def mpris_players(force=False):
    """Return {bus_name: identity_lowercase} for all MPRIS players (cached)."""
    now = time.monotonic()
    if not force and now - _player_cache["at"] < PLAYER_TTL:
        return _player_cache["players"]
    r = subprocess.run(
        ["gdbus", "call", "--session", "--dest", "org.freedesktop.DBus",
         "--object-path", "/org/freedesktop/DBus",
         "--method", "org.freedesktop.DBus.ListNames"],
        capture_output=True, text=True, timeout=5)
    players = {}
    for name in re.findall(r"'(org\.mpris\.MediaPlayer2\.[^']+)'", r.stdout):
        identity = ""
        p = gdbus_call(name, "org.freedesktop.DBus.Properties.Get",
                       "org.mpris.MediaPlayer2", "Identity")
        m = re.search(r"<'(.*)'>", p.stdout)
        if m:
            identity = m.group(1).lower()
        players[name] = identity
    _player_cache["at"] = now
    _player_cache["players"] = players
    return players


# Some clients don't expose a name/binary that matches their MPRIS bus. Map a
# stream identifier (e.g. node.name) to a hint that appears in the bus/Identity.
# High Tide (Tidal) on some audio backends registers only node.name=python3.13.
STREAM_ALIASES = {"python3.13": "high-tide"}


def match_player(ids, players):
    """Best-effort match of a sink-input to an MPRIS bus name.
    ids: list of identifier strings (application.name, process.binary, node.name, media.name)."""
    candidates = []
    for c in ids:
        if not c:
            continue
        c = c.lower()
        candidates.append(c)
        if c in STREAM_ALIASES:
            candidates.append(STREAM_ALIASES[c])
    for busname, identity in players.items():
        suffix = busname[len("org.mpris.MediaPlayer2."):].lower()
        for c in candidates:
            if c in suffix or suffix.startswith(c) or (identity and (c in identity or identity in c)):
                return busname
    return None


def playback_status(busname):
    p = gdbus_call(busname, "org.freedesktop.DBus.Properties.Get",
                   "org.mpris.MediaPlayer2.Player", "PlaybackStatus")
    m = re.search(r"<'(.*)'>", p.stdout)
    return m.group(1) if m else None


def sink_inputs():
    r = subprocess.run(["pactl", "-f", "json", "list", "sink-inputs"],
                       capture_output=True, text=True, timeout=5)
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return []


def stream_volume(si):
    vols = si.get("volume", {})
    vals = [ch.get("value", 0) for ch in vols.values() if isinstance(ch, dict)]
    return max(vals) / 65536 if vals else None


def scan():
    """Reconcile all current sink-inputs against pause state."""
    players = None  # lazy: only list players if something crossed a threshold
    seen = set()
    for si in sink_inputs():
        idx = si.get("index")
        seen.add(idx)
        vol = stream_volume(si)
        if vol is None:
            continue
        props = si.get("properties", {})
        app = props.get("application.name", "")
        binary = props.get("application.process.binary", "")
        ids = [app, binary, props.get("node.name", ""), props.get("media.name", "")]

        if vol < PAUSE_BELOW and idx not in paused_by_us:
            if players is None:
                players = mpris_players()
            busname = match_player(ids, players)
            if not busname:
                # cache may be stale (player just launched) — force one refresh
                players = mpris_players(force=True)
                busname = match_player(ids, players)
            if not busname:
                continue
            if playback_status(busname) == "Playing":
                gdbus_call(busname, "org.mpris.MediaPlayer2.Player.Pause")
                paused_by_us[idx] = busname
                log(f"paused {app or binary or ids[2] or 'stream'} ({busname}), stream #{idx} at 0")

        elif vol > RESUME_ABOVE and idx in paused_by_us:
            busname = paused_by_us.pop(idx)
            if playback_status(busname) == "Paused":
                gdbus_call(busname, "org.mpris.MediaPlayer2.Player.Play")
                log(f"resumed {app or binary or ids[2] or 'stream'} ({busname}), stream #{idx} back up")

    # forget streams that vanished (app closed while paused)
    for idx in [i for i in paused_by_us if i not in seen]:
        del paused_by_us[idx]


def main():
    log("pause-watcher started")
    scan()
    proc = subprocess.Popen(["pactl", "subscribe"], stdout=subprocess.PIPE,
                            text=True, bufsize=1)
    last_scan = 0.0
    pending = False

    def do_scan():
        nonlocal last_scan, pending
        pending = False
        last_scan = time.monotonic()
        try:
            scan()
        except Exception as e:
            log("scan error:", e)

    while True:
        # if a scan is pending, wake up when the 40ms window elapses even if
        # events keep streaming — so we act mid-slide, not only after it stops
        timeout = MIN_SCAN_GAP if pending else None
        ready, _, _ = select.select([proc.stdout], [], [], timeout)
        if ready:
            line = proc.stdout.readline()
            if not line:
                break
            if "sink-input" not in line:
                continue
            if time.monotonic() - last_scan >= MIN_SCAN_GAP:
                do_scan()      # act immediately, throttled to 40ms
            else:
                pending = True  # too soon; a scan is due when the window elapses
        else:
            do_scan()          # burst settled or 40ms window elapsed
    sys.exit(proc.wait())


if __name__ == "__main__":
    main()
