# Copyright 2005-2011 Canonical Ltd.  This software is licensed under
# the GNU Affero General Public License version 3 (see the file LICENSE).

"""
A rotatable log file for use with twisted's --logger option. Call twisted
with --logger=logger.rotatable_log
"""

import signal

from twisted.internet import reactor
from twisted.python.log import FileLogObserver
from twisted.python.logfile import LogFile

log_observer = None

def rotatable_log(filename="txlongpoll.log"):
    global log_observer

    if log_observer is not None:
        return log_observer

    logfile = LogFile.fromFullPath(
        filename, rotateLength=None, defaultMode=0644)

    def signal_handler(*args):
        reactor.callFromThread(logfile.reopen)

    if not signal.getsignal(signal.SIGUSR1):
        # Override if signal is set to None or SIG_DFL (0)
        signal.signal(signal.SIGUSR1, signal_handler)

    log_observer = FileLogObserver(logfile).emit
    return log_observer
