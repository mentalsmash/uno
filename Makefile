VERSION :=  2.3.0
TARBALL := uno_$(VERSION).orig.tar.xz

BUILD_DIR := /opt/uno
UNO_DIR := $(BUILD_DIR)/src
VENV_DIR := $(BUILD_DIR)/venv

ifeq ($(UNO_FLAVOR),static)
	UNO_MIDDLEWARE :=
else
	UNO_MIDDLEWARE := uno_middleware_connext
endif

.PHONY: \
  build \
  tarball \
  clean

build: ../$(TARBALL)
	rm -rf $(UNO_DIR) $(VENV_DIR)
	mkdir -p $(UNO_DIR)
	tar -xvaf $< -C $(UNO_DIR)
	python3 -m venv $(VENV_DIR) \
	&& . $(VENV_DIR)/bin/activate \
	&& pip3 install -U pip setuptools \
	&& pip3 install $(UNO_DIR)
	set -e; \
	if [ -n "$(UNO_MIDDLEWARE)" ]; then \
		pip3 install $(UNO_DIR)/plugins/$(UNO_MIDDLEWARE); \
	fi

clean:
	rm -rf $(BUILD_DIR)

tarball: ../$(TARBALL)

../$(TARBALL):
	git ls-files --recurse-submodules | tar -cvaf $@ -T-
