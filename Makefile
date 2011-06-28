# Copyright 2005-2011 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

PYTHON = python
PY = $(PWD)/bin/py

BUILDOUT_CFG = buildout.cfg

# Do not add bin/buildout to this list. It is impossible to get
# buildout to tell us all the files it would build, since each egg's
# setup.py doesn't tell us that information.
#
# NB: It's important BUILDOUT_BIN only mentions things genuinely
# produced by buildout.
BUILDOUT_BIN = $(PY) bin/tags bin/test bin/twistd


default: check


download-cache:
	mkdir download-cache


bin/buildout: download-cache
	$(PYTHON) bootstrap.py
	touch --no-create $@


$(PY): bin/buildout $(BUILDOUT_CFG) setup.py
	PYTHONPATH=. ./bin/buildout -c $(BUILDOUT_CFG)


$(subst $(PY),,$(BUILDOUT_BIN)): $(PY)


build: $(BUILDOUT_BIN)


check: bin/test
	./bin/test -vv


.PHONY: build check default
