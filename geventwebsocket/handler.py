import urlparse

from gevent.pywsgi import WSGIHandler

from . import hybi
from . import hixie


class WebSocketHandler(WSGIHandler):
    """
    Automatically upgrades the connection to a websocket.

    To prevent the WebSocketHandler to call the underlying WSGI application,
    but only setup the WebSocket negotiations, do:

      mywebsockethandler.prevent_wsgi_call = True

    before calling run_application().  This is useful if you want to do more
    things before calling the app, and want to off-load the WebSocket
    negotiations to this library.  Socket.IO needs this for example, to send
    the 'ack' before yielding the control to your WSGI app.
    """

    websocket = None

    @property
    def ws_url(self):
        return reconstruct_url(self.environ)

    def run_websocket(self):
        """
        Called when a websocket has been created successfully.
        """
        if hasattr(self, 'prevent_wsgi_call') and self.prevent_wsgi_call:
            return

        # since we're now a websocket connection, we don't care what the
        # application actually responds with for the http response
        try:
            self.application(self.environ, self._fake_start_response)
        finally:
            self.websocket.close()

    def run_application(self):
        """
        Attempt to create a websocket. If the request is not a WebSocket
        upgrade request, it will be passed to the application object.

        You probably don't want to override this function, see `run_websocket`.
        """
        upgrade = self.environ.get('HTTP_UPGRADE', '').lower()

        if upgrade == 'websocket':
            connection = self.environ.get('HTTP_CONNECTION', '').lower()

            if connection == 'upgrade':
                if not self.upgrade_websocket() and hasattr(self, 'status'):
                    # the request was handled, probably with an error status
                    self.process_result()

                    return

        self.websocket = self.environ.get('wsgi.websocket')

        if not self.websocket:
            # no websocket could be created and the connection was not upgraded
            super(WebSocketHandler, self).run_application()

            return

        if self.status and not self.headers_sent:
            self.write('')

        self.run_websocket()

    def _fake_start_response(self, status, headers):
        pass

    def start_response(self, status, headers, exc_info=None):
        writer = super(WebSocketHandler, self).start_response(
            status, headers, exc_info=exc_info)

        if self.websocket:
            # so that `finalize_headers` doesn't write a Content-Length header
            self.provided_content_length = False
            # the websocket is now controlling the response
            self.response_use_chunked = False
            # once the request is over, the connection must be closed
            self.close_connection = True
            self.provided_date = True

        return writer

    def upgrade_websocket(self):
        """
        Attempt to upgrade the current environ into a websocket enabled
        connection. If successful, the environ dict with be updated with two
        new entries, `wsgi.websocket` and `wsgi.websocket_version`.

        :returns: Whether the upgrade was successful.
        """
        # some basic sanity checks first
        if self.environ.get("REQUEST_METHOD") != "GET":
            self.start_response('400 Bad Request', [])

            return False

        if self.request_version != 'HTTP/1.1':
            self.start_response('400 Bad Request', [])

            return False

        if self.environ.get('HTTP_SEC_WEBSOCKET_VERSION'):
            result = hybi.upgrade_connection(self, self.environ)
        elif self.environ.get('HTTP_ORIGIN'):
            result = hixie.upgrade_connection(self, self.environ)
        else:
            return False

        if 'wsgi.websocket' not in self.environ:
            # could not upgrade the connection
            self.result = result or []

            return False

        return True


def reconstruct_url(environ):
    """
    Build a WebSocket url based on the supplied environ dict.

    Will return a url of the form:

        ws://host:port/path?query
    """
    secure = environ['wsgi.url_scheme'].lower() == 'https'

    if secure:
        scheme = 'wss'
    else:
        scheme = 'ws'

    host = environ.get('HTTP_HOST', None)

    if not host:
        host = environ['SERVER_NAME']

    port = None
    server_port = environ['SERVER_PORT']

    if secure:
        if server_port != '443':
            port = server_port
    else:
        if server_port != '80':
            port = server_port

    netloc = host

    if port:
        netloc = host + ':' + port

    path = environ.get('SCRIPT_NAME', '') + environ.get('PATH_INFO', '')

    query = environ['QUERY_STRING']

    return urlparse.urlunparse((
        scheme,
        netloc,
        path,
        '',  # params
        query,
        '',  # fragment
    ))
