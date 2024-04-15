DSC_NAME := $(shell head -1 debian/changelog | awk '{print $1;}')
DEB_VERSION := $(shell head -1 debian/changelog | awk '{print $2;}' | tr -d '(' | tr -d ')')
UPSTREAM_VERSION := $(shell echo $(DEB_VERSION) | rev | cut -d- -f2- | rev)
UPSTREAM_TARBALL := $(DSC_NAME)_$(UPSTREAM_VERSION).orig.tar.xz
PY_VERSION := $(shell grep __version__ uno/__init__.py | cut -d= -f2- | tr -d \" | cut '-d ' -f2-)
PY_NAME := $(shell grep '^name =' pyproject.toml | cut -d= -f2- | tr -d \" | cut '-d ' -f2-)
DEB_BUILDER ?= mentalsmash/debian-builder:latest

ifneq ($(UPSTREAM_VERSION),$(PY_VERSION))
$(warning "unexpected debian upstream version ('$(UPSTREAM_VERSION)' != '$(PY_VERSION)')")
endif
ifneq ($(DSC_NAME),$(PY_NAME))
$(warning "unexpected debian source package name ('$(DSC_NAME)' != '$(PY_NAME)')")
endif

.PHONY: \
  build \
  tarball \
  clean \
  debuild \
  changelog

build: \
  build/default

build/%: ../$(UPSTREAM_TARBALL)
	rm -rf $@ build/pyinstaller-$*
	mkdir -p $@/src
	tar -xvaf $< -C $@/src
	scripts/bundle/pyinstaller.sh $*

clean:
	rm -rf build dist

tarball: ../$(UPSTREAM_TARBALL)

../$(UPSTREAM_TARBALL):
	git ls-files --recurse-submodules | tar -cvaf $@ -T-

debuild:
	docker run --rm -ti \
		-v $(pwd)/:/uno \
		$(DEB_BUILDER)  \
		/uno/scripts/debian_build.sh

changelog:
	docker run --rm -ti \
		-v $(pwd)/:/uno \
		$(DEB_BUILDER)  \
		/uno/scripts/bundle/update_changelog.sh
