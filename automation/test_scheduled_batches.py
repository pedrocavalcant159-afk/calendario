"""Regression tests for the twice-daily reminder and assignment cycles."""
import unittest
import tempfile
from contextlib import nullcontext
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import automation as agent


class ScheduledBatchTests(unittest.TestCase):
    def setUp(self):
        self.payload = {
            "team": {
                "members": [{
                    "id": "member-1",
                    "name": "Ana",
                    "active": True,
                    "whatsappGroup": "Demandas Ana",
                }]
            },
            "companies": [{
                "id": "company-1",
                "name": "Cliente",
                "events": [
                    {
                        "id": "overdue",
                        "year": 2026,
                        "month": 8,
                        "day": 20,
                        "text": "Post atrasado",
                        "status": "producao",
                        "responsibleId": "member-1",
                    },
                    {
                        "id": "today",
                        "year": 2026,
                        "month": 8,
                        "day": 22,
                        "text": "Post de hoje",
                        "status": "criacao",
                        "responsibleId": "member-1",
                    },
                    {
                        "id": "future",
                        "year": 2026,
                        "month": 8,
                        "day": 23,
                        "text": "Post futuro",
                        "status": "criacao",
                        "responsibleId": "member-1",
                    },
                ],
            }],
        }

    def test_latest_slots_follow_the_four_requested_times(self):
        reference = datetime(2026, 9, 22, 16, 30, tzinfo=timezone.utc)
        self.assertEqual(
            agent.latest_due_slot({}, "reminder_times", ("09:00", "17:00"), reference),
            "2026-09-22|09:00",
        )
        self.assertEqual(
            agent.latest_due_slot({}, "assignment_notice_times", ("12:00", "17:00"), reference),
            "2026-09-22|12:00",
        )

    def test_reminders_include_only_overdue_and_today_in_each_cycle(self):
        morning, _, _ = agent.build_reminder_batches(
            self.payload,
            {},
            reference=date(2026, 9, 22),
            cycle_slot="2026-09-22|09:00",
            update_url_factory=lambda _company, event: f"https://example.test/{event}",
        )
        afternoon, _, _ = agent.build_reminder_batches(
            self.payload,
            {},
            reference=date(2026, 9, 22),
            cycle_slot="2026-09-22|17:00",
            update_url_factory=lambda _company, event: f"https://example.test/{event}",
        )
        self.assertEqual(morning[0]["event_count"], 2)
        self.assertNotIn("Post futuro", morning[0]["message"])
        self.assertIn("Bom dia", morning[0]["message"])
        self.assertIn("Boa tarde", afternoon[0]["message"])
        self.assertNotEqual(morning[0]["delivery_keys"], afternoon[0]["delivery_keys"])

    def test_scheduled_assignment_is_not_processed_as_an_immediate_command(self):
        commands = [
            {"id": "scheduled", "type": "assignment_notice", "deliveryMode": "scheduled"},
            {"id": "legacy", "type": "assignment_notice"},
            {"id": "manual", "type": "assignment_notice", "deliveryMode": "immediate"},
        ]
        with patch.object(agent, "load_pending_manual_commands", return_value=commands), \
             patch.object(agent, "claim_cluster_leadership", return_value={"isLeader": True}), \
             patch.object(agent, "claim_manual_command", return_value=True), \
             patch.object(agent, "send_assignment_notice", return_value={"sent": True}) as send, \
             patch.object(agent, "finish_manual_command"), \
             patch.object(agent, "log"):
            result = agent.process_pending_manual_commands(None, {}, {})
        self.assertEqual(result["completed"], 1)
        self.assertEqual(send.call_args.args[2]["id"], "manual")

    def test_assignment_created_after_missed_noon_slot_waits_for_five_pm(self):
        before_noon = {
            "createdAt": "2026-09-22T11:59:59",
            "deliveryMode": "scheduled",
        }
        after_noon = {
            "createdAt": "2026-09-22T12:00:01",
            "deliveryMode": "scheduled",
        }
        self.assertTrue(agent.assignment_command_is_due(before_noon, "2026-09-22|12:00"))
        self.assertFalse(agent.assignment_command_is_due(after_noon, "2026-09-22|12:00"))
        self.assertTrue(agent.assignment_command_is_due(after_noon, "2026-09-22|17:00"))

    def test_legacy_assignment_without_delivery_mode_defaults_to_scheduled(self):
        self.payload["companies"][0]["events"] = self.payload["companies"][0]["events"][:1]
        command = {
            "id": "legacy",
            "type": "assignment_notice",
            "companyId": "company-1",
            "eventId": "overdue",
            "createdAt": "2026-09-22T11:00:00",
        }
        page = MagicMock()
        context = MagicMock()
        context.pages = [page]
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(agent, "RUNTIME_DIR", Path(directory)), \
             patch.object(agent, "load_config", return_value={}), \
             patch.object(agent, "automation_lock", return_value=nullcontext()), \
             patch.object(agent, "sync_playwright"), \
             patch.object(agent, "browser_context", return_value=context), \
             patch.object(agent, "read_calendar", return_value=self.payload), \
             patch.object(agent, "claim_cluster_leadership", return_value={"isLeader": True}), \
             patch.object(agent, "load_pending_manual_commands", return_value=[command]), \
             patch.object(agent, "claim_manual_command", return_value=True), \
             patch.object(agent, "finish_manual_command"), \
             patch.object(agent, "whatsapp_page_for_context"), \
             patch.object(agent, "send_whatsapp") as send, \
             patch.object(agent, "update_cluster_state"), \
             patch.object(agent, "log"):
            result = agent.run_assignment_notices("2026-09-22|12:00")
        self.assertTrue(result["sent"])
        send.assert_called_once()

    def test_assignment_cycle_combines_two_demands_in_one_message(self):
        self.payload["companies"][0]["events"] = self.payload["companies"][0]["events"][:2]
        commands = [
            {
                "id": event["id"],
                "type": "assignment_notice",
                "deliveryMode": "scheduled",
                "companyId": "company-1",
                "eventId": event["id"],
                "createdAt": f"2026-09-22T10:0{index}:00+00:00",
            }
            for index, event in enumerate(self.payload["companies"][0]["events"])
        ]
        page = MagicMock()
        context = MagicMock()
        context.pages = [page]
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(agent, "RUNTIME_DIR", Path(directory)), \
             patch.object(agent, "load_config", return_value={}), \
             patch.object(agent, "automation_lock", return_value=nullcontext()), \
             patch.object(agent, "sync_playwright"), \
             patch.object(agent, "browser_context", return_value=context), \
             patch.object(agent, "read_calendar", return_value=self.payload), \
             patch.object(agent, "claim_cluster_leadership", return_value={"isLeader": True}), \
             patch.object(agent, "load_pending_manual_commands", return_value=commands), \
             patch.object(agent, "claim_manual_command", return_value=True), \
             patch.object(agent, "finish_manual_command") as finish, \
             patch.object(agent, "whatsapp_page_for_context"), \
             patch.object(agent, "send_whatsapp") as send, \
             patch.object(agent, "update_cluster_state") as update, \
             patch.object(agent, "log"):
            result = agent.run_assignment_notices("2026-09-22|12:00")
        self.assertTrue(result["sent"])
        self.assertEqual(result["events"], 2)
        self.assertEqual(send.call_count, 1)
        self.assertIn("Post atrasado", send.call_args.args[2])
        self.assertIn("Post de hoje", send.call_args.args[2])
        self.assertEqual(finish.call_count, 2)
        self.assertEqual(update.call_args.args[1]["lastAssignmentNoticeSlot"], "2026-09-22|12:00")


if __name__ == "__main__":
    unittest.main()
