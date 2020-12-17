#!/bin/sh
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
set -e

################################################################################
# General Helper Functions
################################################################################

uno_error()
{
    echo ERROR: $@ >&2
    exit 1
}

uno_warning()
{
    echo WARNING: $@ >&2
}

uno_info()
{
    echo I: $@
}

uno_detect_os()
{
    local uno_platform=
    if [ -x "$(which lsb_release)" ]; then
        uno_platform=$(lsb_release -si)
    elif [ -d /etc/os-release ]; then
        uno_platform=$(
            (. /etc/os-release
             echo ${NAME} ) | awk '{ print $1 }' )
    else
        return
    fi

    case "${uno_platform}" in
        Ubuntu|Raspbian|Debian)
            echo "${uno_platform}"
            ;;
        *)
            ;;
    esac
}

_is_root()
{
    [ "$(id -u)" = 0 ]
}

################################################################################
# Configure screen for whiptail
################################################################################

# Find the rows and columns. Will default to 80x24 if it can not be detected.
screen_size=$(stty size 2>/dev/null || echo 24 80)
rows=$(echo $screen_size | awk '{print $1}')
columns=$(echo $screen_size | awk '{print $2}')

# Divide by two so the dialogs take up half of the screen, which looks nice.
r=$(( rows / 2 ))
c=$(( columns / 2 ))
# Unless the screen is tiny
r=$(( r < 20 ? 20 : r ))
c=$(( c < 70 ? 70 : c ))

################################################################################
# Detect system and greet user
################################################################################

if [ -z "${UNO_PLATFORM:=$(uno_detect_os)}" ]; then
    uno_error "failed to detect host OS, or OS not supported by this script."
fi

if ! _is_root; then
    uno_warning "this script requires root privileges. User ${UNO_USER:=$(whoami)} must be able to use sudo"
    SUDO=sudo
fi

if ! whiptail --title "Welcome to UNO Installer" \
            --yesno \
            "This script will install UNO on the current system.

Before we continue, here's some useful information that was automatically detected:

Host: ${UNO_HOST:=$(hostname)} (${UNO_PLATFORM})
User: ${UNO_USER}:${UNO_USER_GROUP:=$(groups | cut -d" " -f1)}
Source Repository: ${UNO_URL:=https://github.com/mentalsmash/uno} (${UNO_BRANCH:=master})
Installation Target: ${UNO_DIR:=/opt/uno}

Continue with the installation?" \
            ${r} ${c}; then
    echo "Someone is having cold feet"
    exit 1
fi

################################################################################
# Install Git
################################################################################

uno_git_clone()
{
    local tgt_dir="${1}" \
          tgt_url="${2}" \
          tgt_branch="${3}"

    uno_info "Cloning ${UNO_URL} (${UNO_BRANCH}) to ${tgt_dir}"

    cd ${tgt_dir}
    if [ ! -z "$(${GIT} remote 2>/dev/null | grep uno)" ]; then
        uno_info "Repository already initialized: ${tgt_dir}"
        return
    fi
    ${GIT} init
    ${GIT} remote add uno ${tgt_url}
    ${GIT} pull --depth 1 uno ${tgt_branch}
    ${GIT} checkout ${tgt_branch}
}

APT_GET="${SUDO} apt-get"

if [ ! -x "${GIT:=$(which git)}" ]; then
    uno_info "git not found in PATH, installing it"
    ${APT_GET} install -y -qq git
    GIT=$(which git)
fi

################################################################################
# Check if UNO is already installed
################################################################################

if [ -d "${UNO_DIR}" ]; then
    if whiptail --title "Detected existing UNO installation" \
                 --yesno \
                 --defaultno \
                 "UNO seems to be already installed under ${UNO_DIR}. Would you like to delete it?" \
                 ${r} ${c}; then
        ${SUDO} rm -rf "${UNO_DIR}"
    else
        if whiptail --title "Update UNO repository" \
                    --yesno \
                    "Would you like to update UNO's git repository in ${UNO_DIR} to the latest version?" \
                    ${r} ${c}; then
            uno_info "Updating UNO repository..."
            (
                cd ${UNO_DIR}
                ${GIT} pull uno ${UNO_BRANCH}
            )
        else
            uno_warning "UNO not updated: ${UNO_DIR}"
        fi
    fi
fi

################################################################################
# Clone Git Repository
################################################################################
if [ ! -d "${UNO_DIR}" ]; then
    uno_info "Creating base installation directory: ${UNO_DIR}"
    ${SUDO} mkdir -p "${UNO_DIR}"

    uno_info "Setting permission to: ${UNO_USER}:${UNO_USER_GROUP}"
    ${SUDO} chown ${UNO_USER}:${UNO_USER_GROUP} "${UNO_DIR}"

    uno_git_clone "${UNO_DIR}" "${UNO_URL}" "${UNO_BRANCH}"
else
    uno_info "UNO already installed under ${UNO_DIR}"
fi

################################################################################
# System Dependencies
################################################################################

uno_info "Installing common system dependencies..."

${APT_GET} install -y -qq iproute2 \
                      python3-pip \
                      gnupg2 \
                      dnsmasq \
                      quagga \
                      iputils-ping \
                      inetutils-traceroute \
                      dnsutils

case "${UNO_PLATFORM}" in
    Raspbian)
        ${APT_GET} install -y -qq libatlas-base-dev \
                              libopenjp2-7 \
                              libtiff5
        ;;
    *)
        ;;
esac

################################################################################
# WireGuard Installation
################################################################################

uno_install_wireguard_src()
{
    local wg_dir=${WG_DIR:=/opt/wg}
    if ! whiptail --title "Build WireGuard from source?" \
                  --yesno \
                  "It looks like we failed to install WireGuard from one of the known binary sources.

Would you like to try building WireGuard from source?

(Sources will be cloned under ${wg_dir})" \
                  ${r} ${c}; then
        uno_error "FAILED to install WireGuard"
    fi
    uno_info "Installing WireGuard's build dependencies..."
    ${APT_GET} install -y -qq libelf-dev \
                          linux-headers-$(uname -r) \
                          build-essential \
                          pkg-config
    
    uno_info "Cloning WireGuard to ${wg_dir}..."
    ${SUDO} mkdir -p ${wg_dir}
    ${SUDO} chown ${UNO_USER}:${UNO_USER_GROUP} "${wg_dir}"
    ${GIT} clone https://git.zx2c4.com/wireguard-linux-compat \
                 ${wg_dir}/wireguard-linux-compat
    ${GIT} clone https://git.zx2c4.com/wireguard-tools \
                 ${wg_dir}/wireguard-tools
    
    uno_info "Building WireGuard kernel module..."
    make -C ${wg_dir}/wireguard-linux-compat/src -j$(nproc)
    ${SUDO} make -C ${wg_dir}/wireguard-linux-compat/src install

    uno_info "Building wg tool..."
    make -C ${wg_dir}/wireguard-tools/src -j$(nproc)
    ${SUDO} make -C ${wg_dir}/wireguard-tools/src install
}


uno_install_wireguard_ubuntu()
{
    uno_info "Installing WireGuard..."
    # Try to install wireguard from packages
    if ! ${APT_GET} install -y -qq wireguard; then
        uno_install_wireguard_src
    fi
}

uno_install_wireguard_rpi()
{
    uno_info "Adding Debian apt repository for WireGuard packages..."
    # Trust debian's apt repository
    ${SUDO} apt-key adv --keyserver hkp://p80.pool.sks-keyservers.net:80 --recv-keys 04EE7237B7D453EC 648ACFD622F3D138
    # Add debian's apt repository
    if [ ! -f /etc/apt/sources.list.d/unstable.list -o \
         -z "$(cat /etc/apt/sources.list.d/unstable.list |
                grep "http://deb.debian.org/debian/ unstable main")" ]; then
        ${SUDO} sh -c "echo 'deb http://deb.debian.org/debian/ unstable main' >> /etc/apt/sources.list.d/unstable.list"
    fi
    if [ ! -f /etc/apt/preferences.d/limit-unstable -o \
         -z "$(cat /etc/apt/preferences.d/limit-unstable |
                grep "^Pin: release a=unstable$")" ]; then
        ${SUDO} sh -c "printf 'Package: *\nPin: release a=unstable\nPin-Priority: 90\n' >> /etc/apt/preferences.d/limit-unstable"
    fi
    uno_info "Updating apt database..."
    ${APT_GET} update
    uno_info "Installing WireGuard..."
    ${APT_GET} install -y -qq wireguard raspberrypi-kernel-headers
}

uno_install_wireguard_debian()
{
    uno_info "Installing WireGuard..."
    # Try to install wireguard from packages
    if ! ${APT_GET} install -y -qq wireguard; then
        uno_install_wireguard_src
    fi
}

uno_check_wireguard()
{
    [ -n "$(lsmod | grep wireguard)" ] &&
    ${SUDO} modprobe wireguard &&
    [ -x "$(which wg)" ]
}

if ! uno_check_wireguard; then
    whiptail --title "Install WireGuard" \
             --msgbox \
             "UNO requires WireGuard to create VPN links, but it looks like its kernel module is not available in the current kernel.

    We will try to install it from a binary package, or build it from source if that fails." \
             ${r} ${c};

    case "${UNO_PLATFORM}" in
        Ubuntu)
            uno_install_wireguard_ubuntu
            ;;
        Raspbian)
            uno_install_wireguard_rpi
            ;;
        Debian)
            uno_install_wireguard_debian
            ;;
    esac

    ${SUDO} modprobe wireguard

    if ! uno_check_wireguard; then
        uno_error "FAILED to detect WireGuard after installation."
    fi
else
    uno_info "WireGuard already installed: $(wg --version)"
fi

################################################################################
# Install Docker
################################################################################

uno_install_docker()
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
    uno_info "Installing Docker..."
    ${APT_GET} remove -y docker docker-engine docker.io containerd runc
    ${APT_GET} update
    ${APT_GET} install -y -qq apt-transport-https \
                            ca-certificates \
                            curl \
                            gnupg-agent \
                            software-properties-common
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | ${SUDO} apt-key add -
    ${SUDO} add-apt-repository \
        "deb [arch=${docker_arch}] https://download.docker.com/linux/${docker_os} \
        $(lsb_release -cs) \
        stable"
    ${APT_GET} update
    ${APT_GET} install -y -qq docker-ce docker-ce-cli containerd.io
}

uno_install_docker_sh()
{
    uno_info "Install Docker with convenience script..."
    curl -sSL https://get.docker.com | sh
}

uno_check_docker()
{
    [  -x "$(which docker)" ] && ${SUDO} docker ps -a 2>/dev/null 1>&2
}

# Check if docker is installed (naive check for 'docker' in PATH)
if ! uno_check_docker; then
    if whiptail --title "Run uno with Docker" \
                --yesno \
                "UNO's agent may be deployed inside a Docker container.

Would you like to install Docker on the current host?" \
                ${r} ${c}; then
        case "${UNO_PLATFORM}" in
            Ubuntu|Debian)
                uno_install_docker
                ;;
            Raspbian)
                uno_install_docker_sh
                ;;
        esac
    else
        uno_error "Please delete directory ${UNO_DIR} before running this script again."
    fi
else
    uno_info "Docker already installed: $(${SUDO} docker --version)"
fi

# Check if user can run docker
if ! docker ps -a 2>/dev/null 1>&2; then
    if [ -n "$(groups | tr ' ' '\n' | grep ^docker)" ]; then
        uno_error "current user is part of the docker group but can't run docker. Please check your installation."
    fi

    if whiptail --title "Configure Docker for user" \
                --yesno \
                "User '${UNO_USER}' is not configured to access the Docker daemon. All Docker operations will required the use of 'sudo'.

Would you like to add '${UNO_USER}' to group 'docker' to enable access to the Docker daemon?" \
                ${r} ${c}; then
        ${SUDO} usermod -a -G docker ${UNO_USER}
        
        uno_warning "Log out and back in again to enable new user credentials for Docker use."
    fi
fi

################################################################################
# Detect RTI Connext DDS
################################################################################
uno_connext_arch()
{
    case "${UNO_PLATFORM}" in
        Ubuntu|Debian)
            printf "x64Linux4gcc7.3.0"
            ;;
        Raspbian)
            printf "armv7Linuxgcc7.3.0"
            ;;
    esac
}
uno_check_connext()
{
    if [ ! -d "${NDDSHOME}" -o ! -d "${NDDSHOME}/lib/$(uno_connext_arch)" ]; then
        whiptail --title "RTI Connext DDS not found" \
                --msgbox \
                "UNO requires RTI Connext DDS to be installed and configured via the NDDSHOME variable.

    It doesn't look like NDDSHOME ('${NDDSHOME}') is properly configured, or you might have not yet installed RTI Connext DDS.

    Please visit https://www.rti.com/free-trial to retrieve a free copy.

    Make sure to include libraries for target $(uno_connext_arch) in your installation." \
                ${r} ${c}
        uno_error "RTI Connext DDS not found."
    else
        uno_info "RTI Connext DDS found: ${NDDSHOME}"
    fi
}

################################################################################
# Clone connextdds-py
################################################################################
uno_connextddspy_check()
{
    # Check if connextdds-py is already installed
    python3 -c "import rti.connextdds" &&
    sudo python3 -c "import rti.connextdds"
}

uno_connextddspy_wheel()
{
    local _whl=$(
        case "${UNO_PLATFORM}" in
        Ubuntu|Debian)
            printf "rti-0.0.1-cp36-cp36m-linux_x86_64.whl"
            ;;
        Raspbian)
            printf "rti-0.0.1-cp37-cp37m-linux_armv7l.whl"
            ;;
        esac
    )
    
    if [ -f "${_whl}" ]; then
        printf "${_whl}"
        return
    fi

    _whl="${DDSPY_DIR}/${_whl}"
    if [ -f "${_whl}" ]; then
        printf "${_whl}"
        return
    fi
}

uno_connextddspy_build()
{
    local tgt_dir="${1}"

    case "${UNO_PLATFORM}" in
        Raspbian)
            if ! whiptail --title "Building connextdds-py on Raspberry Pi" \
                     --yesno \
                     "connextdds-py requires large amounts of memory to build, and compilation will likely fail on Raspberry Pi 3 or earlier.

Would you still like to try building connextdds-py from source?" \
                     ${r} ${c}; then
                uno_error "Please install connextdds-py manually then try again."
                exit 1
            fi
            ;;
        *)
            ;;
    esac

    uno_check_connext

    uno_info "Installing dependencies for connextdds-py"
    pip3 install -q -U wheel \
               setuptools \
               cmake \
               patchelf-wrapper
    ${APT_GET} install -y -qq build-essential
    
    uno_info "Cloning connextdds-py..."
    ${SUDO} mkdir -p ${tgt_dir}
    ${SUDO} chown ${UNO_USER}:${UNO_USER_GROUP} "${tgt_dir}"
    uno_git_clone "${tgt_dir}" https://github.com/rticommunity/connextdds-py master
    (
        cd ${tgt_dir}
        uno_info "Configuring connextdds-py for $(uno_connext_arch)..."
        python3 configure.py $(uno_connext_arch)
        uno_info "Installing connextdds-py (this might take a while)..."
        CONNEXTDDS_ARCH=$(uno_connext_arch) pip3 install .
    )
    local whl=$(uno_connextddspy_wheel) \
          uno_dir="${UNO_DIR}/libuno/data/dds"
    
    # Install connextdds-py for root to using the generated wheel
    sudo pip3 install ${whl}

    uno_info "Caching $(basename ${whl}) in ${uno_dir}"
    cp ${whl} ${uno_dir}
}


if ! uno_connextddspy_check; then
    DDSPY_DIR="${DDSPY_DIR:=/opt/rti/connextdds-py}"
    _connextddspy_whl=$(uno_connextddspy_wheel)
    if [ -f "${_connextddspy_whl}" ] &&
        whiptail --title "Install connextdds-py from pre-built wheel" \
                 --yesno \
                 "Pre-built wheel for connextdds-py found at: $(uno_connextddspy_wheel)

Would you like to install it?" \
                 ${r} ${c}; then
        uno_info "Instaling connextdds-py with ${_connextddspy_whl}"
        pip3 install ${_connextddspy_whl}
        sudo pip3 install ${_connextddspy_whl}
    else
        uno_info "connextdds-py not found. Building it from source..."
        uno_connextddspy_build "${DDSPY_DIR}"
    fi
else
    uno_info "connextdds-py already installed"
fi


################################################################################
# Install UNO with pip
################################################################################
uno_info "Installing UNO..."
# Install uno for current user
pip3 install -e ${UNO_DIR}

# Install uno for root
sudo pip3 install -e ${UNO_DIR}


################################################################################
# Test uvn command
################################################################################

uno_info "Testing uvn command for ${UNO_USER}..."
uvn --version

uno_info "Testing uvn command for root..."
sudo uvn --version

################################################################################
# Install a trap to peform clean up tasks
################################################################################
_installer_cleanup()
{
    # Delete files generate by simple_validation.sh
    # Use UVN_ADDRESS in case user customized the value
    local test_uvn=$"{UVN_ADDRESS:-test-uvn.localhost}"
    rm -rf ${test_uvn} ${test_uvn}-cells
}

# Use bash's pseudo-signal EXIT to peform cleanup of generated files
trap _installer_cleanup EXIT

################################################################################
# Optionally run simple_validation.sh
################################################################################
_test_interrupted=
_test_check_exit()
{
    _test_interrupted=y
}

_test_dir=$(pwd)/uno-install-test
if whiptail --title "Validate UNO installation" \
            --yesno \
            "UNO has been successfully installed on the system.
            
Would you like to test the installation by generating a demo UVN configuration?

This might take a few minutes. Directory ${_test_dir} will be deleted if it already exists.

After generating a mock uvn configuration, the test will spawn the root registry agent to verify that you can actually run uno on the system.

Once the agent has started, you can resume this script by terminating the agent process with CTRL+C." \
            ${r} ${c}; then
    rm -rf ${_test_dir}
    mkdir ${_test_dir}
    cd ${_test_dir}
    trap _test_check_exit INT TERM
    # disable exit on error
    set +e
    ${UNO_DIR}/test/simple_validation.sh
    test_rc=$?
    if [ -n "${_test_interrupted}" ]; then
        uno_info "UNO validation succeeded!"
    elif [ "${test_rc}" -ne 0 ]; then
        uno_error "UNO validation FAILED (${test_rc})"
    else
        uno_error "uvn agent terminated before signal"
    fi
fi

################################################################################
# Done
################################################################################
whiptail --title "UNO installed" \
         --msgbox \
         "Congratulations, you have successfully installed UNO on ${UNO_HOST}.

Run \`uvn -h\` to get started." \
            ${r} ${c}

uno_info "UNO successfully installed."
