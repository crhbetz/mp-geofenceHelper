import ast
import os
import json
import copy
import time
import requests
import configparser

from flask import Blueprint, render_template, request, Markup
from threading import Thread

import mapadroid.utils.pluginBase
from mapadroid.madmin.functions import auth_required
from mapadroid.geofence.geofenceHelper import GeofenceHelper


class MadPluginExample(mapadroid.utils.pluginBase.Plugin):
    """This plugin is just the identity function: it returns the argument
    """
    def __init__(self, mad):
        super().__init__(mad)

        self._rootdir = os.path.dirname(os.path.abspath(__file__))

        self._mad = mad

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

        self._routes = [
            ("/gfhelper_select", self.select),
            ("/gfhelper_results", self.results),
        ]

        self._hotlink = [
            ("Select geofences", "gfhelper_select", "Make your selections"),
        ]

        if self._pluginconfig.getboolean("plugin", "active", fallback=False):
            self._plugin = Blueprint(str(self.pluginname), __name__, static_folder=self.staticpath,
                                     template_folder=self.templatepath)

            for route, view_func in self._routes:
                self._plugin.add_url_rule(route, route.replace("/", ""), view_func=view_func)

            for name, link, description in self._hotlink:
                self._mad['madmin'].add_plugin_hotlink(name, self._plugin.name + "." + link.replace("/", ""),
                                                       self.pluginname, self.description, self.author, self.url,
                                                       description, self.version)

    def perform_operation(self):
        """The actual implementation of the identity plugin is to just return the
        argument
        """

        # do not change this part ▽▽▽▽▽▽▽▽▽▽▽▽▽▽▽
        if not self._pluginconfig.getboolean("plugin", "active", fallback=False):
            return False
        self._mad['madmin'].register_plugin(self._plugin)
        # do not change this part △△△△△△△△△△△△△△△

        # load your stuff now
        self.logger.success("geofenceHelper plugin successfully registered")

        updateChecker = Thread(name="{}Updates".format(self.pluginname), target=self.update_checker,)
        updateChecker.daemon = True
        updateChecker.start()

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

    def update_checker(self):
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
            time.sleep(3600)

    # get directly from database
    # inspiration: https://github.com/Map-A-Droid/MAD/blob/6eea593aa0e77e93e80fb943a6c375b0ca408c0f/mapadroid/madmin/routes/map.py#L86
    # MADminMap.get_geofences()
    def get_all_fences(self):
        self.logger.debug("::get_all_fences")
        fences = {}
        query = "select fence_data, name, fence_type from settings_geofence"
        geofences = self._mad['db_wrapper'].autofetch_all(query)
        self.logger.debug(f"got geofences: {geofences}")
        for geofence in geofences:
            geofence['fence_data'] = ast.literal_eval(geofence['fence_data'])
            self.logger.debug(f"passing geofence: {geofence}")
            geofence_helper = GeofenceHelper(geofence, None, geofence["name"])
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

    def poracle(self):
        self.logger.debug("::poracle")
        result: str = ""
        allfences = self.get_all_fences()
        for name in self.selected_fences:
            coords = allfences[name]
            result += self.format_geojson([self.poracle_elem(name, coords), ])
        return result

    def poracle_merged(self):
        self.logger.debug("::poracle_merged")
        elems: list = []
        allfences = self.get_all_fences()
        for name in self.selected_fences:
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

    def geojson(self):
        self.logger.debug("::geojson")
        result: str = ""
        allfences = self.get_all_fences()
        for name in self.selected_fences:
            coords = allfences[name]
            result += self.build_geojson([self.feature(name, coords), ])
        return result

    def geojson_merged(self):
        self.logger.debug("geojson_merged")
        features: list = []
        allfences = self.get_all_fences()
        for name in self.selected_fences:
            coords = allfences[name]
            features.append(self.feature(name, coords))
        return self.build_geojson(features)

    def pmsf(self, array=False):
        self.logger.debug("::pmsf")
        result: str = ""
        allfences = self.get_all_fences()
        for name in self.selected_fences:
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

    def pokealarm(self):
        self.logger.debug("::pokealarm")
        result: str = ""
        allfences = self.get_all_fences()
        for name in self.selected_fences:
            coords = allfences[name]
            result += f'[{name}]{self.newline}'
            for coord in coords:
                result += f'{coord["lat"]},{coord["lon"]}{self.newline}'
        return result

    def sqlpolygon(self):
        self.logger.debug("::sqlpolygon")
        result: str = ""
        allfences = self.get_all_fences()
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

    @auth_required
    def select(self):
        return render_template("select.html",
                               header="Select fences", title="Select fences",
                               fences=self.get_all_fences(),
                               )

    @auth_required
    def results(self):
        results = request.args
        allfences = self.get_all_fences()
        self.selected_fences = []
        for key, val in results.items():
            if key in allfences and val == "on":
                self.selected_fences.append(key)

        mode = results.get("mode")
        self.outtype = results.get("type", "script")
        self.newline = "\n" if self.outtype == "script" else "<br />"

        output = self.modes[mode]()
        self.logger.debug(f"Built this output: {output}")

        if self.outtype != "script":
            self.logger.debug("add code tags")
            output = f"<code>{output}</code>"

        output = Markup(output)

        return render_template("results.html",
                               header="Results", title="Results",
                               results=results,
                               output=output
                               )
