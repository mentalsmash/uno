###############################################################################
# (C) Copyright 2021 Andrea Sorbini
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

UVN_DIR         ?= $(BUILD_DIR)/$(UVN)
UNO_ARCHIVES    ?= $(shell pwd)/archive

ifeq ($(UVN),)
$(warning no target UVN specified)
endif
ifeq ($(UVN_DIR),)
$(warning no target UVN_DIR specified)
endif
ifeq ($(UNO_DIR),)
$(warning no UNO_DIR specified)
endif

export UVN \
       UVN_DIR \
	   UNO_DIR \
	   UNO_ARCHIVES

ANSIBLE_ARGS_V = $(ANSIBLE_ARGS)

ifneq ($(UVN_VARS),)
ANSIBLE_ARGS_V += -e @$(UVN_VARS)
endif
ifneq ($(UVN_HOSTS),)
ANSIBLE_ARGS_V += -i $(UVN_HOSTS)
endif

UNO_PLAYBOOKS := $(UNO_DIR)/ansible

ansible.%: $(UNO_PLAYBOOKS)/%.yml
	ansible-playbook $(ANSIBLE_ARGS_V) $(UNO_PLAYBOOKS)/$*.yml

check: ansible.uno-check

install: ansible.uno-install

dist: $(UVN_DIR) \
      ansible.uvn-dist

start: ansible.uvn-start

stop: ansible.uvn-stop

.PHONY: check \
        install \
		dist \
		start \
		stop
