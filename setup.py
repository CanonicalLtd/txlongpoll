#!/usr/bin/env python
# Copyright 2005-2011 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Distutils installer for lazr.amqp."""

from setuptools import setup, find_packages


setup(
    name='lazr.amqp',
    version="0.2",
    packages=find_packages('.') + ['twisted.plugins'],
    package_data={
        'twisted': ['plugins/asyncfrontend_plugin.py'],
    },
    data_files=[('lazr/amqp/specs', ['lazr/amqp/specs/amqp0-8.xml'])],
    package_dir={'': '.'},
    include_package_data=True,
    zip_safe=False,
    description='Magic.',
    entry_points=dict(
        console_scripts=[
            'twistd = twisted.scripts.twistd:run',
        ]
    ),
    install_requires=[
        'rabbitfixture',
        'testresources',
        'testtools',
        'twisted',
        'txamqp',
        'zope.interface',
        ])
