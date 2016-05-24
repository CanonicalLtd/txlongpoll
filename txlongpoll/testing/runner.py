# Copyright 2005-2016 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).
import io
import sys

from subunit.run import SubunitTestRunner, SubunitTestProgram
from subunit import get_default_formatter

from testresources import TestLoader

defaultTestLoader = TestLoader()


class OptimisingSubunitTestProgram(SubunitTestProgram):
    """Test program that uses testresources.OptimisingTestSuite by default."""

    def __init__(self, testLoader=defaultTestLoader, **kwargs):
        super(OptimisingSubunitTestProgram, self).__init__(
            testLoader=testLoader, **kwargs)


# XXX the main() function is copied from subunit.run, just replacing
#     SubunitTestProgram with OptimisingSubunitTestProgram, since there's
#     no other way to customise the test program/runner/loader.

def main():
    # Disable the default buffering, for Python 2.x where pdb doesn't do it
    # on non-ttys.
    get_default_formatter()
    runner = SubunitTestRunner
    # Patch stdout to be unbuffered, so that pdb works well on 2.6/2.7.
    binstdout = io.open(sys.stdout.fileno(), 'wb', 0)
    if sys.version_info[0] > 2:
        sys.stdout = io.TextIOWrapper(binstdout, encoding=sys.stdout.encoding)
    else:
        sys.stdout = binstdout
    OptimisingSubunitTestProgram(
        module=None, argv=sys.argv, testRunner=runner, stdout=sys.stdout)


if __name__ == '__main__':
    main()
