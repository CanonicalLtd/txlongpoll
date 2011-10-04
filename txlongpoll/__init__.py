# Copyright 2005-2011 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

def run():
    from sys import argv
    argv[1:1] = ["--logfile=/dev/null", "txlongpoll"]
    import twisted.scripts.twistd
    twisted.scripts.twistd.run()
