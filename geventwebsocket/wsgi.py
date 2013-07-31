import urlparse


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


def upgrade_websocket(environ, start_response, stream):
    """
    Attempt to upgrade the current environ into a websocket enabled
    connection. If successful, the environ dict with be updated with two
    new entries, `wsgi.websocket` and `wsgi.websocket_version`.

    :returns: Whether the upgrade was successful.
    """
    # some basic sanity checks first
    if environ.get('REQUEST_METHOD', '') != 'GET':
        start_response('400 Bad Request', [])

        return ['Unknown request method']

    upgrade = environ.get('HTTP_UPGRADE', '').lower()

    if upgrade == 'websocket':
        connection = environ.get('HTTP_CONNECTION', '').lower()

        if connection != 'upgrade':
            # this is not a websocket request, so we must not handle it
            return

    if environ.get('HTTP_SEC_WEBSOCKET_VERSION'):
        from . import hybi

        return hybi.upgrade_connection(environ, start_response, stream)
    elif environ.get('HTTP_ORIGIN'):
        from . import hixie

        return hixie.upgrade_connection(environ, start_response, stream)
