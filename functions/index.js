"use strict";

const fs = require("node:fs");
const path = require("node:path");
const {setGlobalOptions} = require("firebase-functions/v2");
const {onRequest} = require("firebase-functions/v2/https");
const {initializeApp} = require("firebase-admin/app");
const {getAuth} = require("firebase-admin/auth");
const {FieldValue, Timestamp, getFirestore} = require("firebase-admin/firestore");
const {
  createRawToken,
  eventIdMatches,
  expirationForEvent,
  normalizeText,
  sanitizePipeline,
  tokenDigest,
  updateEventRecord,
} = require("./lib/reminder");

initializeApp();
setGlobalOptions({
  region: "southamerica-east1",
  memory: "256MiB",
  timeoutSeconds: 30,
  minInstances: 0,
  maxInstances: 3,
});

const db = getFirestore();
const FORM_TEMPLATE = fs.readFileSync(path.join(__dirname, "form.html"), "utf8");
const MASTER_EMAIL = "pedrocavalcant159@gmail.com";
const CENTRAL_ID = "upli_geral_v2";

class ApiError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}

function sendJson(response, status, payload) {
  response.set("Cache-Control", "no-store, max-age=0");
  response.set("X-Content-Type-Options", "nosniff");
  response.status(status).json(payload);
}

function escapeHtml(value) {
  return String(value || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function formatDate(value, includeTime = false) {
  const options = includeTime ?
    {timeZone: "America/Sao_Paulo", dateStyle: "short", timeStyle: "short"} :
    {timeZone: "America/Sao_Paulo", dateStyle: "short"};
  return new Intl.DateTimeFormat("pt-BR", options).format(value);
}

function publicFunctionUrl() {
  const projectId = process.env.GCLOUD_PROJECT || process.env.GCP_PROJECT;
  if (!projectId) throw new ApiError(500, "O endereço da função não está configurado.");
  return "https://southamerica-east1-" + projectId +
    ".cloudfunctions.net/reminderAccess";
}

function sendFormHtml(response, data, rawToken) {
  const statusOptions = Object.entries(data.pipeline).map(([key, value]) => {
    const checked = data.event.status === key ? " checked" : "";
    return '<label class="status">' +
      '<input type="radio" name="status" value="' + escapeHtml(key) + '"' + checked + ">" +
      '<span class="swatch" style="background:' + escapeHtml(value.bg) + '"></span>' +
      "<strong>" + escapeHtml(value.label) + "</strong>" +
      "</label>";
  }).join("");
  const dueDate = new Date(Date.UTC(
    data.event.year, data.event.month, data.event.day, 15, 0, 0
  ));
  const replacements = {
    "{{TOKEN}}": escapeHtml(rawToken),
    "{{RESPONSIBLE_NAME}}": escapeHtml(data.responsibleName),
    "{{EVENT_TITLE}}": escapeHtml(data.event.text),
    "{{COMPANY_NAME}}": escapeHtml(data.companyName),
    "{{EVENT_DATE}}": escapeHtml(formatDate(dueDate)),
    "{{STATUS_OPTIONS}}": statusOptions,
    "{{EXPIRES_AT}}": escapeHtml(formatDate(new Date(data.expiresAt), true)),
  };
  let content = FORM_TEMPLATE;
  for (const [placeholder, value] of Object.entries(replacements)) {
    content = content.replaceAll(placeholder, value);
  }
  response.set("Cache-Control", "no-store, max-age=0");
  response.set("Content-Type", "text/html; charset=utf-8");
  response.set("Referrer-Policy", "no-referrer");
  response.set("X-Content-Type-Options", "nosniff");
  response.set("X-Frame-Options", "DENY");
  response.set(
    "Content-Security-Policy",
    "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; " +
    "connect-src 'self'; form-action 'none'; base-uri 'none'; frame-ancestors 'none'"
  );
  response.status(200).send(content);
}

function requireMethod(request, method) {
  if (request.method !== method) {
    throw new ApiError(405, "Método não permitido.");
  }
}

function requireToken(value) {
  const token = normalizeText(value);
  if (!/^[A-Za-z0-9_-]{40,120}$/.test(token)) {
    throw new ApiError(400, "O link está incompleto ou é inválido.");
  }
  return token;
}

function findEvent(events, eventId) {
  const index = (events || []).findIndex((event) => eventIdMatches(event.id, eventId));
  return {index, event: index >= 0 ? events[index] : null};
}

function validateActiveToken(tokenData, now) {
  if (!tokenData || tokenData.active === false) {
    throw new ApiError(410, "Este link não está mais ativo.");
  }
  const expiresAt = tokenData.expiresAt && tokenData.expiresAt.toDate ?
    tokenData.expiresAt.toDate() :
    new Date(tokenData.expiresAt || 0);
  if (Number.isNaN(expiresAt.getTime()) || expiresAt <= now) {
    throw new ApiError(410, "Este link expirou. Aguarde um novo lembrete.");
  }
  return expiresAt;
}

function validateEventAccess(event, tokenData) {
  if (!event) {
    throw new ApiError(410, "A demanda foi removida e este link não é mais válido.");
  }
  if (normalizeText(event.status) === "publicado") {
    throw new ApiError(410, "Esta demanda já foi publicada.");
  }
  if (!tokenData.responsibleId ||
      normalizeText(event.responsibleId) !== normalizeText(tokenData.responsibleId)) {
    throw new ApiError(410, "O responsável da demanda mudou e este link foi cancelado.");
  }
}

async function requireAdmin(request) {
  const authorization = normalizeText(request.get("authorization"));
  const match = authorization.match(/^Bearer\s+(.+)$/i);
  if (!match) throw new ApiError(401, "Autorização da automação ausente.");
  let decoded;
  try {
    decoded = await getAuth().verifyIdToken(match[1]);
  } catch (error) {
    throw new ApiError(401, "A sessão da automação expirou.");
  }
  const email = normalizeText(decoded.email).toLowerCase();
  const rolesSnapshot = await db.collection("system").doc("roles").get();
  const roles = rolesSnapshot.exists ? rolesSnapshot.data() || {} : {};
  const role = (roles.userRoles || {})[email];
  if (email !== MASTER_EMAIL && role !== "master" && role !== "admin") {
    throw new ApiError(403, "A conta da automação não possui acesso administrativo.");
  }
  return {email, uid: decoded.uid};
}

async function createLink(request, response) {
  requireMethod(request, "POST");
  const issuer = await requireAdmin(request);
  const companyId = normalizeText(request.body && request.body.companyId);
  const eventId = normalizeText(request.body && request.body.eventId);
  if (!companyId || !eventId) throw new ApiError(400, "Empresa ou demanda não informada.");

  const [companySnapshot, teamSnapshot] = await Promise.all([
    db.collection("companies").doc(companyId).get(),
    db.collection("system").doc("team").get(),
  ]);
  if (!companySnapshot.exists) throw new ApiError(404, "O calendário não foi encontrado.");
  const company = companySnapshot.data() || {};
  const {event} = findEvent(company.events, eventId);
  if (!event) throw new ApiError(404, "A demanda não foi encontrada.");
  if (normalizeText(event.status) === "publicado") {
    throw new ApiError(409, "A demanda já foi publicada.");
  }

  const team = teamSnapshot.exists ? teamSnapshot.data() || {} : {};
  const member = (team.members || []).find((item) =>
    item && item.active !== false && normalizeText(item.id) === normalizeText(event.responsibleId)
  );
  if (!member) {
    throw new ApiError(409, "A demanda não possui um responsável ativo cadastrado.");
  }
  const expiresAt = expirationForEvent(event);
  if (expiresAt <= new Date()) {
    throw new ApiError(410, "O prazo para responder esta demanda já expirou.");
  }

  const rawToken = createRawToken();
  const tokenRef = db.collection("reminderTokens").doc(tokenDigest(rawToken));
  await tokenRef.create({
    active: true,
    companyId,
    eventId,
    responsibleId: normalizeText(member.id),
    responsibleName: normalizeText(member.name) || "Responsável",
    createdAt: FieldValue.serverTimestamp(),
    createdByEmail: issuer.email,
    createdByUid: issuer.uid,
    expiresAt: Timestamp.fromDate(expiresAt),
    useCount: 0,
  });

  const formUrl = new URL(publicFunctionUrl());
  formUrl.searchParams.set("token", rawToken);
  sendJson(response, 201, {
    ok: true,
    url: formUrl.toString(),
    expiresAt: expiresAt.toISOString(),
  });
}

async function readLink(request, response) {
  requireMethod(request, "GET");
  if (String(request.query.health || "") === "1") {
    sendJson(response, 200, {ok: true, service: "reminderAccess"});
    return;
  }
  const rawToken = requireToken(request.query.token);
  const tokenSnapshot = await db.collection("reminderTokens").doc(tokenDigest(rawToken)).get();
  if (!tokenSnapshot.exists) throw new ApiError(404, "Este link não foi encontrado.");
  const tokenData = tokenSnapshot.data() || {};
  const expiresAt = validateActiveToken(tokenData, new Date());

  const [companySnapshot, centralSnapshot] = await Promise.all([
    db.collection("companies").doc(tokenData.companyId).get(),
    db.collection("companies").doc(CENTRAL_ID).get(),
  ]);
  if (!companySnapshot.exists) throw new ApiError(410, "O calendário foi removido.");
  const company = companySnapshot.data() || {};
  const {event} = findEvent(company.events, tokenData.eventId);
  validateEventAccess(event, tokenData);
  const central = centralSnapshot.exists ? centralSnapshot.data() || {} : {};

  const data = {
    ok: true,
    companyName: normalizeText(company.name) || "Calendário UPLI",
    responsibleName: tokenData.responsibleName,
    expiresAt: expiresAt.toISOString(),
    pipeline: sanitizePipeline(central.statusPipeline),
    event: {
      text: normalizeText(event.text) || "Post sem título",
      day: Number(event.day),
      month: Number(event.month),
      year: Number(event.year),
      status: normalizeText(event.status) || "criacao",
    },
  };
  if (String(request.query.format || "").toLowerCase() === "json") {
    sendJson(response, 200, data);
    return;
  }
  sendFormHtml(response, data, rawToken);
}

async function updateFromLink(request, response) {
  requireMethod(request, "POST");
  const rawToken = requireToken(request.body && request.body.token);
  const requestedStatus = normalizeText(request.body && request.body.status);
  const note = normalizeText(request.body && request.body.note).slice(0, 500);
  const tokenRef = db.collection("reminderTokens").doc(tokenDigest(rawToken));
  const updatedAt = new Date().toISOString();

  const result = await db.runTransaction(async (transaction) => {
    const tokenSnapshot = await transaction.get(tokenRef);
    if (!tokenSnapshot.exists) throw new ApiError(404, "Este link não foi encontrado.");
    const tokenData = tokenSnapshot.data() || {};
    validateActiveToken(tokenData, new Date());

    const sourceRef = db.collection("companies").doc(tokenData.companyId);
    const centralRef = db.collection("companies").doc(CENTRAL_ID);
    const sourceSnapshot = await transaction.get(sourceRef);
    if (!sourceSnapshot.exists) throw new ApiError(410, "O calendário foi removido.");
    let centralSnapshot = null;
    if (tokenData.companyId !== CENTRAL_ID) {
      centralSnapshot = await transaction.get(centralRef);
    }

    const sourceData = sourceSnapshot.data() || {};
    const sourceEvents = [...(sourceData.events || [])];
    const {index: sourceIndex, event: sourceEvent} = findEvent(sourceEvents, tokenData.eventId);
    validateEventAccess(sourceEvent, tokenData);

    const centralData = centralSnapshot && centralSnapshot.exists ? centralSnapshot.data() || {} : {};
    const pipeline = sanitizePipeline(
      tokenData.companyId === CENTRAL_ID ? sourceData.statusPipeline : centralData.statusPipeline
    );
    if (!Object.prototype.hasOwnProperty.call(pipeline, requestedStatus)) {
      throw new ApiError(400, "Escolha um status válido.");
    }

    const actor = normalizeText(tokenData.responsibleName) || "Responsável";
    sourceEvents[sourceIndex] = updateEventRecord(
      sourceEvent, requestedStatus, note, actor, updatedAt
    );
    transaction.update(sourceRef, {events: sourceEvents});

    if (centralSnapshot && centralSnapshot.exists) {
      const centralEvents = [...(centralData.events || [])];
      const {index: centralIndex, event: centralEvent} = findEvent(
        centralEvents, tokenData.eventId
      );
      if (centralIndex >= 0) {
        centralEvents[centralIndex] = updateEventRecord(
          centralEvent, requestedStatus, note, actor, updatedAt
        );
        transaction.update(centralRef, {events: centralEvents});
      }
    }

    transaction.update(tokenRef, {
      lastUsedAt: FieldValue.serverTimestamp(),
      useCount: FieldValue.increment(1),
      ...(requestedStatus === "publicado" ? {active: false} : {}),
    });
    return {status: requestedStatus, label: pipeline[requestedStatus].label};
  });

  sendJson(response, 200, {ok: true, ...result, updatedAt});
}

exports.reminderAccess = onRequest(
  {cors: false, invoker: "public"},
  async (request, response) => {
    try {
      if (request.method === "GET") {
        await readLink(request, response);
        return;
      }
      const action = normalizeText(request.body && request.body.action);
      if (action === "create") {
        await createLink(request, response);
        return;
      }
      if (action === "update") {
        await updateFromLink(request, response);
        return;
      }
      throw new ApiError(400, "Ação inválida.");
    } catch (error) {
      if (!(error instanceof ApiError)) {
        console.error("Reminder access error", error);
      }
      sendJson(
        response,
        error instanceof ApiError ? error.status : 500,
        {ok: false, error: error instanceof ApiError ? error.message : "Não foi possível concluir a operação."}
      );
    }
  }
);
