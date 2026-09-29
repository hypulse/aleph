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

    def __init__(self, state, settings, events, sim=False):
        self.state = state
        self.settings = settings
        self.events = events
        self.sim = sim
        self.backlight = Backlight()
        self.power_key_lock = Inhibitor("handle-power-key", "aleph handles the power button")
        self.lid_lock = Inhibitor("handle-lid-switch", "music keeps playing with the lid closed")
        self.lid_closed = False
        self.last_activity = time.monotonic()
        self.screen_off_at = None
        self._power_down_at = None
        self._long_press = None
        self._poke = asyncio.Event()

    async def start(self):
        if not self.sim:
            await self.power_key_lock.hold()
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
        self.poke()
        if self.playing() and self.settings["lid_keep_playing"]:
            await self.lid_lock.hold()
        else:
            await self.lid_lock.release()

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

    def _next_deadline(self):
        deadlines = []
        if self.screen_on and self.settings["screen_timeout"]:
            deadlines.append(self.last_activity + self.settings["screen_timeout"])
        if not self.screen_on and not self.playing() and self.screen_off_at:
            deadlines.append(self.screen_off_at + self.settings["sleep_timeout"])
        return min(deadlines) if deadlines else None

    async def _idle_loop(self):
        while True:
            deadline = self._next_deadline()
            timeout = None if deadline is None else max(0.05, deadline - time.monotonic())
            try:
                await asyncio.wait_for(self._poke.wait(), timeout)
                self._poke.clear()
                continue
            except asyncio.TimeoutError:
                pass
            now = time.monotonic()
            if (self.screen_on and self.settings["screen_timeout"]
                    and now - self.last_activity >= self.settings["screen_timeout"]):
                await self.set_screen(False)
            elif (not self.screen_on and not self.playing() and self.screen_off_at
                    and now - self.screen_off_at >= self.settings["sleep_timeout"]):
                self.screen_off_at = None
                await self.sleep()

    async def sleep(self):
        self.events.before_sleep()
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
