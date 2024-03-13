#!/bin/sh -e
# Load shared configuration
. /config.sh
# Enable IPv4 forwarding
echo 1 > /proc/sys/net/ipv4/ip_forward
# Set default route via the public network
ip route delete default
ip route add default via ${TEST_NET_PUBLIC}.1 dev eth1
# Enable NAT between the two networks
iptables -t nat -A POSTROUTING -o eth1 -j MASQUERADE
# Add route to the uvn backbone
ip route add 10.255.192.0/20 via ${TEST_NET_PRIVATE}.10 dev eth0
# Add routes to UVN networks
for net in $(cat /uvn.networks); do
  ip route add ${net} via ${TEST_NET_PRIVATE}.10 dev eth0
done
