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
    def test_open_whatsapp_brings_window_forward_without_reading_calendar_or_sending(self):
        context = MagicMock()
        page = MagicMock()
        page.url = 'https://web.whatsapp.com/'
        with patch.object(agent, 'load_config', return_value={'keep_whatsapp_open': False}), \
             patch.object(agent, 'save_json'), \
             patch.object(agent, 'automation_lock', return_value=nullcontext()), \
             patch.object(agent, 'sync_playwright'), \
             patch.object(agent, 'browser_context', return_value=context) as connect, \
             patch.object(agent, 'whatsapp_page_for_context', return_value=page), \
             patch.object(agent, 'read_calendar') as calendar, \
             patch.object(agent, 'send_whatsapp') as send:
            result = agent.open_whatsapp_window()
        self.assertTrue(result['opened'])
        self.assertTrue(connect.call_args.args[1]['keep_whatsapp_open'])
        self.assertTrue(connect.call_args.kwargs['show_browser'])
        page.bring_to_front.assert_called_once()
        context.close.assert_called_once()
        calendar.assert_not_called()
        send.assert_not_called()

    def test_background_mode_keeps_whatsapp_loaded_without_showing_the_window(self):
        context = MagicMock()
        page = MagicMock()
        with patch.object(agent, 'load_config', return_value={'keep_whatsapp_open': True}), \
             patch.object(agent, 'load_json', return_value={}), \
             patch.object(agent, 'save_json'), \
             patch.object(agent, 'automation_lock', return_value=nullcontext()), \
             patch.object(agent, 'sync_playwright'), \
             patch.object(agent, 'browser_context', return_value=context) as connect, \
             patch.object(agent, 'whatsapp_page_for_context', return_value=page), \
             patch.object(agent, 'whatsapp_is_ready', return_value=True) as ready:
            result = agent.keep_whatsapp_in_background()
        self.assertTrue(result['running'])
        self.assertTrue(result['background'])
        self.assertNotIn('show_browser', connect.call_args.kwargs)
        ready.assert_called_once_with(page, timeout_ms=90_000)
        page.bring_to_front.assert_not_called()
        context.close.assert_called_once()

    def test_existing_headless_automation_chrome_is_reused_during_normal_cycles(self):
        playwright = MagicMock()
        browser = MagicMock()
        playwright.chromium.connect_over_cdp.return_value = browser
        host = {'profile': str(agent.PROFILE_DIR.resolve()), 'port': 9222, 'pid': 321, 'headless': True}
        with patch.object(agent, 'load_json', return_value=host), \
             patch.object(agent, 'save_json'), \
             patch.object(agent, 'chrome_pid_from_cdp', return_value=0), \
             patch.object(agent, 'chrome_pid_for_debug_port', return_value=654), \
             patch.object(agent, 'set_chrome_window_visibility') as visibility:
            result = agent.attach_open_chrome(playwright)
        self.assertIs(result, browser)
        visibility.assert_not_called()

    def test_existing_automation_chrome_falls_back_to_stored_pid(self):
        playwright = MagicMock()
        browser = MagicMock()
        playwright.chromium.connect_over_cdp.return_value = browser
        host = {'profile': str(agent.PROFILE_DIR.resolve()), 'port': 9222, 'pid': 321, 'headless': True}
        with patch.object(agent, 'load_json', return_value=host), \
             patch.object(agent, 'save_json'), \
             patch.object(agent, 'chrome_pid_from_cdp', return_value=0), \
             patch.object(agent, 'chrome_pid_for_debug_port', return_value=0), \
             patch.object(agent, 'set_chrome_window_visibility') as visibility:
            result = agent.attach_open_chrome(playwright)
        self.assertIs(result, browser)
        visibility.assert_not_called()

    def test_existing_automation_chrome_prefers_live_cdp_pid(self):
        playwright = MagicMock()
        browser = MagicMock()
        playwright.chromium.connect_over_cdp.return_value = browser
        host = {'profile': str(agent.PROFILE_DIR.resolve()), 'port': 9222, 'pid': 321, 'headless': True}
        with patch.object(agent, 'load_json', return_value=host), \
             patch.object(agent, 'save_json'), \
             patch.object(agent, 'chrome_pid_from_cdp', return_value=987), \
             patch.object(agent, 'chrome_pid_for_debug_port') as netstat_pid, \
             patch.object(agent, 'set_chrome_window_visibility') as visibility:
            result = agent.attach_open_chrome(playwright)
        self.assertIs(result, browser)
        visibility.assert_not_called()
        netstat_pid.assert_not_called()

    def test_background_mode_restarts_legacy_headed_chrome_as_headless(self):
        playwright = MagicMock()
        headed_browser = MagicMock()
        headless_browser = MagicMock()
        playwright.chromium.connect_over_cdp.side_effect = [headed_browser, headless_browser]
        host = {'profile': str(agent.PROFILE_DIR.resolve()), 'port': 9222, 'pid': 321}
        launched_process = MagicMock()
        launched_process.pid = 456
        with patch.object(agent, 'load_json', return_value=host), \
             patch.object(agent, 'save_json'), \
             patch.object(agent, 'chrome_pid_from_cdp', return_value=0), \
             patch.object(agent, 'chrome_pid_for_debug_port', return_value=0), \
             patch.object(agent.socket, 'create_connection', side_effect=OSError), \
             patch.object(agent.subprocess, 'Popen', return_value=launched_process) as launch:
            result = agent.attach_open_chrome(playwright)
        self.assertIs(result, headless_browser)
        headed_browser.close.assert_called_once()
        self.assertIn('--headless=new', launch.call_args.args[0])

    def test_cdp_minimizes_chrome_without_depending_on_windows_pid(self):
        browser = MagicMock()
        context = MagicMock()
        page = MagicMock()
        session = MagicMock()
        browser.contexts = [context]
        context.pages = [page]
        context.new_cdp_session.return_value = session
        session.send.side_effect = [
            {'windowId': 42, 'bounds': {'windowState': 'normal'}},
            {},
        ]
        self.assertTrue(agent.set_chrome_cdp_window_visibility(browser, False))
        session.send.assert_any_call(
            'Browser.setWindowBounds',
            {'windowId': 42, 'bounds': {'windowState': 'minimized'}},
        )
        session.detach.assert_called_once()

    @unittest.skipUnless(agent.os.name == 'nt', 'Windows process flags')
    def test_chrome_launch_retries_without_breakaway_when_windows_denies_it(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = Path(directory)
            playwright = MagicMock()
            with patch.object(agent, 'RUNTIME_DIR', runtime), \
                 patch.object(agent, 'PROFILE_DIR', runtime / 'profile'), \
                 patch.object(agent, 'BROWSER_HOST_PATH', runtime / 'host.json'), \
                 patch.object(agent, 'chrome_pid_from_cdp', return_value=0), \
                 patch.object(agent, 'chrome_pid_for_debug_port', return_value=0), \
                 patch.object(agent.subprocess, 'Popen', side_effect=[PermissionError('Job restriction'), MagicMock()]) as launch:
                agent.attach_open_chrome(playwright)
            self.assertEqual(launch.call_count, 2)
            self.assertIn('--headless=new', launch.call_args_list[0].args[0])
            self.assertTrue(launch.call_args_list[0].kwargs['creationflags'] & subprocess.CREATE_BREAKAWAY_FROM_JOB)
            self.assertFalse(launch.call_args_list[1].kwargs['creationflags'] & subprocess.CREATE_BREAKAWAY_FROM_JOB)

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
                 patch.object(agent, 'chrome_pid_from_cdp', return_value=0), \
                 patch.object(agent, 'chrome_pid_for_debug_port', return_value=0), \
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
