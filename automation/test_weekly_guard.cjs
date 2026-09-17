const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const python = fs.readFileSync(path.join(__dirname, 'automation.py'), 'utf8');
const body = python.slice(python.indexOf('def reserve_weekly_report('));
const js = body.match(/"""(async input => \{[\s\S]*?)"""/)[1];
const marker = '[UPLI-2026-S38]';
function harness(initial = {}) {
    let data = { leaderMachineId: 'leader', ...initial };
    let tail = Promise.resolve();
    const context = {
        firebase: { firestore: { FieldValue: { serverTimestamp: () => 'now' } } },
        db: {
            collection: () => ({ doc: () => 'cluster' }),
            runTransaction(callback) {
                const result = tail.then(() => callback({
                    get: async () => ({ exists: true, data: () => structuredClone(data) }),
                    set: (_, updates) => { data = { ...data, ...updates }; }
                }));
                tail = result.then(() => {});
                return result;
            }
        }
    };
    const reserve = vm.runInNewContext('(' + js + ')', context);
    const input = { marker, machineId: 'leader', groupName: 'Team', attemptedAt: 'now', force: false };
    return { reserve: overrides => reserve({ ...input, ...overrides }), data: () => data };
}
test('concurrent weekly attempts share one reservation', async () => {
    const h = harness();
    const results = await Promise.all([h.reserve(), h.reserve()]);
    assert.deepEqual(results, [true, false]);
    assert.equal(h.data().weeklyDeliveries[marker].status, 'reserved');
});
test('pause, another leader, completed or already reserved weeks cannot be submitted', async () => {
    for (const initial of [{ paused: true }, { leaderMachineId: 'other' },
        { lastWeeklyMarker: marker }, { weeklyDeliveries: { [marker]: { status: 'reserved' } } }]) {
        assert.equal(await harness(initial).reserve(), false);
    }
});
