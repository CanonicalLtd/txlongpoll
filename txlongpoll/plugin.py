# Copyright 2005-2011 Canonical Ltd.  This software is licensed under
# the GNU Affero General Public License version 3 (see the file LICENSE).

from __future__ import (
    print_function,
    unicode_literals,
    )

__all__ = [
    "AMQServiceMaker",
    ]

from formencode import Schema
from formencode.api import set_stdtranslation
from formencode.validators import (
    Int,
    RequireIfPresent,
    String,
    )
from twisted.application.internet import (
    TCPClient,
    TCPServer,
    )
from twisted.application.service import (
    IServiceMaker,
    MultiService,
    )
from twisted.plugin import IPlugin
from twisted.python import (
    log,
    usage,
    )
from twisted.web.server import Site
from txlongpoll.client import AMQFactory
from txlongpoll.frontend import (
    FrontEndAjax,
    QueueManager,
    )
from txlongpoll.services import (
    LogService,
    OOPSService,
    )
import yaml
from zope.interface import implements


# Ensure that formencode does not translate strings; there are encoding issues
# that are easier to side-step for now.
set_stdtranslation(languages=[])


class ConfigOops(Schema):
    """Configuration validator for OOPS options."""

    if_key_missing = None

    directory = String(if_missing=b"")
    reporter = String(if_missing=b"LONGPOLL")

    chained_validators = (
        RequireIfPresent("reporter", present="directory"),
        )


class ConfigBroker(Schema):
    """Configuration validator for message broker options."""

    if_key_missing = None

    host = String(if_missing=b"localhost")
    port = Int(min=1, max=65535, if_missing=5672)
    username = String(if_missing=b"guest")
    password = String(if_missing=b"guest")
    vhost = String(if_missing="/")


class ConfigFrontend(Schema):
    """Configuration validator for the front-end service."""

    if_key_missing = None

    port = Int(min=1, max=65535, if_missing=8001)
    prefix = String(if_missing=None)
    interface = String(if_missing=None)


class Config(Schema):
    """Configuration validator."""

    if_key_missing = None

    oops = ConfigOops
    broker = ConfigBroker
    frontend = ConfigFrontend

    logfile = String(
        if_empty=b"txlongpoll.log",
        if_missing=b"txlongpoll.log")

    @classmethod
    def parse(cls, stream):
        """Load a YAML configuration from `stream` and validate."""
        return cls.to_python(yaml.load(stream))

    @classmethod
    def load(cls, filename):
        """Load a YAML configuration from `filename` and validate."""
        with open(filename, "rb") as stream:
            return cls.parse(stream)


class Options(usage.Options):

    optParameters = [
        ["config-file", "c", "etc/txlongpoll.yaml",
         "Configuration file to load."],
        ]


class AMQServiceMaker(object):
    """Create an asynchronous frontend server for AMQP."""

    implements(IServiceMaker, IPlugin)

    options = Options

    def __init__(self, name, description):
        self.tapname = name
        self.description = description

    def makeService(self, options):
        """Construct a service."""
        services = MultiService()

        config_file = options["config-file"]
        config = Config.load(config_file)

        log_service = LogService(config["logfile"])
        log_service.setServiceParent(services)

        oops_config = config["oops"]
        oops_dir = oops_config["directory"]
        oops_reporter = oops_config["reporter"]
        oops_service = OOPSService(log_service, oops_dir, oops_reporter)
        oops_service.setServiceParent(services)

        frontend_config = config["frontend"]
        frontend_port = frontend_config["port"]
        frontend_prefix = frontend_config["prefix"]
        frontend_interface = frontend_config["interface"]
        frontend_manager = QueueManager(frontend_prefix)

        broker_config = config["broker"]
        broker_port = broker_config["port"]
        broker_host = broker_config["host"]
        broker_username = broker_config["username"]
        broker_password = broker_config["password"]
        broker_vhost = broker_config["vhost"]

        cb_connected = frontend_manager.connected
        cb_disconnected = frontend_manager.disconnected
        cb_failed = lambda connector_and_reason: (
            log.err(connector_and_reason[1], "Connection failed"))

        client_factory = AMQFactory(
            broker_username, broker_password, broker_vhost,
            cb_connected, cb_disconnected, cb_failed)
        client_service = TCPClient(
            broker_host, broker_port, client_factory)
        client_service.setName("amqp")
        client_service.setServiceParent(services)

        frontend_resource = FrontEndAjax(frontend_manager)
        frontend_service = TCPServer(
            frontend_port, Site(frontend_resource),
            interface=frontend_interface)
        frontend_service.setName("frontend")
        frontend_service.setServiceParent(services)

        return services
