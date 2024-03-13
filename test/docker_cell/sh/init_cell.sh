#!/bin/sh -e
# Load shared configuration
. /config.sh
# Enable IPv4 forwarding
echo 1 > /proc/sys/net/ipv4/ip_forward
# Delete default route
ip route delete default
# Add default route via network's router
ip route add default via ${TEST_NET_PRIVATE}.254 dev eth0


