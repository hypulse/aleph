import asyncio
import json
import logging
import os
import shutil

from .util import run, spawn

log = logging.getLogger("aleph.apps")

SHELL_WORKSPACE = 1
APP_WORKSPACES = range(2, 7)


def _first_existing(*paths):
    return next((p for p in paths if p and (os.path.exists(p) or shutil.which(p))), None)


class AppSpec:
    def __init__(self, key, title_key, argv, needs=None, pauses_music=False, env=None):
        self.key = key
        self.title_key = title_key
        self.argv = argv
        self.needs = needs
        self.pauses_music = pauses_music
        self.env = env or {}

    def available(self):
        return self.needs is None or _first_existing(*self.needs) is not None


PORTS_DIR = "/storage/roms/ports"


def catalog(data_dir):
    koreader = _first_existing("/usr/bin/koreader", "/storage/koreader/koreader.sh")
    portmaster = _first_existing("/usr/bin/start_portmaster.sh")
    return {
        "koreader": AppSpec("koreader", "books", [koreader, "/storage/books"] if koreader else None,
                            needs=[koreader],
                            env={"SDL_FULLSCREEN": "1", "EMULATE_READER_W": "640",
                                 "EMULATE_READER_H": "480"}),
        "portmaster": AppSpec("portmaster", "PortMaster", [portmaster] if portmaster else None,
                              needs=[portmaster]),
        "retroarch": AppSpec("retroarch", "RetroArch", ["retroarch"], needs=["retroarch"],
                             pauses_music=True),
        "video": AppSpec("video", "videos", ["mpv", f"--config-dir={data_dir}/mpv"],
                         needs=["mpv"], pauses_music=True),
    }


class Apps:
    """External programs run as transient systemd units, one sway workspace each."""

    def __init__(self, state, events, env, sim=False):
        self.state = state
        self.events = events
        self.env = env
        self.sim = sim
        self.running = {}
        self.front = None

    async def start(self):
        if not self.sim:
            spawn(self._watch_sway())

    def _publish(self):
        self.state.replace("apps", [
            {"key": key, "title": app["title"], "frozen": app["frozen"], "front": key == self.front}
            for key, app in self.running.items()])
        self.events.page_changed("/")

    def _free_workspace(self):
        used = {app["workspace"] for app in self.running.values()}
        return next((ws for ws in APP_WORKSPACES if ws not in used), None)

    async def launch(self, spec, title, extra_args=()):
        if spec.key in self.running:
            await self.close(spec.key)
        workspace = self._free_workspace()
        if workspace is None or not spec.argv:
            return False
        app_id = f"aleph-app-{workspace}"
        unit = f"aleph-{spec.key}-{workspace}"
        argv = list(spec.argv) + list(extra_args)
        if argv[0] == "mpv":
            argv.insert(1, f"--wayland-app-id={app_id}")
        env = {**self.env, **spec.env, "SDL_VIDEO_WAYLAND_WMCLASS": app_id, "SDL_VIDEO_X11_WMCLASS": app_id}
        self.running[spec.key] = {"title": title, "unit": unit, "workspace": workspace,
                                  "frozen": False, "app_id": app_id}
        if self.sim:
            log.info("sim: launch %s", argv)
        else:
            cmd = ["systemd-run", f"--unit={unit}", "--collect", "--quiet",
                   "--property=KillMode=mixed", "--property=TimeoutStopSec=3"]
            cmd += [f"--setenv={k}={v}" for k, v in env.items()]
            code, _, err = await run(*cmd, "--", *argv)
            if code != 0:
                log.warning("launch failed: %s", err.strip())
                self.running.pop(spec.key, None)
                return False
            await run("swaymsg", "workspace", "number", str(workspace))
        self.front = spec.key
        self.events.foreground_changed()
        self._publish()
        return True

    async def home(self):
        """Freeze the front app and bring the shell forward."""
        key = self.front
        if key is None:
            return
        app = self.running.get(key)
        if app and not self.sim:
            await run("systemctl", "freeze", f"{app['unit']}.service")
        if app:
            app["frozen"] = True
        self.front = None
        if not self.sim:
            await run("swaymsg", "workspace", "number", str(SHELL_WORKSPACE))
        self.events.foreground_changed()
        self._publish()

    async def resume(self, key):
        app = self.running.get(key)
        if not app:
            return
        if not self.sim:
            await run("systemctl", "thaw", f"{app['unit']}.service")
            await run("swaymsg", "workspace", "number", str(app["workspace"]))
        app["frozen"] = False
        self.front = key
        self.events.foreground_changed()
        self._publish()

    async def close(self, key):
        app = self.running.pop(key, None)
        if not app:
            return
        if not self.sim:
            await run("systemctl", "thaw", f"{app['unit']}.service")
            await run("systemctl", "stop", f"{app['unit']}.service", timeout=6)
        if self.front == key:
            self.front = None
            if not self.sim:
                await run("swaymsg", "workspace", "number", str(SHELL_WORKSPACE))
            self.events.foreground_changed()
        self._publish()

    async def _watch_sway(self):
        """Notice apps that exit on their own and return to the shell."""
        while True:
            proc = await asyncio.create_subprocess_exec(
                "swaymsg", "-t", "subscribe", "-m", '["window"]',
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
            while line := await proc.stdout.readline():
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                if event.get("change") != "close":
                    continue
                app_id = (event.get("container") or {}).get("app_id") or ""
                key = next((k for k, a in self.running.items() if a["app_id"] == app_id), None)
                if key:
                    spawn(self._reap(key))
            await proc.wait()
            await asyncio.sleep(2)

    async def _reap(self, key):
        await asyncio.sleep(0.5)
        app = self.running.get(key)
        if not app:
            return
        code, out, _ = await run("systemctl", "is-active", f"{app['unit']}.service")
        if out.strip() in ("active", "activating", "deactivating"):
            return
        self.running.pop(key, None)
        if self.front == key:
            self.front = None
            await run("swaymsg", "workspace", "number", str(SHELL_WORKSPACE))
            self.events.foreground_changed()
        self._publish()


def installed_ports():
    """Launch scripts PortMaster installed, as (title, path)."""
    try:
        names = sorted(os.listdir(PORTS_DIR), key=str.casefold)
    except OSError:
        return []
    return [(os.path.splitext(n)[0], os.path.join(PORTS_DIR, n)) for n in names
            if n.endswith(".sh") and n.lower() != "portmaster.sh"]


def port_spec(title, path):
    return AppSpec("port", title, ["bash", path], pauses_music=True)
