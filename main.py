# Decky backend entry point: settings, the faceplate worker, frontend callables.

import os
import sys

import decky

# Decky appends py_modules to sys.path itself; inserting it first as well keeps
# local runs and older loaders working.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "py_modules"))

from pixelface import __version__  # noqa: E402
from pixelface.handoff import faceplate_owner  # noqa: E402
from pixelface.power_events import PowerEvents  # noqa: E402
from pixelface.service import FaceplateService  # noqa: E402
from pixelface.settings import SettingsStore  # noqa: E402


class Plugin:
    async def _main(self):
        path = os.path.join(decky.DECKY_PLUGIN_SETTINGS_DIR, "settings.json")
        self.settings = SettingsStore(path)
        if self.settings.load_error:
            decky.logger.warning("[Pixel Faceplate] " + self.settings.load_error)
        counter = os.path.join(decky.DECKY_PLUGIN_SETTINGS_DIR, "writes.json")
        plugins_dir = os.path.dirname(decky.DECKY_PLUGIN_DIR)
        self.power = PowerEvents(self.service_power_event, decky.logger)
        self.service = FaceplateService(
            self.settings.values, decky.logger, counter_path=counter,
            owner_check=lambda: faceplate_owner(plugins_dir),
            on_owner_change=self._owner_changed,
        )
        self.power.start()
        self.service.start()
        decky.logger.info(
            "[Pixel Faceplate] v%s loaded as uid %d, mode=%s"
            % (__version__, os.getuid(), self.settings.values["mode"])
        )

    def service_power_event(self, kind, starting):
        self.service.power_event(kind, starting)

    def _owner_changed(self, owner):
        """While GabeCubeAura drives the panel this plugin holds no sleep delay lock either."""
        if owner:
            self.power.stop()
        else:
            self.power.start()

    async def _unload(self):
        self.power.stop()
        self.service.stop()
        decky.logger.info("[Pixel Faceplate] unloaded")

    async def _uninstall(self):
        self.power.stop()
        self.service.stop()

    async def get_status(self):
        return self.service.status()

    async def game_event(self, appid: int, running: bool):
        self.service.game_event(appid, running)
        return True

    async def save_settings(self, changes: dict):
        """Validate and persist; returns {ok, error, status}."""
        try:
            values = self.settings.update(changes)
        except ValueError as error:
            return {"ok": False, "error": str(error), "status": self.service.status()}
        except OSError as error:
            return {"ok": False, "error": "could not save: %s" % error, "status": self.service.status()}
        self.service.configure(values)
        return {"ok": True, "error": "", "status": self.service.status()}

    async def save_game_settings(self, appid: int, changes: dict = None):
        """One game's own art style/logo position; changes=None goes back to the console's."""
        try:
            values = self.settings.update_game(appid, changes)
        except ValueError as error:
            return {"ok": False, "error": str(error), "status": self.service.status()}
        except OSError as error:
            return {"ok": False, "error": "could not save: %s" % error, "status": self.service.status()}
        self.service.configure(values)
        return {"ok": True, "error": "", "status": self.service.status()}
