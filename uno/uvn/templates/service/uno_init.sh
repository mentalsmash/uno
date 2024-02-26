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
DAEMON=uvn
PIDFILE=/var/run/uvn.pid
SCRIPTNAME=/etc/init.d/$NAME

. /lib/lsb/init-functions

case "${1}" in
start)
  log_daemon_msg "Starting $DESC" $NAME
  start_daemon -p $PIDFILE $DAEMON cell agent -W -r /etc/uvn
  RETVAL=$?
  log_end_msg $RETVAL
  exit $RETVAL
  ;;
stop)
  log_daemon_msg "Stopping $DESC" $NAME
  killproc -p $PIDFILE $DAEMON
  RETVAL=$?
  [ $RETVAL -eq 0 ] && [ -e "$PIDFILE" ] && rm -f $PIDFILE
  log_end_msg $RETVAL
  exit $RETVAL
  ;;
restart)
  log_daemon_msg "Restarting $DESC" $NAME
  set -e
  $0 stop
  $0 start
  ;;
reload|force-reload)
  log_daemon_msg "Reloading configuration for $DESC" $NAME
  log_end_msg 0
  exit 0
  ;;
status)
  status_of_proc -p $PIDFILE $DAEMON $NAME && exit 0 || exit $?
  ;;
*)
  log_action_msg "Usage: $SCRIPTNAME {start|stop|status|restart|reload|force-reload}"
  exit 1
  ;;
esac

