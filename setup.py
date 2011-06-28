#!/usr/bin/env python
# Copyright 2005-2011 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Distutils installer for lazr.amqp."""

from setuptools import setup, find_packages


def get_revno():
    import bzrlib.errors
    import bzrlib.workingtree
    try:
        t = bzrlib.workingtree.WorkingTree.open_containing(__file__)[0]
    except (bzrlib.errors.NotBranchError, bzrlib.errors.NoWorkingTree):
        return None
    else:
        return t.branch.revno()


def get_version():
    return "0.0.1-r%s" % get_revno()

setup(
    name='lazr.amqp',
    version="0",#,get_version(),
    packages=find_packages('.'),
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
        'transaction',
        'twisted',
        'txamqp',
        'zope.component',
        'zope.configuration',
        'zope.interface',
        'zope.schema',
        ])
