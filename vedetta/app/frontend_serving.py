"""Serving of the front-end of the /ha page: ha.css and the script from their parts, the modules one by one, and the static folder."""
from fastapi import FastAPI
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles

from . import assets


# ha.css is put together from its parts and the script is a set of modules (app/frontend, see assets.py); these routes come before the static folder.
def _bundle_route(name: str):
    async def serve():
        return Response(assets.bundle(name), media_type=assets.media_type(name))
    return serve


class _Modules(StaticFiles):
    """The modules of the page: served as JavaScript and always checked again (the browser asks with the ETag and gets a 304 when nothing changed), so that after a deploy nobody keeps an old part."""

    def file_response(self, full_path, *args, **kwargs):
        response = super().file_response(full_path, *args, **kwargs)
        response.headers["Cache-Control"] = "no-cache"
        if str(full_path).endswith(".js"):
            response.headers["Content-Type"] = assets.MEDIA[".js"]    # a module must come with a JavaScript type, whatever the system guesses
        return response


def mount_frontend(app: FastAPI, static_dir) -> None:
    for name in assets.BUNDLES:
        app.add_api_route("/static/" + name, _bundle_route(name), methods=["GET"], include_in_schema=False)
    app.mount("/static/ha/js", _Modules(directory=assets.MODULES), name="ha-js")
    app.mount("/static", StaticFiles(directory=static_dir), name="static")
