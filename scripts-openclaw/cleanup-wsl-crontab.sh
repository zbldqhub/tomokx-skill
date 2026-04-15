#!/bin/bash
# Remove the main trading cycle from crontab, keep trailing_stop_manager only.
crontab -l 2>/dev/null | grep -v "trade-cycle.sh" | crontab -
echo "Cleaned up main trading cycle from crontab. Current jobs:"
crontab -l
