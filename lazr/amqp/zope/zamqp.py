# Copyright 2005-2011 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

from urllib import unquote

from zope.interface import implements

from lazr.amqp.zope.interfaces import IZAMQP


__all__ = ["ZAMQP"]


class URI(object):
    """Represents an URI object to connect to an AMQP broker.

    The form of the URI is this: scheme://username:password@host:port/vhost

    @ivar scheme: unused for now, it may contain the AMQP version in the
        future
    @ivar username: the username to connect to the broker.
    @ivar password: the password corresponding to the username.
    @ivar host: the host to connect to.
    @ivar port: the port on which the broker is listening.
    @ivar vhost: the AMPQ virtual host to bind to.
    """
    scheme = None
    username = None
    password = None
    host = None
    port = None
    vhost = None

    def __init__(self, uri_str):
        try:
            self.scheme, rest = uri_str.split(":", 1)
        except ValueError:
            raise ValueError("URI has no scheme: %r" % uri_str)

        if not rest.startswith("//"):
            raise ValueError("Invalid UIR format: %r" % uri_str)

        rest = rest[2:]
        rest, vhost = rest.split("/", 1)
        if not vhost:
            vhost = "/"
        self.vhost = unquote(vhost)
        if "@" in rest:
            userpass, hostport = rest.split("@", 1)
        else:
            userpass = None
            hostport = rest
        if hostport:
            if ":" in hostport:
                host, port = hostport.rsplit(":", 1)
                self.host = unquote(host)
                if port:
                    self.port = int(port)
            else:
                self.host = unquote(hostport)
        if userpass is not None:
            if ":" in userpass:
                username, password = userpass.rsplit(":", 1)
                self.username = unquote(username)
                self.password = unquote(password)
            else:
                self.username = unquote(userpass)


class ZAMQP(object):
    """Utility object to get access to AMQP URIs."""

    implements(IZAMQP)

    def __init__(self):
        self._default_uris = {}

    def set_default_uri(self, name, uri):
        self._default_uris[name] = URI(uri)

    def get(self, name):
        return self._default_uris[name]


global_zamqp = ZAMQP()
