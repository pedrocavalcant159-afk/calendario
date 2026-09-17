// Run with: node --test automation/test_calendar_sync.cjs
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const html = fs.readFileSync(path.join(__dirname, '../index.html'), 'utf8');
function effectContaining(marker) {
    const markerIndex = html.indexOf(marker);
    const start = html.lastIndexOf('useEffect(() => {', markerIndex);
    const end = html.indexOf('\n          }, [', markerIndex);
    assert.ok(start >= 0 && end > start);
    return html.slice(start + 'useEffect(() => {'.length, end);
}
const companiesEffect = effectContaining('const source = userRole');
const authEffect = effectContaining('let unsubscribeRoles');

function harness(overrides = {}) {
    const state = { companies: [], events: [], selectedCompany: null };
    const listeners = [];
    const writes = [];
    const context = {
        user: { email: 'client@example.com' }, rolesReady: true, userRole: 'cliente',
        globalUserCompanies: { 'client@example.com': 'company-a' },
        MEU_EMAIL_MASTER: 'owner@example.com', UPLI_GERAL_ID: 'central',
        STANDARD_CATEGORIES: [{ id: 'post', label: 'Post' }], DEFAULT_STATUS_PIPELINE: {},
        stringToColor: () => '#123456', console: { error() {} },
        localStorage: { getItem: () => null },
        document: { documentElement: { classList: { add() {} } } },
        ...overrides
    };
    for (const key of ['Companies', 'Events', 'SelectedCompany', 'CalendarSync', 'StatusPipeline',
        'RolesReady', 'AccessError', 'GlobalRoles', 'GlobalUserCompanies', 'UserRole', 'LoadingAuth', 'User', 'CurrentUserName']) {
        const stateKey = key[0].toLowerCase() + key.slice(1);
        context['set' + key] = value => { state[stateKey] = typeof value === 'function' ? value(state[stateKey]) : value; };
    }
    function ref(refPath) {
        return {
            doc: id => ref(refPath + '/' + id),
            set: data => { writes.push({ path: refPath, data }); return Promise.resolve(); },
            onSnapshot(...args) {
                const next = args.find(arg => typeof arg === 'function');
                const error = args.filter(arg => typeof arg === 'function')[1];
                const listener = { path: refPath, next, error, stopped: false };
                listeners.push(listener);
                return () => { listener.stopped = true; };
            }
        };
    }
    context.db = { collection: name => ref(name) };
    context.auth = { onAuthStateChanged(callback) { context.login = callback; return () => {}; } };
    const run = code => vm.runInNewContext('(function() {' + code + '\n})()', context);
    return { state, context, listeners, writes, run };
}
function doc(id, data) { return { id, exists: true, data: () => data }; }
function documentSnapshot(data, metadata = {}) {
    return { ...doc('company-a', data), metadata: { fromCache: false, hasPendingWrites: false, ...metadata } };
}

test('a client reads only the assigned document and receives updates from another computer', () => {
    const h = harness();
    const cleanup = h.run(companiesEffect);
    assert.equal(h.listeners[0].path, 'companies/company-a');
    const event = { id: 'shared-event', day: 17, month: 8, year: 2026 };
    h.listeners[0].next(documentSnapshot({ name: 'Company A', events: [event] }));
    assert.equal(h.state.companies[0].events[0].id, 'shared-event');
    assert.equal(h.state.selectedCompany, 'company-a');
    h.listeners[0].next(documentSnapshot({ name: 'Company A', events: [{ ...event, text: 'Updated on another PC' }] }));
    assert.equal(h.state.companies[0].events[0].text, 'Updated on another PC');
    assert.equal(h.state.calendarSync.state, 'ready');
    cleanup();
    assert.equal(h.listeners[0].stopped, true);
});

test('an unassigned client gets an access message without querying companies', () => {
    const h = harness({ globalUserCompanies: {} });
    h.run(companiesEffect);
    assert.equal(h.listeners.length, 0);
    assert.match(h.state.calendarSync.message, /não está vinculada/);
});

test('company reads wait for account permissions', () => {
    const h = harness({ rolesReady: false });
    h.run(companiesEffect);
    assert.equal(h.listeners.length, 0);
});

test('private and missing company documents do not expose events or keep a stale selection', () => {
    const h = harness();
    h.run(companiesEffect);
    h.listeners[0].next(documentSnapshot({ isPrivate: true, events: [{ id: 'private' }] }));
    assert.equal(h.state.companies.length, 0);
    assert.equal(h.state.selectedCompany, null);
    assert.equal(h.state.calendarSync.state, 'empty');
    h.listeners[0].next({ exists: false, metadata: { fromCache: false, hasPendingWrites: false } });
    assert.equal(h.state.companies.length, 0);
});

test('pending and cached events are distinguished from confirmed shared events', () => {
    const h = harness();
    h.run(companiesEffect);
    const listener = h.listeners[0];
    listener.next(documentSnapshot({ events: [] }, { hasPendingWrites: true }));
    assert.equal(h.state.calendarSync.state, 'pending');
    listener.next(documentSnapshot({ events: [] }, { fromCache: true }));
    assert.equal(h.state.calendarSync.state, 'offline');
    listener.next(documentSnapshot({ events: [] }));
    assert.equal(h.state.calendarSync.state, 'ready');
});

test('a Firebase permission error is visible and clears previous events', () => {
    const h = harness();
    h.run(companiesEffect);
    h.listeners[0].next(documentSnapshot({ events: [{ id: 'old' }] }));
    h.listeners[0].error({ code: 'permission-denied' });
    assert.equal(h.state.companies.length, 0);
    assert.equal(h.state.selectedCompany, null);
    assert.equal(h.state.calendarSync.state, 'error');
    assert.match(h.state.calendarSync.message, /bloqueou a leitura/);
});

test('administrators still receive shared company calendars', () => {
    const h = harness({ userRole: 'admin' });
    h.run(companiesEffect);
    assert.equal(h.listeners[0].path, 'companies');
    h.listeners[0].next({ docs: [doc('central', { name: 'UPLI Geral' }), doc('company-a', { events: [{ id: 'shared' }] }), doc('secret', { isPrivate: true })], metadata: { fromCache: false, hasPendingWrites: false } });
    assert.deepEqual(Array.from(h.state.companies, company => company.id), ['central', 'company-a']);
});

test('switching accounts detaches old role listeners and clears the previous account data', () => {
    const h = harness();
    const cleanup = h.run(authEffect);
    h.context.login({ email: 'first@example.com' });
    h.listeners[0].next({ exists: true, data: () => ({ userRoles: { 'first@example.com': 'admin' } }) });
    assert.equal(h.state.userRole, 'admin');
    h.state.events = [{ id: 'old' }];
    h.context.login({ email: 'second@example.com' });
    assert.equal(h.listeners[0].stopped, true);
    assert.equal(h.state.userRole, 'cliente');
    assert.equal(h.state.events.length, 0);
    assert.equal(h.state.rolesReady, false);
    h.listeners[1].error({ code: 'permission-denied' });
    assert.equal(h.state.loadingAuth, false);
    assert.match(h.state.accessError, /permissão/);
    cleanup();
    assert.equal(h.listeners[1].stopped, true);
});
