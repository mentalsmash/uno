#!/bin/sh
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
# Simple logging helpers
################################################################################
log_info()
{
    printf "[i][experiment]%s\n" "$@"
}

log_error()
{
    printf "[ERROR][experiment]%s\n" "$@"
}

log_debug()
{
    [ -z "${VERBOSE}" ] || printf "[d][experiment]%s\n" "$@"
}

################################################################################
# Docker Helpers
################################################################################
docker_image()
{
    local image_name="${1}"
    local image_tag="${image_name}:latest"

    log_debug " deleting docker image: ${image_tag}"
    ((set -x; ${DOCKER} rmi "${image_tag}") || [ -n image_doesnt_exists ]) 2>/dev/null
    log_debug " building docker image: ${image_tag}"
    (
        set -x
        ${DOCKER} build -t "${image_tag}" ${TEST_LIB_DIR}/${image_name}
    )
    log_info "[built] docker image: ${image_tag}"
}

docker_network()
{
    local net_name="${1}" \
          net_subnet="${2}" \
          net_gw="${3}" \
          net_masquerade="${4}"
    
    [ -n "${net_masquerade}" ] || net_masquerade=false

    log_debug " deleting docker network: ${net_name}"
    (
        set -x
        ${DOCKER} network rm ${net_name} || [ -n network_doesnt_exist ]
    ) >> ${EXPERIMENT_LOG} 2>&1
    log_debug " creating docker network: ${net_name}"
        # --gateway=${net_gw} 
    (
        set -x
        ${DOCKER} network create \
            --driver bridge \
            --subnet=${net_subnet} \
            -o com.docker.network.bridge.enable_ip_masquerade=${net_masquerade} \
            ${net_name} \
            >> ${EXPERIMENT_LOG} 2>&1
    )
    log_info "[created] docker network: ${net_name} [${net_subnet}]"
}

docker_network_w_bridge()
{
    local net_name="${1}" \
          net_subnet="${2}" \
          bridge_name="${3}" \
          net_client_range="${4}" \
          bridge_gw="${5}" \
          external_ips="${6}"

    log_debug " deleting docker network: ${net_name}"
    (
        set -x
        ${DOCKER} network rm ${net_name} || [ -n network_doesnt_exist ]
    ) >> ${EXPERIMENT_LOG} 2>&1
    log_debug " creating bridged docker network: ${net_name}"
    ext_ip_args=""
    for ext_ip in ${external_ips}; do
        ext_ip_args="${ext_ip_args} --aux-address=${ext_ip}"
    done
    (
        set -x
        ${DOCKER} network create \
            --driver bridge \
            --gateway=${bridge_gw} \
            --ip-range=${net_client_range} \
            --subnet=${net_subnet} \
            -o com.docker.network.bridge.enable_ip_masquerade=false \
            -o com.docker.network.bridge.name=${bridge_name} \
            ${net_name} \
            >> ${EXPERIMENT_LOG} 2>&1
    )

    # Delete default address from Docker and reassign it in the client range subnet
    local client_range_ip=$(echo ${net_client_range} | cut -d/ -f1) \
          client_range_mask=$(echo ${net_client_range} | cut -d/ -f2) \
          subnet_mask=$(echo ${net_subnet} | cut -d/ -f2)

    # Delete default route, and reassert it only for the docker network's ip range
    # ${SUDO} ip route del ${net_subnet} dev ${bridge_name}
    
    # ${SUDO} ip route add ${net_client_range} dev ${bridge_name}
    
    # ${SUDO} ip addr del ${client_range_ip}/${subnet_mask} dev ${bridge_name}
    # ${SUDO} ip addr add ${net_client_range} dev ${bridge_name}

    log_info "[created] bridged docker network: ${net_name} [${net_subnet}, ${bridge_name}]"
}

docker_container()
{
    local host_name="${1}" \
          host_net="${2}" \
          host_ip="${3}" \
          host_uvn="${4}"

    local container_name=${host_name}.${host_net}

    log_debug " deleting docker container: ${container_name}"
    ((set -x; ${DOCKER} rm -f -v ${container_name}) || [ -n network_doesnt_exist ]) \
        >> ${EXPERIMENT_LOG} 2>&1
    log_debug " creating docker container: ${container_name}"
    (
        extra_args="
            $([ -z "${CELL_ID}" ] || printf -- "-e CELL=${CELL_ID}") \
            $([ -z "${CELL_ID}" ] || printf -- "-v ${UVN_DIR}/cells/${UVN_ID}__${CELL_ID}.uvn-agent:/package.uvn-agent" ) \
            $([ -z "${UNO_DIR}" ] || printf -- "-v ${UNO_DIR}:/uno") \
            $([ -z "${host_uvn}" ] || printf -- "-v ${host_uvn}:/uvn") \
            $([ -z "${host_uvn}" ] || printf -- "-w /uvn") \
            $([ -z "${VERBOSE}" ] || printf -- "-e VERBOSE=${VERBOSE}") \
        "
        cmd="$(
            if [ -z "${host_uvn}" ]; then
                printf -- "sh"
            else
                printf -- "${ACTION}"
            fi
        )"
        # cmd="$([ -n "${host_uvn}" -a -z "${TEST_NO_AGENTS}" ] || printf -- "sh")"

        set -x
        ${DOCKER} create \
            -ti \
            --name ${container_name} \
            --hostname "${container_name}" \
            --net ${host_net} \
            --ip ${host_ip} \
            --privileged \
            --cap-add net_admin \
            --cap-add sys_module \
            -e INIT=/experiment/init.sh \
            -e UNO_MIDDLEWARE=${UNO_MIDDLEWARE} \
            -v ${EXPERIMENT_DIR}/${container_name}:/experiment \
            ${extra_args} \
            uno:latest \
            ${cmd} \
            >> ${EXPERIMENT_LOG} 2>&1
    )
    log_info "[created] docker container: ${container_name}"
}

docker_connect()
{
    local host_name="${1}" \
          host_net="${2}" \
          host_ip="${3}" \
    
    log_debug " connecting docker container to network: ${host_name} → ${host_net}"
    (
        set -x
        ${DOCKER} network connect \
            --ip ${host_ip} ${host_net} ${host_name} \
            >> ${EXPERIMENT_LOG} 2>&1
    )
    log_info "[connected] docker container to network: ${host_name} → ${host_net}"
}

docker_start()
{
    local container_name=${1}

    log_debug " starting docker container: ${container_name}"
    (
        set -x
        ${DOCKER} start ${container_name} >> ${EXPERIMENT_LOG}
    )
    log_info "[started] docker container: ${container_name}"
}

docker_wipe_containers()
{
    log_debug " wiping all docker containers..."
    # (${DOCKER} rm -f $@ || [ -n some_containers_didnt_exists ]) \
    #     >> ${EXPERIMENT_LOG} 2>&1
    # Delete containers one by one to avoid crashing Raspberry Pi
    for d in $@; do
        ((set -x; ${DOCKER} rm -f $d) || [ -n some_containers_didnt_exists ]) \
            >> ${EXPERIMENT_LOG} 2>&1
    done
    # ${DOCKER} rm -f $@
    log_info "[wiped] all docker containers"
}

docker_wipe_networks()
{
    log_debug " wiping all docker networks..."
    ((set -x; ${DOCKER} network rm $@) || [ -n some_networks_didnt_exists ]) \
        >> ${EXPERIMENT_LOG} 2>&1
    # ${DOCKER} network rm $@
    log_info "[wiped] all docker networks"
}

docker_wipe_images()
{
    log_debug " wiping all docker images..."
    ((set -x; ${DOCKER} rmi -f $@) || [ -n some_images_didnt_exists ]) \
        >> ${EXPERIMENT_LOG} 2>&1
    log_info "[wiped] all docker images"
}

setvars_docker_env_files()
{
    h_dir=${EXPERIMENT_DIR}/${1}
    h_hosts="${h_dir}/hosts"
    h_routes="${h_dir}/routes"
    h_network="${h_dir}/network"
    h_init="${h_dir}/init.sh"
    h_common="${h_dir}/common.sh"
    h_forward="${h_dir}/forwarded"
}

################################################################################
# UVN Helpers
################################################################################
uvn_create()
{
    local uvn_address="${1}" \
          uvn_admin="${2}" \
          uvn_admin_name="${3}"

    # if [ -z "${RTI_LICENSE_FILE}" ]; then
    #     log_error "Please set RTI_LICENSE_FILE to a valid rti_license.dat"
    #     exit 1
    # fi

    log_debug " creating UVN: ${uvn_address}"
    (
        set -x
        ${UNO} define uvn ${uvn_address} \
            -a ${uvn_address} \
            -o "${uvn_admin_name} <${uvn_admin}>" \
            -r ${UVN_DIR} \
            $([ -z "${UVN_TIMING_FAST}" ] || printf -- "--timing-profile fast" ) \
            $([ -z "${UVN_SECRET}" ] || printf -- "-p ${UVN_SECRET}" ) \
            --yes \
            ${VERBOSE} \
            ${UVN_EXTRA_ARGS}
    )
    log_info "[created] UVN: ${uvn_address}"
}

uvn_attach()
{
    local cell_name="${1}" \
          cell_address="${2}" \
          cell_admin="${3}" \
          cell_admin_name="${4}"
    
    local cell_subnet="$(eval "echo \${NET_${cell_name}}")"

    (
        cd ${UVN_DIR}
        extra_args="
            $([ -z "${cell_address}" ] || printf -- "-a ${cell_address}")
            $([ -n "${CELL_ROAMING}" -o -z "${cell_subnet}" ] || printf -- "-N ${cell_subnet}")
        "
        set -x
        ${UNO} define user ${cell_admin} --name "${cell_admin_name}" -p ${UVN_SECRET} ${VERBOSE}
        ${UNO} define cell ${cell_name} \
            -o ${cell_admin} \
            ${extra_args} \
            --yes \
            ${VERBOSE} \
            ${UVN_EXTRA_ARGS}
    )
    log_info "[created] UVN cell: ${cell_name}"
}

uvn_particle()
{
    local particle_name="${1}" \
          particle_owner_name="${2}" \
          particle_owner_email=${3}

    (
        cd ${UVN_DIR}
        set -x
        ${UNO} define user ${particle_owner_email} --name "${particle_owner_name}" -p ${UVN_SECRET} ${VERBOSE}
        ${UNO} define particle ${particle_name} \
            -o ${particle_owner_email} \
            --yes \
            ${VERBOSE} \
            ${UVN_EXTRA_ARGS}
    )
    log_info "[created] UVN particle: ${particle_name}"
}

# uvn_ns()
# {
#     local ns_cell=${1} \
#           ns_host=${2} \
#           ns_ip=${3} \
#           ns_tags="${4}"

#     tags=
#     for t in ${ns_tags}; do
#         tags="${tags} -t ${t}"
#     done
#     (
#         cd ${UVN_DIR}
#         set -x
#         ${UVN} nameserver a ${ns_cell} ${ns_host} ${ns_ip} ${tags} ${UVN_EXTRA_ARGS}
#     )
#     log_info "[asserted] DNS record: [${ns_cell}] ${ns_host}/${ns_ip}"
# }

uvn_deploy()
{
    (
        cd ${UVN_DIR}
        set -x
        ${UNO} redeploy \
            $([ -z "${UVN_STRATEGY}" ] || printf -- "-S ${UVN_STRATEGY}") \
            --yes \
            ${VERBOSE} \
            ${UVN_EXTRA_ARGS}
    )
}

uvn_install()
{
    local uvn_address="${1}" \
          cell_name="${2}" \
          with_deployment="${3}"
    
    ${UNO} install \
        -r "${CELLS_DIR}/${cell_name}" \
        ${VERBOSE} \
        "${UVN_DIR}/cells/${cell_name}.uvn-agent"

    # ${UVN} install \
    #     "${UVN_DIR}/installers/uvn-${uvn_address}-bootstrap-${cell_name}.zip" \
    #     "${CELLS_DIR}/${cell_name}" \
    #     ${UVN_EXTRA_ARGS}

    # if [ -n "${with_deployment}" ]; then
    # (
    #     cd "${CELLS_DIR}/${cell_name}"
    #     set -x
    #     ${UVN} install \
    #         "${UVN_DIR}/installers/uvn-${uvn_address}-latest-${cell_name}.zip" \
    #         . \
    #         ${UVN_EXTRA_ARGS}
    # )
    # fi
    log_info "[installed] UVN cell: ${cell_name}"
}


uvn_backup()
{
    rm -rf ${BACKUP_DIR}
    mkdir -p ${BACKUP_DIR}
    # cp -r ${CELLS_DIR} ${UVN_DIR} ${BACKUP_DIR}
    cp -r ${UVN_DIR} ${BACKUP_DIR}
    log_info "[backed up] UVN state"
}

uvn_restore()
{
    ${SUDO} rm -rf ${CELLS_DIR} ${UVN_DIR}
    cp -r ${BACKUP_DIR}/* .
    log_info "[restored] UVN state"
}

################################################################################
# Simple flow control on script execution
################################################################################
_rc_level_next=0

_rc_init_minmax()
{
    local minmax="${1}" \
          max="${2}" \
          min=0
    
    if [ -n "${minmax}" ]; then
        if [ -z "${max}" ]; then
            max=${minmax}
        else
            min=${minmax}
        fi
    else
        max=65535
    fi

    _rc_define NONE ${min}
    _rc_define ALL ${max}

    _rc_level_next=$(expr ${min} + 1)

    if [ ${_rc_level_next} -gt ${max} ]; then
        log_error " invalid experiment configuration: rc.min(${min}) > rc.max(${max})"
        exit 1
    fi
}

_rc_define()
{
    local lvl="${1}" \
          lvl_val="${2}"
    if [ -z "${lvl_val}" ]; then
        lvl_val=$(expr ${_rc_level_next} + 1)
        _rc_level_next=${lvl_val}
    fi
    eval "TEST_RC_${lvl}=${lvl_val}"
    log_debug " rc: ${lvl}"
}

_rc_get()
{
    eval "echo \${TEST_RC_${1}}"
}

_rc_min()
{
    _rc_get ${RC_MIN}
}

_rc_max()
{
    _rc_get ${RC_MAX}
}

rc_init()
{
    _rc_init_minmax
    for lvl in $@; do
        _rc_define ${lvl}
    done
    # Single stage to run
    RC=${RC:-}
    # Minimum stage to run
    RC_MIN=${RC:-${RC_MIN:-NONE}}
    # Maximum stage to run
    RC_MAX=${RC:-${RC_MAX:-ALL}}
}


rc_check()
{
    local lvl=$(_rc_get ${1})
    if [ $(_rc_max) -lt ${lvl} ]; then
        log_debug " rc over: ${1}"
        exit 0
    elif [ $(_rc_min) -gt ${lvl} ]; then
        log_debug " rc skipped: ${1}"
        return 1
    fi
    log_info " rc run: ${1}"
    return 0
}

################################################################################
# Experiment Configuration Helpers
################################################################################
etc_hosts_line()
{
    local host_names="${1}" \
          ip_addr="${2}"
          
    printf "%s  %s\n" "${ip_addr}" "${host_names}"
}

network_prefix()
{
    echo "${1}" | cut -d. -f1-3
}
network_mask()
{
    echo "${1}" | cut -d/ -f2
}

network_info_host()
{
    local outfile="${1}" \
          net="${2}" \
          net_ip="${3}" \
          net_gw="${4}"
    
    printf "TEST_NET=%s\n" "$(network_prefix ${net})" >> "${outfile}"
    printf "TEST_NET_MASK=%s\n" "$(network_mask ${net})" >> "${outfile}"
    printf "TEST_NET_IP=%s\n" "${net_ip}" >> "${outfile}"
    printf "TEST_NET_GW=%s\n" "${net_gw}" >> "${outfile}"
}

network_info_router()
{
    local outfile="${1}" \
          net_priv="${2}" \
          net_priv_ip="${3}" \
          net_pub="${4}" \
          net_pub_ip="${5}" \
          net_pub_gw="${6}"
    
    printf "TEST_NET_PRIV=%s\n" "$(network_prefix ${net_priv})" >> "${outfile}"
    printf "TEST_NET_PRIV_MASK=%s\n" "$(network_mask ${net_priv})" >> "${outfile}"
    printf "TEST_NET_PRIV_IP=%s\n" "${net_priv_ip}" >> "${outfile}"
    printf "TEST_NET_PUB=%s\n" "$(network_prefix ${net_pub})" >> "${outfile}"
    printf "TEST_NET_PUB_MASK=%s\n" "$(network_mask ${net_pub})" >> "${outfile}"
    printf "TEST_NET_PUB_IP=%s\n" "${net_pub_ip}" >> "${outfile}"
    printf "TEST_NET_PUB_GW=%s\n" "${net_pub_gw}" >> "${outfile}"
}

network_info_router_nat_disabled()
{
    local outfile="${1}" \
          net_nat_disabled="${2}"
    
    printf "TEST_NET_NAT_DISABLED=%s\n" "${net_nat_disabled}" >> "${outfile}"
}

network_info_router_use_default_gw()
{
    local outfile="${1}" \
          net_pub_default="${2}"
    
    printf "TEST_NET_PUB_DEFAULT=%s\n" "${net_pub_default}" >> "${outfile}"
}

network_info_dns_server()
{
    local outfile="${1}" \
          server="${2}"
    
    printf "TEST_NET_DNS=%s\n" "${server}" >> "${outfile}"
}

network_info_default_gw()
{
    local outfile="${1}" \
          server="${2}"
    
    printf "TEST_NET_GW=%s\n" "${server}" >> "${outfile}"
}

network_forward_udp_ports()
{
    local outfile="${1}" \
          src_ports="${2}" \
          dst_addr="${3}"
    
    for p in ${src_ports}; do
        printf "%s:%s\n" "${p}" "${dst_addr}" >> ${outfile}
    done
}

router_static_route()
{
    local outfile="${1}" \
          subnet="${2}" \
          gw="${3}"


    printf "ip route add %s via %s\n" "${subnet}" "${gw}" >> ${outfile}
}

################################################################################
# Bridge interface Helpers
################################################################################
_get_nic_address_if_up()
{
    ip addr | sed -rn '/: '"${1}"':.*state UP/{N;N;s/.*inet (\S*).*/\1/p}'
}

_get_nic_network_routes()
{
    ip route | grep -E "^[1-9]+." | grep "dev ${1}" | awk '{print $1;}'
}

_get_nic_default_gw()
{
    ip route | grep -E "^default via " | grep "dev ${1}" | awk '{print $3;}'
}

_assert_nic_address()
{
    local intf="${1}" \
          intf_addr_in="${2}"

    local intf_ip=$(echo ${intf_addr_in} | cut -d/ -f1)
          intf_mask=$(echo ${intf_addr_in} | cut -d/ -f2)
    
    local intf_addr_cur=$(_get_nic_address_if_up ${intf})

    if [ "${intf_addr_cur}" = "${intf_addr_in}" ]; then
        return 0
    fi

    if [ -n "${intf_addr_cur}" ]; then
        ${SUDO} ip addr del ${intf_addr_cur} dev ${intf}
    fi

    ${SUDO} ip addr add ${intf_addr_in} dev ${intf}

    ${SUDO} ip link set dev ${intf} up
}

# Create a bridge interface linked to one of the host's "public NICs" to enable
# one of Docker's bridge networks to access an external LAN/the Internet.
# The bridge interface must be assigned an IP address in order to act as a
# IP routing endpoint for the containers attached to the Docker network.
# To avoid routing problems, any address on the linked interface will be
# removed. This type of configuration is not typically required to create
# a simple bridge interface to merge multiple nics.
docker_bridge_create()
{
    local bridge_name="${1}" \
          lan_intf="${2}" \
          lan_intf_in="${3}" \
          bridge_addr="${4}"

    lan_intf_in_ip=$(echo ${lan_intf_in} | cut -d/ -f1)
    lan_intf_in_mask=$(echo ${lan_intf_in} | cut -d/ -f2)
    log_info "creating bridge interface: ${bridge_name}={ ${lan_intf} [${lan_intf_in_ip}] }"

    bridge_addr_ip=$(echo ${bridge_addr} | cut -d/ -f1)
    bridge_addr_mask=$(echo ${bridge_addr} | cut -d/ -f2)

    lan_intf_default_gw=$(_get_nic_default_gw ${lan_intf})
    lan_intf_network_routes=$(_get_nic_network_routes ${lan_intf})

    (
        # Try to delete bridge interface
        ${SUDO} ip link set dev ${bridge_name} down
        ${SUDO} ip link set dev ${lan_intf} nomaster
        ${SUDO} ip link del dev ${bridge_name}
    ) ||
    (
        log_debug "failed to delete ${bridge_name} (probably doesn't exist)"
    )

    # Add a new bridge interface
    ${SUDO} ip link add name ${bridge_name} type bridge
    # Add the requested address to the bridge interface
    ${SUDO} ip addr add dev ${bridge_name} ${bridge_addr}
    # Enable the bridge interface
    ${SUDO} ip link set dev ${bridge_name} up
    
    # # Remove the current address from the nic (only needed on Raspbian, on
    # # Ubuntu "flush" seems to remove the address)
    # ${SUDO} ip addr del ${lan_intf_in} dev ${lan_intf}
    # # Flush nic configuration to reset it
    # ${SUDO} ip addr flush ${lan_intf}

    # Add the requested nic to the bridge 
    ${SUDO} ip link set dev ${lan_intf} master ${bridge_name}

    # Wait a second for interface to be acquired by bridge
    sleep 1

    # Make sure that the nic has the expected address
    _assert_nic_address ${lan_intf} ${lan_intf_in}
    
    # Remove default route and route to nic's network and readd them at a
    # lower(-est) metric.

    # if [ -n "${lan_intf_default_gw}" ]; then
    #     log_info "reassert default gateway: nic=${lan_intf} gw=${lan_intf_default_gw}"
    #     ${SUDO} ip route del default dev ${lan_intf} || [ -n no_default_route ]
    #     ${SUDO} ip route add default via ${lan_intf_default_gw} \
    #                                  dev ${lan_intf} \
    #                                  metric 4294967294
    # fi

    # for n_addr in ${lan_intf_network_routes}; do
    #     log_info "reassert network route: nic=${lan_intf} net=${n_addr}"
    #     ${SUDO} ip route del ${n_addr} dev ${lan_intf}
    #     ${SUDO} ip route add ${n_addr} dev ${lan_intf} metric 4294967294
    # done
}

# Delete a bridge interface created by docker_bridge_create
docker_bridge_delete()
{
    local bridge_name="${1}" \
          lan_intf="${2}" \
          lan_intf_in="${3}"

    lan_intf_in_ip=$(echo ${lan_intf_in} | cut -d/ -f1)
    lan_intf_in_mask=$(echo ${lan_intf_in} | cut -d/ -f2)

    log_info "deleting bridge interface: ${bridge_name}={ ${lan_intf} [${lan_intf_in_ip}] }"

    lan_intf_addr=$(_get_nic_address_if_up ${lan_intf})
    br_addr=$(_get_nic_address_if_up ${bridge_name})

    if [ -z "${br_addr}" ]; then
        if [ -n "${lan_intf_addr}" ]; then
            log_info "bridge already disabled: ${bridge_name}"
            return 0
        else
            log_info "ERROR: unexpected, both ${lan_intf} and ${bridge_name} don't have an address"
            exit 1
        fi
    fi
    # if [ -n "${lan_intf_addr}" ]; then
    #     log_info "ERROR: unexpected, ${lan_intf} already has an address"
    #     exit 1
    # fi

    # Store existing routes on nic
    lan_intf_default_gw=$(_get_nic_default_gw ${lan_intf})
    lan_intf_network_routes=$(_get_nic_network_routes ${lan_intf})

    ${SUDO} ip link set dev ${lan_intf} nomaster
    ${SUDO} ip link set dev ${bridge_name} down
    ${SUDO} ip link del dev ${bridge_name}

    # Make sure that the nic has the expected address
    _assert_nic_address ${lan_intf} ${lan_intf_in}

    # Reassert routes with default metric
    # if [ -n "${lan_intf_default_gw}" ]; then
    #     log_info "reassert default gateway: nic=${lan_intf} gw=${lan_intf_default_gw}"
    #     ${SUDO} ip route del default dev ${lan_intf}
    #     ${SUDO} ip route add default via ${lan_intf_default_gw} \
    #                                  dev ${lan_intf}
    # fi

    # for n_addr in ${lan_intf_network_routes}; do
    #     log_info "reassert network route: nic=${lan_intf} net=${n_addr}"
    #     ${SUDO} ip route del ${n_addr} dev ${lan_intf}
    #     ${SUDO} ip route add ${n_addr} dev ${lan_intf}
    # done
}


bridge_docker_args()
{
    local bridge_name="${1}" \
          lan_subnet="${2}" \
          lan_client_range="${3}"

    printf "%s %s %s" \
        "--ip-range=${lan_client_range}" \
        "--subnet=${lan_subnet}" \
        "-o \"com.docker.network.bridge.name=${bridge_name}\""
}

################################################################################
# tmux Helpers
################################################################################

tmux_container_start()
{
    local session="${1}" \
          win_id="${2}" \
          pane_id="${3}" \
          container="${4}"
    
    tmux send-keys -t "${session}:${win_id}.${pane_id}" \
        "docker start ${container}" C-m
}

tmux_container_logs()
{
    local session="${1}" \
          win_id="${2}" \
          pane_id="${3}" \
          container="${4}"
    
    tmux send-keys -t "${session}:${win_id}.${pane_id}" \
        "docker logs -f ${container}" C-m
}

tmux_container_sh()
{
    local session="${1}" \
          win_id="${2}" \
          pane_id="${3}" \
          container="${4}"
    
    tmux send-keys -t "${session}:${win_id}.${pane_id}" \
        "docker exec -ti ${container} bash" C-m
}

tmux_session()
{
    local session="${1}"

    # create tmux session (delete if already exists)
    set +e
    tmux kill-session -t ${session} 2>/dev/null
    set -e

    # Create detached so that we can setup different windows
    tmux new-session -s "${session}" -d
}

tmux_window()
{
    local session="${1}" \
          win_id="${2}" \
          win_title="${3}"
    
    tmux new-window -t "${session}:${win_id}" -n "${win_title}"
}

tmux_kill_window()
{
    local session="${1}" \
          win_id="${2}"
    
    tmux kill-window -t "${session}:${win_id}"
}

tmux_split_pane_vertical()
{
    local session="${1}" \
          win_id="${2}" \
          pane_id="${3}"
    
    tmux split-window -t "${session}:${win_id}.${pane_id}" -v -p 50
}

tmux_split_pane_horizontal()
{
    local session="${1}" \
          win_id="${2}" \
          pane_id="${3}"
    
    tmux split-window -t "${session}:${win_id}.${pane_id}" -h -p 50
}

tmux_select_pane()
{
    local session="${1}" \
          win_id="${2}" \
          pane_id="${3}"
    tmux select-window -t "${session}:${win_id}.${pane_id}"
}

################################################################################
# Initialize common global environment
################################################################################
# Directory where the script will generate artifacts
TEST_DIR="${TEST_DIR:-$(pwd)}"
# Directory where the UVN configuration will be stored
UVN_DIR="${TEST_DIR}/uvn"
# Base directory for cell UVN directories
CELLS_DIR="${TEST_DIR}/cells"
# Base directory for additional data to be mounted on Docker containers
EXPERIMENT_DIR="${TEST_DIR}/experiment"
# File containing output from commands
EXPERIMENT_LOG="${TEST_DIR}/experiment.log"
# Directory where to make backups
BACKUP_DIR="${TEST_DIR}/bkp"

# Host initialization scripts
INIT_ROUTER="${TEST_LIB_DIR}/_init_router.sh"
INIT_HOST="${TEST_LIB_DIR}/_init_host.sh"
INIT_COMMON="${TEST_LIB_DIR}/_init_common.sh"

# Docker client executable
: "${DOCKER:=docker}"

# uno executable
: "${UNO:=uno}"

# Other executables
: "${SSH:=ssh}
: "${RSYNC:=rsync}

# Disable commands for "no-op" mode
if [ -n "${NOOP}" ]; then
    DOCKER="echo ${DOCKER}"
    UNO="echo ${UNO}"
    UNO_SUDO=""
    SUDO="echo "
    SSH="echo ${SSH}"
    RSYNC="echo ${RSYNC}"
fi

# Check if we are running as root, otherwise enable sudo
if [ -z "$(id | grep '^uid=0(root)' )" ]; then
    DOCKER="sudo ${DOCKER}"
    UNO_SUDO="sudo "
    SUDO="sudo "
fi

################################################################################
# Set shell control flags
################################################################################
if [ -n "${DEBUG_SH}" ]; then
    set -x
fi
# Enable verbose output if requested
if [ -n "${TRACE}" ]; then
    UVN_VERBOSE=-vvv
elif [ -n "${DEBUG}" ]; then
    UVN_VERBOSE=-vv
elif [ -n "${VERBOSE}" ]; then
    UVN_VERBOSE=-v
fi

# Keep generated files if requested
if [ -n "${KEEP}" ]; then
    UVN_KEEP=-k
fi

# Enable exit-on-error
if [ -z "${IGNORE_ERRORS}" ]; then
    set -e
fi

# Extra arguments passed to uvn
# UVN_EXTRA_ARGS="${UVN_VERBOSE} ${UVN_KEEP}"