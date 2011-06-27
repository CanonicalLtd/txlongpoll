# Copyright 2005-2010 Canonical Limited.  All rights reserved.

import signal

from twisted.trial.unittest import TestCase

from twisted.python.failure import Failure
from twisted.python import log


class FakeThreadPool(object):
    """
    A fake L{twisted.python.threadpool.ThreadPool}, running function inside the
    main thread instead for easing tests.
    """

    def callInThreadWithCallback(self, onResult, func, *args, **kw):
        success = True
        try:
            result = func(*args, **kw)
        except:
            result = Failure()
            success = False

        onResult(success, result)


class TwistedTestCase(TestCase):

    def setUp(self):
        if log.defaultObserver is not None:
            log.defaultObserver.stop()

    def tearDown(self):
        if log.defaultObserver is not None:
            log.defaultObserver.start()
        TestCase.tearDown(self)
        # Trial should restore the handler itself, but doesn't.
        # See bug #3888 in Twisted tracker.
        signal.signal(signal.SIGINT, signal.default_int_handler)
