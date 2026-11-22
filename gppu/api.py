"""gppu.api — ``APIApp``, an async app that serves HTTP. FastAPI and uvicorn come with the ``ld`` extra."""
from __future__ import annotations

from typing import Any

import uvicorn
from fastapi import FastAPI

from .app import AsyncApp


class APIApp(AsyncApp):
    """An AsyncApp that serves HTTP: on uvicorn, at the ``host`` and ``port`` of its configuration, each ASGI app
    ``apis()`` gives at its path, from the end of ``start``. Override ``apis()``; work needed before serving is done
    in ``load``::

        class LDAPI(APIApp, _SQABase):   # its store: the configuration's `db`, the engine and each request's session
            def apis(self): return {'/ld/v1': ld.serve({'/work': work.app}, self)}
    """

    def apis(self) -> dict[str, Any]:
        """path -> the FastAPI (or any ASGI) app served there."""
        return {}

    def _asgi(self) -> FastAPI:
        """The app uvicorn serves: the apps of ``apis()`` at their paths."""
        root = FastAPI(title=self.name)
        for path, app in self.apis().items(): root.mount(path, app)
        return root

    def __start(self) -> None:
        server = self._spawn(uvicorn.Server(uvicorn.Config(self._asgi(), host=self.my('host'), port=self.my('port'))).serve())
        server.add_done_callback(lambda _: self.stop())   # .. uvicorn ends serving on SIGTERM or SIGINT: the app ends with it
