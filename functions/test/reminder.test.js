"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const {
  eventIdMatches,
  expirationForEvent,
  sanitizePipeline,
  tokenDigest,
  updateEventRecord,
} = require("../lib/reminder");

test("matches source and cloned event ids", () => {
  assert.equal(eventIdMatches("post-1", "post-1"), true);
  assert.equal(eventIdMatches("post-1_clone", "post-1"), true);
  assert.equal(eventIdMatches("post-2", "post-1"), false);
});

test("creates a stable digest without storing the raw token", () => {
  const digest = tokenDigest("abcdefghijklmnopqrstuvwxyz_ABCDEFGHIJKLMNOPQRSTUVWXYZ-123456789");
  assert.match(digest, /^[a-f0-9]{64}$/);
  assert.notEqual(digest, "abcdefghijklmnopqrstuvwxyz_ABCDEFGHIJKLMNOPQRSTUVWXYZ-123456789");
});

test("expires three days after the end of the due date", () => {
  const expiresAt = expirationForEvent({year: 2026, month: 8, day: 6});
  assert.equal(expiresAt.toISOString(), "2026-09-10T02:59:59.000Z");
});

test("sanitizes pipeline values", () => {
  const pipeline = sanitizePipeline({
    criacao: {label: "Em criação", bg: "#123456", text: "invalid"},
  });
  assert.equal(pipeline.criacao.label, "Em criação");
  assert.equal(pipeline.criacao.bg, "#123456");
  assert.equal(pipeline.criacao.text, "#FFFFFF");
  assert.equal(Object.keys(pipeline).length, 7);
});

test("updates status and keeps only the latest twenty history entries", () => {
  const history = Array.from({length: 20}, (_, index) => ({to: String(index)}));
  const updated = updateEventRecord(
    {status: "criacao", statusHistory: history},
    "gravacao",
    "Roteiro aprovado",
    "Ana",
    "2026-09-01T12:00:00.000Z"
  );
  assert.equal(updated.status, "gravacao");
  assert.equal(updated.statusHistory.length, 20);
  assert.equal(updated.statusHistory.at(-1).source, "whatsapp-reminder-token");
  assert.equal(updated.updatedBy, "Ana");
});

test("form template has every server-side placeholder", () => {
  const form = fs.readFileSync(path.join(__dirname, "..", "form.html"), "utf8");
  for (const placeholder of [
    "{{TOKEN}}",
    "{{RESPONSIBLE_NAME}}",
    "{{EVENT_TITLE}}",
    "{{COMPANY_NAME}}",
    "{{EVENT_DATE}}",
    "{{STATUS_OPTIONS}}",
    "{{EXPIRES_AT}}",
  ]) {
    assert.equal(form.includes(placeholder), true);
  }
  assert.equal(form.includes("firebase"), false);
  assert.equal(form.includes("trello"), false);
});
