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

UVND_TARGETS      := dist \
                     start \
                     stop \
                     list \
                     deploy \
                     update

.PHONY: $(UVND_TARGETS)

%.registry.list:
	ssh $* "bash -l -c uvn_status"

%.cell.list:
	@echo Checking status for $*
	ssh $(call TGT_CELL_HOST,$*) "bash -l -c uvn_status"

%.registry.update:
	ssh $* "bash -l -c uno_update"

%.cell.update:
	ssh $(call TGT_CELL_HOST,$*) "bash -l -c uno_update"

%.registry.dist: $(BUILD_DIR)/%
	ssh $* sudo rm -rf $*
	rsync -rav --exclude="S.gpg-agent" $(BUILD_DIR)/$* $*:~

%.cell.dist:
	rsync -rav $(call CELL_INSTALLER,$*) $(call TGT_CELL_HOST,$*):~
	ssh $(call TGT_CELL_HOST,$*) "\
		sudo rm -rf $(call TGT_CELL,$*)@$(call TGT_UVN,$*) && \
		uvn I $(call CELL_INSTALLER_NAME,$*) \
		    $(call TGT_CELL,$*)@$(call TGT_UVN,$*)"

%.registry.start: %.registry.dist \
                  %.cells.start
	ssh $* bash -l -c 'uvnd_restart'

%.registry.stop:
	ssh $* bash -l -c 'uvnd_stop'

%.startwait: %.start
	@echo Waiting $(UVND_START_WAIT) seconds for agent to start
	sleep $(UVND_START_WAIT)

%.registry.deploy: %.registry.startwait
	ssh $* bash -l -c 'uvnd_deploy'

%.cell.deploy:
	@echo > /dev/null

%.cell.start: %.cell.dist \
              %.cell.stop
	ssh $(call TGT_CELL_HOST,$*) \
	    bash -l -c 'uvnd_cell "$(call TGT_CELL_INTERFACES,$*)"'

%.cell.stop:
	ssh $(call TGT_CELL_HOST,$*) bash -l -c 'uvnd_stop'

$(foreach tgt,$(UVND_TARGETS),\
  $(eval $(tgt): $(UVNS:%=%.$(tgt)))\
  $(foreach uvn,$(UVNS),\
    $(eval $(uvn).$(tgt): $(uvn).registry.$(tgt) $(uvn).cells.$(tgt))\
    $(eval $(uvn).cells.$(tgt): $(foreach cell,$(call UVN_CELLS,$(uvn)), $(cell).$(uvn).cell.$(tgt)))\
	))
