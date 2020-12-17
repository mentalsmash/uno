#!/bin/sh -e
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

################################################################################
# Experiment Configuration
################################################################################
# ┌───────────────────────────────────────────────────────────────────────────┐
# |                                                                           |
# │                            CONNECTION LAYOUT                              │
# ├───────────────────────────────────────────────────────────────────────────┤
# |  Remote Host                           Local Host                         |
# | ┌────────────────────────────────┐     ┌────────────────────────────────┐ |
# | | ┌───────────────┐              |     |              ┌───────────────┐ | |
# │ │ │       ┌── router ─────┐      │     │      ┌──── router ──┐        │ │ │
# │ │ │ cell  │       │       │      │     │      │       │      │   cell │ │ │
# │ │ │   │ ┌─┴──┐    │       │      │     │      │       │    ┌─┴──┐ │   │ │ │
# │ │ │   └─┤org3│    │       │      │     │      │       │    │org1├─┘   │ │ │
# │ │ │     └─┬──┘    │       │      │     │      │       │    └─┬──┘     │ │ │
# │ │ │       │       │ ┌─────┴────┐ │     │ ┌────┴────┐  │      │        │ │ │
# │ │ │      host     │ │dmz-remote├───┐ ┌───┤dmz-local│  │     host      │ │ │
# │ │ └───────────────┘ └─────┬────┘ │ | | │ └──┬───┬──┘  └───────────────┘ │ │
# │ │                         │      │ │ │ │    │   │     ┌───────────────┐ │ │
# │ │               roam ─────┘      │ │ │ │    │   └── router ──┐        │ │ │
# │ │                                │ │ │ │    │         │      │   cell │ │ │
# │ └────────────────────────────────┘ │ │ │ babylon      │    ┌─┴──┐ │   │ │ │
# │                                    │ │ │              │    │org2├─┘   │ │ │
# │ ┌───────────────────┐              │ │ │              │    └─┬──┘     │ │ │
# │ │        lan        ├──────────────┘ │ │              │      │        │ │ │
# │ │                   ├────────────────┘ │              │     host      │ │ │
# │ └───────────────────┘                  │              └───────────────┘ │ │
# │                                        └────────────────────────────────┘ │
# ├───────────────────────────────────────────────────────────────────────────┤
# |                                                                           |
# │                          NETWORK CONFIGURATION                            │
# ├─────────────┬─────────────────────────────────────────────────────────────┤
# │ lan         │ 192.168.101.0/24 (router.lan)                               │
# ├──────┬──────┴──────────┬──────────────────────────────────────────────────┤
# │      │ router          │ 192.168.101.1                                    │
# ├──────┴──────┬──────────┴──────────────────────────────────────────────────┤
# │ dmz-local   │ 192.168.101.224/27 (router.lan)                             │
# ├──────┬──────┴──────────┬──────────────────────────────────────────────────┤
# │      │ babylon         │ 192.168.101.225                                  │
# │      ├─────────────────┼──────────────────────────────────────────────────┤
# │      │ router.org1     │ 192.168.101.226                                  │
# │      ├─────────────────┼──────────────────────────────────────────────────┤
# │      │ router.org2     │ 192.168.101.227                                  │
# ├──────┴──────┬──────────┴──────────────────────────────────────────────────┤
# │ dmz-remote  │ 192.168.101.192/27 (router.lan)                             │
# ├──────┬──────┴──────────┬──────────────────────────────────────────────────┤
# │      │ router.org3     │ 192.168.101.193                                  │
# │      ├─────────────────┼──────────────────────────────────────────────────┤
# │      │ roam            │ 192.168.101.194                                  │
# ├──────┴──────┬──────────┴──────────────────────────────────────────────────┤
# │ org1        │ 10.101.0.0/24                                               │
# ├──────┬──────┴──────────┬──────────────────────────────────────────────────┤
# │      │ router          │ 10.101.0.254                                     │
# │      ├─────────────────┼──────────────────────────────────────────────────┤
# │      │ cell            │ 10.101.0.2                                       │
# │      ├─────────────────┼──────────────────────────────────────────────────┤
# │      │ host            │ 10.101.0.3                                       │
# ├──────┴──────┬──────────┴──────────────────────────────────────────────────┤
# │ org2        │ 10.102.0.0/24                                               │
# ├──────┬──────┴──────────┬──────────────────────────────────────────────────┤
# │      │ router          │ 10.102.0.254                                     │
# │      ├─────────────────┼──────────────────────────────────────────────────┤
# │      │ cell            │ 10.102.0.2                                       │
# │      ├─────────────────┼──────────────────────────────────────────────────┤
# │      │ host            │ 10.102.0.3                                       │
# ├──────┴──────┬──────────┴──────────────────────────────────────────────────┤
# │ org3        │ 10.103.0.0/24                                               │
# ├──────┬──────┴──────────┬──────────────────────────────────────────────────┤
# │      │ router          │ 10.103.0.254                                     │
# │      ├─────────────────┼──────────────────────────────────────────────────┤
# │      │ cell            │ 10.103.0.2                                       │
# │      ├─────────────────┼──────────────────────────────────────────────────┤
# │      │ host            │ 10.103.0.3                                       │
# ├──────┴─────────────────┴──────────────────────────────────────────────────┤
# |                                                                           |
# │                           UVN CONFIGURATION                               │
# ├─────────────┬─────────────────────────────────────────────────────────────┤
# │ ADDRESS     │ babylon.lan                                                 │
# ├─────────────┼─────────────────────────────────────────────────────────────┤
# │ ADMIN       │ Root (root@babylon)                                         │
# ├─────────────┴─────────────────────────────────────────────────────────────┤
# │ CELLS                                                                     │
# ├─────────────┬──────────┬──────────────────────────────────────────────────┤
# │ org1.uvn    │ ADDRESS  │ router.org1.lan                                  │
# ├─────────────┼──────────┼──────────────────────────────────────────────────┤
# │             │ ADMIN    │ Alpha (alpha@org1)                               │
# ├─────────────┼──────────┼──────────────────────────────────────────────────┤
# │ org2.uvn    │ ADDRESS  │ router.org2.lan                                  │
# ├─────────────┼──────────┼──────────────────────────────────────────────────┤
# │             │ ADMIN    │ Beta (beta@org2)                                 │
# ├─────────────┼──────────┼──────────────────────────────────────────────────┤
# │ org3.uvn    │ ADDRESS  │ router.org3.lan                                  │
# ├─────────────┼──────────┼──────────────────────────────────────────────────┤
# │             │ ADMIN    │ Gamma (gamma@org3)                               │
# ├─────────────┼──────────┼──────────────────────────────────────────────────┤
# │ roam.uvn    │ ADDRESS  │ roam.lan                                         │
# ├─────────────┼──────────┼──────────────────────────────────────────────────┤
# │             │ ADMIN    │ Delta (delta@lan)                                │
# └─────────────┴──────────┴──────────────────────────────────────────────────┘
#
################################################################################
################################################################################
# Global Variables
################################################################################

TEST_UNO_INSTALL_DIR=${TEST_UNO_INSTALL_DIR:-/opt/uno}
TEST_HOST_REMOTE=${TEST_HOST_REMOTE:-192.168.101.8}
TEST_NIC_GW=${TEST_NIC_GW:-192.168.101.1}
TEST_NIC_LAN_IP_LOCAL=${TEST_NIC_LAN_IP_LOCAL:-192.168.101.85/24}
TEST_NIC_LAN_LOCAL=${TEST_NIC_LAN_LOCAL:-enp0s25}
TEST_NIC_BR_LOCAL=${TEST_NIC_BR_LOCAL:-br0}
TEST_NIC_LAN_REMOTE=${TEST_NIC_LAN_REMOTE:-eth0}
TEST_NIC_LAN_IP_REMOTE=${TEST_NIC_LAN_IP_REMOTE:-192.168.101.88/24}
TEST_NIC_BR_REMOTE=${TEST_NIC_BR_REMOTE:-${TEST_NIC_BR_LOCAL}}


# List of UVN cells
# TEST_CELLS_LOCAL="
# org1
# org2"

# TEST_CELLS_REMOTE="
# org3
# roam"
TEST_CELLS_LOCAL="
org1"

TEST_CELLS_REMOTE="
org3"

TEST_CELLS="
${TEST_CELLS_LOCAL}
${TEST_CELLS_REMOTE}"

# Name of all hosts in the experiment
# TEST_HOSTS_LOCAL="
# babylon.lan
# cell.org1
# cell.org2
# host.org1
# host.org2
# router.org1
# router.org2"

# TEST_HOSTS_REMOTE="
# roam.lan
# cell.org3
# host.org3
# router.org3"
TEST_HOSTS_LOCAL="
babylon.lan
cell.org1
host.org1
router.org1"

TEST_HOSTS_REMOTE="
cell.org3
host.org3
router.org3"

TEST_HOSTS="
${TEST_HOSTS_LOCAL}
${TEST_HOSTS_REMOTE}"

# List of all the test LANs
TEST_NETWORKS_LOCAL="
dmz-local
org1
org2"

TEST_NETWORKS_REMOTE="
dmz-remote
org3"

TEST_NETWORKS="
${TEST_NETWORKS_LOCAL}
${TEST_NETWORKS_REMOTE}"

# IP networks for the experiment
NET_lan=192.168.101.0/24
NET_dmz_local=192.168.101.224/27
NET_dmz_remote=192.168.101.192/27
NET_org1=10.101.0.0/24
NET_org2=10.102.0.0/24
NET_org3=10.103.0.0/24

# IP addresses for hosts attached to LAN org1
IP_org1_docker=10.101.0.1
IP_org1_router=10.101.0.254
IP_org1_cell=10.101.0.2
IP_org1_host=10.101.0.3

# IP addresses for hosts attached to LAN org2
IP_org2_docker=10.102.0.1
IP_org2_router=10.102.0.254
IP_org2_cell=10.102.0.2
IP_org2_host=10.102.0.3

# IP addresses for hosts attached to LAN org3
IP_org3_docker=10.103.0.1
IP_org3_router=10.103.0.254
IP_org3_cell=10.103.0.2
IP_org3_host=10.103.0.3

# IP addresses for hosts attached to local LAN
IP_lan_router=192.168.101.1
IP_lan_org1_router=192.168.101.226
IP_lan_org2_router=192.168.101.227
IP_lan_org3_router=192.168.101.193
IP_lan_roam=192.168.101.194
IP_lan_babylon=192.168.101.225

# UDP ports that will be forwarded to cell nodes
PORT_forward="63450 63451 63452 63453"


################################################################################
# /etc/hosts helpers
################################################################################
etc_hosts_lan()
{
    etc_hosts_line  router.lan              ${IP_lan_router} >> ${1}
    etc_hosts_line  router.org1.lan         ${IP_lan_org1_router} >> ${1}
    etc_hosts_line  router.org2.lan         ${IP_lan_org2_router} >> ${1}
    etc_hosts_line  router.org3.lan         ${IP_lan_org3_router} >> ${1}
    etc_hosts_line  roam.lan                ${IP_lan_roam} >> ${1}
    etc_hosts_line  babylon.lan             ${IP_lan_babylon} >> ${1}
    log_info "[added] network hosts: internet -> ${1}"
}

etc_hosts_org1()
{
    etc_hosts_line  router.org1             ${IP_org1_router} >> ${1}
    etc_hosts_line  cell.org1               ${IP_org1_cell} >> ${1}
    etc_hosts_line  host.org1               ${IP_org1_host} >> ${1}
    log_info "[added] network hosts: org1 -> ${1}"
}

etc_hosts_org2()
{
    etc_hosts_line  router.org2             ${IP_org2_router} >> ${1}
    etc_hosts_line  cell.org2               ${IP_org2_cell} >> ${1}
    etc_hosts_line  host.org2               ${IP_org2_host} >> ${1}
    log_info "[added] network hosts: org2 -> ${1}"
}

etc_hosts_org3()
{
    etc_hosts_line  router.org3             ${IP_org3_router} >> ${1}
    etc_hosts_line  cell.org3               ${IP_org3_cell} >> ${1}
    etc_hosts_line  host.org3               ${IP_org3_host} >> ${1}
    log_info "[added] network hosts: org3 -> ${1}"
}

etc_hosts_all()
{
    etc_hosts_lan ${1}
    etc_hosts_org1 ${1}
    etc_hosts_org2 ${1}
    etc_hosts_org3 ${1}
}

################################################################################
# Initialize UVN
################################################################################
test_rc_uvn()
{
    # Initialize new uvn
    rm -rf ${UVN_DIR} ${CELLS_DIR}
    uvn_create              babylon.lan             root@babylon    "Root"

    # Create cells
    uvn_attach  org1        router.org1.lan         alpha@org1      "Alpha"
    # uvn_attach  org2        router.org2.lan         beta@org2       "Beta"
    uvn_attach  org3        router.org3.lan         gamma@org3      "Gamma"
    # uvn_attach  roam        roam.lan                delta@babylon   "Delta"

    # Create deployment
    uvn_deploy

    # Install deployment packages
    rm -rf ${CELLS_DIR}
    uvn_install     babylon.lan     org1
    # uvn_install     babylon.lan     org2
    uvn_install     babylon.lan     org3
    # uvn_install     babylon.lan     roam
}

################################################################################
# Create docker images, networks, and containers
################################################################################
test_rc_cleanup_docker_local()
{
    docker_wipe_containers      ${TEST_HOSTS_LOCAL}
    docker_wipe_networks        ${TEST_NETWORKS_LOCAL}
}

test_rc_cleanup_docker_remote()
{
    docker_wipe_containers      ${TEST_HOSTS_REMOTE}
    docker_wipe_networks        ${TEST_NETWORKS_REMOTE}
}

test_rc_docker_local()
{
    test_rc_cleanup_docker_local

    # Create uvn-runner image
    uvn_runner      "${UVN_DIR}"

    # Define test networks
    docker_bridge_create   ${TEST_NIC_BR_LOCAL} \
                           ${TEST_NIC_LAN_LOCAL} \
                           ${TEST_NIC_LAN_IP_LOCAL} \
                           ${NET_dmz_local}
    docker_network_w_bridge dmz \
                            ${NET_lan} \
                            ${TEST_NIC_BR_LOCAL} \
                            ${NET_dmz_local} \
                            ${TEST_NIC_GW} \
                            "${IP_lan_roam} ${IP_lan_org3_router} ${IP_lan_router}"
    docker_network          org1        ${NET_org1}     ${IP_org1_router}
    # docker_network          org2        ${NET_org2}     ${IP_org2_router}

    # Create router containers
    docker_container    router      org1        ${IP_org1_router}
    # docker_container    router      org2        ${IP_org2_router}
    docker_connect  router.org1     dmz         ${IP_lan_org1_router}
    # docker_connect  router.org2     dmz         ${IP_lan_org2_router}

    # Create uvn containers
    docker_container    cell        org1        ${IP_org1_cell}         ${CELLS_DIR}/org1
    # docker_container    cell        org2        ${IP_org2_cell}         ${CELLS_DIR}/org2
    (host_has_domain=y docker_container    babylon.lan     dmz         ${IP_lan_babylon}       ${UVN_DIR})

    # Create host containers
    docker_container    host        org1        ${IP_org1_host}
    # docker_container    host        org2        ${IP_org2_host}
}

test_rc_docker_remote()
{
    test_rc_cleanup_docker_remote

    # Create uvn-runner image
    first_cell=$(printf -- "${TEST_CELLS_REMOTE}" | tr '\n' ' ' |awk '{print $1;}')
    log_info "initializing uvn-runner from '${first_cell}'"
    uvn_runner      "${CELLS_DIR}/${first_cell}"

    # Define test networks
    docker_bridge_create   ${TEST_NIC_BR_REMOTE} \
                           ${TEST_NIC_LAN_REMOTE} \
                           ${TEST_NIC_LAN_IP_REMOTE} \
                           ${NET_dmz_remote}
    docker_network_w_bridge dmz \
                            ${NET_lan} \
                            ${TEST_NIC_BR_REMOTE} \
                            ${NET_dmz_remote} \
                            ${TEST_NIC_GW} \
                            "${IP_lan_org1_router} ${IP_lan_org2_router} ${IP_lan_babylon}"
    docker_network          org3        ${NET_org3}     ${IP_org2_router}

    # Create router containers
    docker_container    router      org3        ${IP_org3_router}
    docker_connect  router.org3     dmz         ${IP_lan_org3_router}

    # Create uvn containers
    docker_container    cell        org3        ${IP_org3_cell}     ${CELLS_DIR}/org3
    # (host_has_domain=y docker_container    roam.lan        dmz         ${IP_lan_roam}      ${CELLS_DIR}/roam)

    # Create host containers
    docker_container    host        org3        ${IP_org3_host}
}

# Initialize experiment environement directories
test_rc_docker_env()
{
    # Delete experiments directory
    rm -rf ${EXPERIMENT_DIR}

    for h in ${TEST_HOSTS}; do
        setvars_docker_env_files ${h}

        log_debug " creating container environment: ${h_dir}"

        # Create host experiment directory
        mkdir -p ${h_dir}

        # Add static entries to /etc/hosts
        etc_hosts_all ${h_hosts}

        # Copy common init script
        cp ${INIT_COMMON} ${h_common}

        # Copy init script based on host type.
        case ${h} in
        router.*)
            # Copy router init script
            cp ${INIT_ROUTER} ${h_init}
            ;;
        *)
            # Copy (regular) host init script
            cp ${INIT_HOST} ${h_init}
            ;;
        esac

        # Generate host-specific network configuration
        case ${h} in
        babylon.lan)
            network_info_host "${h_network}" ${NET_lan} ${IP_lan_babylon}
            ;;
        cell.org1)
            network_info_host "${h_network}" ${NET_org1} ${IP_org1_cell}
            ;;
        cell.org2)
            network_info_host "${h_network}" ${NET_org2} ${IP_org2_cell}
            ;;
        cell.org3)
            network_info_host "${h_network}" ${NET_org3} ${IP_org3_cell}
            ;;
        host.org1)
            network_info_host "${h_network}" ${NET_org1} ${IP_org1_cell}
            ;;
        host.org2)
            network_info_host "${h_network}" ${NET_org2} ${IP_org2_cell}
            ;;
        host.org3)
            network_info_host "${h_network}" ${NET_org3} ${IP_org3_cell}
            ;;
        roam.lan)
            network_info_host "${h_network}" ${NET_lan} ${IP_lan_roam}
            ;;
        router.org1)
            network_info_router "${h_network}" \
                ${NET_org1} ${IP_org1_router} \
                ${NET_lan} ${IP_lan_org1_router}
            network_forward_udp_ports ${h_forward} "${PORT_forward}" ${IP_org1_cell}
            ;;
        router.org2)
            network_info_router "${h_network}"  \
                ${NET_org2} ${IP_org2_router} \
                ${NET_lan} ${IP_lan_org2_router}
            network_forward_udp_ports ${h_forward} "${PORT_forward}" ${IP_org2_cell}
            ;;
        router.org3)
            network_info_router "${h_network}" \
                ${NET_org3} ${IP_org3_router} \
                ${NET_lan} ${IP_lan_org3_router}
            network_forward_udp_ports ${h_forward} "${PORT_forward}" ${IP_org3_cell}
            ;;
        esac

        chmod +x ${h_dir}/*.sh

        log_info "[created] container environment: ${h_dir}"
    done
}

################################################################################
# Start docker containers
################################################################################
# Start docker containers
test_rc_start_local()
{
    # Start hosts in LAN org1
    docker_start        router.org1
    docker_start        cell.org1
    docker_start        host.org1
    
    # Start hosts in LAN org2
    # docker_start        router.org2
    # docker_start        cell.org2
    # docker_start        host.org2
    
    # Start hosts in local LAN
    docker_start        babylon.lan
}

# Start docker containers
test_rc_start_remote()
{
    # Start hosts in LAN org3
    docker_start        router.org3
    docker_start        cell.org3
    docker_start        host.org3
    
    # Start hosts in local LAN
    # docker_start        roam.lan
}

################################################################################
# Monitor docker containers
################################################################################

# Start and monitor local docker containers
test_rc_tmux_local()
{
    local session="uvndemo"
    local win_ctrl="${session}        1" \
          win_cell_logs="${session}   2" \
          win_cell_ctrl="${session}   3" \
          win_registry="${session}    4" \
          win_router_logs="${session} 5" \
          win_router_ctrl="${session} 6" \
          win_host_logs="${session}   7" \
          win_host_ctrl="${session}   8"
    
    tmux_session ${session}

    # Create windows
    tmux_window ${session} 1 "ctrl"
    tmux_window ${session} 2 "cell logs"
    tmux_window ${session} 3 "cell ctrl"
    tmux_window ${session} 4 "registry"
    tmux_window ${session} 5 "router logs"
    tmux_window ${session} 6 "router ctrl"
    tmux_window ${session} 7 "host logs"
    tmux_window ${session} 8 "host ctrl"

    # Close default window
    tmux_kill_window ${session} 0

    # Window 1 [ctrl]
    # ------------------------------
    # | ctrl        | ctrl         |
    # | local       | remote       |
    # |             |              |
    # ------------------------------
    tmux_split_pane_vertical   ${win_ctrl} 0

    tmux send-keys -t "${session}:1.0" \
        "docker start ${TEST_HOSTS_LOCAL}" C-m
    
    tmux send-keys -t "${session}:1.0" \
        "ssh ${TEST_HOST_REMOTE} docker start ${TEST_HOSTS_REMOTE}" C-m
    

    # Window 1 [Cell Logs]
    # ------------------------------
    # | org1        | org2         |
    # ------------------------------
    # | org3        | roam         |
    # ------------------------------
    tmux_split_pane_vertical   ${win_cell_logs} 0
    tmux_split_pane_horizontal ${win_cell_logs} 0
    tmux_split_pane_horizontal ${win_cell_logs} 2

    tmux_container_logs ${win_cell_logs} 0 cell.org1
    # tmux_container_logs ${win_cell_logs} 1 cell.org2

    tmux send-keys -t "${session}:2.2" \
        "ssh ${TEST_HOST_REMOTE} docker logs -f cell.org3" C-m
    # tmux send-keys -t "${session}:2.3" \
    #     "ssh ${TEST_HOST_REMOTE} docker logs -f roam.lan" C-m

    # Window 2 [Cell Ctrl]
    # ------------------------------
    # | org1        | org2         |
    # ------------------------------
    # | org3        | roam         |
    # ------------------------------

    tmux_split_pane_vertical   ${win_cell_ctrl} 0
    tmux_split_pane_horizontal ${win_cell_ctrl} 0
    tmux_split_pane_horizontal ${win_cell_ctrl} 2

    tmux_container_sh ${win_cell_ctrl} 0 cell.org1
    # tmux_container_sh ${win_cell_ctrl} 1 cell.org2

    tmux send-keys -t "${session}:3.2" \
        "ssh ${TEST_HOST_REMOTE} docker exec -ti cell.org3 bash" C-m
    # tmux send-keys -t "${session}:3.3" \
    #     "ssh ${TEST_HOST_REMOTE} docker exec -ti roam.lan bash" C-m

    # Window 3 [Registry]
    # ------------------------------
    # | babylon     | babylon      |
    # | logs        | ctrl         |
    # |             |              |
    # ------------------------------

    tmux_split_pane_horizontal ${win_registry} 0

    tmux_container_logs ${win_registry} 0 babylon.lan
    tmux_container_sh   ${win_registry} 1 babylon.lan

    # Window 4 [Router Logs]
    # ------------------------------
    # | org1        | org2         |
    # ------------------------------
    # | org3                       |
    # ------------------------------

    tmux_split_pane_vertical   ${win_router_logs} 0
    tmux_split_pane_horizontal ${win_router_logs} 0

    tmux_container_logs ${win_router_logs} 0 router.org1
    # tmux_container_logs ${win_router_logs} 1 router.org2

    tmux send-keys -t "${session}:5.2" \
        "ssh ${TEST_HOST_REMOTE} docker logs -f router.org3" C-m

    # Window 5 [Router Ctrl]
    # ------------------------------
    # | org1        | org2         |
    # ------------------------------
    # | org3                       |
    # ------------------------------

    tmux_split_pane_vertical   ${win_router_ctrl} 0
    tmux_split_pane_horizontal ${win_router_ctrl} 0

    tmux_container_sh ${win_router_ctrl} 0 router.org1
    # tmux_container_sh ${win_router_ctrl} 1 router.org2
    tmux send-keys -t "${session}:6.3" \
        "ssh ${TEST_HOST_REMOTE} docker exec -ti router.org3 bash" C-m

    # Window 1 [Host Logs]
    # ------------------------------
    # | org1        | org2         |
    # ------------------------------
    # | org3                       |
    # ------------------------------

    tmux_split_pane_vertical   ${win_host_logs} 0
    tmux_split_pane_horizontal ${win_host_logs} 0

    tmux_container_logs ${win_host_logs} 0 host.org1
    # tmux_container_logs ${win_host_logs} 1 host.org2

    tmux send-keys -t "${session}:7.2" \
        "ssh ${TEST_HOST_REMOTE} docker logs -f host.org3" C-m

    # Window 2 [Host Ctrl]
    # ------------------------------
    # | org1        | org2         |
    # ------------------------------
    # | org3                       |
    # ------------------------------

    tmux_split_pane_vertical   ${win_host_ctrl} 0
    tmux_split_pane_horizontal ${win_host_ctrl} 0

    tmux_container_sh ${win_host_ctrl} 0 host.org1
    # tmux_container_sh ${win_host_ctrl} 1 host.org2
    tmux send-keys -t "${session}:8.3" \
        "ssh ${TEST_HOST_REMOTE} docker exec -ti host.org3 bash" C-m

    # Switch to first window
    tmux_select_pane ${win_cell_logs} 0

    # Attach to tmux
    tmux attach
}

################################################################################
# 
################################################################################

_run_remote_test_stage()
{
    local test_rc="${1}"
    if [ -n "${LOCAL_ONLY}" ]; then
        log_info "skipping remote test stage: ${test_rc}"
        return 0
    fi
    ${SSH} ${TEST_HOST_REMOTE} \
        "cd ${TEST_DIR} &&
        export OAUTH_TOKEN=${OAUTH_TOKEN} &&
        export VERBOSE=${VERBOSE} &&
        export NOOP=${NOOP} &&
        export DEBUG=${DEBUG} &&
        export IGNORE_ERRORS=${IGNORE_ERRORS} &&
        export TEST_RC_MIN=${test_rc} &&
        export TEST_RC_MAX=${test_rc} &&
        ${TEST_UNO_INSTALL_DIR}/test/local_deploy/experiment_rpi.sh remote"
}

################################################################################
################################################################################
# BEGIN SCRIPT
################################################################################
################################################################################

################################################################################
# Load library of helper functions
################################################################################
# Directory containing this script and other helpers
TEST_LIB_DIR=$(cd $(dirname "${0}") && pwd)
. "${TEST_LIB_DIR}/experiment_lib.sh"

################################################################################
# Perform test stages
################################################################################

if [ -z "${1}" ]; then

    ! test_rc_check ${TEST_RC_UVN}          || test_rc_uvn
    ! test_rc_check ${TEST_RC_DOCKER}       || test_rc_docker_env
    ! test_rc_check ${TEST_RC_DOCKER}       || test_rc_docker_local

    ! test_rc_check ${TEST_RC_UVN}          || (

        ${SSH} ${TEST_HOST_REMOTE} \
            "rm -rf ${EXPERIMENT_DIR} ${CELLS_DIR} &&
                mkdir -p ${EXPERIMENT_DIR} ${CELLS_DIR}"
        
        ${SSH} ${TEST_HOST_REMOTE} \
            "cd ${TEST_UNO_INSTALL_DIR} && git pull"

        ${RSYNC} -rav ${EXPERIMENT_DIR}/ ${TEST_HOST_REMOTE}:${EXPERIMENT_DIR}/
        for c in ${TEST_CELLS_REMOTE}; do
            ${RSYNC} -rav ${CELLS_DIR}/${c} ${TEST_HOST_REMOTE}:${CELLS_DIR}/
        done
    )
    ! test_rc_check ${TEST_RC_UVN}          || _run_remote_test_stage UVN
    ! test_rc_check ${TEST_RC_DOCKER}       || _run_remote_test_stage DOCKER
    ! test_rc_check ${TEST_RC_START}        || _run_remote_test_stage START
    
    ! test_rc_check ${TEST_RC_START}        || test_rc_start_local
    ! test_rc_check ${TEST_RC_MONITOR}      || test_rc_monitor

    ! test_rc_check ${TEST_RC_CLEANUP}      || _run_remote_test_stage CLEANUP
    ! test_rc_check ${TEST_RC_CLEANUP}      || (
        docker_bridge_delete ${TEST_NIC_BR_LOCAL} \
                             ${TEST_NIC_LAN_LOCAL} \
                             ${TEST_NIC_LAN_IP_LOCAL}
        test_rc_cleanup_docker_local
        docker_wipe_images uvn-runner
    )

elif [ "remote" = "${1}" ]; then
    ! test_rc_check ${TEST_RC_DOCKER}       || test_rc_docker_remote
    ! test_rc_check ${TEST_RC_START}        || test_rc_start_remote

    ! test_rc_check ${TEST_RC_CLEANUP}      || (
        docker_bridge_delete ${TEST_NIC_BR_REMOTE} \
                             ${TEST_NIC_LAN_REMOTE} \
                             ${TEST_NIC_LAN_IP_REMOTE}
        test_rc_cleanup_docker_remote
        docker_wipe_images uvn-runner
    )
fi
