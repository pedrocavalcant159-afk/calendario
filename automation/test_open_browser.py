"""Test persistent Chrome with a disposable profile and local WhatsApp fixture.

Run: py -3.14 -m unittest discover -s automation -p test_open_browser.py
"""
import subprocess
import tempfile
import unittest
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import MagicMock, patch

from playwright.sync_api import sync_playwright
import automation as agent


class OpenBrowserTests(unittest.TestCase):
    def test_chrome_and_whatsapp_survive_two_separate_automation_cycles(self):
        real_popen = subprocess.Popen
        processes = []

        def launch_fixture(arguments, **kwargs):
            arguments = list(arguments)
            self.assertIn('--remote-debugging-address=127.0.0.1', arguments)
            # No real WhatsApp, user profile, or visible window in this test.
            arguments[-1] = 'about:blank'
            arguments.extend(['--headless=new', '--disable-background-networking'])
            process = real_popen(arguments, **kwargs)
            processes.append(process)
            return process

        with tempfile.TemporaryDirectory() as directory:
            runtime = Path(directory)
            browser = None
            with patch.object(agent, 'RUNTIME_DIR', runtime), \
                 patch.object(agent, 'PROFILE_DIR', runtime / 'profile'), \
                 patch.object(agent, 'BROWSER_HOST_PATH', runtime / 'browser-host.json'), \
                 patch.object(agent.subprocess, 'Popen', side_effect=launch_fixture):
                try:
                    with sync_playwright() as playwright:
                        first = agent.browser_context(playwright, {})
                        first.context.route('https://web.whatsapp.com/**', lambda route: route.fulfill(
                            body='<div id="pane-side">WhatsApp fixture</div>', content_type='text/html'))
                        whatsapp = agent.whatsapp_page_for_context(first)
                        whatsapp.goto('https://web.whatsapp.com/')
                        whatsapp.evaluate('window.fixtureLoaded = true')
                        self.assertTrue(agent.whatsapp_is_ready(whatsapp, timeout_ms=100))
                        self.assertTrue(whatsapp.evaluate('window.fixtureLoaded'))
                        agent.close_whatsapp_page(whatsapp)
                        self.assertFalse(whatsapp.is_closed())
                        first.close()
                        self.assertTrue(first.worker_page.is_closed())
                        self.assertFalse(whatsapp.is_closed())
                    # Closing the Playwright driver must not close external Chrome.
                    with sync_playwright() as playwright:
                        second = agent.browser_context(playwright, {})
                        browser = second.browser
                        whatsapp = agent.whatsapp_page_for_context(second)
                        self.assertTrue(whatsapp.evaluate('window.fixtureLoaded'))
                        self.assertEqual(len(processes), 1)
                        self.assertEqual(len([p for p in second.context.pages if p.url.startswith('https://web.whatsapp.com/')]), 1)
                        second.close()
                        self.assertFalse(whatsapp.is_closed())
                        browser.close()
                        browser = None
                finally:
                    for process in processes:
                        try:
                            process.wait(timeout=15)
                        except subprocess.TimeoutExpired:
                            process.terminate()
                            process.wait(timeout=5)

    def test_manual_queue_stops_after_transport_failure(self):
        commands = [{'id': 'first', 'type': 'assignment_notice'}, {'id': 'second', 'type': 'assignment_notice'}]
        with patch.object(agent, 'load_pending_manual_commands', return_value=commands), \
             patch.object(agent, 'claim_cluster_leadership', return_value={'isLeader': True}), \
             patch.object(agent, 'claim_manual_command', return_value=True), \
             patch.object(agent, 'send_assignment_notice', side_effect=agent.WhatsAppDeliveryError('No confirmation')) as send, \
             patch.object(agent, 'finish_manual_command') as finish, \
             patch.object(agent, 'log'):
            result = agent.process_pending_manual_commands(None, {}, {})
        self.assertEqual(result['failed'], 1)
        self.assertEqual(send.call_count, 1)
        self.assertEqual(finish.call_count, 1)
        self.assertEqual(finish.call_args.args[:3], (None, 'first', 'failed'))

    def test_reminder_batch_stops_without_reserving_remaining_recipients(self):
        batches = [
            {'responsible': name, 'group_name': name, 'message': name, 'marker': name,
             'delivery_keys': [name], 'event_count': 1}
            for name in ('first', 'second')
        ]
        context = MagicMock()
        context.pages = [MagicMock()]
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(agent, 'RUNTIME_DIR', Path(directory)), \
             patch.object(agent, 'load_config', return_value={}), \
             patch.object(agent, 'load_json', return_value={}), \
             patch.object(agent, 'automation_lock', return_value=nullcontext()), \
             patch.object(agent, 'sync_playwright'), \
             patch.object(agent, 'browser_context', return_value=context), \
             patch.object(agent, 'read_calendar', return_value={}), \
             patch.object(agent, 'claim_cluster_leadership', return_value={'isLeader': True}), \
             patch.object(agent, 'sync_pending_reminder_responses', return_value={}), \
             patch.object(agent, 'firestore_link_factory'), \
             patch.object(agent, 'build_reminder_batches', return_value=(batches, [], 'batch')), \
             patch.object(agent, 'reserve_reminder_batch', return_value='2026-09-17T09:05:00-03:00') as reserve, \
             patch.object(agent, 'save_json'), \
             patch.object(agent, 'update_cluster_state') as update, \
             patch.object(agent, 'whatsapp_page_for_context'), \
             patch.object(agent, 'send_whatsapp', side_effect=agent.WhatsAppDeliveryError('No confirmation')) as send, \
             patch.object(agent, 'log'):
            with self.assertRaisesRegex(agent.AutomationError, 'falharam'):
                agent.run_reminders()
        self.assertEqual(send.call_count, 1)
        self.assertEqual(reserve.call_count, 1)
        self.assertFalse(any('lastReminderCheckDate' in call.args[1] for call in update.call_args_list))


if __name__ == '__main__':
    unittest.main()
