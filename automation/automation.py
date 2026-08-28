from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import sys
import time
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote, urlencode, urlsplit, urlunsplit

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeout
from playwright.sync_api import sync_playwright


BASE_DIR = Path(__file__).resolve().parent
RUNTIME_DIR = BASE_DIR / "runtime"
PROFILE_DIR = RUNTIME_DIR / "browser-profile"
CONFIG_PATH = BASE_DIR / "config.json"
STATE_PATH = RUNTIME_DIR / "state.json"
LOG_PATH = RUNTIME_DIR / "automation.log"
LOCK_PATH = RUNTIME_DIR / "automation.lock"
BRIDGE_PATH = BASE_DIR / "firebase-bridge.html"
DEFAULT_PUBLIC_CALENDAR_URL = "https://pedrocavalcant159-afk.github.io/postpreview/"
UPLI_GERAL_ID = "upli_geral_v2"
CHROME_PATHS = (
    Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
    Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
)


class AutomationError(RuntimeError):
    pass


class SetupRequired(AutomationError):
    pass


def ensure_runtime() -> None:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)


def load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def load_config() -> dict[str, Any]:
    config = load_json(CONFIG_PATH, {})
    if not isinstance(config, dict):
        raise SetupRequired("O arquivo automation/config.json está inválido.")
    return config


def chrome_path() -> Path:
    for candidate in CHROME_PATHS:
        if candidate.exists():
            return candidate
    raise SetupRequired("Google Chrome não foi encontrado.")


def log(message: str) -> None:
    ensure_runtime()
    timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
    line = f"{timestamp} | {message}"
    with LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")
    print(line, flush=True)


@contextmanager
def automation_lock():
    ensure_runtime()
    if LOCK_PATH.exists():
        age = time.time() - LOCK_PATH.stat().st_mtime
        if age < 60 * 60 * 2:
            raise AutomationError("A automação já está em execução.")
        LOCK_PATH.unlink(missing_ok=True)
    descriptor = os.open(LOCK_PATH, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    try:
        os.write(descriptor, str(os.getpid()).encode("ascii"))
        os.close(descriptor)
        yield
    finally:
        LOCK_PATH.unlink(missing_ok=True)


def week_context(reference: date | None = None) -> tuple[date, date, str]:
    today = reference or date.today()
    monday = today - timedelta(days=today.weekday())
    sunday = monday + timedelta(days=6)
    iso = monday.isocalendar()
    marker = f"[UPLI-{iso.year}-S{iso.week:02d}]"
    return monday, sunday, marker


def read_calendar(page) -> dict[str, Any]:
    page.goto(BRIDGE_PATH.as_uri() + "?mode=report", wait_until="domcontentloaded", timeout=45_000)
    page.wait_for_function(
        "document.body.dataset.status && document.body.dataset.status !== 'loading'",
        timeout=45_000,
    )
    status = page.locator("body").get_attribute("data-status")
    if status == "login-required":
        raise SetupRequired("A conta do calendário ainda não foi conectada ao perfil da automação.")
    result_text = page.locator("#result").text_content() or "{}"
    result = json.loads(result_text)
    if status != "ready" or result.get("error"):
        raise AutomationError(f"Falha ao ler o calendário: {result.get('error', status)}")
    return result


def event_id_matches(stored_id: Any, requested_id: Any) -> bool:
    stored = normalize_text(stored_id)
    requested = normalize_text(requested_id)
    return stored == requested or stored == f"{requested}_clone" or f"{stored}_clone" == requested


def find_event(
    payload: dict[str, Any],
    company_id: str,
    event_id: str,
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    companies = payload.get("companies") or []
    company = next((item for item in companies if str(item.get("id")) == company_id), None)
    if company:
        event = next(
            (item for item in (company.get("events") or []) if event_id_matches(item.get("id"), event_id)),
            None,
        )
        if event:
            return company, event
    central = next((item for item in companies if str(item.get("id")) == UPLI_GERAL_ID), None)
    if central:
        event = next(
            (
                item for item in (central.get("events") or [])
                if event_id_matches(item.get("id"), event_id)
                and normalize_text(item.get("sourceCompanyId")) in ("", company_id)
            ),
            None,
        )
        if event:
            return company or central, event
    return None


def reminder_status_options(payload: dict[str, Any]) -> list[dict[str, str]]:
    defaults = {
        "criacao": ("Criação", "#3B82F6"),
        "gravacao": ("Gravação", "#8B5CF6"),
        "producao": ("Produção", "#F59E0B"),
        "aprovacao": ("Aprovação", "#06B6D4"),
        "aprovado": ("Aprovado", "#84CC16"),
        "atrasado": ("Atrasado", "#EF4444"),
        "publicado": ("Publicado", "#10B981"),
    }
    central = next(
        (item for item in (payload.get("companies") or []) if str(item.get("id")) == UPLI_GERAL_ID),
        {},
    )
    pipeline = central.get("statusPipeline") or {}
    options = []
    for key, (default_label, default_color) in defaults.items():
        configured = pipeline.get(key) if isinstance(pipeline, dict) else {}
        if not isinstance(configured, dict):
            configured = {}
        options.append({
            "key": key,
            "label": normalize_text(configured.get("label")) or default_label,
            "color": normalize_text(configured.get("bg")) or default_color,
        })
    return options


def create_firestore_reminder_link(
    page,
    payload: dict[str, Any],
    config: dict[str, Any],
    company_id: str,
    event_id: str,
) -> str:
    found = find_event(payload, company_id, event_id)
    if not found:
        raise AutomationError("A demanda do lembrete não foi encontrada no calendário.")
    company, event = found
    responsible_id = normalize_text(event.get("responsibleId"))
    members = (payload.get("team") or {}).get("members") or []
    member = next(
        (
            item for item in members
            if isinstance(item, dict)
            and item.get("active", True)
            and normalize_text(item.get("id")) == responsible_id
        ),
        None,
    )
    if not member:
        raise SetupRequired("O responsável da demanda não está cadastrado na equipe.")
    try:
        due_date = date(int(event["year"]), int(event["month"]) + 1, int(event["day"]))
    except (KeyError, TypeError, ValueError) as error:
        raise AutomationError("A demanda está sem uma data válida.") from error
    expires_at = datetime.combine(
        due_date + timedelta(days=3),
        datetime.max.time().replace(microsecond=0),
    ).astimezone()
    if expires_at <= datetime.now().astimezone():
        raise AutomationError("O prazo deste formulário já expirou.")
    options = reminder_status_options(payload)
    token = secrets.token_urlsafe(32)
    request_data = {
        "token": token,
        "schemaVersion": 1,
        "companyId": company_id,
        "eventId": event_id,
        "companyName": normalize_text(company.get("name")) or "Calendário UPLI",
        "title": normalize_text(event.get("text")) or "Post sem título",
        "responsibleId": responsible_id,
        "responsibleName": normalize_text(member.get("name")) or "Responsável",
        "dueDate": due_date.isoformat(),
        "dueDateLabel": due_date.strftime("%d/%m/%Y"),
        "currentStatus": normalize_text(event.get("status")) or options[0]["key"],
        "statusKeys": [option["key"] for option in options],
        "statusOptions": options,
        "expiresAt": expires_at.isoformat(),
    }
    page.evaluate(
        """async requestData => {
            const token = requestData.token;
            const expiresAt = firebase.firestore.Timestamp.fromDate(new Date(requestData.expiresAt));
            delete requestData.token;
            delete requestData.expiresAt;
            await db.collection('reminderRequests').doc(token).set({
                ...requestData,
                expiresAt,
                createdAt: firebase.firestore.FieldValue.serverTimestamp(),
                active: true,
                processed: false,
                responseVersion: 0,
                responseStatus: '',
                responseNote: '',
                respondedAt: null,
                processedAt: null,
                outcome: ''
            });
        }""",
        request_data,
    )
    base_url = form_base_url(payload, config)
    if not base_url:
        raise SetupRequired("O endereço público do formulário não está configurado.")
    return f"{base_url}?{urlencode({'reminder': token})}"


def firestore_link_factory(
    page,
    config: dict[str, Any],
    payload: dict[str, Any],
) -> Callable[[str, str], str]:
    cache: dict[str, str] = {}

    def create(company_id: str, event_id: str) -> str:
        key = f"{company_id}|{event_id}"
        if key not in cache:
            cache[key] = create_firestore_reminder_link(
                page, payload, config, company_id, event_id
            )
        return cache[key]

    return create


def sync_pending_reminder_responses(
    page,
    request_token: str = "",
) -> dict[str, Any]:
    return page.evaluate(
        """async requestToken => {
            const centralId = 'upli_geral_v2';
            const matches = (storedId, requestedId) => {
                const stored = String(storedId || '');
                const requested = String(requestedId || '');
                return stored === requested || stored === requested + '_clone' ||
                    stored + '_clone' === requested;
            };
            let queuedDocs = [];
            if (requestToken) {
                const requested = await db.collection('reminderRequests').doc(requestToken).get();
                if (requested.exists) queuedDocs = [requested];
            } else {
                const snapshot = await db.collection('reminderRequests')
                    .where('responseVersion', '==', 1)
                    .limit(50)
                    .get();
                queuedDocs = snapshot.docs;
            }
            const result = { checked: queuedDocs.length, applied: 0, rejected: 0, failed: 0, details: [] };
            for (const queued of queuedDocs) {
                try {
                    const outcome = await db.runTransaction(async transaction => {
                        const requestRef = queued.ref;
                        const requestDoc = await transaction.get(requestRef);
                        if (!requestDoc.exists) return 'ignored';
                        const requestData = requestDoc.data() || {};
                        if (requestData.processed === true || requestData.responseVersion !== 1) {
                            return 'ignored';
                        }
                        const reject = message => {
                            transaction.update(requestRef, {
                                active: false,
                                processed: true,
                                processedAt: firebase.firestore.FieldValue.serverTimestamp(),
                                outcome: 'rejected',
                                processorNote: message
                            });
                            return 'rejected';
                        };
                        const respondedAt = requestData.respondedAt?.toMillis?.() || 0;
                        const expiresAt = requestData.expiresAt?.toMillis?.() || 0;
                        if (!respondedAt || !expiresAt || respondedAt > expiresAt) {
                            return reject('Resposta recebida depois do vencimento do link.');
                        }
                        if (!Array.isArray(requestData.statusKeys) ||
                            !requestData.statusKeys.includes(requestData.responseStatus)) {
                            return reject('Andamento inválido.');
                        }
                        const companyId = String(requestData.companyId || '');
                        const eventId = String(requestData.eventId || '');
                        const sourceRef = db.collection('companies').doc(companyId);
                        const sourceDoc = await transaction.get(sourceRef);
                        if (!sourceDoc.exists) return reject('Calendário não encontrado.');
                        const sourceData = sourceDoc.data() || {};
                        const sourceEvents = [...(sourceData.events || [])];
                        const sourceIndex = sourceEvents.findIndex(item => matches(item.id, eventId));
                        if (sourceIndex < 0) return reject('Demanda não encontrada.');
                        const current = sourceEvents[sourceIndex];
                        if (String(current.responsibleId || '') !== String(requestData.responsibleId || '')) {
                            return reject('O responsável da demanda foi alterado.');
                        }
                        if (String(current.status || '') === 'publicado') {
                            return reject('A demanda já está publicada.');
                        }
                        let centralDoc = null;
                        let centralRef = null;
                        if (companyId !== centralId) {
                            centralRef = db.collection('companies').doc(centralId);
                            centralDoc = await transaction.get(centralRef);
                        }
                        const updatedAt = new Date().toISOString();
                        const historyEntry = {
                            from: current.status || null,
                            to: requestData.responseStatus,
                            note: String(requestData.responseNote || '').trim(),
                            updatedAt,
                            updatedBy: requestData.responsibleName || 'Responsável',
                            updatedByEmail: '',
                            source: 'whatsapp-reminder-free-form'
                        };
                        sourceEvents[sourceIndex] = {
                            ...current,
                            status: requestData.responseStatus,
                            statusUpdateNote: historyEntry.note,
                            statusHistory: [...(current.statusHistory || []), historyEntry].slice(-20),
                            updatedAt,
                            updatedBy: historyEntry.updatedBy,
                            updatedByEmail: ''
                        };
                        transaction.update(sourceRef, { events: sourceEvents });
                        if (centralDoc?.exists) {
                            const centralData = centralDoc.data() || {};
                            const centralEvents = [...(centralData.events || [])];
                            const centralIndex = centralEvents.findIndex(item =>
                                matches(item.id, eventId) &&
                                (!item.sourceCompanyId || item.sourceCompanyId === companyId)
                            );
                            if (centralIndex >= 0) {
                                const centralCurrent = centralEvents[centralIndex];
                                centralEvents[centralIndex] = {
                                    ...centralCurrent,
                                    status: requestData.responseStatus,
                                    statusUpdateNote: historyEntry.note,
                                    statusHistory: [...(centralCurrent.statusHistory || []), historyEntry].slice(-20),
                                    updatedAt,
                                    updatedBy: historyEntry.updatedBy,
                                    updatedByEmail: ''
                                };
                                transaction.update(centralRef, { events: centralEvents });
                            }
                        }
                        transaction.update(requestRef, {
                            active: false,
                            processed: true,
                            processedAt: firebase.firestore.FieldValue.serverTimestamp(),
                            outcome: 'applied',
                            processorNote: ''
                        });
                        return 'applied';
                    });
                    if (outcome === 'applied') result.applied += 1;
                    if (outcome === 'rejected') result.rejected += 1;
                } catch (error) {
                    result.failed += 1;
                    result.details.push(String(error?.message || error));
                }
            }
            return result;
        }""",
        normalize_text(request_token),
    )


def run_sync() -> dict[str, Any]:
    config = load_config()
    with automation_lock(), sync_playwright() as playwright:
        context = browser_context(playwright, config)
        try:
            page = context.pages[0] if context.pages else context.new_page()
            read_calendar(page)
            result = sync_pending_reminder_responses(page)
            log(
                "Respostas verificadas: "
                f"{result.get('applied', 0)} aplicada(s), "
                f"{result.get('rejected', 0)} rejeitada(s), "
                f"{result.get('failed', 0)} falha(s)."
            )
            return result
        finally:
            context.close()


def redact_reminder_token(message: str) -> str:
    return re.sub(
        r"([?&](?:token|reminder)=)[A-Za-z0-9_-]+",
        r"\1[OCULTO]",
        message,
    )


def normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def readiness_value(value: Any) -> bool:
    return value is True or (isinstance(value, dict) and value.get("ready") is True)


def calendar_month_is_active(payload: dict[str, Any], reference: date | None = None) -> bool:
    target = reference or date.today()
    statuses = (payload.get("automation") or {}).get("calendarStatuses") or {}
    month_suffix = f"__{target.year}-{target.month:02d}"
    return any(str(key).endswith(month_suffix) and readiness_value(value) for key, value in statuses.items())


def canonical_event_id(event: dict[str, Any]) -> str:
    event_id = normalize_text(event.get("id"))
    if event.get("sourceCompanyId") and event_id.endswith("_clone"):
        return event_id[:-6]
    return event_id


def form_base_url(payload: dict[str, Any], config: dict[str, Any]) -> str:
    configured = normalize_text(config.get("calendar_url"))
    saved = normalize_text((payload.get("automation") or {}).get("formBaseUrl"))
    candidate = configured or saved or DEFAULT_PUBLIC_CALENDAR_URL
    if not candidate:
        return ""
    parsed = urlsplit(candidate)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return ""
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def status_update_url(base_url: str, company_id: str, event_id: str) -> str:
    query = urlencode({"updateCompany": company_id, "updateEvent": event_id})
    return f"{base_url}?{query}"


def reminder_offsets(config: dict[str, Any]) -> list[int]:
    configured = config.get("reminder_days_before", [3, 1, 0])
    if not isinstance(configured, list):
        configured = [3, 1, 0]
    values = set()
    for item in configured:
        try:
            value = int(item)
        except (TypeError, ValueError):
            continue
        if 0 <= value <= 30:
            values.add(value)
    return sorted(values, reverse=True) or [3, 1, 0]


def human_deadline(due_date: date, days_until: int) -> str:
    if days_until == 0:
        return f"para hoje, dia {due_date:%d/%m}"
    if days_until == 1:
        return f"para amanhã, dia {due_date:%d/%m}"
    return f"para o dia {due_date:%d/%m}"


def build_reminders(
    payload: dict[str, Any],
    config: dict[str, Any],
    state: dict[str, Any] | None = None,
    reference: date | None = None,
    force: bool = False,
) -> tuple[str, list[str], str]:
    today = reference or date.today()
    marker = f"[UPLI-LEM-{today:%Y%m%d}]"
    companies = payload.get("companies") or []
    company_by_id = {str(company.get("id")): company for company in companies}
    selected_ids = {str(item) for item in (config.get("company_ids") or []) if item}
    statuses = (payload.get("automation") or {}).get("calendarStatuses") or {}
    deliveries = (state or {}).get("reminder_deliveries") or {}
    offsets = reminder_offsets(config)

    if selected_ids:
        sources = [company for company in companies if str(company.get("id")) in selected_ids]
    elif "upli_geral_v2" in company_by_id:
        sources = [company_by_id["upli_geral_v2"]]
    else:
        sources = [company for company in companies if not str(company.get("id", "")).startswith("upli_geral")]

    candidates: list[dict[str, Any]] = []
    seen_events: set[str] = set()
    for source in sources:
        source_id = str(source.get("id") or "")
        source_name = normalize_text(source.get("name")) or "Empresa"
        for event in source.get("events") or []:
            try:
                due_date = date(int(event["year"]), int(event["month"]) + 1, int(event["day"]))
            except (KeyError, TypeError, ValueError):
                continue
            days_until = (due_date - today).days
            eligible_offsets = [offset for offset in offsets if days_until <= offset]
            if days_until < 0 or not eligible_offsets:
                continue
            chosen_offset = min(eligible_offsets)
            if normalize_text(event.get("status")) == "publicado":
                continue

            if source_id == "upli_geral_v2":
                source_company_id = normalize_text(event.get("sourceCompanyId"))
                color_company_id = normalize_text(event.get("color"))
                company_id = source_company_id or (
                    color_company_id if color_company_id in company_by_id else "upli_geral_v2"
                )
            else:
                company_id = source_id

            month_token = f"{due_date.year}-{due_date.month:02d}"
            central_ready = readiness_value(statuses.get(f"upli_geral_v2__{month_token}"))
            company_ready = readiness_value(statuses.get(f"{company_id}__{month_token}"))
            source_ready = readiness_value(statuses.get(f"{source_id}__{month_token}"))
            if not (central_ready or company_ready or source_ready):
                continue

            event_id = canonical_event_id(event)
            if not event_id:
                continue
            unique_event = f"{company_id}|{event_id}|{due_date.isoformat()}"
            if unique_event in seen_events:
                continue
            seen_events.add(unique_event)
            delivery_key = f"{unique_event}|D{chosen_offset}"
            if not force and delivery_key in deliveries:
                continue

            event_company = company_by_id.get(company_id, {})
            candidates.append({
                "company_id": company_id,
                "company_name": normalize_text(event_company.get("name")) or source_name,
                "event_id": event_id,
                "title": normalize_text(event.get("text")) or "Post sem título",
                "responsible": normalize_text(event.get("responsible")) or "Não definido",
                "status": normalize_text(event.get("status")),
                "due_date": due_date,
                "days_until": days_until,
                "delivery_key": delivery_key,
            })

    if not candidates:
        return "", [], marker

    base_url = form_base_url(payload, config)
    if not base_url:
        raise SetupRequired(
            "O endereço público do calendário não foi registrado. "
            "Abra o calendário online e marque o mês como Calendário concluído novamente."
        )

    status_labels = {
        "criacao": "Criação",
        "gravacao": "Gravação",
        "producao": "Produção",
        "aprovacao": "Aprovação",
        "aprovado": "Aprovado",
        "atrasado": "Atrasado",
        "publicado": "Publicado",
    }
    candidates.sort(key=lambda item: (item["due_date"], item["company_name"].casefold(), item["title"].casefold()))
    lines = [
        "Olá, pessoal! Bom dia.",
        "",
        "Estava conferindo as próximas demandas e queria saber como está o andamento delas:",
        "",
    ]
    for index, item in enumerate(candidates):
        status_label = status_labels.get(item["status"], "Sem status")
        lines.extend([
            f"*{item['company_name']} | {item['title']}*",
            f"Programada {human_deadline(item['due_date'], item['days_until'])}.",
            f"Responsável: {item['responsible']}",
            f"No calendário está como *{status_label}*.",
            f"Atualizar por aqui: {status_update_url(base_url, item['company_id'], item['event_id'])}",
        ])
        if index != len(candidates) - 1:
            lines.append("")
    lines.extend(["", "Como está o andamento por aí?", "", marker])
    return "\n".join(lines), [item["delivery_key"] for item in candidates], marker


def build_reminder_batches(
    payload: dict[str, Any],
    config: dict[str, Any],
    state: dict[str, Any] | None = None,
    reference: date | None = None,
    force: bool = False,
    update_url_factory: Callable[[str, str], str] | None = None,
) -> tuple[list[dict[str, Any]], list[str], str]:
    today = reference or date.today()
    day_marker = f"[UPLI-LEM-{today:%Y%m%d}]"
    companies = payload.get("companies") or []
    company_by_id = {str(company.get("id")): company for company in companies}
    selected_ids = {str(item) for item in (config.get("company_ids") or []) if item}
    statuses = (payload.get("automation") or {}).get("calendarStatuses") or {}
    deliveries = (state or {}).get("reminder_deliveries") or {}
    offsets = reminder_offsets(config)
    members = [
        member for member in ((payload.get("team") or {}).get("members") or [])
        if isinstance(member, dict) and member.get("active", True)
    ]
    members_by_id = {normalize_text(member.get("id")): member for member in members if member.get("id")}
    members_by_email = {
        normalize_text(member.get("email")).casefold(): member
        for member in members if normalize_text(member.get("email"))
    }
    members_by_name = {
        normalize_text(member.get("name")).casefold(): member
        for member in members if normalize_text(member.get("name"))
    }

    if selected_ids:
        sources = [company for company in companies if str(company.get("id")) in selected_ids]
    elif "upli_geral_v2" in company_by_id:
        sources = [company_by_id["upli_geral_v2"]]
    else:
        sources = [company for company in companies if not str(company.get("id", "")).startswith("upli_geral")]

    candidates: list[dict[str, Any]] = []
    missing: list[str] = []
    seen_events: set[str] = set()
    for source in sources:
        source_id = str(source.get("id") or "")
        source_name = normalize_text(source.get("name")) or "Empresa"
        for event in source.get("events") or []:
            try:
                due_date = date(int(event["year"]), int(event["month"]) + 1, int(event["day"]))
            except (KeyError, TypeError, ValueError):
                continue
            days_until = (due_date - today).days
            eligible_offsets = [offset for offset in offsets if days_until <= offset]
            if days_until < 0 or not eligible_offsets:
                continue
            chosen_offset = min(eligible_offsets)
            if normalize_text(event.get("status")) == "publicado":
                continue

            if source_id == "upli_geral_v2":
                source_company_id = normalize_text(event.get("sourceCompanyId"))
                color_company_id = normalize_text(event.get("color"))
                company_id = source_company_id or (
                    color_company_id if color_company_id in company_by_id else "upli_geral_v2"
                )
            else:
                company_id = source_id

            month_token = f"{due_date.year}-{due_date.month:02d}"
            central_ready = readiness_value(statuses.get(f"upli_geral_v2__{month_token}"))
            company_ready = readiness_value(statuses.get(f"{company_id}__{month_token}"))
            source_ready = readiness_value(statuses.get(f"{source_id}__{month_token}"))
            if not (central_ready or company_ready or source_ready):
                continue

            event_id = canonical_event_id(event)
            if not event_id:
                continue
            unique_event = f"{company_id}|{event_id}|{due_date.isoformat()}"
            if unique_event in seen_events:
                continue
            seen_events.add(unique_event)
            delivery_key = f"{unique_event}|D{chosen_offset}"
            if not force and delivery_key in deliveries:
                continue

            responsible_id = normalize_text(event.get("responsibleId"))
            responsible_email = normalize_text(event.get("responsibleEmail")).casefold()
            responsible_name = normalize_text(event.get("responsible")).casefold()
            member = members_by_id.get(responsible_id)
            if member is None and not responsible_id:
                member = members_by_email.get(responsible_email) or members_by_name.get(responsible_name)
            event_company = company_by_id.get(company_id, {})
            title = normalize_text(event.get("text")) or "Post sem título"
            company_name = normalize_text(event_company.get("name")) or source_name
            if not member:
                missing.append(f"{company_name} | {title}: responsável não cadastrado")
                continue
            try:
                phone = normalize_test_phone(normalize_text(member.get("phone")))
            except SetupRequired:
                missing.append(f"{company_name} | {title}: WhatsApp inválido para {normalize_text(member.get('name'))}")
                continue
            candidates.append({
                "company_id": company_id,
                "company_name": company_name,
                "event_id": event_id,
                "title": title,
                "responsible": normalize_text(member.get("name")) or "Responsável",
                "phone": phone,
                "status": normalize_text(event.get("status")),
                "due_date": due_date,
                "days_until": days_until,
                "delivery_key": delivery_key,
            })

    if not candidates:
        return [], missing, day_marker
    base_url = form_base_url(payload, config)
    if not base_url and update_url_factory is None:
        raise SetupRequired(
            "O endereço público do calendário não foi registrado. "
            "Abra o calendário online e marque o mês como Calendário concluído novamente."
        )

    status_labels = {
        "criacao": "Criação",
        "gravacao": "Gravação",
        "producao": "Produção",
        "aprovacao": "Aprovação",
        "aprovado": "Aprovado",
        "atrasado": "Atrasado",
        "publicado": "Publicado",
    }
    grouped: dict[str, list[dict[str, Any]]] = {}
    for candidate in candidates:
        grouped.setdefault(candidate["phone"], []).append(candidate)

    batches: list[dict[str, Any]] = []
    for phone, items in sorted(grouped.items()):
        items.sort(key=lambda item: (item["due_date"], item["company_name"].casefold(), item["title"].casefold()))
        marker_hash = hashlib.sha256(phone.encode("ascii")).hexdigest()[:6].upper()
        marker = f"[UPLI-LEM-{today:%Y%m%d}-{marker_hash}]"
        responsible = items[0]["responsible"]
        if len(items) == 1:
            item = items[0]
            status_label = status_labels.get(item["status"], "Sem status")
            update_url = (
                update_url_factory(item["company_id"], item["event_id"])
                if update_url_factory
                else status_update_url(base_url, item["company_id"], item["event_id"])
            )
            lines = [
                f"Olá, {responsible}! Bom dia.",
                "",
                (
                    f"Passando para lembrar da demanda *{item['company_name']} | {item['title']}*, "
                    f"que está programada {human_deadline(item['due_date'], item['days_until'])}."
                ),
                "",
                f"No calendário, o status atual é *{status_label}*. Como está o andamento por aí?",
                "",
                "Quando puder, atualize por este link:",
                update_url,
                "",
                marker,
            ]
        else:
            lines = [
                f"Olá, {responsible}! Bom dia.",
                "",
                (
                    "Estava conferindo suas próximas demandas e passei para saber "
                    "como está o andamento delas:"
                ),
                "",
            ]
            for index, item in enumerate(items):
                update_url = (
                    update_url_factory(item["company_id"], item["event_id"])
                    if update_url_factory
                    else status_update_url(base_url, item["company_id"], item["event_id"])
                )
                lines.extend([
                    f"*{item['company_name']} | {item['title']}*",
                    f"Programada {human_deadline(item['due_date'], item['days_until'])}.",
                    f"No calendário está como *{status_labels.get(item['status'], 'Sem status')}*.",
                    f"Atualizar por aqui: {update_url}",
                ])
                if index != len(items) - 1:
                    lines.append("")
            lines.extend([
                "",
                "Quando puder, me conta como estão essas demandas?",
                "",
                marker,
            ])
        batches.append({
            "phone": phone,
            "responsible": items[0]["responsible"],
            "message": "\n".join(lines),
            "marker": marker,
            "delivery_keys": [item["delivery_key"] for item in items],
            "event_count": len(items),
        })
    return batches, missing, day_marker


def build_report(
    payload: dict[str, Any],
    config: dict[str, Any],
    reference: date | None = None,
) -> tuple[str, int, str, str]:
    monday, sunday, marker = week_context(reference)
    companies = payload.get("companies") or []
    company_by_id = {str(company.get("id")): company for company in companies}
    selected_ids = {str(item) for item in (config.get("company_ids") or []) if item}
    statuses = (payload.get("automation") or {}).get("calendarStatuses") or {}
    ready_statuses = {str(key): value for key, value in statuses.items() if readiness_value(value)}
    week_months = set()
    cursor = monday
    while cursor <= sunday:
        week_months.add(f"{cursor.year}-{cursor.month:02d}")
        cursor += timedelta(days=1)
    active_week_statuses = {
        key: value for key, value in ready_statuses.items()
        if any(key.endswith(f"__{month_token}") for month_token in week_months)
    }
    activation_data = {
        key: value.get("completedAt", "") if isinstance(value, dict) else "ready"
        for key, value in sorted(active_week_statuses.items())
    }
    activation_fingerprint = ""
    if activation_data:
        encoded = json.dumps(activation_data, ensure_ascii=False, sort_keys=True).encode("utf-8")
        activation_fingerprint = hashlib.sha256(encoded).hexdigest()

    if selected_ids:
        sources = [company for company in companies if str(company.get("id")) in selected_ids]
    elif "upli_geral_v2" in company_by_id:
        sources = [company_by_id["upli_geral_v2"]]
    else:
        sources = [company for company in companies if not str(company.get("id", "")).startswith("upli_geral")]

    status_labels = {
        "criacao": "Criação",
        "gravacao": "Gravação",
        "producao": "Produção",
        "aprovacao": "Aprovação",
        "aprovado": "Aprovado",
        "atrasado": "Atrasado",
        "publicado": "Publicado",
    }
    rows: list[tuple[date, str, str, str, str]] = []

    for source in sources:
        source_name = normalize_text(source.get("name")) or "Empresa"
        for event in source.get("events") or []:
            try:
                event_date = date(int(event["year"]), int(event["month"]) + 1, int(event["day"]))
            except (KeyError, TypeError, ValueError):
                continue
            if event_date < monday or event_date > sunday:
                continue
            company_id = str(event.get("sourceCompanyId") or event.get("color") or "")
            month_token = f"{event_date.year}-{event_date.month:02d}"
            central_ready = readiness_value(statuses.get(f"upli_geral_v2__{month_token}"))
            company_ready = readiness_value(statuses.get(f"{company_id}__{month_token}"))
            source_ready = readiness_value(statuses.get(f"{source.get('id')}__{month_token}"))
            if not (central_ready or company_ready or source_ready):
                continue
            event_company = company_by_id.get(company_id, {})
            company_name = normalize_text(event_company.get("name")) or source_name
            title = normalize_text(event.get("text")) or "Post sem título"
            responsible = normalize_text(event.get("responsible")) or "Não definido"
            status_key = normalize_text(event.get("status"))
            status = status_labels.get(status_key, "Sem status")
            rows.append((event_date, company_name, title, responsible, status))

    rows.sort(key=lambda row: (row[0], row[1].casefold(), row[2].casefold()))
    title = normalize_text(config.get("report_title")) or "PLANEJAMENTO DE CONTEÚDO DA SEMANA"
    lines = [
        "Olá, pessoal! Bom dia.",
        "",
        "Estava analisando as demandas da semana e preparei este resumo para alinharmos o que está previsto:",
        "",
        f"*{title}*",
        f"Período: {monday:%d/%m/%Y} a {sunday:%d/%m/%Y}",
        "",
    ]

    if not rows:
        lines.append("Pelo calendário, não temos nenhum post programado para esta semana.")
    else:
        current_day = None
        weekdays = ("SEG", "TER", "QUA", "QUI", "SEX", "SÁB", "DOM")
        for event_date, company_name, event_title, responsible, status in rows:
            if event_date != current_day:
                if current_day is not None:
                    lines.append("")
                lines.append(f"*{weekdays[event_date.weekday()]} {event_date:%d/%m}*")
                current_day = event_date
            lines.append(f"• {company_name} | {event_title}")
            lines.append(f"  Responsável: {responsible} | Status: {status}")

    if rows:
        lines.extend((
            "",
            "Conforme forem avançando, atualizem o andamento no Calendário UPLI, por favor.",
        ))
    lines.extend(("", marker))
    return "\n".join(lines), len(rows), marker, activation_fingerprint


def whatsapp_is_ready(page, timeout_ms: int = 60_000) -> bool:
    page.goto("https://web.whatsapp.com/", wait_until="domcontentloaded", timeout=timeout_ms)
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        pane = page.locator("#pane-side")
        if pane.count() and pane.first.is_visible():
            return True
        qr = page.locator("canvas[aria-label*='QR'], canvas[aria-label*='qr']")
        if first_visible(qr) is not None:
            return False
        login_prompt = page.get_by_text(re.compile("Use o WhatsApp no seu computador|Link with phone number|Conectar com número"))
        if first_visible(login_prompt) is not None:
            return False
        page.wait_for_timeout(1000)
    return False


def first_visible(locator):
    for index in range(locator.count()):
        item = locator.nth(index)
        if item.is_visible():
            return item
    return None


def wait_for_outgoing_confirmation(page, marker: str, timeout_ms: int = 30_000) -> None:
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        containers = page.locator("#main [data-testid='msg-container']").filter(has_text=marker)
        for index in range(containers.count()):
            status = containers.nth(index).evaluate(
                """container => {
                    const labels = [...container.querySelectorAll('[aria-label]')]
                        .map(element => (element.getAttribute('aria-label') || '').trim())
                        .filter(Boolean);
                    const own = labels.some(label => {
                        const value = label.toLocaleLowerCase();
                        return value.startsWith('você:') || value.startsWith('you:');
                    });
                    const combined = labels.join(' ').toLocaleLowerCase();
                    return {
                        own,
                        error: /erro|error|falha|failed/.test(combined),
                        confirmed: /enviad|sent|entreg|deliver|lida|read/.test(combined)
                    };
                }"""
            )
            if not status.get("own"):
                continue
            if status.get("error"):
                raise AutomationError(
                    "O WhatsApp criou a mensagem, mas marcou o envio com erro. "
                    "Nada foi confirmado como enviado."
                )
            if status.get("confirmed"):
                return
        page.wait_for_timeout(500)
    raise AutomationError(
        "O WhatsApp não confirmou a mensagem como enviada ou entregue dentro do tempo esperado."
    )


def send_whatsapp(page, group_name: str, message: str, marker: str) -> None:
    if not whatsapp_is_ready(page):
        raise SetupRequired("O WhatsApp Web ainda não está conectado no perfil da automação.")

    search = first_visible(page.locator("#side div[contenteditable='true']"))
    if search is None:
        search = first_visible(page.get_by_role("textbox", name=re.compile("Pesquisar|Search", re.I)))
    if search is None:
        raise AutomationError("Não encontrei a pesquisa de conversas do WhatsApp.")

    search.click()
    search.fill(group_name)
    page.wait_for_timeout(1500)
    conversations = page.locator("#pane-side")
    result = first_visible(conversations.get_by_title(group_name, exact=True))
    if result is None:
        result = first_visible(conversations.get_by_text(group_name, exact=True))
    if result is None:
        raise SetupRequired(f"O grupo '{group_name}' não foi encontrado no WhatsApp.")
    result.click()

    composer = page.locator("footer div[contenteditable='true']")
    composer.first.wait_for(state="visible", timeout=20_000)
    input_box = first_visible(composer)
    if input_box is None:
        raise AutomationError("Não encontrei a caixa de mensagem do grupo.")
    input_box.click()
    input_box.fill(message)
    input_box.press("Enter")
    page.wait_for_timeout(500)
    if normalize_text(input_box.text_content()):
        raise AutomationError("O WhatsApp não confirmou o envio da mensagem.")
    wait_for_outgoing_confirmation(page, marker)


def normalize_test_phone(value: str) -> str:
    digits = re.sub(r"\D", "", value or "")
    if len(digits) in (10, 11):
        digits = "55" + digits
    if not 12 <= len(digits) <= 15:
        raise SetupRequired(
            "Número de teste inválido. Informe DDD e número, por exemplo 27999999999."
        )
    return digits


def send_whatsapp_to_phone(page, phone: str, message: str, marker: str) -> str:
    normalized_phone = normalize_test_phone(phone)
    if not whatsapp_is_ready(page):
        raise SetupRequired("O WhatsApp Web ainda não está conectado no perfil da automação.")
    url = f"https://web.whatsapp.com/send?phone={normalized_phone}&text={quote(message)}"
    page.goto(url, wait_until="domcontentloaded", timeout=60_000)
    deadline = time.monotonic() + 45
    input_box = None
    while time.monotonic() < deadline:
        invalid = first_visible(page.get_by_text(re.compile(
            r"número.+inválido|phone number.+invalid|não está no WhatsApp|isn't on WhatsApp",
            re.I,
        )))
        if invalid is not None:
            raise SetupRequired("O número informado não está disponível no WhatsApp.")
        input_box = first_visible(page.locator("footer div[contenteditable='true']"))
        if input_box is not None:
            break
        page.wait_for_timeout(500)
    if input_box is None:
        raise AutomationError("Não encontrei a caixa de mensagem para o número de teste.")
    if not normalize_text(input_box.text_content()):
        input_box.fill(message)
    input_box.click()
    input_box.press("Enter")
    page.wait_for_timeout(500)
    wait_for_outgoing_confirmation(page, marker)
    return normalized_phone


def browser_context(playwright, config: dict[str, Any], headless: bool | None = None):
    use_headless = bool(config.get("headless", True)) if headless is None else headless
    return playwright.chromium.launch_persistent_context(
        user_data_dir=str(PROFILE_DIR),
        executable_path=str(chrome_path()),
        headless=use_headless,
        viewport={"width": 1440, "height": 960},
        locale="pt-BR",
        timezone_id="America/Sao_Paulo",
    )


def verify_sessions(config: dict[str, Any]) -> dict[str, Any]:
    result = {
        "calendar": False,
        "whatsapp": False,
        "calendar_user": "",
        "active_month": False,
        "form_url": False,
    }
    with sync_playwright() as playwright:
        context = browser_context(playwright, config, headless=True)
        try:
            page = context.pages[0] if context.pages else context.new_page()
            payload = read_calendar(page)
            result["calendar"] = True
            result["calendar_user"] = payload.get("user", "")
            result["active_month"] = calendar_month_is_active(payload)
            result["form_url"] = bool(form_base_url(payload, config))
            whatsapp_page = context.new_page()
            result["whatsapp"] = whatsapp_is_ready(whatsapp_page, timeout_ms=45_000)
        finally:
            context.close()
    return result


def run_send(force: bool = False, dry_run: bool = False) -> dict[str, Any]:
    config = load_config()
    group_name = normalize_text(config.get("group_name"))
    if not group_name and not dry_run:
        raise SetupRequired("Informe o nome exato do grupo em automation/config.json ou execute setup.ps1.")

    state = load_json(STATE_PATH, {})
    monday, _, marker = week_context()

    with automation_lock(), sync_playwright() as playwright:
        context = browser_context(playwright, config)
        try:
            page = context.pages[0] if context.pages else context.new_page()
            payload = read_calendar(page)
            sync_result = sync_pending_reminder_responses(page)
            if sync_result.get("applied"):
                payload = read_calendar(page)
            message, event_count, marker, activation_fingerprint = build_report(payload, config)
            if not activation_fingerprint:
                paused_message = "Automação pausada: nenhum calendário desta semana foi marcado como concluído."
                (RUNTIME_DIR / "last-report.txt").write_text(paused_message, encoding="utf-8")
                log(paused_message)
                return {"sent": False, "paused": True, "events": 0, "marker": marker}
            if (
                not force
                and state.get("last_success_marker") == marker
                and state.get("last_activation_fingerprint") == activation_fingerprint
            ):
                log(f"Envio ignorado: o relatório {marker} já foi enviado para os calendários liberados.")
                return {"sent": False, "duplicate": True, "marker": marker}
            (RUNTIME_DIR / "last-report.txt").write_text(message, encoding="utf-8")
            if dry_run:
                log(f"Relatório de teste gerado com {event_count} post(s).")
                return {"sent": False, "dry_run": True, "events": event_count, "marker": marker}
            whatsapp_page = context.new_page()
            send_whatsapp(whatsapp_page, group_name, message, marker)
            state.update({
                "last_success_marker": marker,
                "last_activation_fingerprint": activation_fingerprint,
                "last_success_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                "last_event_count": event_count,
                "last_group": group_name,
                "week_start": monday.isoformat(),
            })
            save_json(STATE_PATH, state)
            log(f"Relatório {marker} enviado para '{group_name}' com {event_count} post(s).")
            return {"sent": True, "events": event_count, "marker": marker}
        except Exception:
            try:
                context.pages[-1].screenshot(path=str(RUNTIME_DIR / "last-error.png"), full_page=True)
            except Exception:
                pass
            raise
        finally:
            context.close()


def run_reminders(force: bool = False, dry_run: bool = False) -> dict[str, Any]:
    config = load_config()
    state = load_json(STATE_PATH, {})
    with automation_lock(), sync_playwright() as playwright:
        context = browser_context(playwright, config)
        try:
            page = context.pages[0] if context.pages else context.new_page()
            payload = read_calendar(page)
            sync_result = sync_pending_reminder_responses(page)
            if sync_result.get("applied"):
                payload = read_calendar(page)
            update_url_factory = (
                (lambda _company_id, _event_id: form_base_url(payload, config) + "?reminder=GERADO-NO-ENVIO")
                if dry_run
                else firestore_link_factory(page, config, payload)
            )
            batches, missing, marker = build_reminder_batches(
                payload,
                config,
                state=state,
                force=force,
                update_url_factory=update_url_factory,
            )
            event_count = sum(batch["event_count"] for batch in batches)
            preview_sections = []
            for batch in batches:
                preview_sections.extend([
                    f"DESTINO: {batch['responsible']} (final {batch['phone'][-4:]})",
                    redact_reminder_token(batch["message"]),
                    "",
                ])
            if missing:
                preview_sections.extend(["PENDÊNCIAS:", *missing])
            preview = "\n".join(preview_sections).strip() or "Nenhum lembrete necessário hoje."
            (RUNTIME_DIR / "last-reminders.txt").write_text(preview, encoding="utf-8")
            if not batches:
                state["last_reminder_issues"] = missing
                save_json(STATE_PATH, state)
                if missing:
                    log(f"Lembretes não enviados: {len(missing)} post(s) sem responsável com WhatsApp válido.")
                else:
                    log("Lembretes verificados: nenhum post precisa de aviso hoje.")
                return {
                    "sent": False,
                    "events": 0,
                    "recipients": 0,
                    "missing_recipients": len(missing),
                    "marker": marker,
                }

            if dry_run:
                log(f"Teste de lembretes gerado com {event_count} post(s) para {len(batches)} pessoa(s).")
                return {
                    "sent": False,
                    "dry_run": True,
                    "events": event_count,
                    "recipients": len(batches),
                    "missing_recipients": len(missing),
                    "marker": marker,
                }

            whatsapp_page = context.new_page()
            deliveries = dict(state.get("reminder_deliveries") or {})
            failures: list[str] = []
            sent_events = 0
            sent_recipients = 0
            for batch in batches:
                try:
                    send_whatsapp_to_phone(
                        whatsapp_page,
                        batch["phone"],
                        batch["message"],
                        batch["marker"],
                    )
                    sent_at = datetime.now().astimezone().isoformat(timespec="seconds")
                    deliveries.update({key: sent_at for key in batch["delivery_keys"]})
                    sent_events += batch["event_count"]
                    sent_recipients += 1
                    state.update({
                        "reminder_deliveries": deliveries,
                        "last_reminder_at": sent_at,
                        "last_reminder_count": sent_events,
                        "last_reminder_recipients": sent_recipients,
                    })
                    save_json(STATE_PATH, state)
                    log(
                        f"Lembrete confirmado para {batch['responsible']} "
                        f"(número final {batch['phone'][-4:]}), com {batch['event_count']} post(s)."
                    )
                except Exception as error:
                    failures.append(
                        f"{batch['responsible']} (final {batch['phone'][-4:]}): {error}"
                    )

            cutoff = datetime.now().astimezone() - timedelta(days=90)
            deliveries = {
                key: timestamp
                for key, timestamp in deliveries.items()
                if not isinstance(timestamp, str)
                or not timestamp
                or _delivery_is_recent(timestamp, cutoff)
            }
            state.update({
                "reminder_deliveries": deliveries,
                "last_reminder_count": sent_events,
                "last_reminder_recipients": sent_recipients,
                "last_reminder_issues": [*missing, *failures],
            })
            save_json(STATE_PATH, state)
            if failures:
                raise AutomationError(
                    f"{len(failures)} destinatário(s) falharam. "
                    f"{sent_recipients} destinatário(s) foram confirmados."
                )
            log(
                f"Lembretes privados concluídos: {sent_events} post(s) "
                f"para {sent_recipients} pessoa(s)."
            )
            return {
                "sent": sent_recipients > 0,
                "events": sent_events,
                "recipients": sent_recipients,
                "missing_recipients": len(missing),
                "marker": marker,
            }
        except Exception:
            try:
                context.pages[-1].screenshot(path=str(RUNTIME_DIR / "last-error.png"), full_page=True)
            except Exception:
                pass
            raise
        finally:
            context.close()


def _delivery_is_recent(timestamp: str, cutoff: datetime) -> bool:
    try:
        return datetime.fromisoformat(timestamp) >= cutoff
    except (TypeError, ValueError):
        return True


def test_marker() -> str:
    return f"[UPLI-TEST-{datetime.now().astimezone():%Y%m%d%H%M%S}]"


def build_test_message(
    mode: str,
    payload: dict[str, Any],
    config: dict[str, Any],
    company_id: str = "",
    reference: date | None = None,
    update_url_factory: Callable[[str, str], str] | None = None,
) -> tuple[str, int, str]:
    today = reference or date.today()
    marker = test_marker()
    companies = payload.get("companies") or []
    company_by_id = {str(company.get("id")): company for company in companies}
    selected_company = company_by_id.get(company_id) or company_by_id.get("upli_geral_v2")

    if mode == "message":
        message = "\n".join([
            "*TESTE DA AUTOMAÇÃO UPLI*",
            marker,
            "",
            "Conexão com o calendário: OK",
            "Envio para o grupo do WhatsApp: OK",
            "",
            "Esta é apenas uma mensagem de teste. Nenhum envio oficial foi registrado.",
        ])
        return message, 0, marker

    if mode == "weekly":
        test_payload = json.loads(json.dumps(payload, ensure_ascii=False))
        automation = test_payload.setdefault("automation", {})
        statuses = automation.setdefault("calendarStatuses", {})
        monday, sunday, weekly_marker = week_context(today)
        cursor = monday
        target_company_id = str((selected_company or {}).get("id") or "upli_geral_v2")
        while cursor <= sunday:
            month_token = f"{cursor.year}-{cursor.month:02d}"
            statuses[f"{target_company_id}__{month_token}"] = {"ready": True, "completedAt": "test"}
            cursor += timedelta(days=1)
        test_config = dict(config)
        test_config["company_ids"] = [target_company_id]
        report, event_count, _, _ = build_report(test_payload, test_config, reference=today)
        report = report.replace(weekly_marker, marker)
        message = "\n".join([
            "*TESTE - RELATÓRIO SEMANAL*",
            "Este teste não conta como envio oficial.",
            "",
            report,
        ])
        return message, event_count, marker

    if mode == "reminder":
        if not selected_company:
            raise SetupRequired("Nenhum calendário foi encontrado para testar o lembrete.")
        base_url = form_base_url(payload, config)
        if not base_url and update_url_factory is None:
            raise SetupRequired(
                "O endereço público dos formulários ainda não foi registrado. "
                "Conclua um mês pelo calendário online antes de testar um lembrete."
            )
        source_id = str(selected_company.get("id") or "")
        candidates = []
        for event in selected_company.get("events") or []:
            try:
                event_date = date(int(event["year"]), int(event["month"]) + 1, int(event["day"]))
            except (KeyError, TypeError, ValueError):
                continue
            if event_date < today or normalize_text(event.get("status")) == "publicado":
                continue
            event_id = canonical_event_id(event)
            if not event_id:
                continue
            if source_id == "upli_geral_v2":
                source_company_id = normalize_text(event.get("sourceCompanyId"))
                color_company_id = normalize_text(event.get("color"))
                target_company_id = source_company_id or (
                    color_company_id if color_company_id in company_by_id else "upli_geral_v2"
                )
            else:
                target_company_id = source_id
            candidates.append((event_date, normalize_text(event.get("text")), event, target_company_id, event_id))
        if not candidates:
            raise SetupRequired("Não há post futuro e não publicado neste calendário para testar o lembrete.")
        event_date, title, event, target_company_id, event_id = min(
            candidates,
            key=lambda item: (item[0], item[1].casefold()),
        )
        target_company = company_by_id.get(target_company_id, selected_company)
        responsible = normalize_text(event.get("responsible")) or "responsável"
        company_name = normalize_text(target_company.get("name")) or "Empresa"
        days_until = (event_date - today).days
        status_labels = {
            "criacao": "Criação",
            "gravacao": "Gravação",
            "producao": "Produção",
            "aprovacao": "Aprovação",
            "aprovado": "Aprovado",
            "atrasado": "Atrasado",
            "publicado": "Publicado",
        }
        status_label = status_labels.get(normalize_text(event.get("status")), "Sem status")
        update_url = (
            update_url_factory(target_company_id, event_id)
            if update_url_factory
            else status_update_url(base_url, target_company_id, event_id)
        )
        message = "\n".join([
            "*TESTE - LEMBRETE DE POST*",
            "Este teste não conta como lembrete oficial.",
            "",
            f"Olá, {responsible}! Bom dia.",
            "",
            (
                f"Passando para lembrar da demanda *{company_name} | {title or 'Post sem título'}*, "
                f"que está programada {human_deadline(event_date, days_until)}."
            ),
            "",
            f"No calendário, o status atual é *{status_label}*. Como está o andamento por aí?",
            "",
            "Quando puder, atualize por este link:",
            update_url,
            "",
            marker,
        ])
        return message, 1, marker

    raise ValueError(f"Modo de teste desconhecido: {mode}")


def run_test(
    mode: str,
    company_id: str = "",
    test_phone: str = "",
    dry_run: bool = False,
) -> dict[str, Any]:
    config = load_config()
    group_name = normalize_text(config.get("group_name"))
    if not group_name and not dry_run:
        raise SetupRequired("Informe o nome exato do grupo antes de executar um teste.")

    with automation_lock(), sync_playwright() as playwright:
        context = browser_context(playwright, config)
        try:
            page = context.pages[0] if context.pages else context.new_page()
            payload = read_calendar(page)
            update_url_factory = None
            if mode == "reminder":
                update_url_factory = (
                    (lambda _company_id, _event_id: form_base_url(payload, config) + "?reminder=GERADO-NO-TESTE")
                    if dry_run
                    else firestore_link_factory(page, config, payload)
                )
            message, event_count, marker = build_test_message(
                mode,
                payload,
                config,
                company_id=company_id,
                update_url_factory=update_url_factory,
            )
            (RUNTIME_DIR / "last-test.txt").write_text(
                redact_reminder_token(message),
                encoding="utf-8",
            )
            if dry_run:
                log(f"Teste '{mode}' gerado sem envio.")
                return {
                    "sent": False,
                    "dry_run": True,
                    "mode": mode,
                    "events": event_count,
                    "marker": marker,
                }
            whatsapp_page = context.new_page()
            if normalize_text(test_phone):
                normalized_phone = send_whatsapp_to_phone(
                    whatsapp_page,
                    test_phone,
                    message,
                    marker,
                )
                destination = f"número final {normalized_phone[-4:]}"
            else:
                send_whatsapp(whatsapp_page, group_name, message, marker)
                destination = f"grupo '{group_name}'"
            log(f"Teste '{mode}' confirmado no {destination}.")
            return {
                "sent": True,
                "mode": mode,
                "events": event_count,
                "marker": marker,
                "destination": destination,
            }
        except Exception:
            try:
                context.pages[-1].screenshot(path=str(RUNTIME_DIR / "last-error.png"), full_page=True)
            except Exception:
                pass
            raise
        finally:
            context.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Automação semanal do Calendário UPLI")
    parser.add_argument("--force", action="store_true", help="Ignora o bloqueio de envio semanal duplicado")
    parser.add_argument("--dry-run", action="store_true", help="Gera o relatório sem enviar")
    parser.add_argument("--verify", action="store_true", help="Verifica as sessões do calendário e WhatsApp")
    parser.add_argument("--reminders", action="store_true", help="Envia os lembretes de prazo com links de atualização")
    parser.add_argument("--sync-responses", action="store_true", help="Aplica as respostas dos formulários")
    parser.add_argument("--test-mode", choices=("message", "weekly", "reminder"), help="Executa um envio de teste isolado")
    parser.add_argument("--test-company", default="", help="Calendário usado no relatório ou lembrete de teste")
    parser.add_argument("--test-phone", default="", help="Número opcional para receber o envio de teste")
    args = parser.parse_args()
    ensure_runtime()
    try:
        config = load_config()
        if args.sync_responses:
            print(json.dumps(run_sync(), ensure_ascii=False))
        elif args.verify:
            print(json.dumps(verify_sessions(config), ensure_ascii=False))
        elif args.test_mode:
            print(json.dumps(
                run_test(
                    args.test_mode,
                    company_id=args.test_company,
                    test_phone=args.test_phone,
                    dry_run=args.dry_run,
                ),
                ensure_ascii=False,
            ))
        elif args.reminders:
            print(json.dumps(run_reminders(force=args.force, dry_run=args.dry_run), ensure_ascii=False))
        else:
            print(json.dumps(run_send(force=args.force, dry_run=args.dry_run), ensure_ascii=False))
        return 0
    except (AutomationError, PlaywrightError, PlaywrightTimeout, OSError, ValueError) as error:
        log(f"ERRO: {error}")
        print(json.dumps({"error": str(error)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    sys.exit(main())
