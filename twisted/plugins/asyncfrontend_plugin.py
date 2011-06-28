# Copyright 2005-2011 Canonical Ltd.  This software is licensed under
# the GNU Affero General Public License version 3 (see the file LICENSE).

import signal

from zope.interface import implements

from twisted.application.internet import TCPServer, TCPClient
from twisted.application.service import (
    Application, IServiceMaker, MultiService)
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
        ["brokerport", "p", None, "Broker port"],
        ["brokerhost", "h", None, "Broker host"],
        ["brokeruser", "u", None, "Broker user"],
        ["brokerpassword", "a", None, "Broker password"],
        ["brokervhost", "v", None, "Broker vhost"],
        ["frontendport", "f", None, "Frontend port"],
        ]


class AMQServiceMaker(object):
    """Create an asynchronous frontend server for AMQP."""
    implements(IServiceMaker, IPlugin)
    tapname = "asyncfrontend"
    description = """
        Asynchronous frontend server.

        This application contains 2 components: the queue manager, which
        received queue creation commands from the Web UI and subscribes to
        them, and the Ajax frontend, which receives HTTP calls from Javascript
        and gets messages from the queue manager.
        """

    options = Options

    def makeService(self, options):
        """Construct a TCPServer and TCPClient. """
        # See Twisted bug 638.
        #if options["logfile"]:
        #    setUpLogFile(application, options["logfile"])

        broker_port = int(options["brokerport"])
        broker_host = options["brokerhost"]
        broker_user = options["brokeruser"]
        broker_password = options["brokerpassword"]
        broker_vhost = options["brokervhost"]
        frontend_port = int(options["frontendport"])

        manager = QueueManager("XXX")
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

