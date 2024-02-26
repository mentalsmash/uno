#!/bin/sh

### BEGIN INIT INFO
# Provides:          uvn
# Required-Start:    $local_fs $remote_fs $network $syslog
# Required-Stop:     $local_fs $remote_fs $network $syslog
# Default-Start:     2 3 4 5
# Default-Stop:      0 1 6
# Short-Description: UVN agent script
# Description:       Connects the host to UVN {{agent.uvn_id.name}} as agent {{agent.cell.name}}.
#                    with backbone peers {{', '.join(agent.peers.local_peer.backbone_peers)}}
### END INIT INFO

PATH=/sbin:/bin:/usr/sbin:/usr/bin
CONFIG_DIR=/etc/uvn/
NAME=uvn
DESC="agent {{agent.cell.name}} for UVN {{agent.uvn_id.name}}"
SCRIPTNAME=/etc/init.d/$NAME
VPN_INTERFACES="
{%- if agent.enable_root_vpn %}
{{agent.root_vpn.config.intf.name}}
{%- endif %}
{%- if agent.enable_particles_vpn %}
{{agent.particles_vpn.config.intf.name}}
{%- endif %}
{%- for backbone_vpn in agent.backbone_vpns %}
{{backbone_vpn.config.intf.name}}
{%- endfor %}
"
LAN_INTERFACES="
{%- for lan in agent.lans %}
{{lan.nic.name}}
{% endfor -%}
"

. /lib/lsb/init-functions

vpn_start()
{
  local nic=${1}
  ip link set down dev ${nic} || true
  ip address flush dev ${nic} || true
  ip address add dev ${nic}
  wg setconf ${nic} ${CONFIG_DIR}/wg-${nic}.conf
  ip link set up dev ${nic}
  iptables -A FORWARD -i ${nic} -j ACCEPT
  iptables -A FORWARD -o ${nic} -j ACCEPT
  iptables -A INPUT -i ${nic} -j ACCEPT
  iptables -t nat -A POSTROUTING -o ${nic} -j MASQUERADE
}

vpn_stop()
{
  local nic=${1}
  iptables -D FORWARD -i ${nic} -j ACCEPT
  iptables -D FORWARD -o ${nic} -j ACCEPT
  iptables -D INPUT -i ${nic} -j ACCEPT
  iptables -t nat -D POSTROUTING -o ${nic} -j MASQUERADE
  ip link set down dev ${nic}
  ip address flush dev ${nic}
  ip link delete ${nic}
}

lan_start()
{
  local nic=${1}
  iptables -t nat -A POSTROUTING -o ${nic} -j MASQUERADE
}

lan_stop()
{
  local nic=${1}
  iptables -t nat -D POSTROUTING -o ${nic} -j MASQUERADE
}

frr_start()
{
  sed -i -r 's/^(zebra|ospfd)=no$/\1=yes/g' /etc/frr/daemons
  cp ${CONFIG_DIR}/frr.conf /etc/frr/frr.conf
  service frr restart
}

frr_stop()
{
  service frr stop
}

uvn_start()
{
  echo 1 > /proc/sys/net/ipv4/ip_forward
  for nic in ${vpn_interfaces}; do
    vpn_start ${nic}
  done
  for nic in ${lan_interfaces}; do
    lan_start ${nic}
  done
  frr_start
}

uvn_stop()
{
  frr_stop
  for nic in ${vpn_interfaces}; do
    vpn_stop ${nic}
  done
  for nic in ${lan_interfaces}; do
    lan_stop ${nic}
  done
}

case "${1}" in
  start)
    log_daemon_msg "Starting $DESC" $NAME
    if ! uvn_start; then
      log_end_msg 1
    else
      log_end_msg 0
    fi
    ;;
  stop)
    log_daemon_msg "Stopping $DESC" $NAME
    if ! uvn_stop; then
      log_end_msg 1
    else
      log_end_msg 0
    fi
    ;;
  *)
    echo "Usage: $SCRIPTNAME {start|stop}" >&2
    exit 1
    ;;
esac



