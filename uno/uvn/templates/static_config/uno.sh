#!/bin/sh -e
###############################################################################
# Shell helpers to configure a host for connection to a UVN
###############################################################################

# Log an info message
uvn_log_info()
{
  printf -- "[INFO] $(basename ${0}): $@\n" >&2
}

# Log an error message and possibly terminate the script
# by returning a failure
uvn_log_failed()
{
  printf -- "[ERROR] $(basename ${0}): $@\n" >&2
}

# Initialize a WireGuard VPN interface.
uvn_vpn_start()
{
  local nic=${1} \
        config="${2}" \
        ip_config="${3}"

  uvn_log_info "enabling VPN interface: ${nic}"

  # Read nic IP address from configuration file
  local nic_addr=$(grep "^${nic}=" "${ip_config}" | cut -d= -f2- | xargs)

  # Make sure the interface doesn't exist
  ip link delete ${nic} || true

  # Create the interface
  if ! (
    set -x
    ip link add dev ${nic} type wireguard
  ); then
    uvn_log_failed "failed to create VPN interface: ${nic}"
    return 1
  fi

  # Reset the interface's configuration if it exists
  ip link set down dev ${nic} || true
  ip address flush dev ${nic} || true

  # Create the interface
  if ! (
    set -x
    ip address add dev ${nic} ${nic_addr}
  ); then
    uvn_log_failed "failed to configure address on VPN interface: ${nic} -> ${nic_addr}"
    return 1
  fi

  # Configure WireGuard on the inteface
  if ! (
    set -x
    wg setconf ${nic} "${config}"
  ); then
    uvn_log_failed "failed to configure VPN interface: ${nic}"
    return 1
  fi

  # Enable the interface
  if ! (
    set -x
    ip link set up dev ${nic}
  ); then
    uvn_log_failed "failed to enable VPN interface: ${nic}"
    return 1
  fi

  if ! (
    set -x

    # Accept incoming packets from the interface
    iptables -A INPUT -i ${nic} -j ACCEPT

    # Enable in/out IP forwarding on the interface
    iptables -A FORWARD -i ${nic} -j ACCEPT
    iptables -A FORWARD -o ${nic} -j ACCEPT

    # Enable output NAT on the interface 
    iptables -t nat -A POSTROUTING -o ${nic} -j MASQUERADE
  ); then
    uvn_log_failed "failed to configure iptables for VPN interface: ${nic}"
    return 1
  fi

  uvn_log_info "VPN interface ready: ${nic}"
}


# Disable a WireGuard VPN interface.
uvn_vpn_stop()
{
  local nic=${1}

  uvn_log_info "disabling VPN interface: ${nic}"
  (
    set -x

    # Disable IP forwarding
    iptables -D FORWARD -i ${nic} -j ACCEPT
    iptables -D FORWARD -o ${nic} -j ACCEPT

    # Stop accepting packets
    iptables -D INPUT -i ${nic} -j ACCEPT

    # Disable output NAT
    iptables -t nat -D POSTROUTING -o ${nic} -j MASQUERADE

    # Reset interface
    ip link set down dev ${nic}
    ip address flush dev ${nic}
  ) || true # Ignore failures since we're going to delete the interface anyway

  # delete the interface
  if ! (
    set -x
    ip link delete ${nic}
  ); then
    uvn_log_failed "VPN interface not deleted"
    return 1
  fi

  uvn_log_info "VPN interface deleted: ${nic}"
}


# Configure a LAN interface to communicate with the UVN
uvn_lan_start()
{
  local nic=${1}

  uvn_log_info "enabling LAN interface: ${nic}"
  if ! (
    # Enable output NAT
    iptables -t nat -A POSTROUTING -o ${nic} -j MASQUERADE
  ); then
    uvn_log_failed "failed to configure iptables for LAN interface: ${nic}"
    return 1
  fi
  uvn_log_info "LAN interface ready: ${nic}"
}


# Stop communication between a LAN interface and the UVN
uvn_lan_stop()
{
  local nic=${1}

  uvn_log_info "disabling LAN interface: ${nic}"
  if ! (
    # Disable output NAT
    iptables -t nat -D POSTROUTING -o ${nic} -j MASQUERADE
  ); then
    uvn_log_failed " failed to disable iptables for LAN interface: ${nic}"
    return 1
  fi

  uvn_log_info "LAN interface deconfigured: ${nic}"
}


# Configure all network interfaces associated with the UVN
uvn_net_start()
{
  local vpn_configs_dir="${1}" \
    vpn_interfaces="${2}" \
    lan_interfaces="${3}" \
    ip_config="${4}"

  uvn_log_info "starting all network interfaces"

  for nic in ${vpn_interfaces}; do
    uvn_vpn_start ${nic} "${vpn_configs_dir}/${nic}.conf" "${ip_config}"
  done

  for nic in ${lan_interfaces}; do
    uvn_lan_start ${nic}
  done

  # Make sure IPv4 forwarding is enabled in the kernel
  echo 1 > /proc/sys/net/ipv4/ip_forward

  uvn_log_info "network interfaces started"
}


# Disable all network interfaces associated with the UVN
uvn_net_stop()
{
  local vpn_interfaces="${1}" \
    lan_interfaces="${2}"

  uvn_log_info "stopping all network interfaces"

  local failed=

  for nic in ${vpn_interfaces}; do
    if ! uvn_vpn_stop ${nic}; then
      failed="${nic} ${failed}"
    fi
  done

  for nic in ${lan_interfaces}; do
    if ! uvn_lan_stop ${nic}; then
      failed="${nic} ${failed}"
    fi
  done

  if [ -n "${failed}" ]; then
    return 1
  fi

  uvn_log_info "network interfaces stopped"
}


# Configure and start a cell's IP router.
uvn_router_start()
{
  local frr_conf="${1}"

  uvn_log_info "starting router"
  if ! (
    set -x
    sed -i -r 's/^(zebra|ospfd)=no$/\1=yes/g' /etc/frr/daemons
  ); then
    uvn_log_failed "failed to enable frr daemons"
    return 1
  fi
  if ! (
    cp "${frr_conf}" /etc/frr/frr.conf
  ); then
    uvn_log_failed "failed to intall frr configuration"
    return 1
  fi
  if ! (
    set -x
    service frr restart
  ); then
    uvn_log_failed "failed to start frr service"
    return 1
  fi

  uvn_log_info "router started"
}


# Stop a cell's IP router.
uvn_router_stop()
{
  if ! (
    set -x
    service frr stop
  ); then
    uvn_log_failed "failed to stop frr service"
    return 1
  fi
}


# Configure and start all UVN services on the cell
uvn_cell_start()
{
  local cell_dir="${1}"
        vpn_interfaces="${2}"
        lan_interfaces="${3}"

  uvn_net_start \
    "${cell_dir}/wg" \
    "${vpn_interfaces}" \
    "${lan_interfaces}" \
    "${cell_dir}/wg-ip.config"

  uvn_router_start \
    "${cell_dir}/frr.conf"
}


# Stop all UVN services on the cell
uvn_cell_stop()
{
  local vpn_interfaces="${1}"
        lan_interfaces="${2}"

  if ! uvn_net_stop \
    "${vpn_interfaces}" \
    "${lan_interfaces}"; then
    uvn_log_failed "there were error disabling some network interface: ${failed}"
    uvn_log_failed "please review the system's state before continuing."
  fi

  uvn_router_stop || true
}

# Check if the agent is running
uvn_detect_agent()
{
  if [ -e "${UVN_AGENT_PID}" ]; then
    uvn_log_failed "cell agent detected: ${UVN_AGENT_PID}"
    uvn_log_failed "refusing to perform static configuration operations while agent is running."
    return
  fi
  return 1
}


# All cell configuration is located in UVN_CELL_ROOT
# which the defaults to the script's location.
: "${UVN_CELL_ROOT:=$(cd "$(dirname $0)" && pwd)}"

# The agent should have generated a configuration file when bootstrapped
UVN_CELL_CONF="${UVN_CELL_ROOT}/uvn.config"

# Throw an error if the configuration file doesn't exist, since we
# can't do much without it
if [ ! -e "${UVN_CELL_CONF}" ]; then
  uvn_log_failed "no cell configuration found in '${UVN_CELL_ROOT}'"
  exit 1
fi

# Load configuration variables
. "${UVN_CELL_CONF}"

UVN_NET_PID=/var/run/uno/uvn-net.up
UVN_AGENT_PID=/var/run/uno/uvn-agent.pid

case "${1}" in
start)
  if uvn_detect_agent; then
    exit 1
  fi

  if [ -e "${UVN_NET_PID}" ]; then
    if [ "$(cat ${UVN_NET_PID} 2>/dev/null)" = "${UVN_DEPLOYMENT}" ]; then
      uvn_log_info "already initialized: ${UVN_DEPLOYMENT}"
      exit 0
    else
      uvn_log_failed "system is already initialized with another deployment: ${UVN_DEPLOYMENT}"
      exit 1
    fi
  fi

  uvn_cell_start \
    "${UVN_CELL_ROOT}" \
    "${UVN_CELL_VPN_INTERFACES}" \
    "${UVN_CELL_LAN_INTERFACES}"
  
  mkdir -p $(dirname ${UVN_NET_PID})
  echo ${UVN_DEPLOYMENT} > ${UVN_NET_PID}

  uvn_log_info "cell services started"
  ;;
stop)
  if uvn_detect_agent; then
    exit 1
  fi

  if [ -e "${UVN_NET_PID}" ]; then
    if [ "$(cat ${UVN_NET_PID} 2>/dev/null)" != "${UVN_DEPLOYMENT}" ]; then
      uvn_log_failed "system is already initialized with another deployment: ${UVN_DEPLOYMENT}"
      exit 1
    fi
  fi

  uvn_cell_stop \
    "${UVN_CELL_VPN_INTERFACES}" \
    "${UVN_CELL_LAN_INTERFACES}"

  rm -rf ${UVN_NET_PID}

  uvn_log_info "cell services stopped"
  ;;
*)
  uvn_log_failed "invalid arguments: '$@'"
  printf -- "usage: $(basename ${0}) start|stop"
  exit 254
esac

