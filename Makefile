# Copyright 2005-2011 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

PYTHON = python
# Whether to build offline, using a download-cache
OFFLINE ?= 0

BOOTSTRAP_BIN := bootstrap.py
BOOTSTRAP_FLAGS := --eggs=eggs --version=1.5.2
ifeq "$(OFFLINE)" "1"
BOOTSTRAP_FLAGS += \
    --setup-source=download-cache/dist/ez_setup.py \
    --download-base=download-cache/dist
endif
BOOTSTRAP = PYTHONPATH= $(PYTHON) $(BOOTSTRAP_BIN) $(BOOTSTRAP_FLAGS)

BUILDOUT_BIN := bin/buildout
BUILDOUT_CFG := buildout.cfg
BUILDOUT_FLAGS := -qc $(BUILDOUT_CFG)
ifeq "$(OFFLINE)" "1"
BUILDOUT_FLAGS += buildout:install-from-cache=true
endif
BUILDOUT = PYTHONPATH= $(BUILDOUT_BIN) $(BUILDOUT_FLAGS)


default: check

build: bin/twistd


# When a built tree is moved this updates absolute paths.
build-update-paths:
	$(BUILDOUT)


check: bin/testpy
	bin/testpy -m testtools.run -- discover


dist: $(BUILDOUT_BIN)
	$(BUILDOUT) setup setup.py egg_info -r sdist


TAGS: bin/tags
	bin/tags --ctags-emacs


tags: bin/tags
	bin/tags --ctags-vi


download-cache:
	mkdir -p download-cache


eggs:
	mkdir -p eggs


$(BUILDOUT_BIN): download-cache eggs
	$(BOOTSTRAP)
	touch --no-create $@


bin/twistd: $(BUILDOUT_BIN) $(BUILDOUT_CFG) setup.py
	$(BUILDOUT) install runtime


bin/testpy: $(BUILDOUT_BIN) $(BUILDOUT_CFG) setup.py
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
    build build-update-paths check clean clean_all clean_buildout \
    clean_eggs default dist
