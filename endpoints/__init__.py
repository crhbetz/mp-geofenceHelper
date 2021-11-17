from aiohttp import web
from plugins.geofenceHelper.endpoints.geofenceHelperEndpoints import geofenceHelperResultsEndpoint, geofenceHelperSelectEndpoint


def register_custom_plugin_endpoints(app: web.Application):
    # Simply register any endpoints here. If you do not intend to add any views (which is discouraged) simply "pass"
    app.router.add_view('/gfhelper_select', geofenceHelperSelectEndpoint, name='gfhelper_select')
    app.router.add_view('/gfhelper_results', geofenceHelperResultsEndpoint, name='gfhelper_results')
