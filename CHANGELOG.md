# Changelog — Linux/PipeWire desktop build

This fork builds on [bagel88/deej-pipewire](https://github.com/bagel88/deej-pipewire)
(itself a fork of [omriharel/deej](https://github.com/omriharel/deej)) and adds a
handful of Linux-desktop quality-of-life changes plus a companion daemon.

## Added

### `pause-watcher.py` — pause media when a slider hits zero
A small stdlib-only companion daemon (`pactl` + `gdbus`, no dependencies). When
any application's audio stream drops to ~0%, it pauses that app via its MPRIS
media-control interface; when the volume comes back up, it resumes it. It only
ever auto-resumes what it itself paused, so manual pauses are respected, and
apps without MPRIS (games, etc.) are left alone. Works with any volume source —
deej sliders, the desktop volume menu, or media keys.

- Hysteresis (pause below 0.5%, resume above 2%) so pot jitter can't flap it.
- Acts mid-slide at a ~40 ms cadence and caches MPRIS player lookups, so
  pause/resume fires in ~70 ms rather than after the slider stops moving.

### `volume_curve` config option — perceptually-even fader taper
PulseAudio's raw volume field is cubic in amplitude, so a linear fader spends
most of its travel nearly silent. `volume_curve` pre-shapes the slider value
(`raw = position ^ curve`) so travel maps to roughly even perceived loudness.
`1.0` restores stock behaviour; the default `0.6` gives an even taper.

### `noise_reduction: fine` — 1% fader granularity
A new noise-reduction level with a 0.5% threshold (below one 1% step), so every
1% of movement registers. The bundled Arduino sketch oversamples each slider
16× to suppress ADC/pot jitter, so the finer gate doesn't pass electrical noise.

### Event-driven volume re-assert on new streams
deej now subscribes to PulseAudio sink-input events and re-applies the mapped
slider volume the instant a **new** stream appears, instead of waiting for the
next poll. This fixes apps that spawn a fresh audio stream at their own default
volume on certain actions (e.g. Firefox recreating its stream on tab focus /
audio restart) — previously the volume stayed wrong until the next poll or a
manual slider nudge. Only *new*-stream events are acted on (change/remove are
ignored) so deej's own volume writes don't feed back into a loop; bursts are
coalesced over 120 ms.

Companion fix: `GetVolume()` now inverts the `volume_curve` taper so volumes read
back in the same space they're set in. Without this the change-detection
comparison never matched the (curved) stored value, so deej re-wrote every
session on every cycle and couldn't distinguish a real external change from its
own output.

### Track-skip slider gestures
Jog a slider down-and-back twice quickly to go to the previous track, up-and-back
twice for the next — on top of the existing pause-at-0. A "jog" is a fast move of
at least `gestureJogDelta` that reverses within `gestureJogWindow` (a valley for
down, a peak for up); two of the same kind within `gestureDoubleWindow` fire
`Previous`/`Next` over MPRIS via `gdbus`. Config: `track_gestures_enabled`
(default false), `track_gesture_slider` (default 2), `track_gesture_player` (MPRIS
bus-name substring, default `high-tide`). Disabled by default — fires nothing
until enabled.

### Headless operation
The system-tray integration is stubbed out so the daemon builds and runs with no
GTK/AppIndicator dependencies. Stop it with Ctrl+C or `SIGTERM` (or run it under
the bundled systemd user services in `contrib/systemd/`).

### Packaging
- `contrib/systemd/deej.service` and `deej-pause-watcher.service` — systemd user
  services for the daemon and the pause-watcher.
- `config.yaml.example` — documents all of the options above.

## Notes
Endpoint calibration was intentionally **not** added: on hardware where the
potentiometers electrically saturate (read 0 / 1023) before their mechanical
ends, no software remap can recover the lost travel — that's a mechanical trait
of the pot, not a configuration issue.
