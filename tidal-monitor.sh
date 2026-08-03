#!/bin/bash
# Live Tidal volume + deej's volume writes. deej keeps running. Ctrl-C to stop.
echo "Reproduce the Tidal jump now (move sliders as usual). Ctrl-C when done."
echo "-------------------------------------------------------------"
journalctl --user -u deej.service -f -n0 --no-pager 2>/dev/null \
  | grep --line-buffered -E "Adjusting session volume|Failed to set" \
  | sed -u -E 's/.*deej\.sessions\.([a-zA-Z0-9._]+).*(to.: .[0-9.]+.).*/          [deej writes] \1 = \2/' &
JPID=$!
trap 'kill $JPID 2>/dev/null; echo; exit 0' INT TERM EXIT
while true; do
  v=$(pactl list sink-inputs 2>/dev/null | awk '/^Sink Input #/{i=$3} /^[[:space:]]*Volume:/{for(x=1;x<=NF;x++) if($x~/%$/){vv=$x;break}} /application.process.binary = "python3.13"/{print vv; exit}')
  printf '%s  Tidal = %s\n' "$(date +%H:%M:%S)" "${v:-(no stream)}"
  sleep 0.3
done
