#!/bin/sh

################################################################################
# apt helpers
################################################################################
# This file requires the following pre-defined global variables:
# - APT_GET
# - SUDO
#
# This file requires the following pre-defined functions:
# - uno_info
#

uno_apt_sources_deps()
{
    ${APT_GET} install -y -qq \
        apt-transport-https \
        ca-certificates \
        curl \
        gnupg-agent \
        software-properties-common
}

uno_apt_sources_add_debian_unstable()
{
    local sources_tgt=/etc/apt/sources.list.d/debian-unstable.list \
          prefs_tgt=/etc/apt/preferences.d/limit-debian-unstable

    uno_apt_sources_deps

    uno_info "Adding Debian's unstable apt repository to ${sources_tgt}"
    # Trust debian's apt repository
    ${SUDO} apt-key adv --keyserver hkp://p80.pool.sks-keyservers.net:80 \
                        --recv-keys 04EE7237B7D453EC 648ACFD622F3D138
    # Add debian's apt repository
    if [ ! -f ${sources_tgt} ]; then
        ${SUDO} sh -c "echo 'deb http://deb.debian.org/debian/ unstable main' > ${sources_tgt}"
    fi
    if [ ! -f ${prefs_tgt} ]; then
        ${SUDO} sh -c "printf 'Package: *\nPin: release a=unstable\nPin-Priority: 90\n' > ${prefs_tgt}"
    fi
    uno_info "Updating apt database..."
    ${APT_GET} update
}

uno_apt_sources_add_docker()
{
    uno_info "adding Docker repository to apt sources"
    
    uno_apt_sources_deps
    
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | ${SUDO} apt-key add -
    ${SUDO} add-apt-repository \
        "deb [arch=${docker_arch}] https://download.docker.com/linux/${docker_os} \
        $(lsb_release -cs) \
        stable"
}
