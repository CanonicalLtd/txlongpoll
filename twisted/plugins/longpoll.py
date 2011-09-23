# Copyright 2005-2011 Canonical Ltd.  This software is licensed under
# the GNU Affero General Public License version 3 (see the file LICENSE).

import signal

from zope.interface import implements

from oops_datedir_repo import DateDirRepo
from oops_twisted import (
    Config as oops_config,
    defer_publisher,
    OOPSObserver,
    )
from twisted.application.internet import TCPServer, TCPClient
from twisted.application.service import IServiceMaker, MultiService
from twisted.plugin import IPlugin
from twisted.python import log, usage
from twisted.python.log import (
    addObserver,
    FileLogObserver
    )
from twisted.python.logfile import LogFile
from twisted.web.server import Site

from txlongpoll.client import AMQFactory
from txlongpoll.frontend import QueueManager, FrontEndAjax


def getRotatableLogFileObserver(filename):
    """Setup a L{LogFile} for the given application."""
    logfile = LogFile.fromFullPath(
        filename, rotateLength=None, defaultMode=0644)

    def signal_handler(*args):
        logfile.reopen()

    signal.signal(signal.SIGUSR1, signal_handler)
    return FileLogObserver(logfile)


def setUpOopsHandler(options):
    """Add OOPS handling based on the passed command line options."""
    config = oops_config()

    # Add the oops publisher that writes files in the configured place
    # if the command line option was set.
    if options["oops-dir"]:
        repo = DateDirRepo(options["oops-dir"], options["oops-prefix"])
        config.publishers.append(defer_publisher(repo))

    # Add the log file observers. The second observer is to put OOPSes
    # in the log too.
    logfile = getRotatableLogFileObserver(options["logfile"])
    observer = OOPSObserver(config, logfile.emit)
    addObserver(observer.emit)


class Options(usage.Options):
    optParameters = [
        ["logfile", "l", "txlongpoll.log", "Logfile name."],
        ["brokerport", "p", 5672, "Broker port"],
        ["brokerhost", "h", '127.0.0.1', "Broker host"],
        ["brokeruser", "u", None, "Broker user"],
        ["brokerpassword", "a", None, "Broker password"],
        ["brokervhost", "v", '/', "Broker vhost"],
        ["frontendport", "f", None, "Frontend port"],
        ["prefix", "x", 'XXX', "Queue prefix"],
        ["oops-dir", "r", None, "Where to write OOPS reports"],
        ["oops-prefix", "o", "LONGPOLL", "String prefix for OOPS IDs"],
        ]

    def postOptions(self):
        for man_arg in ('frontendport', 'brokeruser', 'brokerpassword'):
            if not self[man_arg]:
                raise usage.UsageError("--%s must be specified." % man_arg)
        for int_arg in ('brokerport', 'frontendport'):
            try:
                self[int_arg] = int(self[int_arg])
            except (TypeError, ValueError):
                raise usage.UsageError("--%s must be an integer." % int_arg)


class AMQServiceMaker(object):
    """Create an asynchronous frontend server for AMQP."""
    implements(IServiceMaker, IPlugin)
    tapname = "amqp-longpoll"
    description = "An AMQP long-poll HTTP service."

    options = Options

    def makeService(self, options):
        """Construct a TCPServer and TCPClient. """
        setUpOopsHandler(options)

        broker_port = options["brokerport"]
        broker_host = options["brokerhost"]
        broker_user = options["brokeruser"]
        broker_password = options["brokerpassword"]
        broker_vhost = options["brokervhost"]
        frontend_port = options["frontendport"]
        prefix = options["prefix"]

        manager = QueueManager(prefix)
        factory = AMQFactory(
            broker_user, broker_password, broker_vhost, manager.connected,
            manager.disconnected,
            lambda (connector, reason): log.err(reason, "Connection failed"))
        resource = FrontEndAjax(manager)

        client_service = TCPClient(broker_host, broker_port, factory)
        server_service = TCPServer(frontend_port, Site(resource))
        services = MultiService()
        services.addService(client_service)
        services.addService(server_service)

        return services


# Now construct an object which *provides* the relevant interfaces
# The name of this variable is irrelevant, as long as there is *some*
# name bound to a provider of IPlugin and IServiceMaker.

serviceMaker = AMQServiceMaker()
