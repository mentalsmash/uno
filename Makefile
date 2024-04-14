
BUILD_DIR := build/uno
UNO_DIR := $(BUILD_DIR)/src
VENV_DIR := $(BUILD_DIR)/venv

ifeq ($(UNO_FLAVOR),static)
	UNO_MIDDLEWARE :=
else
	UNO_MIDDLEWARE := uno_middleware_connext
endif

.PHONY: build

build:
	rm -rf $(UNO_DIR) $(VENV_DIR)
	mkdir -p $(UNO_DIR)
	git ls-files --recurse-submodules | tar -c -T- | tar -x -C $(UNO_DIR)
	# git archive HEAD | tar -x -C $(UNO_DIR)
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
