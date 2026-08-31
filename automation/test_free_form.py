from __future__ import annotations

import argparse
import secrets
from datetime import datetime, timedelta

from playwright.sync_api import sync_playwright

from automation import (
    BASE_DIR,
    browser_context,
    chrome_path,
    load_config,
    read_calendar,
    sync_pending_reminder_responses,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--public-url", default="")
    args = parser.parse_args()
    token = secrets.token_urlsafe(32)
    created = False
    browser = None
    with sync_playwright() as playwright:
        context = browser_context(playwright, load_config(), headless=True)
        admin_page = context.pages[0] if context.pages else context.new_page()
        try:
            read_calendar(admin_page)
            admin_page.evaluate(
                """async data => {
                    await db.collection('reminderRequests').doc(data.token).set({
                        schemaVersion: 1,
                        companyId: 'upli-form-test',
                        eventId: 'test-event',
                        companyName: 'Teste UPLI',
                        title: 'Demanda de teste do formulario',
                        responsibleId: 'test-member',
                        responsibleName: 'Pessoa de Teste',
                        dueDate: '2026-08-28',
                        dueDateLabel: '28/08/2026',
                        currentStatus: 'criacao',
                        statusKeys: ['criacao', 'aprovado'],
                        statusOptions: [
                            {key: 'criacao', label: 'Criacao', color: '#3B82F6'},
                            {key: 'aprovado', label: 'Aprovado', color: '#84CC16'}
                        ],
                        expiresAt: firebase.firestore.Timestamp.fromDate(new Date(data.expiresAt)),
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
                {
                    "token": token,
                    "expiresAt": (datetime.now().astimezone() + timedelta(hours=1)).isoformat(),
                },
            )
            created = True

            browser = playwright.chromium.launch(
                executable_path=str(chrome_path()),
                headless=True,
            )
            public_page = browser.new_page()
            page_errors: list[str] = []
            public_page.on("pageerror", lambda error: page_errors.append(str(error)))
            if args.public_url:
                url = args.public_url.rstrip("/") + f"/?reminder={token}"
            else:
                url = (BASE_DIR.parent / "index.html").as_uri() + f"?reminder={token}"
            public_page.goto(url, wait_until="domcontentloaded", timeout=45_000)
            public_page.get_by_text("Demanda de teste do formulario").wait_for(timeout=30_000)
            public_page.locator("input[value='aprovado']").check()
            public_page.locator("textarea").fill("Resposta automatizada de validacao")
            public_page.get_by_role("button", name="Confirmar andamento").click()
            public_page.get_by_text("Resposta recebida.", exact=False).wait_for(timeout=30_000)

            saved = admin_page.evaluate(
                """async token => {
                    const snapshot = await db.collection('reminderRequests').doc(token).get();
                    const data = snapshot.data() || {};
                    return {
                        version: data.responseVersion,
                        status: data.responseStatus,
                        note: data.responseNote
                    };
                }""",
                token,
            )
            expected = {
                "version": 1,
                "status": "aprovado",
                "note": "Resposta automatizada de validacao",
            }
            if saved != expected:
                raise AssertionError(f"Resposta gravada diferente do esperado: {saved!r}")
            if page_errors:
                raise AssertionError(f"Erros na pagina: {page_errors!r}")
            sync_result = sync_pending_reminder_responses(admin_page, request_token=token)
            if sync_result.get("rejected") != 1 or sync_result.get("failed") != 0:
                raise AssertionError(f"Processamento sintetico inesperado: {sync_result!r}")
            processed = admin_page.evaluate(
                """async token => {
                    const snapshot = await db.collection('reminderRequests').doc(token).get();
                    const data = snapshot.data() || {};
                    return {processed: data.processed, outcome: data.outcome};
                }""",
                token,
            )
            if processed != {"processed": True, "outcome": "rejected"}:
                raise AssertionError(f"Fila nao processada como esperado: {processed!r}")
            print("Formulario anonimo, regras e fila validados sem alterar demandas.")
            return 0
        finally:
            if created:
                try:
                    admin_page.evaluate(
                        "token => db.collection('reminderRequests').doc(token).delete()",
                        token,
                    )
                except Exception:
                    pass
            if browser:
                browser.close()
            context.close()


if __name__ == "__main__":
    raise SystemExit(main())
