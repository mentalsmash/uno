#!/bin/sh

################################################################################
# Docker helpers
################################################################################
# This file requires the following pre-defined global variables:
# - APT_GET
# - SUDO
# - UNO_PLATFORM
#
# This file requires the following pre-defined functions:
# - uno_info
# - uno_error
# - uno_yesno
# - uno_wprc_yes
#

DOCKER_AVAILABLE=

uno_docker_install_apt()
{
    local docker_arch=
    case "${UNO_PLATFORM}" in
        Ubuntu)
            docker_arch="amd64"
            docker_os="ubuntu"
            ;;
        Debian)
            docker_arch="amd64"
            docker_os="debian"
            ;;
        *)
            return 1
            ;;
    esac
    uno_info "removing older Docker versions..."
    ${APT_GET} remove -y docker docker-engine docker.io containerd runc >/dev/null 2>&1 ||
        [ -n "some_packages_not_installed" ]
    uno_apt_sources_add_docker
    uno_info "installing Docker..."
    ${APT_GET} update
    ${APT_GET} install -y -qq docker-ce docker-ce-cli containerd.io
}

uno_docker_install_sh()
{
    uno_info "Install Docker with convenience script..."
    curl -sSL https://get.docker.com | sh
}

uno_docker_check()
{
    [  -x "$(which docker)" ] && ${SUDO} docker ps -a 2>/dev/null 1>&2
}

uno_docker_install()
{
    uno_yesno "Run uno with Docker" \
"UNO's agent may be deployed inside Docker containers.

Would you like to install Docker on the current host?"
    if uno_wprc_yes; then
        case "${UNO_PLATFORM}" in
            Ubuntu|Debian)
                uno_docker_install_apt
                ;;
            Raspbian)
                uno_docker_install_sh
                ;;
        esac
        uno_docker_check ||
            uno_error "Docker not available after installation"
        DOCKER_AVAILABLE=y
    else
        uno_warning "Docker not installed"
    fi
}

uno_docker_setup_user()
{

    if ! docker ps -a 2>/dev/null 1>&2; then
        if [ -n "$(groups | tr ' ' '\n' | grep ^docker)" ]; then
            uno_error "current user is part of the docker group but can't run docker. Please check your installation."
        fi

        uno_yesno "Configure Docker for user" \
    "User '${UNO_USER}' is not configured to access the Docker daemon. All Docker operations will require the use of 'sudo'.

    Would you like to add '${UNO_USER}' to group 'docker' to enable access to the Docker daemon?"
        if uno_wprc_yes; then
            ${SUDO} usermod -a -G docker ${UNO_USER}
            uno_warning "New credentials for user ${UNO_USER} will be enabled on the next login."
        fi
    else
        uno_info "Docker enabled for ${UNO_USER}"
    fi
}