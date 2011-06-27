# Copyright 2005-2010 Canonical Limited.  All rights reserved.

from zope.interface import Interface
from zope.schema import TextLine


class IAMQPBrokerDirective(Interface):

    name = TextLine(title=u"Name", description=u"Broker name")
    uri = TextLine(title=u"URI", description=u"Broker URI")
