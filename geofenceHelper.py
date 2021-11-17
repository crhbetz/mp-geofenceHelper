import ast
import os
import json
import copy
import time
import requests
import configparser
import asyncio
from aiohttp import web
from typing import Dict

import mapadroid.plugins.pluginBase
from plugins.geofenceHelper.endpoints import register_custom_plugin_endpoints
from mapadroid.geofence.geofenceHelper import GeofenceHelper
from mapadroid.db.helper.SettingsGeofenceHelper import SettingsGeofenceHelper
from mapadroid.utils.logging import get_logger, LoggerEnums


class gfHelper(mapadroid.plugins.pluginBase.Plugin):
    """This plugin is just the identity function: it returns the argument
    """

    def _file_path(self) -> str:
        return os.path.dirname(os.path.abspath(__file__))

    def __init__(self, subapp_to_register_to: web.Application, mad_parts: Dict):
        super().__init__(subapp_to_register_to, mad_parts)

        self._rootdir = os.path.dirname(os.path.abspath(__file__))

        self._mad = self._mad_parts

        self._pluginconfig.read(self._rootdir + "/plugin.ini")
        self._versionconfig.read(self._rootdir + "/version.mpl")
        self.author = self._versionconfig.get("plugin", "author", fallback="unknown")
        self.url = self._versionconfig.get("plugin", "url", fallback="https://www.maddev.eu")
        self.description = self._versionconfig.get("plugin", "description", fallback="unknown")
        self.version = self._versionconfig.get("plugin", "version", fallback="unknown")
        self.pluginname = self._versionconfig.get("plugin", "pluginname", fallback="https://www.maddev.eu")
        self.staticpath = self._rootdir + "/static/"
        self.templatepath = self._rootdir + "/template/"
        self.logger = self._mad['logger']

        self._hotlink = [
            ("Select geofences", "gfhelper_select", "Make your selections"),
        ]

        if self._pluginconfig.getboolean("plugin", "active", fallback=False):
            register_custom_plugin_endpoints(self._plugin_subapp)
            for name, link, description in self._hotlink:
                self._mad_parts['madmin'].add_plugin_hotlink(name, link.replace("/", ""),
                                                             self.pluginname, self.description, self.author, self.url,
                                                             description, self.version)

    async def _perform_operation(self):
        if not self._pluginconfig.getboolean("plugin", "active", fallback=False):
            return False

        # load your stuff now
        self.logger.success("geofenceHelper plugin successfully registered")

        loop = asyncio.get_event_loop()
        loop.create_task(self.update_checker())
        return True

    def _is_update_available(self):
        update_available = None
        try:
            raw_url = self.url.replace("github.com", "raw.githubusercontent.com")
            r = requests.get("{}/main/version.mpl".format(raw_url))
            self.github_mpl = configparser.ConfigParser()
            self.github_mpl.read_string(r.text)
            self.available_version = self.github_mpl.get("plugin", "version", fallback=self.version)
        except Exception as e:
            self.logger.warning(f"Failed getting version info for {self.pluginname} from github: {e}")
            return None

        try:
            from pkg_resources import parse_version
            update_available = parse_version(self.version) < parse_version(self.available_version)
        except Exception:
            pass

        if update_available is None:
            try:
                from distutils.version import LooseVersion
                update_available = LooseVersion(self.version) < LooseVersion(self.available_version)
            except Exception:
                pass

        if update_available is None:
            try:
                from packaging import version
                update_available = version.parse(self.version) < version.parse(self.available_version)
            except Exception:
                pass

        return update_available

    async def update_checker(self):
        while True:
            self.logger.debug("{} checking for updates ...", self.pluginname)
            result = self._is_update_available()
            if result:
                self.logger.warning("An update of {} from version {} to version {} is available!",
                                    self.pluginname, self.version, self.available_version)
            elif result is False:
                self.logger.success("{} is up-to-date! ({} = {})", self.pluginname, self.version,
                                    self.available_version)
            else:
                self.logger.warning("Failed checking for updates!")
            await asyncio.sleep(3600)


class gfFormatter(object):
    def __init__(self, query, session, instance_id):

        self._session = session
        self._instance_id = instance_id
        self.logger = get_logger(LoggerEnums.plugin)

        self.query = query
        self.mode = query.get("mode")
        self.outtype = query.get("type", "script")
        self.newline = "\n" if self.outtype == "script" else "<br />"

        # map mode strings to methods
        # https://bytebaker.com/2008/11/03/switch-case-statement-in-python/
        # geoJson and poracle is handled differently because of the merge option
        self.modes = {"pmsf": self.pmsf,
                      "pmsfarray": self.pmsfarray,
                      "pokealarm": self.pokealarm,
                      "sqlpolygon": self.sqlpolygon,
                      "geojson": self.geojson,
                      "geojson_merged": self.geojson_merged,
                      "poracle": self.poracle,
                      "poracle_merged": self.poracle_merged
                      }

        # define geoJson patterns to deepcopy later
        self.geojson_pattern: dict = {}
        self.geojson_pattern["type"]: str = "FeatureCollection"
        self.geojson_pattern["features"]: list = []

        self.feature_pattern: dict = {}
        self.feature_pattern["type"]: str = "Feature"
        self.feature_pattern["properties"]: dict = {}
        self.feature_pattern["geometry"]: dict = {}
        self.feature_pattern["geometry"]["type"]: str = "Polygon"
        self.feature_pattern["geometry"]["coordinates"]: list = []

    async def selected_fences(self):
        self.logger.debug("::selected_fences")
        selected_fences = []
        allfences = await self.get_all_fences()
        for key, val in self.query.items():
            if key in allfences and val == "on":
                selected_fences.append(key)
        return selected_fences

    async def get_all_fences(self):
        self.logger.debug("::get_all_fences")
        fences = {}
        geofences = await SettingsGeofenceHelper.get_all_mapped(self._session, self._instance_id)
        self.logger.debug(f"got geofences: {geofences}")
        for num in geofences:
            geofence_helper = GeofenceHelper(geofences[num], None, str(geofences[num]))
            for geofenced_area in geofence_helper.geofenced_areas:
                if "polygon" in geofenced_area:
                    if len(geofence_helper.geofenced_areas) == 1:
                        name = geofenced_area["name"]
                    else:
                        name = f'{geofence["name"]}_{geofenced_area["name"]}'
                    if name not in fences:
                        fences[name] = geofenced_area["polygon"]
        return fences

    def format_geojson(self, geojson):
        self.logger.debug("::format_geojson")
        # use HTML &emsp to force visible tab
        if self.outtype == "pp":
            return json.dumps(geojson, indent=4).replace("    ", "&emsp;").replace("\n", "<br />") + "<br />"

        # the \t is sadly not rendered, but &emsp would be copied and cause invalid JSON
        elif self.outtype == "copy":
            return json.dumps(geojson, indent=4).replace("    ", "\t").replace("\n", "<br />") + "<br />"

        # do not replace the spaces and newlines - this can be loaded with wget/curl and used further
        else:
            return json.dumps(geojson, indent=4)

    def build_geojson(self, features=[]):
        self.logger.debug("::build_geojson")
        this_dict = copy.deepcopy(self.geojson_pattern)
        for feature in features:
            self.logger.debug(f"append feature {feature} to featrues")
            this_dict["features"].append(feature)
        self.logger.debug(f"format and return: {this_dict}")
        return self.format_geojson(this_dict)

    def feature(self, name="unknown", coords=[]):
        self.logger.debug("::feature")
        this_feature = copy.deepcopy(self.feature_pattern)
        this_feature["properties"]["name"] = name
        coordset: list = []
        for coord in coords:
            # real geoJson uses lon,lat
            coordset.append([coord["lon"], coord["lat"]])
        this_feature["geometry"]["coordinates"].append(coordset)
        return this_feature

    async def poracle(self):
        self.logger.debug("::poracle")
        result: str = ""
        allfences = await self.get_all_fences()
        for name in await self.selected_fences():
            coords = allfences[name]
            result += self.format_geojson([self.poracle_elem(name, coords), ])
        return result

    async def poracle_merged(self):
        self.logger.debug("::poracle_merged")
        elems: list = []
        allfences = await self.get_all_fences()
        for name in await self.selected_fences():
            coords = allfences[name]
            elems.append(self.poracle_elem(name, coords))
        return self.format_geojson(elems)

    def poracle_elem(self, name="unknown", coords=[]):
        self.logger.debug("::poracle_elem")
        this_dict = {}
        this_dict["name"] = name
        this_dict["path"] = []
        for coord in coords:
            this_dict["path"].append([coord["lat"], coord["lon"]])
        return this_dict

    async def geojson(self):
        self.logger.debug("::geojson")
        result: str = ""
        allfences = await self.get_all_fences()
        for name in await self.selected_fences():
            coords = allfences[name]
            result += self.build_geojson([self.feature(name, coords), ])
        return result

    async def geojson_merged(self):
        self.logger.debug("geojson_merged")
        features: list = []
        allfences = await self.get_all_fences()
        for name in await self.selected_fences():
            coords = allfences[name]
            features.append(self.feature(name, coords))
        return self.build_geojson(features)

    async def pmsf(self, array=False):
        self.logger.debug("::pmsf")
        result: str = ""
        allfences = await self.get_all_fences()
        for name in await self.selected_fences():
            coords = allfences[name]
            if array:
                result += f'$fencearr["{name}"] = \''
            else:
                result += f'${name} = \''
            result += f"{self.create_sqlpolygon(name=name, coords=coords, newline=False)}\';{self.newline}"
        return result

    def pmsfarray(self, name="unknown", coords=[]):
        self.logger.debug("::pmsfarray")
        return self.pmsf(array=True)

    async def pokealarm(self):
        self.logger.debug("::pokealarm")
        result: str = ""
        allfences = await self.get_all_fences()
        for name in await self.selected_fences():
            coords = allfences[name]
            result += f'[{name}]{self.newline}'
            for coord in coords:
                result += f'{coord["lat"]},{coord["lon"]}{self.newline}'
        return result

    async def sqlpolygon(self):
        self.logger.debug("::sqlpolygon")
        result: str = ""
        allfences = await self.get_all_fences()
        for name in self.selected_fences:
            coords = allfences[name]
            result += self.create_sqlpolygon(name, coords)
        return result

    def create_sqlpolygon(self, name="unknown", coords=[], newline=True):
        self.logger.debug("::create_sqlpolygon")
        result: str = ""
        first_coord = None
        for coord in coords:
            if not first_coord:
                first_coord = coord
            result += f'{coord["lat"]} {coord["lon"]},'
        result += f'{first_coord["lat"]} {first_coord["lon"]}'
        if newline:
            return f"{result}{self.newline}"
        else:
            return result
