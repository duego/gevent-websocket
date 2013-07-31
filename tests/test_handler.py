try:
    import unittest2 as unittest
except ImportError:
    import unittest

import mock

from geventwebsocket import handler as ws_handler, wsgi

from .util import FakeSocket


class HandlerTestCase(unittest.TestCase):
    def my_app(self, environ, start_response):
        start_response('200 OK', [])

        return []

    def make_handler(self, environ=None, socket=None):
        socket = socket or FakeSocket()

        my_handler = ws_handler.WebSocketHandler(
            socket, ('localhost', 1010), None)

        my_handler.environ = environ or {}
        my_handler.request_version = 'HTTP/1.1'
        my_handler.application = mock.Mock()
        my_handler.process_result = mock.Mock()
        my_handler.request_version = 'HTTP/1.1'
        my_handler.headers_sent = False
        my_handler.status = None
        # gevent 0.13.*
        my_handler.response_headers_list = []
        my_handler.result = []
        my_handler.provided_date = None
        my_handler.provided_content_length = None

        return my_handler


class RunApplicationTestCase(HandlerTestCase):
    """
    Tests for `run_application`.
    """

    def test_missing_upgrade(self):
        """
        A request with a missing `HTTP_UPGRADE` header must not create a
        websocket.
        """
        environ = {
            'REQUEST_METHOD': 'GET',
            'SERVER_PROTOCOL': 'HTTP/1.1',
        }
        handler = self.make_handler(environ)

        handler.run_application()

        self.assertIsNone(handler.websocket)
        self.assertNotIn('wsgi.websocket', environ)
        self.assertTrue(handler.application.called)

    def test_missing_connection(self):
        """
        A request with a missing `HTTP_CONNECTION` header must not create a
        websocket.
        """
        environ = {
            'HTTP_UPGRADE': 'WebSocket',
            'REQUEST_METHOD': 'GET',
            'SERVER_PROTOCOL': 'HTTP/1.1',
        }
        handler = self.make_handler(environ)

        handler.run_application()

        self.assertIsNone(handler.websocket)
        self.assertNotIn('wsgi.websocket', environ)
        self.assertTrue(handler.application.called)

    def test_failed_upgrade(self):
        """
        If a call to `upgrade_websocket` returns False, a websocket must not be
        created.
        """
        environ = {
            'HTTP_UPGRADE': 'WebSocket',
            'REQUEST_METHOD': 'GET',
            'SERVER_PROTOCOL': 'HTTP/1.1',
            'HTTP_CONNECTION': 'Upgrade'
        }
        handler = self.make_handler(environ)

        with mock.patch.object(wsgi, 'upgrade_websocket') as upgrade:
            handler.status = '404 Not Found'
            upgrade.return_value = False

            handler.run_application()

        self.assertNotIn('wsgi.websocket', environ)
        self.assertTrue(handler.process_result.called)

    def test_failed_upgrade_no_response(self):
        """
        If a call to `upgrade_websocket` returns False but no status is set,
        a websocket must not be created.
        """
        environ = {
            'HTTP_UPGRADE': 'WebSocket',
            'HTTP_CONNECTION': 'Upgrade'
        }
        handler = self.make_handler(environ)

        with mock.patch.object(wsgi, 'upgrade_websocket') as upgrade:
            upgrade.return_value = False

            handler.run_application()

        self.assertNotIn('wsgi.websocket', environ)
        self.assertTrue(handler.application.called)

    def test_upgrade_successful(self):
        """
        A successful upgrade requires specific attrs to be set
        """
        sentinel = mock.Mock()
        environ = {
            'HTTP_UPGRADE': 'WebSocket',
            'HTTP_CONNECTION': 'Upgrade',
            'wsgi.websocket': sentinel,
        }
        handler = self.make_handler(environ)

        with mock.patch.object(wsgi, 'upgrade_websocket') as upgrade:
            upgrade.return_value = True

            handler.code = 101
            handler.status = '101 Switching Protocols'
            handler.response_headers = []
            handler.response_length = 0

            handler.run_application()

        self.assertIs(environ['wsgi.websocket'], sentinel)
        self.assertIs(handler.websocket, sentinel)

        self.assertTrue(handler.application.called)

    def test_close_websocket(self):
        """
        When the application has been run, the websocket must be closed.
        """
        websocket = mock.Mock()
        handler = self.make_handler({
            'wsgi.websocket': websocket
        })

        self.executed = False

        def my_app(environ, start_response):
            self.executed = True
            self.assertFalse(websocket.close.called)

        handler.application = my_app
        handler.run_websocket()

        self.assertTrue(self.executed)
        self.assertTrue(websocket.close.called)

    def test_close_websocket_error(self):
        """
        Even hen the application errors, the websocket must be closed.
        """
        websocket = mock.Mock()
        handler = self.make_handler({
            'wsgi.websocket': websocket
        })

        class MyTestException(Exception):
            pass

        def my_app(environ, start_response):
            raise MyTestException

        handler.application = my_app
        self.assertRaises(MyTestException, handler.run_websocket)

        self.assertTrue(websocket.close.called)

    def test_prevent_wsgi_call(self):
        """
        When `prevent_wsgi_call` is set on the handler, the underlying
        application must not be called.
        """
        sentinel = object()
        environ = {
            'HTTP_UPGRADE': 'WebSocket',
            'HTTP_CONNECTION': 'Upgrade',
            'wsgi.websocket': sentinel,
        }
        handler = self.make_handler(environ)
        handler.prevent_wsgi_call = True

        with mock.patch.object(wsgi, 'upgrade_websocket') as upgrade:
            upgrade.return_value = True

            handler.code = 101
            handler.status = '101 Switching Protocols'
            handler.response_headers = []
            handler.response_length = 0

            handler.run_application()

        self.assertIs(environ['wsgi.websocket'], sentinel)
        self.assertIs(handler.websocket, sentinel)

        self.assertFalse(handler.application.called)

    def test_start_websocket_response(self):
        """
        Calling `start_response` with a 101 status must set default values on
        the handler.
        """
        handler = self.make_handler({
            'wsgi.websocket': object()
        })

        handler.start_response('101 FooBar', [])

        self.assertFalse(handler.provided_content_length)
        self.assertFalse(handler.response_use_chunked)
        self.assertTrue(handler.close_connection)
        self.assertTrue(handler.provided_date)

    def test_broken_socket(self):
        """
        If a socket error occurs when upgrading the websocket, ensure the
        underlying application is not called.
        """
        environ = {
            'HTTP_UPGRADE': 'WebSocket',
            'HTTP_CONNECTION': 'Upgrade',
        }
        handler = self.make_handler(environ)

        with mock.patch.object(wsgi, 'upgrade_websocket') as upgrade:
            from socket import error
            upgrade.side_effect = error

            self.assertRaises(error, handler.run_application)

        self.assertFalse(handler.application.called)


class UpgradeWebsocketTestCase(unittest.TestCase):
    """
    Tests for `upgrade_websocket`
    """

    def test_method(self):
        """
        A request method != GET must result in a 400.
        """
        for request_method in ['POST', 'DELETE', 'PUT', 'OPTIONS', 'HEAD']:
            self.executed = False
            environ = {
                'REQUEST_METHOD': request_method
            }

            def start_response(status, headers):
                self.executed = True
                self.assertEqual(status, '400 Bad Request')
                self.assertEqual(headers, [])

            result = wsgi.upgrade_websocket(environ, start_response, None)

            self.assertTrue(self.executed)
            self.assertEqual(
                result,
                ['Unknown request method']
            )

    def test_set_status(self):
        """
        Setting a status != 101 in `*.upgrade_connection` must result in a
        failure.
        """
        environ = {
            'REQUEST_METHOD': 'GET',
            'HTTP_ORIGIN': '*'
        }

        self.executed = False

        def start_response(status, headers):
            self.executed = True
            self.assertEqual(status, '400 Bad Request')
            self.assertEqual(headers, [])

        result = wsgi.upgrade_websocket(environ, start_response, None)

        self.assertTrue(self.executed)
        self.assertEqual(
            result,
            ['Bad protocol version']
        )

    def test_upgrade(self):
        """
        Given the correct conditions, `upgrade_websocket` should return true.
        """
        from geventwebsocket import hixie

        environ = {
            'REQUEST_METHOD': 'GET',
            'HTTP_ORIGIN': '*',
            'wsgi.websocket': object()
        }

        with mock.patch.object(hixie, 'upgrade_connection'):
            self.executed = False

            def start_response(status, headers):
                self.executed = True
                self.assertEqual(status, '400 Bad Request')
                self.assertEqual(headers, [])

            result = wsgi.upgrade_websocket(environ, start_response, None)

            self.assertTrue(self.executed)
            self.assertTrue(result)
