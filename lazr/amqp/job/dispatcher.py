# Copyright 2005-2011 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

import json
import uuid
import logging
import threading
import transaction
from transaction.interfaces import IDataManager

from zope.interface import implements

from twisted.internet.defer import inlineCallbacks
from twisted.internet.threads import blockingCallFromThread
from twisted.internet import reactor

from txamqp.content import Content

from lazr.amqp.job.interfaces import IJobsDispatcher


__all__ = ["JobsDispatcher"]


class DispatcherAttributes(threading.local):
    """
    Thread-local object to store thread-sensitive attributes of
    L{JobsDispatcher}.
    """

    def __init__(self):
        super(DispatcherAttributes, self).__init__()
        self.queues = []
        self.jobs = []
        self.added = False


class JobsDispatcher(object):
    """
    Send job requests that will be run by the external job handler.

    @ivar _local: L{DispatcherAttributes} to store thread local variables.
    @ivar _channel: C{AMQChannel} to communicate with AMQP server.
    @ivar _client: C{AMQClient} connected to the AMQP server.
    """
    implements(IJobsDispatcher, IDataManager)

    def __init__(self, prefix):
        self._prefix = prefix
        self._local = DispatcherAttributes()
        self._channel = None
        self._client = None

    @inlineCallbacks
    def connected(self, (client, channel)):
        """Called by the C{AMQFactory} when connected to the AMQP server."""
        self._client = client
        self._channel = channel

        yield channel.exchange_declare(
            exchange="%s.notifications-exchange" % self._prefix, type="direct")
        yield channel.exchange_declare(
            exchange="%s.job-handler-exchange" % self._prefix, type="direct")

    def disconnected(self):
        """
        Called by the C{AMQFactory} when the connection with the AMQP server is
        lost.
        """
        self._channel = None
        self._client = None

    def get_queue_name(self, uuid):
        """Build a queue name from a UUID."""
        return "%s.notifications-queue.%s" % (self._prefix, uuid)

    def registerDataManager(self):
        """
        Register the dispatcher as L{IDataManager}, so that it's called when
        the transaction ends.

        @note: This is called in a thread which is not the main thread.
        """
        if not self._local.added:
            transaction.manager.get().join(self)
            self._local.added = True

    def create_job_queue(self, namespaces):
        """
        Create a new job queue, used to handle page messages.

        @note: This is called in a thread which is not the main thread.
        """
        self.registerDataManager()
        page_key = str(uuid.uuid4())
        self._local.queues.append((page_key, namespaces))
        return page_key

    def create_job(self, page_key, namespace, action, **kwargs):
        """
        Create a job request, returning the job identifier to be used to get
        the job result.

        @note: This is called in a thread which is not the main thread.
        """
        self.registerDataManager()
        kwargs["uuid"] = page_key
        kwargs["action"] = action
        kwargs["namespace"] = namespace
        self._local.jobs.append(kwargs)

    @inlineCallbacks
    def _declare_queue(self, page_key, namespaces):
        """
        Create the queue for the given C{page_key}, bind it to the proper
        C{namespaces}.

        @note: This has to be called in the main thread.
        """
        queue_name = self.get_queue_name(page_key)
        channel = self._channel
        yield channel.queue_declare(
            queue=queue_name, arguments={"x-expires": 300000})
        yield channel.queue_bind(queue=queue_name,
            exchange="%s.notifications-exchange" % self._prefix,
            routing_key=queue_name)
        for namespace in namespaces:
            yield channel.queue_bind(queue=queue_name,
                exchange="%s.notifications-exchange" % self._prefix,
                routing_key=namespace)

    def _publish_message(self, content):
        """Publish a message to the job handler queue.

        @note: This has to be called in the main thread.
        """
        return self._channel.basic_publish(
            content=content, exchange="%s.job-handler-exchange" % self._prefix,
            routing_key="%s.job-handler-queue" % self._prefix)

    def tpc_finish(self, txn):
        """
        Send created jobs and queues after commit, cleaning up local
        attributes.

        @note: This is called in a thread which is not the main thread.
        """
        if not reactor.running:
            logging.warning("Reactor is not running, unable to send messages.")
            return
        try:
            self._local.added = False

            for page_key, namespaces in self._local.queues:
                # Declare the queues in the main thread
                blockingCallFromThread(
                    reactor, self._declare_queue, page_key, namespaces)
            self._local.queues = []

            for kwargs in self._local.jobs:
                body = json.dumps(kwargs)
                content = Content(body)
                # Send the message in the main thread
                blockingCallFromThread(reactor, self._publish_message, content)

            self._local.jobs = []
        except Exception, e:
            logging.warning("Exception during message publication: %s" % (e,))
            try:
                # The connection is likely to be in an inconsistent state,
                # let's reconnect.
                blockingCallFromThread(
                    reactor, self._client.transport.loseConnection)
            except Exception:
                # We really don't want the transaction to break at that point.
                pass

    def abort(self, txn):
        """Clean created jobs and queues when aborting."""
        self._local.added = False
        self._local.queues = []
        self._local.jobs = []

    def tpc_begin(self, txn):
        pass

    def commit(self, txn):
        pass

    def tpc_vote(self, txn):
        pass

    def tpc_abort(self, txn):
        pass

    def sortKey(self):
        return "job_dispatcher_%d" % id(self)


global_jobs_dispatcher = JobsDispatcher("landscape")
