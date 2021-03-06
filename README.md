## Generic long poll server used by Launchpad and Landscape.
[![Build Status](https://travis-ci.org/CanonicalLtd/txlongpoll.svg?branch=master)](https://travis-ci.org/CanonicalLtd/txlongpoll)
### Dependencies

By default txlongpoll attempts to fetch resources from the internet.

instead it tries 
and you must download all the dependencies yourself.

If you prefer to find all dependencies from download-cache/dist, then
prepend OFFLINE=1 to your make commands:

    $ OFFLINE=1 make build
    $ OFFLINE=1 make check


### Building

    $ make build

will build only those parts needed to run txlongpoll. No support for
tags or testing.


### Testing

    $ make check

will build all the test-related parts of txlongpoll and then do a full
test run, but

    $ make bin/testpy

will just do the first part.

There is testrepository <https://launchpad.net/testrepository>
support, so you can also do the following:

    $ testr init
    $ testr run

This is probably the best way to develop txlongpoll.


### Continous Integration

The lp:txlongpoll branch is mirrored on GitHub using a Launchpad webhook:

https://github.com/CanonicalLtd/txlongpoll

Travis builds will be triggered at each commit:

https://travis-ci.org/CanonicalLtd/txlongpoll/builds


### Running

   $ bin/twistd txlongpoll
