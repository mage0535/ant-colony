#!/bin/bash
# Ant Colony — service health check
# Runs every minute via systemd timer.
# Restarts any service that is not active.
SERVICES="ant-colony-gateway ant-colony-callback ant-colony-dashboard"
for s in $SERVICES; do
    if ! systemctl is-active --quiet "$s" 2>/dev/null; then
        systemctl restart "$s"
        logger -t "ant-health" "Restarted $s (was inactive)"
    fi
done
