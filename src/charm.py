#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

"""Charm for MySQL HAProxy."""

import logging

from ops.charm import CharmBase, ConfigChangedEvent
from ops.main import main
from ops.model import ActiveStatus, WaitingStatus
from ops.pebble import Layer

logger = logging.getLogger(__name__)


WORKLOAD_CONTAINER_NAME = "mysql-haproxy"
HAPROXY_BACKEND_CONFIG_PATH = "/configs/haproxy.cfg"
HAPROXY_USERNAME = "haproxy"


class MySQLHAProxyOperatorCharm(CharmBase):
    """Charm the service."""

    def __init__(self, *args):
        super().__init__(*args)

        self.service_name = "mysql-haproxy"

        self.framework.observe(
            self.on.mysql_haproxy_pebble_ready, self._on_mysql_haproxy_pebble_ready
        )
        self.framework.observe(self.on.config_changed, self._on_config_changed)

    # =======================
    #  Charm Lifecycle Hooks
    # =======================

    def _on_mysql_haproxy_pebble_ready(self, event) -> None:
        """Define and start a workload using the Pebble API."""
        # Get a reference the container attribute on the PebbleReadyEvent
        container = event.workload

        # Add initial Pebble config layer using the Pebble API
        pebble_layer = self._mysql_haproxy_pebble_layer()
        container.add_layer(self.service_name, pebble_layer, combine=True)

        self._push_haproxy_config_to_workload()

        # Autostart any services that were defined with startup: enabled
        container.autostart()

        self.unit.status = ActiveStatus("HAProxy started in the workload container")

    def _on_config_changed(self, event: ConfigChangedEvent) -> None:
        """Handle changes in configuration."""
        container = self.unit.get_container(WORKLOAD_CONTAINER_NAME)

        # Wait until pebble is operational
        if not container.can_connect():
            self.unit.status = WaitingStatus(
                f"Waiting for {WORKLOAD_CONTAINER_NAME} container to start"
            )
            event.defer()
            return

        # Push an updated HAProxy config to the workload container and restart HAProxy
        self._push_haproxy_config_to_workload()

        self._restart_haproxy()

        self.unit.status = ActiveStatus()

    # =======================
    #  Helpers
    # =======================

    def _mysql_haproxy_pebble_layer(self) -> dict:
        """Define a pebble layer for HAProxy."""
        return Layer(
            {
                "summary": "mysql haproxy layer",
                "description": "pebble config layer for mysql haproxy",
                "services": {
                    self.service_name: {
                        "override": "replace",
                        "summary": "mysql haproxy",
                        "command": "haproxy -f /configs",
                        "startup": "enabled",
                    }
                },
            }
        )

    def _push_haproxy_config_to_workload(self) -> None:
        """Push HAProxy config file to the workload container."""
        container = self.unit.get_container(WORKLOAD_CONTAINER_NAME)

        logger.debug("Pushing new HAProxy config file to the workload container")

        container.push(
            HAPROXY_BACKEND_CONFIG_PATH,
            self._haproxy_backend_config(),
            permissions=0o600,
            user=HAPROXY_USERNAME,
            make_dirs=True,
        )

        logger.info("Pushed new HAProxy config file to the workload container")

    def _haproxy_backend_config(self) -> str:
        """Return a config for HAProxy backends."""
        mysql_host = self.model.config.get("mysql_host", "mysql")
        mysql_port = self.model.config.get("mysql_port", 3306)

        return f"""backend mysql-writers
    mode tcp
    option srvtcpka
    balance roundrobin
    option external-check
    external-check command /usr/local/bin/check_mysql.sh
    server mysql {mysql_host}:{mysql_port} check

backend mysql-readers
    mode tcp
    option srvtcpka
    balance roundrobin
    option external-check
    external-check command /usr/local/bin/check_mysql.sh
    server mysql {mysql_host}:{mysql_port} check
"""

    def _restart_haproxy(self) -> None:
        """Restart the HAProxy service in the workload container using pebble."""
        layer = self._mysql_haproxy_pebble_layer()

        container = self.unit.get_container(WORKLOAD_CONTAINER_NAME)

        try:
            plan = container.get_plan()

            if plan.services != layer.services:
                container.add_layer(self.service_name, layer, combine=True)

                if container.get_service(self.service_name).is_running():
                    container.stop(self.service_name)

                container.start(self.service_name)

            self.unit.status = ActiveStatus()
        except ConnectionError:
            logger.error(f"Could not restart {self.service_name}")


if __name__ == "__main__":
    main(MySQLHAProxyOperatorCharm)
