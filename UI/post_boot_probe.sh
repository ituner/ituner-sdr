#!/bin/sh
LOG=/home/ituner/codex-sdr-display/post-boot-thermal.log
sleep 30
{
  echo "--- $(date -Is) ---"
  echo "service=$(systemctl is-active kiwi-gl-display.service 2>/dev/null || true)"
  if command -v vcgencmd >/dev/null 2>&1; then vcgencmd measure_temp; fi
  pid=$(pgrep -f "^/usr/bin/python3 /home/ituner/codex-sdr-display/tools/kiwi_gl_display.py" | head -1)
  if [ -n "$pid" ]; then
    ps -p "$pid" -o pid,time,etime,pcpu,pmem,rss,args
  else
    echo "no kiwi_gl_display pid"
  fi
} >> "$LOG" 2>&1
