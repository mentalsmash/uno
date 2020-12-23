#!/bin/sh

################################################################################
# WireGuard helpers
################################################################################
# This file requires the following pre-defined global variables:
# - APT_GET
# - SUDO
# - UNO_PLATFORM

WG_DIR=/opt/wg
WG_DEPS="libelf-dev
         linux-headers-$(uname -r)
         build-essential
         pkg-config" \
WG_URL=https://git.zx2c4.com/wireguard-linux-compat \
WG_URL_TOOLS=https://git.zx2c4.com/wireguard-tools \
WG_BRANCH=master

uno_wireguard_build()
{
    local wg_dir=$(uno_select "WireGuard source directory" \
                              "WireGuard will be cloned in directory" \
                              ${WG_DIR})
    
    uno_info "Installing WireGuard's build dependencies..."
    ${APT_GET} install -y -qq ${WG_DEPS}
    
    uno_info "Cloning WireGuard to ${wg_dir}..."
    uno_mkdir ${wg_dir}
    uno_git_clone "wireguard kernel module" 
                  "${wg_dir}/wireguard-linux-compat" ${WG_URL} ${WG_BRANCH}
    uno_git_clone "wireguard tools" \
                  "${wg_dir}/wireguard-tools" ${WG_URL_TOOLS} ${WG_BRANCH}
    
    uno_info "Building WireGuard kernel module..."
    make -C "${wg_dir}/wireguard-linux-compat/src" -j$(nproc)
    ${SUDO} make -C "${wg_dir}/wireguard-linux-compat/src" install

    uno_info "Building wg tool..."
    make -C "${wg_dir}/wireguard-tools/src" -j$(nproc)
    ${SUDO} make -C "${wg_dir}/wireguard-tools/src" install
}

uno_wireguard_install()
{
    uno_msgbox "Installing WireGuard" \
"UNO requires WireGuard to create VPN links.

We will try to install it from binary packages, or build it from source if that fails."

    local wireguard_pkg=
    
    uno_info "Installing WireGuard..."

    case ${UNO_PLATFORM} in
        Ubuntu|Debian)
            wireguard_pkg="wireguard linux-headers-$(uname -r)"
            ;;
        Raspbian)
            uno_apt_sources_add_debian_unstable
            wireguard_pkg="wireguard raspberrypi-kernel-headers"
            ;;
        *)
            ;;
    esac

    if [ -n "${wireguard_pkg}" ]; then
        uno_info "Installing WireGuard from binary packages"
        if ! ${APT_GET} install -y -qq ${wireguard_pkg}; then
            uno_warning "Failed to install WireGuard from binary packages."
            wireguard_pkg=
        fi
    fi 

    # Try to install wireguard from packages
    if [ -z "${wireguard_pkg}" ]; then
        uno_yesno "Build WireGuard from source?" \
"Failed to install WireGuard from binary packages.

Would you like to try building it from source?

The kernel headers are required to do this, and they will be automatically installed."
        if uno_wprc_no; then
            uno_error "WireGuard must be installed to run uno"
        fi
        uno_wireguard_build
    fi
}

uno_wireguard_check()
{
    # Try to load wireguard module (noop if already loaded)
    ${SUDO} modprobe wireguard &&
    # check that it's loaded
    [ -n "$(lsmod | grep wireguard)" ] &&
    # Check that wireguard-tools are also installed
    [ -x "$(which wg)" ]
}
