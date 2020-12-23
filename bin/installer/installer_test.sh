#!/bin/sh


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

################################################################################
# Optionally run the included tests
################################################################################
_test_interrupted=
_test_rc=
_test_dir=
_test=
_test_desc=
_test_disabled=
_test_do_run=

uno_test_interrupted()
{
    _test_interrupted=y
}

uno_test_check()
{
    if [ -n "${_test_interrupted}" -o ${_test_rc} -eq 0 ]; then
        uno_info "test ${_test} succeeded!"
    elif [ ${_test_rc} -ne 0 ]; then
        uno_error "test ${_test} FAILED (${_test_rc})"
    fi
}

uno_test_run()
{
    _test="${1}"
    _test_run="${2}"
    _test_dir="${3}"
    _test_desc="${4}"
    _test_exit="${5}"
    _test_disabled="${6}"

    local test_disabled=$(
        if uno_nonint ||
           [ -z "${_test_do_run}" ] ||
           [ -n "${_test_disabled}" ]; then
            printf disabled
        fi
    )

    [ -n "${test_disabled}" ] || uno_yesno "Run test ${_test}" \
"${_test} ${_test_desc}

Directory ${_test_dir} will be created (and deleted if it already exists).

Run the test?

(${_test_exit})"

    if [ -n "${test_disabled}" ] || uno_wprc_no; then
        uno_info "test skipped: ${_test}"
        return
    fi

    ${SUDO} rm -rf ${_test_dir}
    uno_mkdir ${_test_dir}
    trap uno_test_interrupted INT TERM
    cd ${_test_dir}
    # disable exit on error
    set +e
    ${_test_run}
    _test_rc=$?
    # re-enable exit on error
    set -e
    cd -
    uno_test_check ${_test_rc}
}

################################################################################
# simple_validation.sh
################################################################################
uno_installer_test_simple_validation()
{
    uno_test_run \
        simple_validation \
        ${UNO_DIR}/test/simple_validation.sh \
        $(pwd)/uno-test-simple \
"performs a basic validation of the uno installation:

- It creates a new UVN configuration.
- It attaches 3 cells to the UVN.
- It generates a new deployment.
- It installs the generated deployment packages.
- It starts the root agent." \
"You can exit the test at any time by pressing CTRL+C."
}

################################################################################
# experiment_local.sh
################################################################################
_experiment_local_nets=4
_experiment_local_deploy="generate deployment"
_tmux_escape="CTRL+B"

_tmux_check_escape()
{
    local tmux_conf="${HOME}/.tmux.conf"
    local tmux_cfg="set -g prefix C-a"
    ! grep "${tmux_cfg}" ${tmux_conf} || local already_enabled=y

    if [ ! -f "${tmux_conf}" -o -z "${already_enabled}" ] ; then
        uno_yesno "Update tmux escape sequence" \
"It looks like you are using tmux's default escape sequence, CTRL+B.
This sequence must be typed to perform any command, and it's a bit awkward.

Taking inspiration from the \`screen\` utility, we think CTRL+A is a more natural mapping.

Would you like to install rule '${tmux_cfg}' in ${tmux_conf} to modify the escape sequence to CTRL+A?"

        if uno_wprc_yes; then
            printf "# make ctrl-a the default key to get to \"meta\" mode instead of ctrl-b
${tmux_cfg}
" >> ${tmux_conf}
            uno_warning "Enabled CTRL+A as tmux escape sequence"
            _tmux_escape="CTRL+A"
        fi
    elif [ -z "${already_enabled}" ]; then
        _tmux_escape="CTRL+A"
    fi
}

_experiment_local()
{
    case "${UNO_PLATFORM}" in
    Raspbian)
        local rpi_warning="\nSince you are running on a Raspberry Pi, you should keep this number low or risk running out of memory (e.g. 2-3 networks).\n"
    esac

    _experiment_local_nets=$(uno_select "number of private networks" \
        "Select the number of private networks that the test will attach to the UVN.
${rpi_warning}
Current value" \
        ${_experiment_local_nets})
    
    _experiment_local_deploy=$(uno_select "generate deployment configuration" \
        "The test can optionally generate a deployment configuration before starting the nodes.
If you skip this step, the UVN will be launched without a backbone.
You can generate a deployment at any time by navigating to the root agent's container, and using alias \`uvnd_deploy\`.

Current value (leave empty to disable)" \
        ${_experiment_local_deploy})
    
    _tmux_check_escape

    uno_msgbox "One more thing before we start..." \
"The test uses tmux to display terminals to each containers.

You can navigate between tmux panels using ${_tmux_escape} and the arrow keys.
To switch between windows press ${_tmux_escape} then P or N.

All panels display either one of the container's logs, or a control shell inside it."

    (
        cd ${_test_dir}
        NETS=${_experiment_local_nets} \
        PREDEPLOY=${_experiment_local_deploy} \
        VERBOSE=y \
            ${UNO_DIR}/test/local_deploy/experiment_local.sh
    )
}

uno_installer_test_experiment_local()
{
    uno_test_run \
        local_deploy \
        _experiment_local \
        $(pwd)/uno-test-local \
"is a more advanced test which simulates a uvn locally using Docker containers.
The test creates an arbitrary number of private networks, each one containing 3 hosts (a gateway, a cell, and regular host).
All LANs are connected to a common \"internet\" which contains the UVN registry, and a \"roaming\" cell." \
"Use CTRL+C to interrupt the test while loading. Exit tmux by pressing ${_tmux_escape}, and typing ':kill-session'" \
        $([ -n "${_docker_avail}" ] || printf test_disabled)
}


################################################################################
# Top-level function to run tests
################################################################################
uno_installer_test()
{

    uno_yesno "Validate uno installation" \
    "uno has been successfully installed on the system.

    Would you like to run some demo scenarios to verify that it actually works?"

    uno_wprc_yes || return

    # Use bash's pseudo-signal EXIT to peform cleanup of generated files
    trap _installer_cleanup EXIT
    
    uno_installer_test_simple_validation
    uno_installer_test_experiment_local
}