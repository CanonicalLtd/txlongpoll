# Copyright 2005-2011 Canonical Ltd.  This software is licensed under
# the GNU Affero General Public License version 3 (see the file LICENSE).

import signal

from zope.interface import implements

from twisted.application.internet import TCPServer, TCPClient
from twisted.application.service import IServiceMaker, MultiService
from twisted.plugin import IPlugin
from twisted.python import log, usage
from twisted.python.log import ILogObserver, FileLogObserver
from twisted.python.logfile import LogFile
from twisted.web.server import Site

from lazr.amqp.async.client import AMQFactory
from lazr.amqp.async.frontend import QueueManager, FrontEndAjax


def setUpLogFile(application, filename):
    """Setup a L{LogFile} for the given application."""
    logfile = LogFile.fromFullPath(
        filename, rotateLength=None, defaultMode=0644)

    def signal_handler(*args):
        logfile.reopen()

    signal.signal(signal.SIGUSR1, signal_handler)
    application.setComponent(ILogObserver, FileLogObserver(logfile).emit)


class Options(usage.Options):
    optParameters = [
        ["logfile", "l", None, "Optional logfile name."],
        ["brokerport", "p", 5672, "Broker port"],
        ["brokerhost", "h", '127.0.0.1', "Broker host"],
        ["brokeruser", "u", None, "Broker user"],
        ["brokerpassword", "a", None, "Broker password"],
        ["brokervhost", "v", '127.0.0.1', "Broker vhost"],
        ["frontendport", "f", None, "Frontend port"],
        ["prefix", "x", 'XXX', "Queue prefix"],
        ]

    def postOptions(self):
        if not self['frontendport']:
            raise usage.UsageError("--frontendport must be specified.")
        try:
            self['brokerport'] = int(self['brokerport'])
        except (TypeError, ValueError):
            raise usage.UsageError("--brokerport must be an integer.")
        try:
            self['frontendport'] = int(self['frontendport'])
        except (TypeError, ValueError):
            raise usage.UsageError("--frontendport must be an integer.")


class AMQServiceMaker(object):
    """Create an asynchronous frontend server for AMQP."""
    implements(IServiceMaker, IPlugin)
    tapname = "amqp-longpoll"
    description = "An AMQP long-poll HTTP service."

    options = Options

    def makeService(self, options):
        """Construct a TCPServer and TCPClient. """
        # See Twisted bug 638.
        #if options["logfile"]:
        #    setUpLogFile(application, options["logfile"])

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
