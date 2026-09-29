import asyncio
import glob
import logging
import os
import shutil
import time

from .util import run, spawn

log = logging.getLogger("aleph.power")


class Backlight:
    MIN_PERCENT = 3

    def __init__(self, root="/sys/class/backlight"):
        self.path = None
        self.max = 1
        for dev in sorted(glob.glob(os.path.join(root, "*"))):
            try:
                with open(os.path.join(dev, "max_brightness")) as f:
                    self.max = max(1, int(f.read()))
                self.path = os.path.join(dev, "brightness")
                break
            except (OSError, ValueError):
                continue

    def set_percent(self, percent):
        if not self.path:
            return
        percent = max(0, min(100, percent))
        value = 0 if percent == 0 else max(1, round(self.max * max(percent, self.MIN_PERCENT) / 100))
        try:
            with open(self.path, "w") as f:
                f.write(str(value))
        except OSError as e:
            log.warning("backlight: %s", e)


class Inhibitor:
    """Holds a logind inhibitor lock for as long as a `systemd-inhibit` child is alive."""

    def __init__(self, what, why):
        self.what = what
        self.why = why
        self.proc = None

    async def hold(self):
        if self.proc or not shutil.which("systemd-inhibit"):
            return
        self.proc = await asyncio.create_subprocess_exec(
            "systemd-inhibit", f"--what={self.what}", "--who=aleph", f"--why={self.why}",
            "--mode=block", "sleep", "infinity",
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)

    async def release(self):
        if self.proc:
            self.proc.terminate()
            await self.proc.wait()
            self.proc = None


class Power:
    LONG_PRESS = 1.2
    LID_SLEEP = 30

    def __init__(self, state, settings, events, sim=False):
        self.state = state
        self.settings = settings
        self.events = events
        self.sim = sim
        self.backlight = Backlight()
        self.power_key_lock = Inhibitor("handle-power-key", "aleph handles the power button")
        self.lid_lock = Inhibitor("handle-lid-switch", "aleph decides what closing the lid does")
        self.lid_closed = False
        self.last_activity = time.monotonic()
        self.screen_off_at = None
        self.stopped_at = 0.0
        self._power_down_at = None
        self._long_press = None
        self._poke = asyncio.Event()

    async def start(self):
        if not self.sim:
            await self.power_key_lock.hold()
            await self.lid_lock.hold()
        self.apply_brightness()
        spawn(self._idle_loop())

    @property
    def screen_on(self):
        return self.state.get("screen")["on"]

    def playing(self):
        return self.state.get("player")["state"] == "play"

    def apply_brightness(self):
        if self.screen_on:
            self.backlight.set_percent(self.settings["brightness"])

    async def set_screen(self, on):
        if on == self.screen_on:
            return
        self.state.update("screen", on=on)
        self.screen_off_at = None if on else time.monotonic()
        if not self.sim:
            await run("swaymsg", "output", "*", "power", "on" if on else "off")
        self.backlight.set_percent(self.settings["brightness"] if on else 0)
        if on:
            self.last_activity = time.monotonic()
        self.poke()

    def activity(self):
        self.last_activity = time.monotonic()
        self.poke()

    async def wake(self):
        """Any key while the screen is dark only turns it back on."""
        self.activity()
        if not self.screen_on and not self.lid_closed:
            await self.set_screen(True)
            return True
        return False

    async def playback_changed(self):
        if not self.playing():
            self.stopped_at = time.monotonic()
        self.poke()

    async def lid(self, closed):
        self.lid_closed = closed
        if closed:
            await self.set_screen(False)
            if not (self.playing() and self.settings["lid_keep_playing"]):
                await self.sleep()
        else:
            await self.set_screen(True)

    async def power_key(self, pressed):
        if pressed:
            self._power_down_at = time.monotonic()
            self._long_press = asyncio.get_running_loop().call_later(
                self.LONG_PRESS, self.events.power_menu)
            return
        if self._long_press:
            self._long_press.cancel()
            self._long_press = None
        held = time.monotonic() - (self._power_down_at or time.monotonic())
        self._power_down_at = None
        if held >= self.LONG_PRESS:
            return
        if self.screen_on:
            await self.set_screen(False)
        else:
            await self.set_screen(True)

    def poke(self):
        self._poke.set()

    def _screen_deadline(self):
        if self.screen_on and self.settings["screen_timeout"]:
            return self.last_activity + self.settings["screen_timeout"]
        return None

    def _sleep_deadline(self):
        """Dark and silent: sleep soon with the lid shut, later with it open."""
        if self.screen_on or self.playing() or not self.screen_off_at:
            return None
        wait = self.LID_SLEEP if self.lid_closed else self.settings["sleep_timeout"]
        return max(self.screen_off_at, self.stopped_at) + wait

    async def _idle_loop(self):
        while True:
            deadlines = [d for d in (self._screen_deadline(), self._sleep_deadline()) if d is not None]
            timeout = max(0.05, min(deadlines) - time.monotonic()) if deadlines else None
            try:
                await asyncio.wait_for(self._poke.wait(), timeout)
                self._poke.clear()
                continue
            except asyncio.TimeoutError:
                pass
            now = time.monotonic()
            screen, sleep = self._screen_deadline(), self._sleep_deadline()
            if screen is not None and now >= screen:
                await self.set_screen(False)
            elif sleep is not None and now >= sleep:
                await self.sleep()

    async def sleep(self):
        self.events.before_sleep()
        # Dark before we go, so the button that wakes us turns the screen back on; the
        # countdown restarts so a wake that nobody follows up sleeps again later.
        await self.set_screen(False)
        self.screen_off_at = time.monotonic()
        if self.sim:
            log.info("sim: suspend")
            return
        await run("systemctl", "suspend")

    async def restart(self):
        if not self.sim:
            await run("systemctl", "reboot")

    async def shut_down(self):
        if not self.sim:
            await run("systemctl", "poweroff")
