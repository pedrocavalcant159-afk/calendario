# Automação local UPLI

Esta pasta envia o relatório do calendário para um grupo do WhatsApp toda segunda-feira às 9h. Diariamente, envia às 9h e às 17h lembretes somente das demandas atrasadas e das demandas do dia. As novas marcações são consolidadas às 12h e às 17h. O relatório semanal vai para o grupo geral; lembretes e marcações vão para o grupo específico cadastrado para cada responsável.

## Equipe e responsáveis

Administradores podem abrir **Equipe** no calendário para cadastrar, editar e remover funcionários ou membros da equipe. Cada cadastro contém nome, nome exato do grupo individual de WhatsApp e, opcionalmente, o telefone e o e-mail da conta que acessa o formulário.

- Ao criar ou editar um post, o responsável é escolhido entre os membros cadastrados.
- Os lembretes de demandas atrasadas e do dia são agrupados por responsável e enviados às 9h e às 17h.
- Um responsável com várias demandas recebe uma única mensagem contendo todos os posts daquele ciclo.
- Novas marcações são agrupadas por responsável às 12h e às 17h. O lote das 17h não repete as marcações já enviadas às 12h.
- Uma demanda sem responsável cadastrado ou sem grupo configurado não é enviada. Ela fica registrada como pendência no diagnóstico e em \`runtime/last-reminders.txt\`.
- Alterar o nome ou o grupo no cadastro vale para os próximos lembretes, porque a automação consulta a equipe novamente antes de cada execução.
- Ao remover um membro, os posts já atribuídos a ele permanecem no calendário, mas deixam de gerar lembretes até receberem outro responsável.
- O nome do grupo deve ser digitado exatamente como aparece no WhatsApp.

O link temporário já identifica o membro cadastrado como responsável. Ele não precisa informar e-mail ou senha para atualizar o andamento.

## Conclusão no Trello

Quando o responsável escolher o status **Concluído** no formulário, a automação marca como concluído o cartão Trello vinculado àquela demanda. Outros status só atualizam o calendário.

- Ao exportar uma demanda para o Trello, o calendário guarda o identificador do cartão para as próximas sincronizações.
- Execute `configurar-trello.ps1` uma vez em cada PC que possa virar líder e informe o token pessoal do Trello. O token fica apenas no `config.json` local e não vai para o GitHub Pages.
- Cartões exportados antes desta atualização não têm vínculo salvo. Exporte novamente somente essas demandas para criar o vínculo.
- Se o Trello estiver indisponível, a automação mantém a conclusão em uma fila e tenta novamente no próximo ciclo.

## Lembretes e atualização pelo celular

Um post ainda não publicado gera lembretes quando está atrasado ou quando vence no dia. A verificação ocorre às 9h e às 17h; cada ciclo tem controle próprio para não duplicar a mesma mensagem. Cada demanda contém um link temporário exclusivo. O formulário já identifica o responsável, permite escolher o andamento e salva a alteração no calendário da empresa e no UPLI Geral.

- O link é criado pela automação autenticada e usa o calendário hospedado no GitHub Pages.
- O endereço contém um token aleatório de 256 bits e expira três dias depois do prazo.
- O formulário público só pode gravar o status escolhido, uma observação e o horário da resposta.
- A resposta fica em uma fila do Firestore e este computador a aplica ao calendário em até um minuto.
- Se o computador estiver desligado, a resposta permanece guardada e é aplicada quando ele ligar.
- Trocar o responsável, remover o post ou marcá-lo como **Publicado** invalida o link.
- Alterar a data do post gera novas chaves de lembrete para o novo prazo.
- Posts com status **Publicado** não geram lembretes.
- Cada combinação de post e ciclo (9h ou 17h) é enviada uma única vez.
- Antes de abrir o WhatsApp, cada lote é reservado no estado compartilhado. Se o navegador travar ou a confirmação do WhatsApp ficar ambígua, o lote não é tentado novamente de forma automática; a falha fica no diagnóstico para revisão e eventual reenvio manual.
- O histórico das últimas 20 alterações feitas pelo formulário fica armazenado no próprio post.

Os horários podem ser alterados em `reminder_times` e `assignment_notice_times` no arquivo `config.json`.

## Testes manuais

O instalador cria o atalho **Testar Automacao UPLI** na Área de Trabalho deste computador. O painel oferece:

- diagnóstico completo sem enviar mensagem;
- mensagem simples para confirmar o grupo;
- relatório semanal marcado como teste;
- lembrete de uma demanda atrasada ou do dia com um link real do formulário.

Além desse painel local, administradores podem abrir **Automação** no calendário, selecionar uma demanda e usar **Enviar lembrete agora** ou **Enviar mensagem de marcação**. Ambos os envios usam o grupo específico do responsável cadastrado em **Equipe**.

Os modos que enviam ao WhatsApp exigem a confirmação `SIM`. Mensagens de teste recebem o marcador `UPLI-TEST` e não alteram os registros de envio oficial, as chaves de lembrete ou o status dos posts. O status só muda se alguém abrir o link do lembrete e confirmar o formulário.

Depois da confirmação, o painel aceita um número com DDD para receber o teste diretamente. Se o campo ficar vazio, usa o grupo configurado. O teste de lembrete também gera um link temporário real. O painel só informa sucesso quando a bolha de saída aparece como enviada, entregue ou lida; mensagens marcadas com erro pelo WhatsApp são reportadas como falha.

## Controle da automação

A automação usa os posts atuais do calendário no momento de cada envio. Não é necessário concluir ou liberar o mês. Em semanas que atravessam dois meses, o relatório inclui normalmente todos os posts de segunda-feira a domingo.

Administradores podem abrir **Automação** no calendário e usar **Pausar automação**. A pausa vale para todos os computadores e bloqueia relatórios, lembretes, avisos de atribuição e pedidos manuais. O heartbeat e a sincronização das respostas já recebidas continuam ativos. Ao retomar, os lembretes automáticos voltam no próximo ciclo agendado, sem reabrir o ciclo interrompido no mesmo dia.

Enquanto estiver pausada, a tela mostra quantos computadores ativos estão na **Versão segura**. A retomada fica bloqueada até todos os computadores ativos terem sido atualizados com o instalador atual.

## Primeira configuração

1. Execute `install.ps1` com o PowerShell.
2. Informe o nome exato do grupo.
3. Na janela do Chrome aberta pelo assistente, conecte a conta do calendário.
4. Abra o WhatsApp Web e leia o QR Code.
5. Durante a configuração, deixe o Chrome aberto e volte ao assistente para validar. Depois da validação, a janela é ocultada automaticamente e a aba do WhatsApp continua carregada em segundo plano.

O instalador cria estas tarefas no Agendador do Windows:

- `Calendario UPLI - Relatorio Semanal`: segunda-feira às 9h.
- `Calendario UPLI - Lembretes Diarios`: todos os dias às 9h e às 17h.
- `Calendario UPLI - Sincronizar Respostas`: verifica a fila a cada minuto.
- `Calendario UPLI - Verificacao ao Entrar`: sempre que o usuário entrar no Windows.

O verificador confere internet, Chrome, sessões do calendário e WhatsApp e todos os agendamentos. Se o computador estava desligado no horário, ele sincroniza as respostas guardadas e tenta recuperar o envio quando o usuário entrar. Os marcadores semanais e individuais impedem duplicidade; antes de enviar, a automação também verifica na conversa se o mesmo lote já foi submetido.

## Arquivos de diagnóstico

- `runtime/status.html`: painel de situação, acessível pelo botão **Automação** no calendário.
- `runtime/automation.log`: histórico técnico.
- `runtime/last-report.txt`: último relatório gerado.
- `runtime/last-reminders.txt`: última mensagem de lembretes gerada.
- `runtime/last-assignment-notices.txt`: último lote de novas marcações gerado.
- `runtime/last-test.txt`: última mensagem de teste gerada.
- `runtime/last-error.png`: captura da tela quando um envio falha.
- `runtime/last-whatsapp-delivery.json`: resultado da última tentativa de envio, usado pelo diagnóstico para distinguir sessão conectada de envio confirmado.
- `runtime/browser-host.json`: porta, processo e perfil do Chrome persistente mantido em segundo plano.
- `runtime/weekly-deliveries.json`: reservas locais de relatórios semanais, gravadas antes do envio e compartilhadas no heartbeat.
- `test_free_form.py`: teste sintético do formulário, das regras e da fila; não altera demandas reais.

Execute `setup.ps1` para trocar o grupo ou reconectar as contas. Para remover a automação deste computador, use `DESINSTALAR-AUTOMACAO-UPLI.bat` na raiz do pacote ou o atalho **Desinstalar Automacao UPLI** criado na Área de Trabalho. O desinstalador exige a confirmação `DESINSTALAR`, remove tarefas, atalhos, sessão e registros locais, mas preserva o calendário online, os posts, o Chrome e o Python. Para remover somente as tarefas e preservar os dados locais, execute `uninstall.ps1 -KeepLocalData`.

Para atualizar uma instalação existente na pasta padrão, extraia o pacote atualizado e execute `ATUALIZAR-AUTOMACAO-UPLI.bat`. O atualizador interrompe e remove as tarefas, atalhos e arquivos da versão anterior antes de instalar a nova. Configurações, sessões e histórico local são guardados temporariamente e restaurados após a reinstalação. O envio prefere o botão **Enviar**, e mensagens sem confirmação ficam como falha no diagnóstico, com captura da conversa no momento da falha. O diagnóstico sem envio verifica a conexão e a última tentativa registrada; ele não comprova uma nova entrega.

A partir da versão 8, o Chrome e a aba do WhatsApp ficam ativos entre execuções. Somente a aba temporária usada para consultar o calendário é fechada. Uma falha de envio interrompe o restante do lote; mensagens ainda não submetidas permanecem pendentes. Para usar o comportamento anterior, configure `keep_whatsapp_open` como `false` em `config.json`.

A versão 9 abre o WhatsApp diretamente ao concluir a instalação ou atualização e exibe qualquer falha de abertura no assistente. O atalho **Abrir WhatsApp da Automação** permite abrir essa janela sem enviar mensagens nem consultar os posts do calendário.

A versão 11 mantém a reserva segura do relatório semanal e adiciona ciclos independentes para lembretes e marcações agrupadas.

A versão atual mantém o WhatsApp carregado em um Chrome persistente no modo headless, sem criar janela no desktop. O Chrome não reduz os temporizadores da aba em segundo plano, e a automação tenta uma recarga controlada quando o WhatsApp não termina de carregar. O atalho **Abrir WhatsApp da Automação** troca temporariamente para uma instância visível para manutenção ou leitura do QR Code; ao finalizar, ela é encerrada e a mesma sessão volta ao modo headless.

A versão 13 transforma toda atualização em uma reinstalação limpa. A versão anterior é removida, mas a sessão do WhatsApp, o login do calendário, as configurações e o histórico são preservados e restaurados automaticamente. O painel exige a versão 13.

## Limitação

Esta integração controla o WhatsApp Web sem usar a API oficial. Mudanças na interface do WhatsApp podem exigir manutenção, e automação não oficial pode sofrer restrições da plataforma. Para reduzir o risco, o agente envia somente o relatório semanal, os lembretes previstos e os lotes de marcações; ele não tenta ler conversas.
