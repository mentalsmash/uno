VERSION :=  2.3.0
TARBALL := uno_$(VERSION).orig.tar.xz

.PHONY: \
  build \
  tarball \
  clean \
	clean-debian-tmp

build: \
  build/default \
  build/static

build/default: ../$(TARBALL)
	set -ex; \
	rm -rf \
    build/default \
    /opt/uno; \
	mkdir -p /opt/uno/src; \
	tar -xvaf $< -C /opt/uno/src; \
	python3 -m venv /opt/uno/venv; \
	. /opt/uno/venv/bin/activate; \
	pip3 install -U pip setuptools; \
	pip3 install /opt/uno/src; \
	pip3 install /opt/uno/src/plugins/uno_middleware_connext; \
	pip3 uninstall --yes pip setuptools; \
	mkdir -p build/default/usr/bin
	ln -s /opt/uno/venv/bin/uno build/default/usr/bin/uno
	mv /opt/uno build/default

build/static: ../$(TARBALL)
	set -ex; \
	rm -rf \
    build/static \
    /opt/uno-static; \
	mkdir -p /opt/uno-static/src; \
	tar -xvaf $< -C /opt/uno-static/src; \
	python3 -m venv /opt/uno-static/venv; \
	. /opt/uno-static/venv/bin/activate; \
	pip3 install -U pip setuptools; \
	pip3 install /opt/uno-static/src; \
	pip3 uninstall --yes pip setuptools; \
	mkdir -p build/static/usr/bin
	ln -s /opt/uno-static/venv/bin/uno build/static/usr/bin/uno-static
	mv /opt/uno-static build/static/

clean-debian-tmp:
	rm -rf debian/tmp

clean:
	rm -rf /opt/uno /opt/uno-static

tarball: ../$(TARBALL)

../$(TARBALL):
	git ls-files --recurse-submodules | tar -cvaf $@ -T-
