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

# Enable wireguard debugging
# echo 'module wireguard +p' >> /sys/kernel/debug/dynamic_debug/control

################################################################################
# Helper functions
################################################################################
dump_experiment_config()
{
    printf "%s EXPERIMENT CONFIGURATION %s\n" "--------" "--------"
    case ${EXPERIMENT_TYPE} in
    host)
        printf "TEST_NET=%s\n" "${TEST_NET}"
        printf "TEST_NET_MASK=%s\n" "${TEST_NET_MASK}"
        printf "TEST_NET_IP=%s\n" "${TEST_NET_IP}"
        printf "TEST_NET_NIC=%s\n" "${TEST_NET_NIC}"
        ;;
    router)
        printf "TEST_NET_PRIV=%s\n" "${TEST_NET_PRIV}"
        printf "TEST_NET_PRIV_MASK=%s\n" "${TEST_NET_PRIV_MASK}"
        printf "TEST_NET_PRIV_IP=%s\n" "${TEST_NET_PRIV_IP}"
        printf "TEST_NET_PRIV_NIC=%s\n" "${TEST_NET_PRIV_NIC}"
        printf "TEST_NET_PUB=%s\n" "${TEST_NET_PUB}"
        printf "TEST_NET_PUB_MASK=%s\n" "${TEST_NET_PUB_MASK}"
        printf "TEST_NET_PUB_IP=%s\n" "${TEST_NET_PUB_IP}"
        printf "TEST_NET_PUB_NIC=%s\n" "${TEST_NET_PUB_NIC}"
        printf "TEST_NET_PUB_DEFAULT=%s\n" "${TEST_NET_PUB_DEFAULT}"
        printf "TEST_NET_NAT_DISABLED=%s\n" "${TEST_NET_NAT_DISABLED}"
        ;;
    esac
}

dump_host_config()
{
    printf "%s SYSTEM CONFIGURATION %s\n" "--------" "--------"
    (
        set -x
        ip address show
        ip route
        cat /etc/hosts
    )
}

_nic_has_address()
{
    [ -n "$(ip address show dev ${1} 2>/dev/null | grep "inet ${2}")" ]
}

_find_nic_by_address()
{
    for nic in eth0 eth1; do
        if _nic_has_address ${nic} "${1}"; then
            printf ${nic}
            return
        fi
    done

    printf "unknown"
}

host_nic()
{
    _find_nic_by_address "${TEST_NET_IP}"
}

router_nic_public()
{
    _find_nic_by_address "${TEST_NET_PUB_IP}"
}

router_nic_private()
{
    _find_nic_by_address "${TEST_NET_PRIV_IP}"
}

is_default_route()
{
    [ "$(ip route show default)" = "default via ${2} dev ${1}" ]
}

define_test_aliases()
{
    cat - > /root/bashrc.test << EOF
_is_number()
{
    case \${1} in
      ''|*[!0-9]*) return 1 ;;
      *) return 0 ;;
    esac
}
# ping_n <n> <base-hostname> [<base-hostname>...]
ping_n()
{
    local n=\${1} \\
          failed=0
    shift
    printf "ping_n: %s %s\n" "\${n}" "\$@"
    for baseh in \$@; do
        for i in \$(seq 1 \${n}); do
            local h=\${baseh}\${i}
            if ping -c 1 \${h} >/dev/null 2>&1; then
                local rc=OK
            else
                local rc=FAILED
                failed=1
            fi
            printf "ping: %s %s\n" "\${h}" "\${rc}"
        done
    done

    return \${failed}
}
ping_hosts() { ping_n \${1} host.org ; }
ping_cells() { ping_n \${1} cell.org ; }
ping_routers() { ping_n \${1} router.org ; }
ping_lans() { ping_n \${1} host.org cell.org router.org ; }
ping_test() {
    if ! _is_number "\${1}" || ! _is_number "\${2}" ; then
        printf "usage: ping_test <number of nets> <sleep interval>\n" s>&2
        return 1
    fi
    while :; do
        clear
        ping_lans \${1}
        sleep \${2}
    done
}
EOF
    if [ -z "$(grep bashrc.test /root/.bashrc)" ]; then
        printf "%s\n" "source /root/bashrc.test" >> /root/.bashrc
    fi
}

################################################################################
# BEGIN SCRIPT
################################################################################
# Load network configuration
printf "Loading experiment network configuration from %s\n" \
    "${EXPERIMENT_DIR}/network"
. ${EXPERIMENT_DIR}/network

case ${EXPERIMENT_TYPE} in
    router)
        export TEST_NET_PRIV_NIC=$(router_nic_private) \
               TEST_NET_PUB_NIC=$(router_nic_public)
        ;;
    host)
        export TEST_NET_NIC=$(host_nic)
        ;;
esac

# Dump experiment configuration for logging
dump_experiment_config

# Perform one-time initialization
if [ ! -f /experiment.initialized -o -n "do this anyway" ]; then
    printf "Initializing experiment on %s...\n" "$(hostname)"

    # Dump additional hostnames in /etc/hosts
    cat ${EXPERIMENT_DIR}/hosts >> /etc/hosts

    # Add static routes if present
    if [ -f ${EXPERIMENT_DIR}/routes ]; then
        printf "Installing static routes:\n"
        cat ${EXPERIMENT_DIR}/routes
        . ${EXPERIMENT_DIR}/routes
    fi

    if [ -n "${TEST_NET_DNS}" ]; then
        printf "Enablding DNS server: %s\n" "${TEST_NET_DNS}"
        # sleep 1 && rm -f /etc/resolv.conf
        printf "nameserver %s\n" "${TEST_NET_DNS}" > /etc/resolv.conf
    fi

    define_test_aliases

    printf "Experiment initialized on %s\n" "$(hostname)"

    echo 1 > /experiment.initialized
fi
