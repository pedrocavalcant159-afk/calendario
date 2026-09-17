"""Local browser fixtures only; never opens WhatsApp or sends real messages.

Run: py -3.14 -m unittest discover -s automation -p test_whatsapp_delivery.py
"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from playwright.sync_api import sync_playwright

import automation as agent
import verify


class WhatsAppDeliveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(executable_path=str(agent.chrome_path()), headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.runtime = Path(self.temp.name)
        self.status_path = self.runtime / 'last-whatsapp-delivery.json'
        self.patches = [
            patch.object(agent, 'WHATSAPP_STATUS_PATH', self.status_path),
            patch.object(agent, 'RUNTIME_DIR', self.runtime),
            patch.object(agent, 'log'),
        ]
        for item in self.patches:
            item.start()
        self.page = self.browser.new_page()
        self.page.set_content('''
            <div id="main"><div id="messages"></div>
            <footer><div contenteditable="true" role="textbox"></div>
            <button aria-label="Enviar"><span data-icon="send"></span></button></footer></div>
            <script>
                window.clicks = 0;
                const editor = document.querySelector('[contenteditable]');
                function send() {
                    window.clicks++;
                    const bubble = document.createElement('div');
                    bubble.dataset.id = 'true_message';
                    const body = document.createElement('div');
                    body.dataset.testid = 'msg-container';
                    body.textContent = editor.textContent;
                    const check = document.createElement('span');
                    check.dataset.testid = 'msg-check';
                    bubble.append(body, check);
                    document.querySelector('#messages').append(bubble);
                    editor.textContent = '';
                }
                document.querySelector('button').onclick = send;
                // Enter deliberately does not send in this fixture.
                editor.onkeydown = event => { if (event.key === 'Enter') event.preventDefault(); };
            </script>
        ''')
        self.editor = self.page.locator('[contenteditable]')

    def tearDown(self):
        self.page.close()
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    def test_send_button_submits_multiline_message_when_enter_does_not_send(self):
        agent.submit_whatsapp_message(self.page, self.editor, 'Olá!\nDemanda\n[UPLI-TEST]', '[UPLI-TEST]')
        self.assertEqual(self.page.evaluate('window.clicks'), 1)
        self.assertEqual(agent.outgoing_marker_state(self.page, '[UPLI-TEST]'), 'confirmed')
        self.assertEqual(json.loads(self.status_path.read_text())['status'], 'confirmed')

    def test_incoming_message_and_composer_do_not_count_as_delivery(self):
        self.page.locator('#messages').evaluate('''node => {
            node.innerHTML = '<div class="message-in" data-id="false_message">[UPLI-TEST]<span data-icon="msg-check"></span></div>';
        }''')
        self.editor.fill('[UPLI-TEST]')
        self.assertEqual(agent.outgoing_marker_state(self.page, '[UPLI-TEST]'), 'missing')
        agent.submit_whatsapp_message(self.page, self.editor, '[UPLI-TEST]', '[UPLI-TEST]')
        self.assertEqual(self.page.evaluate('window.clicks'), 1)

    def test_confirmed_existing_message_is_not_sent_again(self):
        agent.submit_whatsapp_message(self.page, self.editor, '[UPLI-TEST]', '[UPLI-TEST]')
        agent.submit_whatsapp_message(self.page, self.editor, '[UPLI-TEST]', '[UPLI-TEST]')
        self.assertEqual(self.page.evaluate('window.clicks'), 1)

    def test_long_collapsed_report_keeps_marker_visible_and_does_not_send_twice(self):
        self.page.evaluate('''() => {
            document.querySelector('button').onclick = () => {
                window.clicks++;
                const bubble = document.createElement('div');
                bubble.dataset.id = 'true_long';
                // Simulate WhatsApp omitting the tail behind Read more.
                bubble.textContent = document.querySelector('[contenteditable]').textContent.slice(0, 100);
                const check = document.createElement('span');
                check.dataset.icon = 'msg-check';
                bubble.append(check);
                document.querySelector('#messages').append(bubble);
            };
        }''')
        message = 'Weekly report\n' + ('Demand details\n' * 100) + '[UPLI-TEST]'
        agent.submit_whatsapp_message(self.page, self.editor, message, '[UPLI-TEST]')
        agent.submit_whatsapp_message(self.page, self.editor, message, '[UPLI-TEST]')
        self.assertEqual(self.page.evaluate('window.clicks'), 1)

    def test_unconfirmed_existing_message_fails_without_resending_and_saves_evidence(self):
        self.page.locator('#messages').evaluate('''node => {
            node.innerHTML = '<div data-id="true_pending">[UPLI-TEST]<span data-icon="msg-time"></span></div>';
        }''')
        original_wait = agent.wait_for_outgoing_confirmation
        with patch.object(agent, 'wait_for_outgoing_confirmation', side_effect=lambda page, marker: original_wait(page, marker, timeout_ms=10)):
            with self.assertRaisesRegex(agent.AutomationError, 'Confira o grupo'):
                agent.submit_whatsapp_message(self.page, self.editor, '[UPLI-TEST]', '[UPLI-TEST]')
        self.assertEqual(self.page.evaluate('window.clicks'), 0)
        self.assertEqual(json.loads(self.status_path.read_text())['status'], 'failed')
        self.assertTrue((self.runtime / 'last-error.png').exists())

    def test_whatsapp_error_icon_never_counts_as_success(self):
        self.page.locator('#messages').evaluate('''node => {
            node.innerHTML = '<div data-id="true_failed">[UPLI-TEST]<span data-icon="msg-error"></span></div>';
        }''')
        self.assertEqual(agent.outgoing_marker_state(self.page, '[UPLI-TEST]'), 'error')
        with self.assertRaisesRegex(agent.AutomationError, 'marcou o envio com erro'):
            agent.wait_for_outgoing_confirmation(self.page, '[UPLI-TEST]', timeout_ms=10)

    def test_read_more_label_does_not_count_as_read_receipt(self):
        self.page.locator('#messages').evaluate('''node => {
            node.innerHTML = '<div data-id="true_pending">[UPLI-TEST]<button aria-label="Read more">Read more</button></div>';
        }''')
        self.assertEqual(agent.outgoing_marker_state(self.page, '[UPLI-TEST]'), 'submitted')

    def test_missing_message_fails_without_clicking_send_twice(self):
        self.page.evaluate('() => { document.querySelector("button").onclick = () => { window.clicks++; }; }')
        original_wait = agent.wait_for_outgoing_confirmation
        with patch.object(agent, 'wait_for_outgoing_confirmation', side_effect=lambda page, marker: original_wait(page, marker, timeout_ms=10)):
            with self.assertRaisesRegex(agent.AutomationError, 'dentro do tempo esperado'):
                agent.submit_whatsapp_message(self.page, self.editor, '[UPLI-TEST]', '[UPLI-TEST]')
        self.assertEqual(self.page.evaluate('window.clicks'), 1)
        self.assertEqual(json.loads(self.status_path.read_text())['status'], 'failed')

    def test_diagnostic_reports_delivery_failure_even_when_sessions_are_connected(self):
        agent.record_whatsapp_delivery('failed', '[UPLI-TEST]', 'Envio sem confirmação')
        with patch.multiple(verify, RUNTIME_DIR=self.runtime, WHATSAPP_STATUS_PATH=self.status_path,
                            STATUS_PATH=self.runtime / 'status.json', STATUS_HTML_PATH=self.runtime / 'status.html'), \
             patch.object(verify, 'load_config', return_value={'group_name': 'Equipe'}), \
             patch.object(verify, 'chrome_path'), \
             patch.object(verify, 'internet_available', return_value=True), \
             patch.object(verify, 'task_exists', return_value=True), \
             patch.object(verify, 'test_shortcut_exists', return_value=True), \
             patch.object(verify, 'temporary_forms_available', return_value=True), \
             patch.object(verify, 'verify_sessions', return_value={'calendar': True, 'whatsapp': True, 'form_url': True, 'active_month': True}), \
             patch.object(verify, 'log'):
            result = verify.verify(allow_catchup=False)
        self.assertTrue(result['checks']['whatsapp'])
        self.assertFalse(result['ready'])
        self.assertTrue(any('Envio sem confirmação' in issue for issue in result['issues']))


if __name__ == '__main__':
    unittest.main()
