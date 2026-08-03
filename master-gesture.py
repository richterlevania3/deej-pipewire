#!/usr/bin/env python3
"""master-gesture.py — track-skip gestures on the MASTER (default sink) volume.

Two quick volume-DOWN steps in a row -> Previous track; two quick UP steps ->
Next track. Meant for a master volume driven by a hardware knob / keyboard
decoder (not a deej slider). Fires MPRIS Next/Previous via gdbus to the active
player. Stdlib only (pactl + gdbus), companion to pause-watcher.py.

Being stopped is its off switch: it does nothing unless the systemd user service
master-gesture.service is running.

Caveat: master volume doubles as your normal listening control, so a fast normal
volume change can look like a gesture. STEP_WINDOW is deliberately tight and a
COOLDOWN prevents repeats; tune below if it mis-fires. A reversal-based variant
(down-then-back "bump") is possible if same-direction proves too twitchy.
"""
import subprocess
import sys
import re
import time

# --- tuning ---
STEP_WINDOW = 0.45   # max seconds between the two steps to count as a gesture
COOLDOWN = 0.9       # seconds to ignore input after firing
MIN_STEP = 0.01      # ignore volume changes smaller than this (fraction 0-1)


def log(*a):
    print("[master-gesture]", *a, file=sys.stderr, flush=True)


def master_volume():
    r = subprocess.run(["pactl", "get-sink-volume", "@DEFAULT_SINK@"],
                       capture_output=True, text=True)
    m = re.search(r"(\d+)%", r.stdout)
    return int(m.group(1)) / 100.0 if m else None


def mpris_players():
    r = subprocess.run(["gdbus", "call", "--session", "--dest", "org.freedesktop.DBus",
                        "--object-path", "/org/freedesktop/DBus",
                        "--method", "org.freedesktop.DBus.ListNames"],
                       capture_output=True, text=True)
    return [t.strip(" []()'\n\t\r") for t in r.stdout.split(",")
            if "org.mpris.MediaPlayer2." in t]


def is_playing(bus):
    r = subprocess.run(["gdbus", "call", "--session", "--dest", bus,
                        "--object-path", "/org/mpris/MediaPlayer2", "--method",
                        "org.freedesktop.DBus.Properties.Get",
                        "org.mpris.MediaPlayer2.Player", "PlaybackStatus"],
                       capture_output=True, text=True)
    return "Playing" in r.stdout


def pick_player():
    players = mpris_players()
    if not players:
        return None
    for p in players:              # prefer whatever is actually playing
        if is_playing(p):
            return p
    for p in players:              # then Tidal/High Tide
        if "high-tide" in p:
            return p
    return players[0]


def fire(direction):  # -1 = previous, +1 = next
    method = "Previous" if direction < 0 else "Next"
    bus = pick_player()
    if not bus:
        log("no MPRIS player for", method)
        return
    subprocess.run(["gdbus", "call", "--session", "--dest", bus,
                    "--object-path", "/org/mpris/MediaPlayer2", "--method",
                    "org.mpris.MediaPlayer2.Player." + method],
                   capture_output=True, text=True)
    log("fired", method, "->", bus)


def main():
    last_vol = master_volume()
    last_t = time.time()
    streak_dir = 0
    streak_count = 0
    last_fire = 0.0

    proc = subprocess.Popen(["pactl", "subscribe"], stdout=subprocess.PIPE, text=True)
    log("watching master volume; two quick downs=Previous, two quick ups=Next")

    for line in proc.stdout:
        if "on sink " not in line and "on server" not in line:
            continue
        v = master_volume()
        if v is None:
            continue
        t = time.time()
        if last_vol is None:
            last_vol, last_t = v, t
            continue

        dv = v - last_vol
        if abs(dv) < MIN_STEP:
            last_vol = v
            continue

        d = -1 if dv < 0 else 1
        dt = t - last_t
        if d == streak_dir and dt <= STEP_WINDOW:
            streak_count += 1
        else:
            streak_dir, streak_count = d, 1

        if streak_count >= 2 and (t - last_fire) > COOLDOWN:
            fire(d)
            last_fire = t
            streak_dir, streak_count = 0, 0

        last_vol, last_t = v, t


if __name__ == "__main__":
    main()
