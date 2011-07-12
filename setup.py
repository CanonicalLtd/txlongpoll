#!/usr/bin/env python
# Copyright 2005-2011 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Distutils installer for lazr.amqp."""

from setuptools import setup, find_packages


setup(
    name='lazr.amqp',
    version="0.2",
    packages=find_packages('.') + ['twisted.plugins'],
    data_files=[('lazr/amqp/specs', ['lazr/amqp/specs/amqp0-8.xml'])],
    package_dir={'': '.'},
    include_package_data=True,
    zip_safe=False,
    description='Magic.',
    install_requires=[
        'amqplib',
        'fixtures',
        'rabbitfixture',
        'testresources',
        'testtools',
        'transaction',
        'twisted',
        'txamqp',
        'zope.component',
        'zope.configuration',
        'zope.interface',
        'zope.schema',
        ])
