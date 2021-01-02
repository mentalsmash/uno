###############################################################################
# (C) Copyright 2020 Andrea Sorbini
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as 
# published by the Free Software Foundation, either version 3 of the 
# License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.
###############################################################################

SRC_DIR     ?= $(shell pwd)/uvns
BUILD_DIR   ?= $(shell pwd)/build
UVNS        ?= $(patsubst $(SRC_DIR)/%.yml, %, $(wildcard $(SRC_DIR)/*.yml))

################################################################################

ifneq ($(VERBOSE),)
  UNO_ARGS += -vv
else
  UNO_ARGS += -v
endif

ifneq ($(KEEP),)
  UNO_ARGS += -k
endif

ifneq ($(DEPLOY),)
  UNO_ARGS_DEPLOY += -d
endif

################################################################################

define TGT_CELL
$(shell printf "%s" '$(1)' | cut -d. -f 1)
endef

define TGT_UVN
$(shell printf "%s" '$(1)' | cut -d. -f 2-)
endef

define CELL_INSTALLER_NAME
uvn-$(call TGT_UVN,$(1))-bootstrap-$(call TGT_CELL,$(1)).zip
endef

define CELL_INSTALLER
$(BUILD_DIR)/$(call TGT_UVN,$(1))/installers/$(call CELL_INSTALLER_NAME,$(1))
endef

SHYAML   ?= shyaml

SHYAML_VERSION := $(shell $(SHYAML) --version 2>/dev/null)

ifeq ($(SHYAML_VERSION),)
$(error shyaml binary not available: '$(SHYAML)')
endif

define Q_CELLS_COUNT
$$(cat $(1) | $(SHYAML) get-length cells)
endef

define Q_CELL_NAME
$$(printf $$(cat $(1) | $(SHYAML) -y get-value cells.$(2) | $(SHYAML) get-value name))
endef

define Q_CELLS
$(shell for i in $$(seq 0 $$(expr $(call Q_CELLS_COUNT,$(1)) - 1)); do \
  echo $(call Q_CELL_NAME,$(1),$${i}); \
done)
endef

define Q_CELL_N
$(shell for i in $$(seq 0 $$(expr $(call Q_CELLS_COUNT,$(1)) - 1)); do \
  cell_name="$(call Q_CELL_NAME,$(1),$${i})"; \
  [ "$${cell_name}" = "$(2)" ] || continue; \
  echo $${i};\
  break;\
done)
endef

define Q_CELL_HOST
$(shell cat $(1) | $(SHYAML) get-value cells.$(call Q_CELL_N,$(1),$(2)).address)
endef

define Q_CELL_INTERFACES
$(shell n=$(call Q_CELL_N,$(1),$(2)); \
for i in $$(seq 0 $$(expr $$(cat $(1) | $(SHYAML) get-length cells.$${n}.agent.nics) - 1)); do \
  cat $(1) | $(SHYAML) get-value cells.$${n}.agent.nics.$${i}; \
done)
endef

define UVN_CELLS
$(call Q_CELLS,$(SRC_DIR)/$(1).yml)
endef

define TGT_CELL_HOST
$(call Q_CELL_HOST,$(SRC_DIR)/$(call TGT_UVN,$(1)).yml,$(call TGT_CELL,$(1)))
endef

define TGT_CELL_INTERFACES
$(shell for intf in $(call Q_CELL_INTERFACES,$(SRC_DIR)/$(call TGT_UVN,$(1)).yml,$(call TGT_CELL,$(1))); do\
  printf -- "-i %s " "$${intf}"; \
done)
endef

.PHONY: all \
        create \
        clean

all:
	@echo available UVNs: $(UVNS)

create: $(UVNS:%=$(BUILD_DIR)/%)
	@echo Generated UVNs: $(UVNS)

clean: $(UVNS:%=%.clean)
	@echo Cleaned up UVNs: $(UVNS)

%.clean:
	rm -rf $(BUILD_DIR)/$*
	@echo Cleaned up UVN: $*

$(BUILD_DIR)/%: $(SRC_DIR)/%.yml
	rm -rf $@
	uvn c $(UNO_ARGS_DEPLOY) $(UNO_ARGS) \
	      -f $(SRC_DIR)/$*.yml \
		  $@
	cd $@ && uvn i $(UNO_ARGS)
