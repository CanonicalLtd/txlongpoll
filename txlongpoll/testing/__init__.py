# Copyright 2005-2011 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).
from testtools import run
from testresources import OptimisingTestSuite

# It seems there's no way to indicate the desired suite class to use via the
# command line, so we set it in the module directly. Since this is the only
# tweak we need, it's not worth creating a custom run() entry point and
# instantiating a test runner/loader by hand.
run.defaultTestLoaderCls.suiteClass = OptimisingTestSuite
