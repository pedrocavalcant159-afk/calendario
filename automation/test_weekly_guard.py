"""Regression tests for a weekly report whose delivery was ambiguous."""
import json
import tempfile
import unittest
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import MagicMock, patch
import automation as agent


class WeeklyGuardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.patches = [patch.object(agent, 'WEEKLY_GUARD_PATH', self.root / 'weekly.json'),
                        patch.object(agent, 'WHATSAPP_STATUS_PATH', self.root / 'delivery.json'),
                        patch.object(agent, 'machine_identity', return_value={'id': 'pc-one'})]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    def test_reserved_report_is_not_reserved_again_after_restart(self):
        page = MagicMock()
        page.evaluate.return_value = True
        self.assertTrue(agent.reserve_weekly_report(page, '[UPLI-2026-S38]', 'Team'))
        self.assertFalse(agent.reserve_weekly_report(page, '[UPLI-2026-S38]', 'Team'))
        self.assertEqual(page.evaluate.call_count, 1)
        self.assertTrue(agent.reserve_weekly_report(page, '[UPLI-2026-S39]', 'Team'))

    def test_cloud_rejection_never_records_a_new_local_reservation(self):
        page = MagicMock()
        page.evaluate.return_value = False
        self.assertFalse(agent.reserve_weekly_report(page, '[UPLI-2026-S38]', 'Team'))
        self.assertFalse(agent.WEEKLY_GUARD_PATH.exists())

    def test_previous_version_failure_is_preserved_without_resending(self):
        agent.WHATSAPP_STATUS_PATH.write_text(json.dumps({'marker': '[UPLI-2026-S38]', 'status': 'failed'}))
        page = MagicMock()
        self.assertFalse(agent.reserve_weekly_report(page, '[UPLI-2026-S38]', 'Team'))
        page.evaluate.assert_not_called()
        self.assertEqual(json.loads(agent.WEEKLY_GUARD_PATH.read_text())['[UPLI-2026-S38]']['status'], 'legacy-attempt')

    def test_weekly_supervisor_respects_local_and_shared_reservations(self):
        marker = agent.week_context()[2]
        self.assertFalse(agent.weekly_supervisor_due({}, {'weeklyDeliveries': {marker: {}}}))
        agent.WEEKLY_GUARD_PATH.write_text(json.dumps({marker: {}}))
        self.assertFalse(agent.weekly_supervisor_due({}, {}))

    def test_timeout_after_submission_does_not_send_on_the_next_minute(self):
        context = MagicMock()
        page = MagicMock()
        page.evaluate.return_value = True
        context.pages = [page]
        marker = '[UPLI-2026-S38]'
        with patch.object(agent, 'RUNTIME_DIR', self.root), \
             patch.object(agent, 'load_config', return_value={'group_name': 'Team'}), \
             patch.object(agent, 'STATE_PATH', self.root / 'state.json'), \
             patch.object(agent, 'automation_lock', side_effect=lambda: nullcontext()), \
             patch.object(agent, 'sync_playwright'), \
             patch.object(agent, 'browser_context', return_value=context), \
             patch.object(agent, 'read_calendar', return_value={}), \
             patch.object(agent, 'claim_cluster_leadership', return_value={'isLeader': True}), \
             patch.object(agent, 'sync_pending_reminder_responses', return_value={}), \
             patch.object(agent, 'build_report', return_value=('Long report', 10, marker, 'fingerprint')), \
             patch.object(agent, 'send_whatsapp', side_effect=agent.WhatsAppDeliveryError('No confirmation')) as send, \
             patch.object(agent, 'log'):
            with self.assertRaises(agent.WhatsAppDeliveryError):
                agent.run_send()
            second = agent.run_send()
        self.assertTrue(second['duplicate'])
        self.assertEqual(send.call_count, 1)


if __name__ == '__main__':
    unittest.main()
