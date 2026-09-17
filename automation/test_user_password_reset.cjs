// Run with: node --test automation/test_user_password_reset.cjs
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const html = fs.readFileSync(path.join(__dirname, '../index.html'), 'utf8');
const start = html.indexOf('const handleResetUserPassword =');
const end = html.indexOf('const handleRemoveRole =', start);
assert.ok(start >= 0 && end > start);

function harness(overrides = {}) {
    const sent = [];
    const state = {};
    const context = {
        user: { email: 'master@example.com' }, rolesReady: true, userRole: 'master',
        MEU_EMAIL_MASTER: 'owner@example.com',
        globalRoles: { 'other@example.com': 'master', 'client@example.com': 'cliente' },
        passwordResetPending: { current: false },
        setResettingUserEmail: email => { state.pending = email; },
        setUserPasswordFeedback: feedback => { state.feedback = feedback; },
        auth: { sendPasswordResetEmail: async email => { sent.push(email); } },
        ...overrides
    };
    const reset = vm.runInNewContext(`(function() { ${html.slice(start, end)} return handleResetUserPassword; })()`, context);
    return { reset, sent, state, context };
}

test('masters can request resets for another master, the original master and a client', async () => {
    const h = harness();
    await h.reset(' OTHER@example.com ');
    await h.reset('owner@example.com');
    await h.reset('client@example.com');
    assert.deepEqual(h.sent, ['other@example.com', 'owner@example.com', 'client@example.com']);
    assert.equal(h.state.feedback.type, 'success');
    assert.equal(h.state.pending, '');
});

test('signed-out users, admins, clients and unverified roles cannot trigger the panel action', async () => {
    for (const overrides of [{ user: null }, { userRole: 'admin' }, { userRole: 'cliente' }, { rolesReady: false }]) {
        const h = harness(overrides);
        await h.reset('other@example.com');
        assert.equal(h.sent.length, 0);
    }
});

test('unknown targets cannot trigger the panel action', async () => {
    const h = harness();
    await h.reset('unknown@example.com');
    await h.reset('');
    assert.equal(h.sent.length, 0);
});

test('concurrent clicks send a single request and release the pending state', async () => {
    let finish;
    let count = 0;
    const h = harness({ auth: { sendPasswordResetEmail: () => { count++; return new Promise(resolve => { finish = resolve; }); } } });
    const first = h.reset('other@example.com');
    await h.reset('client@example.com');
    assert.equal(count, 1);
    assert.equal(h.state.pending, 'other@example.com');
    finish();
    await first;
    assert.equal(h.context.passwordResetPending.current, false);
    assert.equal(h.state.pending, '');
});

test('failed requests show an error and permit retry', async () => {
    for (const code of ['auth/too-many-requests', 'auth/network-request-failed', 'auth/user-not-found']) {
        const h = harness({ auth: { sendPasswordResetEmail: async () => { throw { code }; } } });
        await h.reset('other@example.com');
        assert.equal(h.state.feedback.type, 'error');
        assert.equal(h.context.passwordResetPending.current, false);
        assert.equal(h.state.pending, '');
        h.context.auth.sendPasswordResetEmail = async email => { h.sent.push(email); };
        await h.reset('other@example.com');
        assert.equal(h.state.feedback.type, 'success');
    }
});
