#!/bin/sh -ex
###############################################################################

################################################################################
# Experiment Configuration
################################################################################
# ┌───────────────────────────────────────────────────────────────────────────┐
# |                                                                           |
# │                            CONNECTION LAYOUT                              │
# ├───────────────────────────────────────────────────────────────────────────┤
# |                                                                           |
# |                                ┌──────────┐                               |
# │            ┌───────────────┐   │ babylon  │   ┌───────────────┐           │
# │            │       ┌── router ───┐  │  ┌─── router ──┐        │           │
# │            │ cell  │       │   │ │  │  │  │   │      │   cell │           │
# │            │   │ ┌─┴──┐    │   │ │  │  │  │   │    ┌─┴──┐ │   │           │
# │            │   └─┤org1│    │   │ │  │  │  │   │    │org2├─┘   │           │
# │            │     └─┬──┘    │   │ │  │  │  │   │    └─┬──┘     │           │
# │            │       │       │   │ │  │  │  │   │      │        │           │
# │            │      host     │   │┌┴──┴──┴─┐│   │     host      │           │
# │            └───────────────┘   ││internet├──┐ └───────────────┘           │
# │                                │└┬──┬────┘│ │                             │
# │            ┌───────────────┐   │ │  │     │ │ ┌───────────────┐           │
# │            │       ┌── router ───┘  │     │ router ──┐        │           │
# │            │ cell  │       │   │   roam   │   │      │   cell │           │
# │            │   │ ┌─┴──┐    │   └──────────┘   │    ┌─┴──┐ │   │           │
# │            │   └─┤org3│    │                  │    │org4├─┘   │           │
# │            │     └─┬──┘    │                  │    └─┬──┘     │           │
# │            │       │       │                  │      │        │           │
# │            │      host     │                  │     host      │           │
# │            └───────────────┘                  └───────────────┘           │
# |                                                                           |
# ├───────────────────────────────────────────────────────────────────────────┤
# |                                                                           |
# │                          NETWORK CONFIGURATION                            │
# ├─────────────┬─────────────────────────────────────────────────────────────┤
# │ internet    │ 10.230.255.0/24 (router.internet)                           │
# ├──────┬──────┴──────────┬──────────────────────────────────────────────────┤
# │      │ babylon         │ 10.230.255.253                                   │
# │      ├─────────────────┼──────────────────────────────────────────────────┤
# │      │ router          │ 10.230.255.254                                   │
# │      ├─────────────────┼──────────────────────────────────────────────────┤
# │      │ router.org1     │ 10.230.255.2                                     │
# │      ├─────────────────┼──────────────────────────────────────────────────┤
# │      │ router.org2     │ 10.230.255.3                                     │
# │      ├─────────────────┼──────────────────────────────────────────────────┤
# │      │ router.org3     │ 10.230.255.4                                     │
# │      ├─────────────────┼──────────────────────────────────────────────────┤
# |      │ roam            │ 10.230.255.50                                    │
# ├──────┴──────┬──────────┴──────────────────────────────────────────────────┤
# │ org1        │ 10.230.254.0/24                                             │
# ├──────┬──────┴──────────┬──────────────────────────────────────────────────┤
# │      │ router          │ 10.230.254.254                                   │
# │      ├─────────────────┼──────────────────────────────────────────────────┤
# │      │ cell            │ 10.230.254.2                                     │
# │      ├─────────────────┼──────────────────────────────────────────────────┤
# │      │ host            │ 10.230.254.3                                     │
# ├──────┴──────┬──────────┴──────────────────────────────────────────────────┤
# │ org2        │ 10.230.253.0/24                                             │
# ├──────┬──────┴──────────┬──────────────────────────────────────────────────┤
# │      │ router          │ 10.230.253.254                                   │
# │      ├─────────────────┼──────────────────────────────────────────────────┤
# │      │ cell            │ 10.230.253.2                                     │
# │      ├─────────────────┼──────────────────────────────────────────────────┤
# │      │ host            │ 10.230.253.3                                     │
# ├──────┴──────┬──────────┴──────────────────────────────────────────────────┤
# │ org3        │ 10.230.252.0/24                                             │
# ├──────┬──────┴──────────┬──────────────────────────────────────────────────┤
# │      │ router          │ 10.230.252.254                                   │
# │      ├─────────────────┼──────────────────────────────────────────────────┤
# │      │ cell            │ 10.230.252.2                                     │
# │      ├─────────────────┼──────────────────────────────────────────────────┤
# │      │ host            │ 10.230.252.3                                     │
# ├──────┴──────┬──────────┴──────────────────────────────────────────────────┤
# │ org4        │ 10.230.251.0/24                                             │
# ├──────┬──────┴──────────┬──────────────────────────────────────────────────┤
# │      │ router          │ 10.230.251.254                                   │
# │      ├─────────────────┼──────────────────────────────────────────────────┤
# │      │ cell            │ 10.230.251.2                                     │
# │      ├─────────────────┼──────────────────────────────────────────────────┤
# │      │ host            │ 10.230.251.3                                     │
# └──────┴─────────────────┴──────────────────────────────────────────────────┘
################################################################################
################################################################################
# Global Variables
################################################################################
TEST_NETWORKS_PRIVATE_COUNT=${TEST_NETWORKS_PRIVATE_COUNT:-${NETS}}
if [ -z "${TEST_NETWORKS_PRIVATE_COUNT}" ]; then
    if [ -n "${EXTRA_NETS}" ]; then
        TEST_NETWORKS_PRIVATE_COUNT=8
    else
        TEST_NETWORKS_PRIVATE_COUNT=4
        # TEST_NETWORKS_PRIVATE_COUNT=1
    fi
fi
if [ "${TEST_NETWORKS_PRIVATE_COUNT}" -gt 4 ]; then
    EXTRA_NETS=y
fi

# Name of all hosts in the experiment
TEST_HOSTS_PRIVATE=$(
    for n in $(seq 1 ${TEST_NETWORKS_PRIVATE_COUNT}); do
        printf "cell.org${n} host.org${n} router.org${n} "
    done
)

TEST_HOSTS="
${TEST_HOSTS_PRIVATE}
babylon.internet
roam.internet
"

# List of all the test LANs
TEST_NETWORKS_PRIVATE=$(
    for n in $(seq 1 ${TEST_NETWORKS_PRIVATE_COUNT}); do
        printf "org${n} "
    done
)

TEST_NETWORKS="
internet
${TEST_NETWORKS_PRIVATE}"

# IP networks for the experiment
NET_internet=10.230.255.0/24

_define_test_network()
{
    local net="${1}" \
          net_id="${2}" \
          n_ip="${2}" \
          p_ip="${2}"

    n_ip=$(expr 255 - ${n_ip})
    p_ip=$(expr ${p_ip} + 1)
    eval "export NET_${net}=10.230.${n_ip}.0/24"
    eval "export IP_${net}_docker=10.230.${n_ip}.1"
    eval "export IP_${net}_router=10.230.${n_ip}.254"
    eval "export IP_${net}_cell=10.230.${n_ip}.2"
    eval "export IP_${net}_host=10.230.${n_ip}.3"
    eval "export IP_internet_${net}_router=10.230.255.${p_ip}"
}

nid=1
for net in ${TEST_NETWORKS_PRIVATE}; do
    _define_test_network ${net} ${nid}
    nid=$(expr ${nid} + 1)
done

# IP addresses for hosts attached LAN internet
IP_internet_router=10.230.255.254
IP_internet_roam=10.230.255.50
IP_internet_babylon=10.230.255.253

# UDP ports that will be forwarded to cell nodes
PORT_forward="63448 63449 $(for i in $(seq 1 ${TEST_NETWORKS_PRIVATE_COUNT}); do expr ${i} + 63449; done | xargs)"
PORT_forward_registry="63550"

################################################################################
# /etc/hosts helpers
################################################################################
etc_hosts_internet()
{
    local outfile="${1}"

    etc_hosts_line  router.internet         ${IP_internet_router} >> ${outfile}
    for net in ${TEST_NETWORKS_PRIVATE}; do
        etc_hosts_line  router.${net}.internet \
                        $(eval "echo \${IP_internet_${net}_router}") >> ${outfile}
    done
    etc_hosts_line  roam.internet           ${IP_internet_roam} >> ${outfile}
    etc_hosts_line  babylon.internet        ${IP_internet_babylon} >> ${outfile}
    log_debug "[added] network hosts: internet -> ${outfile}"
}

etc_hosts_subnet()
{
    local outfile="${1}" \
          net="${2}"

    etc_hosts_line  router.${net}   $(eval "echo \${${IP_${net}_router}}") >> ${outfile}
    etc_hosts_line  cell.${net}     $(eval "echo \${${IP_${net}_cell}}") >> ${outfile}
    etc_hosts_line  host.${net}     $(eval "echo \${${IP_${net}_host}}") >> ${outfile}
    log_debug "[added] network hosts: ${net} -> ${outfile}"
}

etc_hosts_all()
{
    etc_hosts_internet ${1}
    for net in ${TEST_NETWORKS_PRIVATE}; do
        etc_hosts_subnet ${1} ${net}
    done
    log_info "[added] network hosts -> ${1}"
}

################################################################################
# Initialize UVN
################################################################################
# Initialize new uvn
test_rc_uvn_create()
{
    ${SUDO} rm -rf ${UVN_DIR} ${CELLS_DIR}
    uvn_create              babylon.internet        root@babylon    "Root"
}


# Create cells
test_rc_uvn_attach()
{
    if [ -n "${TEST_ROAM}" ]; then
        CELL_ROAMING=y \
        uvn_attach roam roam.internet admin@internet "Internet's Administrator"
    fi

    for net in ${TEST_NETWORKS_PRIVATE}; do
        if printf -- "${HOST_ONLY_CELLS}\n" | grep -q ${net}; then
            continue
        fi
        if printf -- "${TEST_NETWORKS_BEHIND_NAT}\n" | grep -q ${net}; then
            local net_address=
        else
            local net_address=router.${net}.internet
        fi

        uvn_attach ${net} \
                   "${net_address}" \
                   admin@${net} \
                   "${net}'s Administrator"
    done

}

# Define nameserver entries
test_rc_uvn_ns()
{
    # for net in ${TEST_NETWORKS_PRIVATE}; do
    #     uvn_ns ${net} router.${net} $(eval "echo \${IP_${net}_router}") "lan router gw"
    #     uvn_ns ${net} cell.${net}   $(eval "echo \${IP_${net}_cell}")   "lan cell router"
    #     uvn_ns ${net} host.${net}   $(eval "echo \${IP_${net}_host}")   "lan host"
    # done
    true
}

test_rc_uvn_particles()
{
    local i=1
    for n in ${TEST_NETWORKS_PRIVATE}; do
        uvn_particle particle${i} "Particle ${n} Owner <particle@${n}>"
        i=$(expr ${i} + 1)
    done
}

# Create deployment
test_rc_uvn_deploy()
{
    uvn_deploy
}

# Install deployment packages
test_rc_uvn_install()
{
    if [ -n "${PREDEPLOY}" ]; then
        local with_deployment=with_deployment
    fi
    
    rm -rf ${CELLS_DIR}
    for net in ${TEST_NETWORKS_PRIVATE}; do
        if printf -- "${HOST_ONLY_CELLS}\n" | grep -q ${net}; then
            continue
        fi
        uvn_install     babylon.internet    ${net}    ${with_deployment}
    done

    if [ -n "${TEST_ROAM}" ]; then
        uvn_install     babylon.internet    roam  ${with_deployment}
    fi
}

test_rc_uvn_backup()
{
    uvn_backup
}

test_rc_uvn_restore()
{
    uvn_restore
}

################################################################################
# Create docker images, networks, and containers
################################################################################
# Wipe docker containers and networks
test_rc_docker_wipe()
{
    docker_wipe_containers      ${TEST_HOSTS}
    docker_wipe_networks        ${TEST_NETWORKS}
}

# Create test container images
test_rc_docker_image()
{
    # uvn_runner          "${UVN_DIR}"
    true
}

# Define test networks
test_rc_docker_network()
{
    docker_network      internet    ${NET_internet}     ${IP_internet_router}
    for net in ${TEST_NETWORKS_PRIVATE}; do
        docker_network ${net} \
                       $(eval "echo \${NET_${net}}") \
                       $(eval "echo \${IP_${net}_router}")
    done
}

# Create router containers
test_rc_docker_router()
{
    for net in ${TEST_NETWORKS_PRIVATE}; do
        docker_container router ${net} $(eval "echo \${IP_${net}_router}")
        docker_connect router.${net} internet $(eval "echo \${IP_internet_${net}_router}")
    done
}

# Create uvn containers
test_rc_docker_uvn()
{
    for net in ${TEST_NETWORKS_PRIVATE}; do
        if printf -- "${HOST_ONLY_CELLS}\n" | grep -q ${net}; then
            local no_agent=y
        else
            local no_agent=
        fi
        CELL_ID=${net} NO_AGENT=${no_agent} \
        docker_container cell ${net} \
                         $(eval "echo \${IP_${net}_cell}") ${CELLS_DIR}/${net}
    done
    
    if [ -n "${TEST_ROAM}" ]; then
        CELL_ROAMING=y CELL_ID=roam \
        docker_container    roam        internet    ${IP_internet_roam}     ${CELLS_DIR}/roam
    fi

    NO_AGENT=y \
    docker_container    babylon     internet    ${IP_internet_babylon}  ${UVN_DIR}
}

# Create host containers
test_rc_docker_host()
{
    for net in ${TEST_NETWORKS_PRIVATE}; do
        docker_container host ${net} $(eval "echo \${IP_${net}_host}")
    done
}

_static_routes_subnet()
{
    local outfile="${1}" \
          net="${2}"
    for onet in ${TEST_NETWORKS_PRIVATE}; do
        if [ "${net}" = "${onet}" ]; then
            continue
        fi
        router_static_route ${h_routes} \
                            $(eval "echo \${NET_${onet}}") \
                            $(eval "echo \${IP_${net}_cell}")
    done
}

# Initialize experiment environement directories
_docker_env_network_info()
{
    local outfile="${1}" \
          host_name="${2}" \
          host_dns="${3}"
    local host_hostname=$(printf "${host_name}" | cut -d. -f1) \
          host_net=$(printf "${host_name}" | cut -d. -f1)
    local ip_net=$(eval "echo \${NET_${host_net}}") \
          ip_host=$(eval "echo \${IP_${host_net}_${host_hostname}}")

    network_info_host "${outfile}" ${ip_net} ${ip_host}
    if [ -n "${host_dns}" ]; then
        network_info_dns_server "${outfile}" ${host_dns}
    fi
}

test_rc_docker_env()
{
    # Delete experiments directory
    rm -rf ${EXPERIMENT_DIR}

    for h in ${TEST_HOSTS}; do
        h_dir=${EXPERIMENT_DIR}/${h}
        h_hosts="${h_dir}/hosts"
        h_routes="${h_dir}/routes"
        h_network="${h_dir}/network"
        h_init="${h_dir}/init.sh"
        h_common="${h_dir}/common.sh"
        h_forward="${h_dir}/forwarded"

        log_debug " creating container environment: ${h_dir}"

        # Create host experiment directory
        mkdir -p ${h_dir}

        # Add static entries to /etc/hosts
        # etc_hosts_all ${h_hosts}
        etc_hosts_internet ${h_hosts}

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
        babylon.internet)
            network_info_host "${h_network}" ${NET_internet} ${IP_internet_babylon}
            ;;
        cell.*)
            local net=${h##cell.}
            network_info_host ${h_network} \
                              $(eval "echo \${NET_${net}}") \
                              $(eval "echo \${IP_${net}_cell}")
            ;;
        host.*)
            local net=${h##host.}
            network_info_host ${h_network} \
                              $(eval "echo \${NET_${net}}") \
                              $(eval "echo \${IP_${net}_host}")
            network_info_dns_server "${h_network}" $(eval "echo \${IP_${net}_cell}")
            ;;
        roam.internet)
            network_info_host "${h_network}" ${NET_internet} ${IP_internet_roam}
            ;;
        router.*)
            local net=${h##router.}
            network_info_router "${h_network}" \
                $(eval "echo \${NET_${net}}") $(eval "echo \${IP_${net}_router}") \
                ${NET_internet} $(eval "echo \${IP_internet_${net}_router}")
            network_forward_udp_ports ${h_forward} "${PORT_forward}" \
                                                   $(eval "echo \${IP_${net}_cell}")
            network_info_dns_server "${h_network}" $(eval "echo \${IP_${net}_cell}")
            _static_routes_subnet ${h_routes} ${net}
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
test_rc_start()
{
    for net in ${TEST_NETWORKS_PRIVATE}; do
        docker_start        router.${net}
        docker_start        cell.${net}
        docker_start        host.${net}
    done

    # Start hosts in LAN internet
    if [ -n "${TEST_ROAM}" ]; then
        docker_start        roam.internet
    fi
    docker_start        babylon.internet
}

################################################################################
# Monitor docker containers
################################################################################

_tmux_window_4x()
{
    local session="${1}" \
          win_id="${2}" \
          win_title="${3}" \
          win_content="${4}"
    shift; shift; shift; shift
    
    # ------------------------------
    # | 1           | 2            |
    # ------------------------------
    # | 3           | 4            |
    # ------------------------------
    tmux_window ${session} ${win_id} "${win_title}"

    tmux_split_pane_vertical   ${session} ${win_id} 0
    tmux_split_pane_horizontal ${session} ${win_id} 0
    tmux_split_pane_horizontal ${session} ${win_id} 2

    pane_i=0
    for container in $@; do
        ${win_content} ${session} ${win_id} ${pane_i} ${container}
        pane_i=$(expr ${pane_i} + 1)
        if [ ${pane_i} -ge 4 ]; then
            break
        fi
    done
}

_tmux_window_2x()
{
    local session="${1}" \
          win_id="${2}" \
          win_title="${3}" \
          win_content="${4}"
    shift; shift; shift; shift
    
    # ------------------------------
    # | 1           | 2            |
    # |             |              |
    # |             |              |
    # ------------------------------
    tmux_window ${session} ${win_id} "${win_title}"

    tmux_split_pane_horizontal ${session} ${win_id} 0

    pane_i=0
    for container in $@; do
        ${win_content} ${session} ${win_id} ${pane_i} ${container}
        pane_i=$(expr ${pane_i} + 1)
        if [ ${pane_i} -ge 2 ]; then
            break
        fi
    done
}

# Monitor docker containers
test_rc_monitor()
{
    local session="uvndemo"
    
    # Define a new tmux session
    tmux_session ${session}

    # Counter for next window id
    local wid=1

    if [ ${TEST_NETWORKS_PRIVATE_COUNT} -ge 3 ]; then
        group1_window=_tmux_window_4x
    else
        group1_window=_tmux_window_2x
    fi

    ############################################################################
    ${group1_window} ${session} ${wid} \
                    "1-4 [logs]" \
                    tmux_container_logs \
                    cell.org1 \
                    cell.org2 \
                    cell.org3 \
                    cell.org4
    wid=$(expr ${wid} + 1)
    ############################################################################
    if [ -n "${EXTRA_NETS}" ]; then
        _tmux_window_4x ${session} ${wid} \
                        "5-8 [logs]" \
                        tmux_container_logs \
                        cell.org5 \
                        cell.org6 \
                        cell.org7 \
                        cell.org8
        wid=$(expr ${wid} + 1)
    fi
    ############################################################################
    _tmux_window_2x ${session} ${wid} "reg [logs]" \
                    tmux_container_logs \
                    roam.internet \
                    babylon.internet
    wid=$(expr ${wid} + 1)
    ############################################################################
    ${group1_window} ${session} ${wid} \
                    "1-4 [ctrl]" \
                    tmux_container_sh \
                    cell.org1 \
                    cell.org2 \
                    cell.org3 \
                    cell.org4
    wid=$(expr ${wid} + 1)
    ############################################################################
    if [ -n "${EXTRA_NETS}" ]; then
        _tmux_window_4x ${session} ${wid} \
                        "5-8 [ctrl]" \
                        tmux_container_sh \
                        cell.org5 \
                        cell.org6 \
                        cell.org7 \
                        cell.org8
        wid=$(expr ${wid} + 1)
    fi
    ############################################################################
    _tmux_window_2x ${session} ${wid} "reg [ctrl]" \
                    tmux_container_sh \
                    roam.internet \
                    babylon.internet
    wid=$(expr ${wid} + 1)
    ############################################################################
    ${group1_window} ${session} ${wid} \
                    "1-4 [route]" \
                    tmux_container_sh \
                    router.org1 \
                    router.org2 \
                    router.org3 \
                    router.org4
    wid=$(expr ${wid} + 1)
    ############################################################################
    if [ -n "${EXTRA_NETS}" ]; then
        _tmux_window_4x ${session} ${wid} \
                        "5-8 [route]" \
                        tmux_container_sh \
                        router.org5 \
                        router.org6 \
                        router.org7 \
                        router.org8
        wid=$(expr ${wid} + 1)
    fi
    ############################################################################
    ${group1_window} ${session} ${wid} \
                    "1-4 [host]" \
                    tmux_container_sh \
                    host.org1 \
                    host.org2 \
                    host.org3 \
                    host.org4
    wid=$(expr ${wid} + 1)
    ############################################################################
    if [ -n "${EXTRA_NETS}" ]; then
        _tmux_window_4x ${session} ${wid} \
                        "5-8 [host]" \
                        tmux_container_sh \
                        host.org5 \
                        host.org6 \
                        host.org7 \
                        host.org8
        wid=$(expr ${wid} + 1)
    fi
    ############################################################################

    # Close default window
    tmux_kill_window ${session} 0

    # Switch to first window
    tmux_select_pane ${session} 1 0

    # Attach to tmux
    tmux attach
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

# Enable development docker image
export UNO_DEV="$(cd ${TEST_LIB_DIR}/../.. && pwd)"

################################################################################
# Define rc levels
################################################################################
if [ -n "${PREDEPLOY}" ]; then
    deploy_stages="UVN_DEPLOY UVN_INSTALL"
else
    deploy_stages="UVN_INSTALL UVN_DEPLOY"
fi

rc_init UVN \
        UVN_CREATE \
        UVN_ATTACH \
        UVN_NS \
        UVN_PARTICLES \
        ${deploy_stages} \
        UVN_BACKUP \
        UVN_DONE \
        DOCKER \
        DOCKER_WIPE \
        DOCKER_IMAGE \
        DOCKER_NETWORK \
        DOCKER_ENV \
        DOCKER_ROUTER \
        DOCKER_UVN \
        DOCKER_HOST \
        DOCKER_DONE \
        START \
        MONITOR \
        CLEANUP

################################################################################
# Perform test stages
################################################################################
if [ -n "${WITH_BACKUP}" ]; then
    uvn_restore
else
    ! rc_check UVN_CREATE       || test_rc_uvn_create
    ! rc_check UVN_ATTACH       || test_rc_uvn_attach
    ! rc_check UVN_NS           || test_rc_uvn_ns
    ! rc_check UVN_PARTICLES    || test_rc_uvn_particles
    ! rc_check UVN_DEPLOY       || test_rc_uvn_deploy
    ! rc_check UVN_INSTALL      || test_rc_uvn_install
    ! rc_check UVN_BACKUP       || test_rc_uvn_backup
fi
! rc_check DOCKER_WIPE      || test_rc_docker_wipe
! rc_check DOCKER_IMAGE     || test_rc_docker_image
! rc_check DOCKER_NETWORK   || test_rc_docker_network
! rc_check DOCKER_ENV       || test_rc_docker_env
! rc_check DOCKER_ROUTER    || test_rc_docker_router
! rc_check DOCKER_UVN       || test_rc_docker_uvn
! rc_check DOCKER_HOST      || test_rc_docker_host
! rc_check START            || test_rc_start
! rc_check MONITOR          || test_rc_monitor
