# Automação local UPLI

Esta pasta envia o relatório do calendário para um grupo do WhatsApp toda segunda-feira às 9h e verifica lembretes de prazo diariamente às 9h05, usando um perfil local e separado do Chrome. O relatório semanal vai para o grupo; os lembretes de prazo vão individualmente para o WhatsApp do responsável.

## Equipe e responsáveis

Administradores podem abrir **Equipe** no calendário para cadastrar, editar e remover funcionários ou membros da equipe. Cada cadastro contém nome, WhatsApp e, opcionalmente, o e-mail da conta que acessa o formulário.

- Ao criar ou editar um post, o responsável é escolhido entre os membros cadastrados.
- Os lembretes do dia são agrupados por responsável e enviados em uma conversa privada para o número cadastrado.
- Um responsável com várias demandas recebe uma única mensagem contendo todos os posts daquele dia.
- Uma demanda sem responsável cadastrado ou com WhatsApp inválido não é enviada ao grupo. Ela fica registrada como pendência no diagnóstico e em \`runtime/last-reminders.txt\`.
- Alterar o nome ou o número no cadastro vale para os próximos lembretes, porque a automação consulta a equipe novamente antes de cada execução.
- Ao remover um membro, os posts já atribuídos a ele permanecem no calendário, mas deixam de gerar lembretes até receberem outro responsável.

O link temporário já identifica o membro cadastrado como responsável. Ele não precisa informar e-mail ou senha para atualizar o andamento.

## Lembretes e atualização pelo celular

Por padrão, um post ainda não publicado pode gerar avisos 3 dias antes, 1 dia antes e no próprio prazo. Cada aviso individual contém um link temporário exclusivo. O formulário já identifica o responsável, permite escolher o andamento e salva a alteração no calendário da empresa e no UPLI Geral.

- O link é criado pela automação autenticada e usa o calendário hospedado no GitHub Pages.
- O endereço contém um token aleatório de 256 bits e expira três dias depois do prazo.
- O formulário público só pode gravar o status escolhido, uma observação e o horário da resposta.
- A resposta fica em uma fila do Firestore e este computador a aplica ao calendário em até um minuto.
- Se o computador estiver desligado, a resposta permanece guardada e é aplicada quando ele ligar.
- Trocar o responsável, remover o post ou marcá-lo como **Publicado** invalida o link.
- Alterar a data do post gera novas chaves de lembrete para o novo prazo.
- Posts com status **Publicado** não geram lembretes.
- Cada combinação de post, prazo e antecedência é enviada uma única vez.
- O histórico das últimas 20 alterações feitas pelo formulário fica armazenado no próprio post.

Os dias podem ser alterados em `reminder_days_before` no arquivo `config.json`.

## Testes manuais

O instalador cria o atalho **Testar Automacao UPLI** na Área de Trabalho deste computador. O painel oferece:

- diagnóstico completo sem enviar mensagem;
- mensagem simples para confirmar o grupo;
- relatório semanal marcado como teste;
- lembrete do próximo post com um link real do formulário.

Os modos que enviam ao WhatsApp exigem a confirmação `SIM`. Mensagens de teste recebem o marcador `UPLI-TEST` e não alteram os registros de envio oficial, as chaves de lembrete ou o status dos posts. O status só muda se alguém abrir o link do lembrete e confirmar o formulário.

Depois da confirmação, o painel aceita um número com DDD para receber o teste diretamente. Se o campo ficar vazio, usa o grupo configurado. O teste de lembrete também gera um link temporário real. O painel só informa sucesso quando a bolha de saída aparece como enviada, entregue ou lida; mensagens marcadas com erro pelo WhatsApp são reportadas como falha.

## Liberação mensal

A automação começa somente depois que um administrador abre o calendário desejado e clica em **Calendário concluído**. A liberação é registrada por empresa, ano e mês.

- No **UPLI Geral**, concluir o mês libera todas as empresas daquele período.
- Em um calendário individual, libera somente aquela empresa.
- Ao virar o mês, o novo período começa pausado.
- O botão **Reabrir mês** remove a liberação e pausa novamente aquele calendário.
- Em semanas que atravessam dois meses, entram apenas os posts dos meses liberados.

## Primeira configuração

1. Execute `install.ps1` com o PowerShell.
2. Informe o nome exato do grupo.
3. Na janela do Chrome aberta pelo assistente, conecte a conta do calendário.
4. Abra o WhatsApp Web e leia o QR Code.
5. Feche todas as janelas desse perfil e volte ao assistente para validar.

O instalador cria estas tarefas no Agendador do Windows:

- `Calendario UPLI - Relatorio Semanal`: segunda-feira às 9h.
- `Calendario UPLI - Lembretes Diarios`: todos os dias às 9h05.
- `Calendario UPLI - Sincronizar Respostas`: verifica a fila a cada minuto.
- `Calendario UPLI - Verificacao ao Entrar`: sempre que o usuário entrar no Windows.

O verificador confere internet, Chrome, sessões do calendário e WhatsApp e todos os agendamentos. Se o computador estava desligado no horário, ele sincroniza as respostas guardadas e tenta recuperar o envio quando o usuário entrar. O marcador semanal impede duplicidade.

## Arquivos de diagnóstico

- `runtime/status.html`: painel de situação, acessível pelo botão **Automação** no calendário.
- `runtime/automation.log`: histórico técnico.
- `runtime/last-report.txt`: último relatório gerado.
- `runtime/last-reminders.txt`: última mensagem de lembretes gerada.
- `runtime/last-test.txt`: última mensagem de teste gerada.
- `runtime/last-error.png`: captura da tela quando um envio falha.
- `test_free_form.py`: teste sintético do formulário, das regras e da fila; não altera demandas reais.

Execute `setup.ps1` para trocar o grupo ou reconectar as contas. Execute `uninstall.ps1` para remover apenas as tarefas agendadas; sessões e registros são preservados.

## Limitação

Esta integração controla o WhatsApp Web sem usar a API oficial. Mudanças na interface do WhatsApp podem exigir manutenção, e automação não oficial pode sofrer restrições da plataforma. Para reduzir o risco, o agente envia somente o relatório semanal e os lembretes previstos no calendário; ele não tenta ler conversas.
