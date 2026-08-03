#!/usr/bin/env python3
"""master-gesture.py — track-skip gestures on the MASTER (default sink) volume.

Meant for a master volume driven by a ROTARY encoder (not a deej slider). Because
that same rotary is used for normal volume, the gesture is a deliberate REVERSAL
("bump") that never happens while steadily turning:

    quickly turn DOWN then back up, twice  -> Previous track
    quickly turn UP then back down, twice   -> Next track

Each down-then-back is a "valley", each up-then-back a "peak"; two of the same
kind within DOUBLE_WINDOW fires the action over MPRIS (gdbus) to the active
player. Steadily turning the knob one way only (normal volume change) produces no
reversal, so it never mis-fires.

Stdlib only (pactl + gdbus), companion to pause-watcher.py. Being stopped is its
off switch — nothing happens unless master-gesture.service is running.
"""
import subprocess
import sys
import re
import time

# --- tuning (all seconds / 0-1 volume fractions) ---
JOG_DELTA = 0.03      # min depth of one down/up leg to count (a rotary click ~ few %)
JOG_WINDOW = 0.35     # each leg (the down, or the back-up) must complete this fast
DOUBLE_WINDOW = 1.2   # the two bumps must land within this
COOLDOWN = 0.8        # ignore input after firing
MEMORY = 1.5          # forget turning points older than this
IDLE_RESET = 0.6      # a gap longer than this drops any in-progress bump
MIN_CHANGE = 0.004    # ignore volume jitter smaller than this


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


class JogDetector:
    def __init__(self):
        self.have = False
        self.last_v = 0.0
        self.last_t = 0.0
        self.dir = 0            # current leg direction: +1 up, -1 down, 0 none
        self.piv_v = 0.0
        self.piv_t = 0.0
        self.points = []        # list of (kind, t): kind -1 valley, +1 peak
        self.fired_t = 0.0

    def feed(self, v, t):
        if not self.have:
            self.have, self.last_v, self.last_t = True, v, t
            self.piv_v, self.piv_t = v, t
            return

        # a long gap means whatever motion was in progress is abandoned
        if t - self.last_t > IDLE_RESET:
            self.last_v, self.last_t = v, t
            self.dir = 0
            self.piv_v, self.piv_t = v, t
            return

        delta = v - self.last_v
        if abs(delta) < MIN_CHANGE:
            self.last_v = v
            return

        inst = -1 if delta < 0 else 1
        if self.dir == 0:
            self.piv_v, self.piv_t = self.last_v, self.last_t
            self.dir = inst
        elif inst != self.dir:
            leg_amp = abs(self.last_v - self.piv_v)
            leg_dur = self.last_t - self.piv_t
            if leg_amp >= JOG_DELTA and leg_dur <= JOG_WINDOW:
                self._register(self.dir, self.last_t)  # dir -1 leg -> valley, +1 -> peak
            self.piv_v, self.piv_t = self.last_v, self.last_t
            self.dir = inst

        self.last_v, self.last_t = v, t

    def _register(self, kind, t):
        self.points = [p for p in self.points if p[1] > t - MEMORY]
        self.points.append((kind, t))
        if t - self.fired_t < COOLDOWN:
            return
        valleys = sum(1 for k, pt in self.points if k < 0 and t - pt <= DOUBLE_WINDOW)
        peaks = sum(1 for k, pt in self.points if k > 0 and t - pt <= DOUBLE_WINDOW)
        if valleys >= 2:
            fire(-1)
            self.fired_t, self.points = t, []
        elif peaks >= 2:
            fire(+1)
            self.fired_t, self.points = t, []


def main():
    det = JogDetector()
    v0 = master_volume()
    if v0 is not None:
        det.feed(v0, time.time())
    proc = subprocess.Popen(["pactl", "subscribe"], stdout=subprocess.PIPE, text=True)
    log("watching master volume (rotary): down-bump x2 = Previous, up-bump x2 = Next")
    for line in proc.stdout:
        if "on sink " not in line and "on server" not in line:
            continue
        v = master_volume()
        if v is not None:
            det.feed(v, time.time())


if __name__ == "__main__":
    main()
