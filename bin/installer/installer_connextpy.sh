#!/bin/sh

################################################################################
# Clone connextdds-py
################################################################################
# This file requires the following pre-defined global variables:
# - APT_GET
# - SUDO
# - UNO_PLATFORM
# - UNO_DIR
#
# This file requires the following pre-defined functions:
# - uno_info
# - uno_error
# - uno_warning
# - uno_yesno
# - uno_wprc_no
# - uno_select
# - uno_msgbox
# - uno_git_clone
# - uno_connext_arch
# - uno_connext_host
# - uno_connext_target
#

CONNEXTDDSPY_WHEEL=
CONNEXTDDSPY_DIR=/opt/rti/connextdds-py
CONNEXTDDSPY_DEPS_PIP="wheel
                setuptools
                cmake
                patchelf-wrapper"
CONNEXTDDSPY_DEPS=build-essential
CONNEXTDDSPY_URL=https://github.com/rticommunity/connextdds-py
UNO_WHL_DIR="${UNO_DIR}/libuno/data/dds"

uno_connextddspy_check_missing()
{
    if [ ! -f "${UNO_WHL_DIR}/$(uno_connextddspy_wheel_name)" ]; then
        printf "${UNO_WHL_DIR}/$(uno_connextddspy_wheel_name)"
    fi
}

uno_connextddspy_wheel_name()
{
    local pyv=$(python3 --version | awk '{print $2;}' | cut -d. -f1,2 | tr -d .) \
          pya=

    case "${UNO_PLATFORM}" in
    Ubuntu|Debian)
        pya=x86_64
        ;;
    Raspbian)
        pya=armv7l
        ;;
    esac

    if [ "${pyv}" = "37" -o "${pyv}" = "36" ]; then
        local pextra=m
    fi

    printf "rti-0.0.1-cp${pyv}-cp${pyv}${pextra}-linux_${pya}.whl"
}

uno_connextddspy_wheel_find()
{
    local tgt_dir="${1}"
    local whl_name=$(uno_connextddspy_wheel_name)
    local whl="$(pwd)/${whl_name}"
    
    uno_info "searching for ${whl_name} in $(pwd)"
    
    CONNEXTDDSPY_WHEEL=
    
    if [ -f "${whl}" ]; then
        CONNEXTDDSPY_WHEEL="${whl}"
    elif [ -n "${tgt_dir}" ]; then
        uno_info "searching for ${whl_name} in ${tgt_dir}"
        whl="${tgt_dir}/${whl_name}"
        if [ -f "${whl}" ]; then
            CONNEXTDDSPY_WHEEL="${whl}"
        fi
    fi

    if [ -z "${CONNEXTDDSPY_WHEEL}" ]; then
        uno_warning "${whl_name} not found"
    else
        uno_info "found ${whl_name} in $(dirname ${CONNEXTDDSPY_WHEEL})"
    fi
}

uno_connextddspy_install()
{
    uno_msgbox "Install connextdds-py" \
"uno requires the connextdds-py DDS API for Python to run.

If you have wheel file $(uno_connextddspy_wheel_name) at hand, place it in the current directory, then restart the script to install it automatically.

We will now try to build a copy from source."

    local tgt_dir="$(uno_select "connextdds-py source directory" \
        "connextdds-py will be cloned in directory" \
        "${CONNEXTDDSPY_DIR}")"
    
    uno_connextddspy_wheel_find ${tgt_dir}

    local use_whl=

    if [ -f "${CONNEXTDDSPY_WHEEL}" ]; then
       uno_yesno "Install connextdds-py from wheel" \
"Pre-built wheel for connextdds-py found: ${CONNEXTDDSPY_WHEEL}

Would you like to install it?"
        uno_wprc_no || use_whl=y
    fi

    if [ -n "${use_whl}" ]; then
        uno_connextddspy_wheel_install ${CONNEXTDDSPY_WHEEL}
    else
        uno_connextddspy_wheel_generate "${tgt_dir}"
    fi

}

uno_connextddspy_wheel_generate()
{
    local tgt_dir="${1}"

    uno_info "Building connextdds-py from source..."

    case "${UNO_PLATFORM}" in
        Raspbian)
            uno_yesno "Building connextdds-py on Raspberry Pi" \
"connextdds-py requires large amounts of memory to build, and compilation will likely fail on Raspberry Pi 3 or earlier.

Would you like to try building connextdds-py from source anyway?"
            if uno_wprc_no; then
                uno_error "Please install connextdds-py manually for users ${UNO_USER} and root, then run this script again."
                exit 1
            fi
            ;;
        *)
            ;;
    esac

    if ! uno_connext_check; then

        uno_msgbox "RTI Connext DDS not found" \
"connextdds-py requires RTI Connext DDS to be installed and configured via the NDDSHOME variable in order to build.

If you have the following installer files, place them in the current directory, then restart the script to install them automatically:

- $(uno_connext_host)
- $(uno_connext_target)

You can visit https://www.rti.com/free-trial for a free copy.

We will now try to perform the installation for you."

        uno_connext_install
    else
        uno_info "RTI Connext DDS found: ${NDDSHOME}"
    fi

    uno_info "Installing Python dependencies for connextdds-py: ${CONNEXTDDSPY_DEPS_PIP}"
    pip3 install -q -U ${CONNEXTDDSPY_DEPS_PIP}
    uno_info "Installing system dependencies for connextdds-py: ${CONNEXTDDSPY_DEPS}"
    ${APT_GET} install -y -qq ${CONNEXTDDSPY_DEPS}
    
    uno_git_clone "connextdds-py"\
                  "${tgt_dir}" \
                  ${CONNEXTDDSPY_URL} master


    local b_whl=${tgt_dir}/$(uno_connextddspy_wheel_name)

    if [ ! -f "${b_whl}" ]; then
        uno_warning "Overwriting existing connextdds-py wheel: ${b_whl}"
    fi

    local njobs=$(uno_select "Number of build jobs for connextdds-py" \
"connextdds-py is a C++ wrapper layer that exposes the C++11 DDS API to Python.
C++ takes a long time to build, and a lot of memory too.
You should run more than one build job in order to speed up the process, but keep in mind your system might run out of memory with too many parallel jobs.

Number of parallel build jobs to spawn"
2)

    (
        cd ${tgt_dir}
        connext_arch=$(uno_connext_arch)
        uno_info "Configuring connextdds-py for ${connext_arch}..."
        python3 configure.py -j${njobs} ${connext_arch}
        uno_info "Generating connextdds-py wheel (this might take a while): ${whl_base}"
        CONNEXTDDS_ARCH=${connext_arch} pip3 wheel .
    )
    
    uno_connextddspy_wheel_find ${tgt_dir}

    if [ -z "${CONNEXTDDSPY_WHEEL}" -o "${CONNEXTDDSPY_WHEEL}" != "${b_whl}" ]; then
        uno_error "failed to load built connextdds-py wheel: ${b_whl}"
    fi

    uno_connextddspy_wheel_install "${CONNEXTDDSPY_WHEEL}"
}

uno_connextddspy_wheel_install()
{
    local whl="${1}"
    local whl_base=$(basename ${whl})

    # Install connextdds-py for user and root to using the generated wheel
    uno_info "Installing connextdds-py for ${UNO_USER} from: ${whl}"
    pip3 install ${whl}

    uno_info "Installing connextdds-py for root from: ${whl}"
    sudo pip3 install ${whl}

    uno_info "Caching ${whl_base} in ${UNO_WHL_DIR}"
    cp ${whl} ${UNO_WHL_DIR}/$(uno_connextddspy_wheel_name)
}