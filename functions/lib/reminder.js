"use strict";

const crypto = require("node:crypto");

const DEFAULT_PIPELINE = {
  criacao: {label: "Criação", bg: "#3B82F6", text: "#FFFFFF"},
  gravacao: {label: "Gravação", bg: "#F97316", text: "#FFFFFF"},
  producao: {label: "Produção", bg: "#8B5CF6", text: "#FFFFFF"},
  aprovacao: {label: "Aprovação", bg: "#EAB308", text: "#111827"},
  aprovado: {label: "Aprovado", bg: "#14B8A6", text: "#FFFFFF"},
  atrasado: {label: "Atrasado", bg: "#EF4444", text: "#FFFFFF"},
  publicado: {label: "Publicado", bg: "#22C55E", text: "#FFFFFF"},
};

function normalizeText(value) {
  return String(value || "").replace(/\s+/g, " ").trim();
}

function eventIdMatches(storedId, requestedId) {
  const stored = normalizeText(storedId);
  const requested = normalizeText(requestedId);
  return stored === requested ||
    stored === requested + "_clone" ||
    stored + "_clone" === requested;
}

function tokenDigest(token) {
  return crypto.createHash("sha256").update(String(token || ""), "utf8").digest("hex");
}

function createRawToken() {
  return crypto.randomBytes(32).toString("base64url");
}

function expirationForEvent(event) {
  const year = Number(event.year);
  const month = Number(event.month) + 1;
  const day = Number(event.day);
  if (!Number.isInteger(year) || !Number.isInteger(month) || !Number.isInteger(day)) {
    throw new Error("A demanda possui uma data inválida.");
  }
  const datePart = [
    String(year).padStart(4, "0"),
    String(month).padStart(2, "0"),
    String(day).padStart(2, "0"),
  ].join("-");
  const endOfDueDate = new Date(datePart + "T23:59:59-03:00");
  if (Number.isNaN(endOfDueDate.getTime())) {
    throw new Error("A demanda possui uma data inválida.");
  }
  return new Date(endOfDueDate.getTime() + (3 * 24 * 60 * 60 * 1000));
}

function sanitizePipeline(pipeline) {
  const source = {...DEFAULT_PIPELINE, ...(pipeline || {})};
  const result = {};
  for (const [key, fallback] of Object.entries(DEFAULT_PIPELINE)) {
    const value = source[key] || fallback;
    result[key] = {
      label: normalizeText(value.label) || fallback.label,
      bg: /^#[0-9a-f]{6}$/i.test(value.bg || "") ? value.bg : fallback.bg,
      text: /^#[0-9a-f]{6}$/i.test(value.text || "") ? value.text : fallback.text,
    };
  }
  return result;
}

function updateEventRecord(event, status, note, actor, updatedAt) {
  const historyEntry = {
    from: normalizeText(event.status) || null,
    to: status,
    note,
    updatedAt,
    updatedBy: actor,
    updatedByEmail: "",
    source: "whatsapp-reminder-token",
  };
  return {
    ...event,
    status,
    statusUpdateNote: note,
    statusHistory: [...(event.statusHistory || []), historyEntry].slice(-20),
    updatedAt,
    updatedBy: actor,
    updatedByEmail: "",
  };
}

module.exports = {
  DEFAULT_PIPELINE,
  createRawToken,
  eventIdMatches,
  expirationForEvent,
  normalizeText,
  sanitizePipeline,
  tokenDigest,
  updateEventRecord,
};
