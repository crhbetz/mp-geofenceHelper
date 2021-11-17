from mapadroid.plugins.endpoints.AbstractPluginEndpoint import AbstractPluginEndpoint
import aiohttp_jinja2
from aiohttp import web

from mapadroid.db.helper.SettingsGeofenceHelper import SettingsGeofenceHelper


class geofenceHelperSelectEndpoint(AbstractPluginEndpoint):
    """
    "/gfhelper_select"
    """

    @aiohttp_jinja2.template('select.html')
    async def get(self):
        fences = await SettingsGeofenceHelper.get_all_mapped(self._session, self._get_instance_id())
        return {"header": "Select fences",
                "title": "Select fences",
                "fences": fences}


class geofenceHelperResultsEndpoint(AbstractPluginEndpoint):
    """
    "/gfhelper_results"
    """

    @aiohttp_jinja2.template('results.html')
    async def get(self):
        from plugins.geofenceHelper.geofenceHelper import gfFormatter
        mode = self.request.query.get("mode")
        formatter = gfFormatter(self.request.query, self._session, self._get_instance_id())
        output = await formatter.modes[mode]()

        if self.request.query.get("type") != "script":
            output = f"<code>{output}</code>"

        return web.Response(text=output, content_type='text/html')