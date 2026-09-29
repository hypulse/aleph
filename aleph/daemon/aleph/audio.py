import asyncio
import json
import logging

from .util import run, spawn

log = logging.getLogger("aleph.audio")


class Pactl:
    """Volume and sinks through pipewire-pulse, the path ROCKNIX's own volume script uses."""

    def __init__(self):
        self.listener = lambda: None
        self.sinks = []
        self.default = None

    async def start(self, listener):
        self.listener = listener
        await self.refresh()
        spawn(self._monitor())

    async def _monitor(self):
        while True:
            try:
                proc = await asyncio.create_subprocess_exec(
                    "pactl", "subscribe", stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL)
            except OSError:
                return
            pending = None
            while line := await proc.stdout.readline():
                if b"sink" in line or b"server" in line:
                    if pending is None or pending.done():
                        pending = spawn(self._debounced())
            await proc.wait()
            await asyncio.sleep(1)

    async def _debounced(self):
        await asyncio.sleep(0.05)
        await self.refresh()

    async def refresh(self):
        code, out, _ = await run("pactl", "-f", "json", "list", "sinks")
        try:
            sinks = json.loads(out) if code == 0 else []
        except ValueError:
            sinks = []
        _, default, _ = await run("pactl", "get-default-sink")
        self.default = default.strip() or None
        self.sinks = [_sink(s) for s in sinks]
        self.listener()

    def current(self):
        return next((s for s in self.sinks if s["name"] == self.default), None)

    async def set_volume(self, sink, percent):
        await run("pactl", "set-sink-volume", sink, f"{percent}%")
        await self.refresh()

    async def set_mute(self, sink, on):
        await run("pactl", "set-sink-mute", sink, "1" if on else "0")


def _sink(raw):
    props = raw.get("properties", {})
    levels = [int(str(ch.get("value_percent", "0")).rstrip("%") or 0)
              for ch in (raw.get("volume") or {}).values()]
    api = props.get("device.api", "")
    port = (raw.get("active_port") or "").lower()
    if api == "bluez5":
        kind = "bluetooth"
    elif "headphone" in port:
        kind = "headphones"
    elif "hdmi" in raw.get("name", "").lower():
        kind = "hdmi"
    else:
        kind = "speaker"
    return {"name": raw.get("name", ""), "description": raw.get("description", ""),
            "level": max(levels) if levels else 0, "muted": bool(raw.get("mute")), "kind": kind}


class FakeAudio:
    def __init__(self):
        self.listener = lambda: None
        self.sinks = [{"name": "alsa_output.speaker", "description": "Speaker", "level": 40,
                       "muted": False, "kind": "speaker"}]
        self.default = "alsa_output.speaker"

    async def start(self, listener):
        self.listener = listener
        listener()

    def current(self):
        return next((s for s in self.sinks if s["name"] == self.default), None)

    async def set_volume(self, sink, percent):
        for s in self.sinks:
            if s["name"] == sink:
                s["level"] = percent
        self.listener()

    async def set_mute(self, sink, on):
        for s in self.sinks:
            if s["name"] == sink:
                s["muted"] = on

    def add_bluetooth(self, name):
        self.sinks.append({"name": "bluez_output.fake", "description": name, "level": 50,
                           "muted": False, "kind": "bluetooth"})
        self.default = "bluez_output.fake"
        self.listener()

    def remove_bluetooth(self):
        self.sinks = [s for s in self.sinks if s["kind"] != "bluetooth"]
        self.default = "alsa_output.speaker"
        self.listener()


class Audio:
    STEP = 5

    def __init__(self, backend, state, settings, remember=None):
        self.backend = backend
        self.state = state
        self.settings = settings
        self.remember = remember
        self.parked = set()
        self._save = None

    async def start(self):
        await self.backend.start(self._publish)
        await self.clamp_to_limit()

    def _publish(self):
        sink = self.backend.current()
        if sink:
            self.state.update("volume", level=sink["level"], muted=sink["muted"],
                              output=sink["kind"], name=sink["description"])

    async def change(self, delta):
        sink = self.backend.current()
        if not sink:
            return None
        limit = self.settings["volume_limit"]
        level = max(0, min(limit, sink["level"] + delta))
        if level != sink["level"]:
            await self.backend.set_volume(sink["name"], level)
            if sink["kind"] in ("speaker", "headphones") and self.remember:
                # ROCKNIX restores this at boot; Bluetooth devices keep their own level.
                if self._save:
                    self._save.cancel()
                self._save = asyncio.get_running_loop().call_later(1.5, self.remember, level)
        return level

    async def clamp_to_limit(self):
        sink = self.backend.current()
        if sink and sink["level"] > self.settings["volume_limit"]:
            await self.backend.set_volume(sink["name"], self.settings["volume_limit"])

    async def park_speaker(self):
        """While headphones or Bluetooth play, keep the speaker muted so a dropout stays silent."""
        for sink in self.backend.sinks:
            if sink["kind"] == "speaker" and not sink["muted"]:
                await self.backend.set_mute(sink["name"], True)
                self.parked.add(sink["name"])

    async def unpark_speaker(self, delay=0.4):
        await asyncio.sleep(delay)
        for name in list(self.parked):
            await self.backend.set_mute(name, False)
            self.parked.discard(name)
