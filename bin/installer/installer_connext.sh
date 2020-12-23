#!/bin/sh

################################################################################
# Detect RTI Connext DDS
################################################################################
# This file requires the following pre-defined global variables:
# - APT_GET
# - SUDO
# - UNO_PLATFORM
#
# This file requires the following pre-defined functions:
# - uno_mkdir
# - uno_chown
# - uno_info
# - uno_error
# - uno_yesno
# - uno_wprc_yes
# - uno_select
#

NDDSHOME_DEFAULT=/opt/rti/ndds

uno_nddshome_check()
{
    [ -n "${NDDSHOME}" ] && [ -d "${NDDSHOME}" -o -h "${NDDSHOME}" ]
}

uno_connext_target_check()
{
    uno_nddshome_check &&
        [ -d "${NDDSHOME}/lib/$(uno_connext_arch)" -o \
          -h "${NDDSHOME}/lib/$(uno_connext_arch)" ]
}

uno_connext_check()
{
    uno_connext_target_check
}

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

uno_connext_host()
{
    case "${UNO_PLATFORM}" in
        Ubuntu|Debian)
            printf "rti_connext_dds-6.0.1-pro-host-x64Linux.run"
            ;;
        Raspbian)
            printf "rti_connext_dds-6.0.1-pro-armv8Linux4gcc7.3.0.tar.gz"
            ;;
    esac
}

uno_connext_target()
{
    printf "rti_connext_dds-6.0.1-pro-target-$(uno_connext_arch).rtipkg"
}

uno_connext_configure_nddshome()
{
    local user_profile="${HOME}/.profile"

    if (grep "NDDSHOME=${NDDSHOME}" ${user_profile} ||
        grep ${NDDSHOME}/resource/scripts/rtisetenv_$(uno_connext_arch)) >/dev/null 2>&1; then
        uno_info "NDDSHOME already configured in ${user_profile}"
    fi

    uno_yesno "Configure NDDSHOME for user ${UNO_USER}" \
"Now that RTI Connext DDS has been installed on ${UNO_HOST}, you should configure variable NDDSHOME for user ${UNO_USER} to point to ${NDDSHOME}.

Would you like to add an entry for this in ${user_profile}?"

    if uno_wprc_yes; then
        printf "# Load RTI Connext DDS in the environment
export NDDSHOME=${NDDSHOME}

# Uncomment the following line on Bash to also configure LD_LIBRARY_PATH
# source ${NDDSHOME}/resource/scripts/rtisetenv_$(uno_connext_arch).bash
" >> ${user_profile}
        uno_info "enabled NDDSHOME for user ${UNO_USER}: ${NDDSHOME}"
    fi
}

uno_connext_install_host()
{
    local host_file="${1}"

    if [ ! -f "${host_file}" ]; then
        uno_error "Required host bundle not found: ${host_file}"
    fi

    local base_dir=$(dirname ${NDDSHOME})
    local install_dir="${base_dir}/rti_connext_dds-6.0.1"
    host_file=$(realpath ${host_file})

    uno_mkdir ${base_dir}

    uno_info "Installing RTI Connext DDS host bundle ${host_file} in ${NDDSHOME}"

    if [ ! -d "${install_dir}" ]; then
        case "${host_file}" in
        *.run)
            (
                cd $(dirname ${host_file})
                ./$(basename ${host_file}) --mode unattended --prefix ${base_dir} ||
                    uno_error "Connext host installer failed with rc: $?"
            )
            ;;
        *.tar.gz)
            (
                cd ${base_dir}
                tar xzf ${host_file}
            )
            ;;
        esac
    fi

    if [ "${install_dir}" != "${NDDSHOME}" ]; then
        # refuse to delete a directory, we expect a symlink
        ${SUDO} rm -f "${NDDSHOME}"
        ${SUDO} ln -s ${install_dir} ${NDDSHOME}
        uno_chown "${NDDSHOME}"
    fi
}

uno_connext_install_target()
{
    local tgt_file="${1}"

    if [ ! -f "${tgt_file}" ]; then
        uno_error "Required target bundle not found: ${tgt_file}"
    fi

    if ! uno_nddshome_check; then
        uno_error "NDDSHOME not found: ${NDDSHOME}"
    fi

    uno_info "Installing RTI Connext DDS target bundle ${tgt_file} in ${NDDSHOME}"

    # check if we have rtipkginstall
    local rtipkginstall="${NDDSHOME}/bin/rtipkginstall"

    if [ -x "${rtipkginstall}" ]; then
        uno_info "installing with rtpkginstall: $(basename ${tgt_file})"
        ${rtipkginstall} -u ${tgt_file}
    else
        uno_info "install manually: $(basename ${tgt_file})"
        local tmp_dir=/tmp/rtipkginstall-${RANDOM}
        tgt_file=$(realpath ${tgt_file})
        mkdir ${tmp_dir}
        cd ${tmp_dir}
        unzip ${tgt_file}
        unzip $(basename ${tgt-file} | sed 's/\.rtipkg/.zip/')
        rsync -ra rti_connext_dds-6.0.1/ ${NDDSHOME}/
    fi
}

uno_connext_install()
{
    local install_host= \
          install_tgt=
    
    if [ ! -d "${NDDSHOME}" ]; then
        install_host=$(uno_connext_host)
    fi

    if [ ! -d "${NDDSHOME}/lib/$(uno_connext_arch)" ]; then
        install_tgt=$(uno_connext_target)
    fi

    local nddshome=$(uno_select "RTI Connext DDS Installation Directory" \
        "RTI Connext DDS [$(uno_connext_arch)] will be installed in" \
        "${NDDSHOME:-${NDDSHOME_DEFAULT}}")
    
    export NDDSHOME="${nddshome}"

    if [ -n "${install_host}" ]; then
        uno_connext_install_host "${install_host}"
    fi

    if [ -n "${install_tgt}" ]; then
        uno_connext_install_target "${install_tgt}"
    fi

    if ! uno_connext_check; then
        uno_error "failed to install RTI Connext DDS"
    fi

    uno_connext_configure_nddshome
}
