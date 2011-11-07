#!/usr/bin/env python
# Copyright 2005-2011 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Distutils installer for txlongpoll."""

from setuptools import (
    find_packages,
    setup,
    )


setup(
    name='txlongpoll',
    version="0.2.10",
    packages=find_packages('.') + ['twisted.plugins'],
    include_package_data=True,
    zip_safe=False,
    description='Long polling HTTP frontend for AMQP',
    install_requires=[
        'oops_amqp',
        'oops_datedir_repo',
        'oops_twisted >= 0.0.3',
        'setproctitle',
        'Twisted',
        'txAMQP >= 0.5',
        'zope.interface',
        ],
    extras_require=dict(
        test=[
            'rabbitfixture',
            'testresources >= 0.2.4_r58',
            'testtools',
            # 'subunit',  # Not easy-installable.
            ],
        ))
