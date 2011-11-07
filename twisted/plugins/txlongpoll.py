# Copyright 2005-2011 Canonical Ltd.  This software is licensed under
# the GNU Affero General Public License version 3 (see the file LICENSE).

from __future__ import absolute_import

from txlongpoll.plugin import AMQServiceMaker

# Construct objects which *provide* the relevant interfaces. The name of
# these variables is irrelevant, as long as there are *some* names bound to
# providers of IPlugin and IServiceMaker.

service_amqp_longpoll = AMQServiceMaker(
    "amqp-longpoll", "An AMQP -> HTTP long-poll bridge. *Note* that "
    "the `amqp-longpoll' name is deprecated; please use `txlongpoll' "
    "instead.")

service_txlongpoll = AMQServiceMaker(
    "txlongpoll", "An AMQP -> HTTP long-poll bridge.")
