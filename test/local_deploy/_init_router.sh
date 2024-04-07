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

EXPERIMENT_TYPE=router

printf "Initializing router %s...\n" "$(hostname)"

# Include common init script
EXPERIMENT_DIR=$(cd $(dirname "${0}") && pwd)
. ${EXPERIMENT_DIR}/common.sh

# Dump host configuration for logging
dump_host_config

# Delte default route
printf "Deleting default route...\n"
ip route delete default

# # Delete default route via Docker gateway on private network
# if is_default_route ${TEST_NET_PRIV_NIC} ${TEST_NET_PRIV}.1; then
#     printf "Delete default route via %s.1 on %s\n" \
#         "${TEST_NET_PRIV}" "${TEST_NET_PRIV_NIC}"
#     ip route delete default via ${TEST_NET_PRIV}.1 dev ${TEST_NET_PRIV_NIC}
# fi

# ip route add ${TEST_NET_PUB}.1/32 via ${TEST_NET_PUB}.1 dev ${TEST_NET_PUB_NIC}
# ip route add ${TEST_NET_PRIV}.1/32 via ${TEST_NET_PRIV}.1 dev ${TEST_NET_PRIV_NIC}

# Add default route via public network
# (either custom router or default Docker router)
if [ -z "${TEST_NET_PUB_DEFAULT}" ]; then
    TEST_NET_PUB_GW=${TEST_NET_PUB_GW:-${TEST_NET_PUB}.254}
    default_route_ip="${TEST_NET_PUB_GW}"
    default_route_nic="${TEST_NET_PUB_NIC}"
    printf "Add default route via %s on %s\n" \
        "${default_route_ip}" "${default_route_nic}"
    ip route add default via ${default_route_ip} dev ${default_route_nic}
# else
#     default_route_ip="${TEST_NET_PUB}.1"
#     default_route_nic="${TEST_NET_PUB_NIC}"
fi

# Enable IPv4 forwarding
sysctl -w net.ipv4.ip_forward=1

if [ -z "${TEST_NET_NAT_DISABLED}" ]; then
    printf "Enabling NAT between networks %s.0/%s and %s.0/%s\n" \
        "${TEST_NET_PRIV}" "${TEST_NET_PRIV_MASK}" \
        "${TEST_NET_PUB}" "${TEST_NET_PUB_MASK}"
    
    # Add iptables rules to remap all packets coming from the default
    # docker gateway, as if they were coming from the custom upstream
    # router in the public network
    # iptables -t nat -A INPUT -s ${TEST_NET_PRIV}.1 -j SNAT --to-source ${TEST_NET_PUB_IP}

    # Enable NAT on public nic via MASQUERADE.
    # We could also use SNAT, but this matches more closely the
    # configuration of a router with an actual nic exposed to the public
    # internet with a dynamic IP address
    iptables -t nat -A POSTROUTING -o ${TEST_NET_PUB_NIC} -j MASQUERADE
    iptables -A FORWARD -i ${TEST_NET_PUB_NIC} -o ${TEST_NET_PRIV_NIC} \
            -m state --state RELATED,ESTABLISHED -j ACCEPT
    iptables -A FORWARD -i ${TEST_NET_PUB_NIC} -o ${TEST_NET_PRIV_NIC} -j ACCEPT
    iptables -A FORWARD -i ${TEST_NET_PRIV_NIC} -o ${TEST_NET_PUB_NIC} \
            -m state --state RELATED,ESTABLISHED -j ACCEPT
    iptables -A FORWARD -i ${TEST_NET_PRIV_NIC} -o ${TEST_NET_PUB_NIC} -j ACCEPT

else
    printf "NAT disabled between networks %s.0/%s and %s.0/%s\n" \
        "${TEST_NET_PRIV}" "${TEST_NET_PRIV_MASK}" \
        "${TEST_NET_PUB}" "${TEST_NET_PUB_MASK}"
fi

# Forward UDP ports to UVN cell
for port_entry in $(cat ${EXPERIMENT_DIR}/forwarded); do
    udp_port=$(echo ${port_entry} | cut -d: -f1)
    fwd_host=$(echo ${port_entry} | cut -d: -f2)
    printf "Forwarding UDP port: %s:%s → %s:%s\n" \
           "${TEST_NET_PUB_IP}" "${udp_port}" \
           "${fwd_host}" "${udp_port}"
    iptables -t nat -A PREROUTING -i ${TEST_NET_PUB_NIC} -p udp --dport ${udp_port} \
        -j DNAT --to-destination ${fwd_host}:${udp_port}
    # iptables -A FORWARD -i ${TEST_NET_PUB_NIC} -p udp --dport ${udp_port} \
    #     -m state --state NEW,ESTABLISHED,RELATED -j ACCEPT
done

# Dump host configuration for logging
dump_host_config

printf "Router initialized: %s\n" "$(hostname)"
