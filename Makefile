VERSION :=  2.3.0
TARBALL := uno_$(VERSION).orig.tar.xz

.PHONY: \
  build \
  build-default \
  build-static \
  tarball \
  clean \
	clean-debian-tmp

build: \
  build-default \
  build-static


build-default: ../$(TARBALL) \
               clean-debian-tmp
	set -ex; \
	rm -rf /opt/uno; \
	mkdir -p /opt/uno; \
	tar -xvaf $< -C /opt/uno/src; \
	python3 -m venv /opt/uno/venv; \
	. /opt/uno/venv/bin/activate; \
	pip3 install -U pip setuptools; \
	pip3 install /opt/uno; \
	pip3 install /opt/uno/src/plugins/uno_middleware_connext; \
	mkdir -p \
	  debian/tmp/usr/bin \
		debian/tmp/opt
	mv /opt/uno debian/tmp/opt
	ln -s /opt/uno/venv/bin/uno debian/tmp/usr/bin/uno

build-static: ../$(TARBALL) \
               clean-debian-tmp
	set -ex; \
	rm -rf /opt/uno-static; \
	mkdir -p /opt/uno-static; \
	tar -xvaf $< -C /opt/uno-static/src; \
	python3 -m venv /opt/uno-static/venv; \
	. /opt/uno-static/venv/bin/activate; \
	pip3 install -U pip setuptools; \
	pip3 install /opt/uno-static; \
	mkdir -p \
	  debian/tmp/usr/bin \
		debian/tmp/opt
	mv /opt/uno-static debian/tmp/opt
	ln -s /opt/uno-static/venv/bin/uno debian/tmp/usr/bin/uno-static

clean-debian-tmp:
	rm -rf debian/tmp

clean:
	rm -rf /opt/uno /opt/uno-static

tarball: ../$(TARBALL)

../$(TARBALL):
	git ls-files --recurse-submodules | tar -cvaf $@ -T-
