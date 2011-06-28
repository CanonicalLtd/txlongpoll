# Copyright 2005-2011 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for the amqp_broker zcml directive and the ZAMQP utility."""

from unittest import defaultTestLoader, TestCase

from zope.configuration import xmlconfig
from zope.component import queryUtility, provideUtility

import lazr.amqp.zope
from lazr.amqp.zope.zamqp import URI, ZAMQP
from lazr.amqp.zope.interfaces import IZAMQP


class URITests(TestCase):
    """Tests for L{URI} parsing."""

    def test_no_scheme(self):
        """
        L{URI} raises a C{ValueError} if no scheme is specified.
        """
        self.assertRaises(ValueError, URI, "user@localhost/host")

    def test_invalid_scheme(self):
        """
        L{URI} raises a C{ValueError} if the scheme doesn't end with '://'.
        """
        self.assertRaises(ValueError, URI, "scheme:user@localhost/host")

    def test_no_vhost(self):
        """
        L{URI} raises a C{ValueError} if no vhost is specified.
        """
        self.assertRaises(ValueError, URI, "scheme://user@localhost")

    def test_vhost(self):
        """
        The C{vhost} attribute of the L{URI} maps to the last part of the
        passed string.
        """
        uri = URI("scheme://user@localhost/host")
        self.assertEquals(uri.vhost, "host")

    def test_vhost_slash(self):
        """
        If the vhost is '/' L{URI} is able to parse it.
        """
        uri = URI("scheme://user@localhost/")
        self.assertEquals(uri.vhost, "/")

    def test_vhost_unescape(self):
        """
        L{URI} unescapes the vhost part.
        """
        uri = URI("scheme://user@localhost/ho%73t")
        self.assertEquals(uri.vhost, "host")

    def test_password(self):
        """
        The password can be specified after the username and before the host.
        """
        uri = URI("scheme://user:password@localhost/host")
        self.assertEquals(uri.username, "user")
        self.assertEquals(uri.password, "password")

    def test_unescape_user_password(self):
        """
        Both username and password can contain escape characters, which are
        parsed by L{URI}.
        """
        uri = URI("scheme://u%73er:pas%73word@localhost/host")
        self.assertEquals(uri.username, "user")
        self.assertEquals(uri.password, "password")

    def test_default_user_password(self):
        """
        If no username or password are specified the values are kepts to
        C{None}.
        """
        uri = URI("scheme://localhost/host")
        self.assertTrue(uri.username is None)
        self.assertTrue(uri.password is None)

    def test_username(self):
        """
        L{URI} can parse an uri with an username but no password.
        """
        uri = URI("scheme://user@localhost/host")
        self.assertEquals(uri.username, "user")
        self.assertTrue(uri.password is None)

    def test_unescape_username(self):
        """
        If no password is specified the username is still unescaped.
        """
        uri = URI("scheme://u%73er@localhost/host")
        self.assertEquals(uri.username, "user")

    def test_host(self):
        """
        L{URI} can parse the host from the uri string.
        """
        uri = URI("scheme://localhost/host")
        self.assertEquals(uri.host, "localhost")
        self.assertTrue(uri.port is None)

    def test_unescape_host(self):
        """
        The host part is unescaped by L{URI}.
        """
        uri = URI("scheme://localho%73t/host")
        self.assertEquals(uri.host, "localhost")

    def test_host_port(self):
        """
        The port can be specified in the uri string and is coerced to an
        integer.
        """
        uri = URI("scheme://localhost:1234/host")
        self.assertEquals(uri.host, "localhost")
        self.assertEquals(uri.port, 1234)

    def test_unescape_host_port(self):
        """
        The host is unescaped even when the port is specified.
        """
        uri = URI("scheme://localho%73t:1234/host")
        self.assertEquals(uri.host, "localhost")

    def test_invalid_port(self):
        """
        The port part of the uri string must be coercable to an integer:
        L{URI} raises a C{ValueError} if it's not the case.
        """
        self.assertRaises(ValueError, URI, "scheme://localhost:1234foo/host")


class ZAMQPTests(TestCase):
    """Tests for L{ZAMQP}."""

    def setUp(self):
        self.utility = queryUtility(IZAMQP)
        self.zamqp = ZAMQP()
        provideUtility(self.zamqp, IZAMQP)

    def tearDown(self):
        provideUtility(self.utility, IZAMQP)

    def test_implements(self):
        """
        L{ZAMQP} implements the L{IZAMQP} interface.
        """
        self.assertTrue(IZAMQP.providedBy(self.zamqp))

    def test_known_uri(self):
        """
        L{ZAMQP.get} returns L{URI} registered in L{ZAMQP.set_default_uri}.
        """
        self.zamqp.set_default_uri("test", "scheme://localhost/host")
        uri = self.zamqp.get("test")
        self.assertEquals(uri.host, "localhost")
        self.assertEquals(uri.vhost, "host")

    def test_unknow_uri(self):
        """
        L{ZAMQP.get} raises a C{ValueError} if no broker is registered for the
        given name.
        """
        self.assertRaises(KeyError, self.zamqp.get, "test")

    def test_zcml_broker_directive(self):
        """
        The C{amqp_broker} ZCML directive makes an URI available via a name in
        the L{IZAMQP} utility.
        """
        context = xmlconfig.file("meta.zcml",
                                 package=lazr.amqp.zope)
        zcml = """
<configure xmlns="http://namespaces.zope.org/zope">
  <amqp_broker name="broker1" uri="scheme://localhost/host" />
</configure>
"""
        xmlconfig.string(zcml, context)
        uri = self.zamqp.get("broker1")
        self.assertEquals(uri.host, "localhost")
        self.assertEquals(uri.vhost, "host")

    def test_zcml_invalid_broker_directive(self):
        """
        The C{amqp_broker} ZCML directive expects a name.
        """
        context = xmlconfig.file("meta.zcml",
                                 package=lazr.amqp.zope)
        zcml = """
<configure xmlns="http://namespaces.zope.org/zope">
  <amqp_broker uri="scheme://localhost/host" />
</configure>
"""
        self.assertRaises(
            xmlconfig.ZopeXMLConfigurationError,
            xmlconfig.string, zcml, context)


def test_suite():
    return defaultTestLoader.loadTestsFromName(__name__)
