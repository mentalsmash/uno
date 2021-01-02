#!/bin/sh

uno_installer_load()
{
    uno_info "loading installer component: ${1}"
    . ${1}
}

INSTALLER_COMPONENTS="apt
                      connext
                      connextpy
                      docker
                      env
                      wg
                      test"

for comp in ${INSTALLER_COMPONENTS}; do
    uno_installer_load ${UNO_DIR}/bin/installer/installer_${comp}.sh
done

################################################################################
# Install System Dependencies
################################################################################
UNO_DEPS_SYS="iproute2
              python3-pip
              gnupg2
              dnsmasq
              quagga
              iputils-ping
              inetutils-traceroute
              dnsutils
              tmux
              screen
              rsync
              qrencode
              unzip"
UNO_DEPS_RPI="libatlas-base-dev
              libopenjp2-7
              libtiff5"

UNO_DEPS="${UNO_DEPS_SYS}"
case "${UNO_PLATFORM}" in
    Raspbian)
        UNO_DEPS="${UNO_DEPS} ${UNO_DEPS_RPI}"
        ;;
    *)
        ;;
esac

uno_info "Installing uno's system dependencies: ${UNO_DEPS}"
${APT_GET} install -y -qq ${UNO_DEPS}

################################################################################
# WireGuard Installation
################################################################################
if ! uno_wireguard_check; then
    uno_wireguard_install

    if ! uno_wireguard_check; then
        uno_error "Failed to detect WireGuard after installation."
    fi
else
    uno_info "WireGuard already installed: $(wg --version)"
fi

################################################################################
# Install Docker
################################################################################
# Check if docker is installed (naive check for 'docker' in PATH)
if ! uno_docker_check; then
    uno_docker_install
else
    uno_info "Docker already installed: $(${SUDO} docker --version)"
    DOCKER_AVAILABLE=y
fi

# Check if user can run docker
if [ -n "${DOCKER_AVAILABLE}" ]; then
    uno_docker_setup_user
fi

################################################################################
# Clone and build connextdds-py
################################################################################
CONNEXTDDSPY_WHEEL_BUILD=
CONNEXTDDSPY_WHEEL_MISSING=$(uno_connextddspy_check_missing)

if [ -n "${CONNEXTDDSPY_WHEEL_MISSING}" ]; then
    uno_info "installing connextdds-py to ${CONNEXTDDSPY_WHEEL_MISSING}"
    uno_connextddspy_wheel_find
    if [ -z "${CONNEXTDDSPY_WHEEL}" ]; then
        uno_info "must build connextdds-py wheel from source"
        CONNEXTDDSPY_WHEEL_BUILD=yes
    else
        uno_connextddspy_wheel_install "${CONNEXTDDSPY_WHEEL}"
    fi
else
    uno_info "connextdds-py already installed in ${UNO_WHL_DIR}"
fi

if ! uno_python_check rti.connextdds || [ -n "${CONNEXTDDSPY_WHEEL_BUILD}" ]; then
    uno_connextddspy_install
fi

if ! uno_python_check rti.connextdds; then
    uno_error "Failed to load connextdds-py"
else
    uno_info "installed: connextdds-py"
fi

################################################################################
# Install UNO with pip
################################################################################
UNO_INSTALL_USER=
UNO_INSTALL_ROOT=

if uno_python_check_user libuno; then
    uno_yesno "Re-install uno for ${UNO_USER}?" \
"uno seems to be already installed for user \`${UNO_USER}\`.

Would you like to re-install it anyway?" \
    --defaultno

    uno_wprc_no || UNO_INSTALL_USER=y
else
    UNO_INSTALL_USER=y
fi

if uno_python_check_root libuno; then
    uno_yesno "Re-install uno for root?" \
"uno seems to be already installed for root.

Would you like to re-install it anyway?" \
    --defaultno

    uno_wprc_no || UNO_INSTALL_ROOT=y
else
    UNO_INSTALL_ROOT=y
fi

if [ -n "${UNO_INSTALL_USER}" ]; then
    uno_info "Installing uno for ${UNO_USER}"
    # Install uno for current user
    pip3 install -e ${UNO_DIR}
fi

if [ -n "${UNO_INSTALL_ROOT}" ]; then
    uno_info "Installing uno for root"
    # Install uno for root
    sudo pip3 install -e ${UNO_DIR}
fi

if ! uno_python_check libuno; then
    uno_error "Failed to load libuno"
else
    uno_info "installed: uno"
fi

################################################################################
# Test uvn command
################################################################################
uno_info "Testing uvn command for ${UNO_USER}..."
uvn --version

uno_info "Testing uvn command for root..."
sudo uvn --version

################################################################################
# Optionally run the included tests
################################################################################
uno_installer_test

################################################################################
# Done
################################################################################
uno_msgbox "UNO installed" \
"Congratulations, you have successfully installed UNO on ${UNO_HOST}.

Run \`uvn -h\` to get started with a list of available commands or visit ${UNO_WEB} to consult the documentation." \
            ${r} ${c}

uno_info "UNO successfully installed."
