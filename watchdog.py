"""Exit code 10 = 'today's Short is still not built although the morning window has started' -> publish.yml
triggers an emergency build (publish ~25 min later). Anything else = fine."""
import sys
import scheduler

h = scheduler.now_ist().hour
if 9 <= h <= 12 and not scheduler.already_built("short"):
    print("[watchdog] today's short missing in the morning window")
    sys.exit(10)
print("[watchdog] ok")
