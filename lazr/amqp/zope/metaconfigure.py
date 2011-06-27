# Copyright 2005-2010 Canonical Limited.  All rights reserved.

from zope import component

from lazr.amqp.zope.interfaces import IZAMQP


def set_default_uri(name, uri):
    zamqp = component.getUtility(IZAMQP)
    zamqp.set_default_uri(name, uri)


def amqp_broker(context, name, uri):
    context.action(discriminator=("amqp_broker", name),
                   callable=set_default_uri,
                   args=(name, uri))
