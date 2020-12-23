#!/bin/sh

################################################################################
# Installation Environment Helpers
################################################################################
# This file doesn't have any external dependency.

uno_ubuntu_release()
{
    lsb_release -r | awk '{print $2;}'
}

uno_python_check_user()
{
    # Check if a python module is already installed
    python3 -c "import ${1}; print(${1}.__name__)" 1>/dev/null || return 0
}

uno_python_check_root()
{
    # Check if a python module is already installed
    sudo python3 -c "import ${1}; print(${1}.__name__)" 1>/dev/null || return 0
}

uno_python_check()
{
    uno_python_check_user "${1}"
    uno_python_check_root "${1}"
}
