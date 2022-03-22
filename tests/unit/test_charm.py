# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.
#
# Learn more about testing at: https://juju.is/docs/sdk/testing

import unittest
from unittest.mock import patch

from ops.model import ActiveStatus, WaitingStatus
from ops.testing import Harness

from charm import MySQLHAProxyOperatorCharm


class TestCharm(unittest.TestCase):
    def setUp(self):
        self.haproxy_container = "mysql-haproxy"

        self.harness = Harness(MySQLHAProxyOperatorCharm)
        self.addCleanup(self.harness.cleanup)
        self.harness.begin()

    def test_mysql_haproxy_pebble_ready(self):
        initial_plan = self.harness.get_container_pebble_plan(self.haproxy_container)
        self.assertEqual(initial_plan.to_yaml().strip(), "{}")

        expected_plan = {
            "services": {
                "mysql-haproxy": {
                    "override": "replace",
                    "summary": "mysql haproxy",
                    "command": "haproxy -f /configs",
                    "startup": "enabled",
                }
            }
        }

        container = self.harness.model.unit.get_container(self.haproxy_container)
        self.harness.charm.on.mysql_haproxy_pebble_ready.emit(container)

        updated_plan = self.harness.get_container_pebble_plan(self.haproxy_container).to_dict()
        self.assertEqual(expected_plan, updated_plan)

        service = self.harness.model.unit.get_container(self.haproxy_container).get_service(
            "mysql-haproxy"
        )
        self.assertTrue(service.is_running())
        self.assertEqual(
            self.harness.model.unit.status,
            ActiveStatus("HAProxy started in the workload container"),
        )

    @patch("ops.model.Container.can_connect", return_value=False)
    @patch("ops.charm.ConfigChangedEvent.defer")
    def test_config_changed_container_cannot_connect(self, can_connect, defer):
        self.harness.update_config({"mysql_port": 3307})
        self.assertEqual(
            self.harness.model.unit.status,
            WaitingStatus(f"Waiting for {self.haproxy_container} container to start"),
        )
        defer.assert_called()

    @patch("charm.MySQLHAProxyOperatorCharm._push_haproxy_config_to_workload")
    @patch("charm.MySQLHAProxyOperatorCharm._restart_haproxy")
    def test_config_changed(self, _push_haproxy_config_to_workload, _restart_haproxy):
        self.harness.update_config({"mysql_port": 3307})

        self.assertEqual(self.harness.model.unit.status, ActiveStatus())
