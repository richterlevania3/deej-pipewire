#!/bin/bash
# Live raw-slider monitor. Stops deej to read the serial, shows all 5 values live,
# restarts deej on exit. Wiggle ONE physical slider at a time and see which column
# (idx0..idx4) moves -> that's its deej index.
cleanup(){ systemctl --user start deej.service >/dev/null 2>&1; echo; echo "[deej restarted]"; }
trap cleanup EXIT INT TERM
systemctl --user stop deej.service; sleep 0.5
stty -F /dev/ttyUSB0 9600 raw -echo 2>/dev/null
echo "Columns:  idx0 | idx1 | idx2 | idx3 | idx4"
echo "Move ONE fader at a time; note which column changes. Ctrl-C when done."
echo
stdbuf -oL cat /dev/ttyUSB0 | while IFS= read -r l; do printf '\r  %-45s' "$l"; done
