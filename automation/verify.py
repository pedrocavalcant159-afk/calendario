from __future__ import annotations

import argparse
import html
import json
import os
import subprocess
import sys
import urllib.request
import winreg
from datetime import datetime, time as clock_time, timedelta
from pathlib import Path
from typing import Any

from automation import (
    CONFIG_PATH,
    RUNTIME_DIR,
    STATE_PATH,
    SetupRequired,
    chrome_path,
    load_config,
    load_json,
    log,
    normalize_text,
    run_send,
    save_json,
    verify_sessions,
    week_context,
)


TASK_WEEKLY = "Calendario UPLI - Relatorio Semanal"
TASK_REMINDERS = "Calendario UPLI - Lembretes Diarios"
TASK_SYNC = "Calendario UPLI - Sincronizar Respostas"
TASK_LOGIN = "Calendario UPLI - Verificacao ao Entrar"
STATUS_PATH = RUNTIME_DIR / "status.json"
STATUS_HTML_PATH = RUNTIME_DIR / "status.html"


def internet_available() -> bool:
    try:
        request = urllib.request.Request(
            "https://www.gstatic.com/generate_204",
            headers={"User-Agent": "UPLI-Automation-Check/1.0"},
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status in (200, 204)
    except Exception:
        return False


def temporary_forms_available(config: dict[str, Any]) -> bool:
    try:
        public_url = normalize_text(config.get("calendar_url"))
        if not public_url.startswith("https://"):
            return False
        request = urllib.request.Request(
            public_url,
            headers={"User-Agent": "UPLI-Automation-Check/1.0"},
        )
        with urllib.request.urlopen(request, timeout=15) as response:
            content = response.read().decode("utf-8", errors="replace")
            return (
                response.status == 200
                and "PublicReminderUpdate" in content
                and "reminderRequests" in content
            )
    except Exception:
        return False


def task_exists(task_name: str) -> bool:
    completed = subprocess.run(
        ["schtasks.exe", "/Query", "/TN", task_name],
        capture_output=True,
        text=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    return completed.returncode == 0


def test_shortcut_exists() -> bool:
    desktop = ""
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders",
        ) as key:
            desktop = str(winreg.QueryValueEx(key, "Desktop")[0])
    except OSError:
        desktop = str(Path.home() / "Desktop")
    desktop = os.path.expandvars(desktop)
    return (Path(desktop) / "Testar Automacao UPLI.lnk").exists()


def scheduled_due(config: dict[str, Any], state: dict[str, Any]) -> bool:
    if not config.get("catch_up_missed_send", True):
        return False
    monday, _, marker = week_context()
    if state.get("last_success_marker") == marker:
        return False
    not_before_text = normalize_text(config.get("first_send_not_before"))
    if not not_before_text:
        return False
    try:
        if datetime.now().astimezone() < datetime.fromisoformat(not_before_text):
            return False
    except ValueError:
        return False
    hour_text = normalize_text(config.get("send_time")) or "09:00"
    try:
        hour, minute = (int(part) for part in hour_text.split(":", 1))
        due_at = datetime.combine(monday, clock_time(hour, minute)).astimezone()
    except (TypeError, ValueError):
        return False
    return datetime.now().astimezone() >= due_at


def render_status(status: dict[str, Any]) -> None:
    checks = status.get("checks", {})
    issues = status.get("issues", [])
    notes = status.get("notes", [])
    rows = []
    labels = {
        "config": "Configuração",
        "chrome": "Google Chrome",
        "internet": "Internet",
        "weekly_task": "Agendamento de segunda às 9h",
        "reminder_task": "Lembretes diários às 9h05",
        "sync_task": "Sincronização das respostas",
        "login_task": "Verificação ao entrar no Windows",
        "test_shortcut": "Painel local de testes",
        "calendar": "Sessão do calendário",
        "whatsapp": "Sessão do WhatsApp Web",
        "secure_form": "Formulários gratuitos sem login",
        "active_month": "Automação ativa",
    }
    for key, label in labels.items():
        passed = bool(checks.get(key))
        result_class = "ok" if passed else "bad"
        result_text = "OK" if passed else "ATENÇÃO"
        rows.append(
            f"<tr><td>{html.escape(label)}</td><td class={result_class}>{result_text}</td></tr>"
        )
    issue_html = "".join(f"<li>{html.escape(str(issue))}</li>" for issue in issues) or "<li>Nenhum problema encontrado.</li>"
    note_html = "".join(f"<li>{html.escape(str(note))}</li>" for note in notes)
    last_success = html.escape(str(status.get("last_success_at") or "Nenhum envio registrado"))
    content = f"""<!DOCTYPE html>
<html lang="pt-BR"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Status da Automação UPLI</title><style>
body{{font-family:Arial,sans-serif;background:#f3f4f6;color:#111827;margin:0;padding:24px}}main{{max-width:760px;margin:auto;background:white;border:1px solid #d1d5db;border-radius:8px;padding:24px;box-shadow:0 12px 30px rgba(0,0,0,.1)}}
h1{{margin-top:0}}table{{width:100%;border-collapse:collapse;margin:20px 0}}td{{padding:11px;border-bottom:1px solid #e5e7eb}}td:last-child{{text-align:right;font-weight:700}}.ok{{color:#047857}}.bad{{color:#b91c1c}}.pause{{color:#b45309}}.box{{background:#f9fafb;border:1px solid #e5e7eb;border-radius:6px;padding:14px}}a{{color:#0369a1;font-weight:700}}small{{color:#6b7280}}</style></head>
<body><main><h1>Automação UPLI</h1><p>Verificação: {html.escape(str(status.get('checked_at', '')))}</p>
<table>{''.join(rows)}</table><div class="box"><strong>Diagnóstico</strong><ul>{issue_html}{note_html}</ul></div>
<p><strong>Último envio:</strong> {last_success}</p>
<p><a href="../setup.ps1">Abrir arquivo de configuração</a> · <a href="automation.log">Ver registro técnico</a> · <a href="last-report.txt">Ver último relatório</a> · <a href="last-reminders.txt">Ver últimos lembretes</a> · <a href="last-test.txt">Ver último teste</a></p>
<small>Para reconfigurar, execute setup.ps1 pelo Explorador de Arquivos.</small></main></body></html>"""
    STATUS_HTML_PATH.write_text(content, encoding="utf-8")


def verify(allow_catchup: bool = True) -> dict[str, Any]:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    status: dict[str, Any] = {
        "checked_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "ready": False,
        "checks": {},
        "issues": [],
        "notes": [],
        "catchup": None,
    }
    checks = status["checks"]
    issues = status["issues"]
    notes = status["notes"]

    try:
        config = load_config()
        group_name = normalize_text(config.get("group_name"))
        checks["config"] = bool(group_name)
        if not group_name:
            issues.append("Informe o nome exato do grupo executando automation/setup.ps1.")
    except SetupRequired as error:
        config = {}
        checks["config"] = False
        issues.append(str(error))

    try:
        chrome_path()
        checks["chrome"] = True
    except SetupRequired as error:
        checks["chrome"] = False
        issues.append(str(error))

    checks["internet"] = internet_available()
    if not checks["internet"]:
        issues.append("Sem acesso à internet durante a verificação.")

    checks["weekly_task"] = task_exists(TASK_WEEKLY)
    checks["reminder_task"] = task_exists(TASK_REMINDERS)
    checks["sync_task"] = task_exists(TASK_SYNC)
    checks["login_task"] = task_exists(TASK_LOGIN)
    checks["test_shortcut"] = test_shortcut_exists()
    if not checks["weekly_task"]:
        issues.append("A tarefa semanal ainda não está instalada.")
    if not checks["reminder_task"]:
        issues.append("A tarefa diária de lembretes ainda não está instalada.")
    if not checks["sync_task"]:
        issues.append("A tarefa de sincronização das respostas ainda não está instalada.")
    if not checks["login_task"]:
        issues.append("A verificação ao entrar no Windows ainda não está instalada.")
    if not checks["test_shortcut"]:
        issues.append("O atalho do painel de testes ainda não está instalado na Área de Trabalho.")

    checks["calendar"] = False
    checks["whatsapp"] = False
    checks["form_url"] = False
    checks["secure_form"] = checks["internet"] and temporary_forms_available(config)
    checks["active_month"] = False
    if checks["chrome"] and checks["internet"]:
        try:
            sessions = verify_sessions(config)
            checks["calendar"] = bool(sessions.get("calendar"))
            checks["whatsapp"] = bool(sessions.get("whatsapp"))
            checks["form_url"] = bool(sessions.get("form_url"))
            checks["active_month"] = bool(sessions.get("active_month"))
            status["calendar_user"] = sessions.get("calendar_user", "")
        except Exception as error:
            issues.append(f"Não foi possível abrir o perfil da automação: {error}")
    if not checks["calendar"]:
        issues.append("Conecte a conta do calendário no perfil da automação.")
    if not checks["whatsapp"]:
        issues.append("Conecte o WhatsApp Web no perfil da automação.")
    if not checks["secure_form"]:
        issues.append("O formulário gratuito do GitHub Pages não está atualizado.")

    essential = all(checks.get(key) for key in ("config", "chrome", "internet", "calendar", "whatsapp"))
    essential = essential and checks["secure_form"]
    state = load_json(STATE_PATH, {})
    status["last_success_at"] = state.get("last_success_at")
    reminder_issues = state.get("last_reminder_issues") or []
    if reminder_issues:
        notes.append(
            f"Última verificação de lembretes: {len(reminder_issues)} pendência(s). "
            "Consulte Ver últimos lembretes para identificar as demandas."
        )

    if allow_catchup and essential and scheduled_due(config, state):
        try:
            status["catchup"] = run_send()
            state = load_json(STATE_PATH, {})
            status["last_success_at"] = state.get("last_success_at")
        except Exception as error:
            issues.append(f"O envio de recuperação falhou: {error}")

    status["ready"] = (
        essential
        and checks["weekly_task"]
        and checks["reminder_task"]
        and checks["sync_task"]
        and checks["login_task"]
        and checks["test_shortcut"]
        and not issues
    )
    save_json(STATUS_PATH, status)
    render_status(status)
    log("Verificação concluída: " + ("pronto" if status["ready"] else "atenção necessária"))
    return status


def main() -> int:
    parser = argparse.ArgumentParser(description="Verifica a automação local do Calendário UPLI")
    parser.add_argument("--skip-catchup", action="store_true")
    args = parser.parse_args()
    status = verify(allow_catchup=not args.skip_catchup)
    # O diagnóstico pode conter caracteres fora da página de códigos do
    # PowerShell legado do Windows. Escapá-los mantém o JSON legível e evita
    # que a verificação falhe apenas ao exibir o resultado.
    print(json.dumps(status, ensure_ascii=True))
    return 0 if status["ready"] else 1


if __name__ == "__main__":
    sys.exit(main())
