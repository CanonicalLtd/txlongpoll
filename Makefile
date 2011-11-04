# Copyright 2005-2011 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

PYTHON = python

BUILDOUT_BIN := bin/buildout
BUILDOUT_CFG := buildout.cfg
BUILDOUT := $(BUILDOUT_BIN) -qc $(BUILDOUT_CFG)


default: check


build: bin/py bin/twistd


check: bin/test
	bin/test -vv


dist: bin/py
	bin/py setup.py egg_info -r sdist


TAGS: bin/tags
	bin/tags --ctags-emacs


tags: bin/tags
	bin/tags --ctags-vi


update-paths:
	$(BUILDOUT)


download-cache:
	mkdir -p download-cache


eggs:
	mkdir -p eggs


$(BUILDOUT_BIN): download-cache eggs
	PYTHONPATH= $(PYTHON) bootstrap.py \
	    --setup-source=ez_setup.py \
	    --download-base=download-cache/dist \
	    --eggs=eggs --version=1.5.2
	touch --no-create $@


bin/py bin/twistd: $(BUILDOUT_BIN) $(BUILDOUT_CFG) setup.py
	$(BUILDOUT) install runtime


bin/test: $(BUILDOUT_BIN) $(BUILDOUT_CFG) setup.py
	$(BUILDOUT) install test


bin/tags: $(BUILDOUT_BIN) $(BUILDOUT_CFG) setup.py
	$(BUILDOUT) install tags


clean_buildout:
	$(RM) -r bin
	$(RM) -r parts
	$(RM) -r develop-eggs
	$(RM) .installed.cfg
	$(RM) -r build
	$(RM) -r dist


clean_eggs:
	$(RM) -r download-cache
	$(RM) -r *.egg-info
	$(RM) -r eggs


clean: clean_buildout
	find txlongpoll twisted -name '*.py[co]' -print0 | xargs -r0 $(RM)

clean_all: clean_buildout clean_eggs


.PHONY: \
    build check clean clean_all clean_buildout clean_eggs default \
    dist update-paths
