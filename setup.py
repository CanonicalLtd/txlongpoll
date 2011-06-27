#!/usr/bin/env python
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
    install_requires=[
        'storm',
        'transaction',
        'twisted',
        'txamqp',
        'zope.component',
        'zope.configuration',
        'zope.interface',
        'zope.schema',
        ])
