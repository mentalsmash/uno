#!/bin/sh

### BEGIN INIT INFO
# Provides:          uvn
# Required-Start:    $local_fs $remote_fs $network $syslog
# Required-Stop:     $local_fs $remote_fs $network $syslog
# Default-Start:     2 3 4 5
# Default-Stop:      0 1 6
# Short-Description: UVN agent script
# Description:       Connects the host to a UVN.
### END INIT INFO

PATH=/bin:/usr/bin:/sbin:/usr/sbin:/usr/local/bin
DESC="local agent"
NAME=uvn
DAEMON=/usr/local/bin/uvn
PIDFILE=/var/run/uvn.pid
SCRIPTNAME=/etc/init.d/$NAME

. /lib/lsb/init-functions

set -e

case "${1}" in
start)
  log_daemon_msg "Starting $DESC" $NAME
  if ! start_daemon -p $PIDFILE $DAEMON cell agent -W -r /etc/uvn; then
    log_end_msg 1
  else
    log_end_msg 0
  fi
  ;;
stop)
  log_daemon_msg "Stopping $DESC" $NAME
  if ! killproc -p $PIDFILE $DAEMON; then
    log_end_msg 1
  else
    if [ -e "$PIDFILE" ]; then
      rm -f $PIDFILE
    fi
    log_end_msg 0
  fi
  ;;
restart)
  log_daemon_msg "Restarting $DESC" $NAME
  $0 stop
  $0 start
  ;;
reload|force-reload)
  log_daemon_msg "Reloading configuration for $DESC" $NAME
  log_end_msg 0
  ;;
status)
  status_of_proc -p $PIDFILE $DAEMON $NAME && exit 0 || exit $?
  ;;
*)
  log_action_msg "Usage: $SCRIPTNAME {start|stop|status|restart|reload|force-reload}"
  exit 1
  ;;
esac

