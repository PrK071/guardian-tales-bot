# Guardian Tales — piloto local para MSI App Player

**Estado: protótipo parcial. Não conclui todo o modo história.**

## Atualização 0.2 — agente hierárquico persistente

A execução por rotas continua disponível. O painel agora inclui **Agente hierárquico**, com **Só observar** e **Executar / retomar**. Esse modo usa planejamento estratégico, decomposição de tarefas, controle tático, memória SQLite, pesquisa HTTP e verificação explícita dos resultados. Leia `docs/ARQUITETURA-COGNITIVA.md` e `docs/ACEITACAO.md` para os contratos, evidências e limites.

O planejamento combina regras verificáveis e o modelo textual local Qwen3-0.6B (Q8), executado pelo llama.cpp em processo curto, com duas threads. O modelo não recebe autoridade para inventar rotas ou ignorar pré-condições. Houve um erro real no primeiro teste de modelo; as possibilidades de resposta agora são limitadas às opções sustentadas pelo contexto. A evidência está em `evaluations/real-model*.json`. Nenhuma capacidade de VLM ou análise de vídeo é presumida.

A memória fica em `data/cognitive.sqlite`; a trilha de decisões em `logs/cognitive.jsonl`. Um comando interrompido pode ter produzido efeito: a retomada observa o jogo novamente e reconcilia o resultado antes de continuar. `Executar / retomar` usa até 8 ciclos e 180 segundos por chamada; o objetivo permanece salvo para a próxima execução.

Todos os arquivos novos deste projeto, capturas, ferramentas e modelos ficam em `E:\GuardianTalesBot`. A instalação existente do MSI Player e os dados Android já instalados não foram movidos.

## Abrir e parar

1. Abra Guardian Tales no MSI App Player e mantenha o jogo em primeiro plano dentro do Android.
2. O Android Debug Bridge (ADB) do emulador precisa estar ativado. Foi ativado pelo usuário durante a configuração.
3. Execute `Iniciar.cmd`. O painel abre em `http://127.0.0.1:8765`. Se já estiver aberto, o iniciador reaproveita o servidor.
4. O botão **Parar**, ou Esc com foco no painel, interrompe a execução. Um toque/arrasto já enviado não pode ser desfeito e pode levar até 1,5 segundo para soltar.
5. **Encerrar servidor** encerra o processo local. O bot não cria tarefa agendada nem inicia junto com o Windows.

O painel escuta somente no próprio computador. A execução usa captura Android, reconhecimento de texto local e comandos ADB. Não exige chave de API nem envia capturas a um provedor de IA.

## O que está implementado

- Imagem do Android e identificação de telas por OCR e características visuais.
- Movimento, ataque, interação e habilidade a partir do painel.
- Combate curto experimental: procura barras de inimigos, aproxima e ataca. Não resolve chefes ou esquiva de projéteis.
- Gravação dos comandos feitos no painel com checkpoints visuais.
- Reprodução de rotas JSON com verificação visual antes das ações registradas.
- Pausa em telas desconhecidas, divergência de checkpoint, loja e reviver.
- Biblioteca com referências do Mundo 1 e índice de busca para outros mundos. Há links de YouTube, Reddit, fórum e suporte oficial. O fórum localizado retornou 403; seu conteúdo não foi importado.

## Cobertura real

A única rota incluída é `mundo1_passagem1_inicio`, um trecho de aproximação que começa no nascimento da Passagem 1 e termina antes do encontro seguinte. Ela não conclui a fase. O estado da reprodução mais recente está em `logs/validation.json` e no histórico do painel.

Movimento e interação foram calibrados no jogo real. Também foi executado um ciclo de ataques no primeiro encontro. Durante a exploração manual do corredor de armadilhas, o personagem morreu; o detector reconheceu reviver e bloqueou comandos. Nenhuma gema foi gasta na ressurreição. O teste foi reiniciado pelo botão Início.

**Não há solucionador universal de puzzles, navegação de todos os mapas, treino de modelo a partir de vídeos nem rotas completas dos mundos.** Os guias são informações de referência. Um link de vídeo não faz o programa saber reproduzir o caminho. Para ampliar, é necessário programar/testar os checkpoints e os estados de cada puzzle e encontro.

## Gravar uma rota

Use um nome novo, por exemplo `mundo1_passagem1_parte2`, e pressione Gravar. Envie movimentos e ações pelo painel e pressione Salvar. Cada ação recebe uma imagem do estado anterior. Na reprodução, o piloto pausa quando a imagem diverge da referência. Movimentos gravados não se adaptam a mudanças de mapa ou NPCs.

O checkpoint padrão compara uma região central da imagem. Não serve como prova matemática de localização: corredores semelhantes e animações podem produzir coincidências ou rejeições. Revise a rota observando o jogo e só a considere validada após reprodução completa. O tempo máximo por rota é de dez minutos.

Não deixe um personagem parado junto a armadilhas enquanto estiver usando o editor. O jogo continua rodando quando apenas o bot está parado; use a pausa do próprio jogo para interromper perigos.

## Arquivos

- `bot.py`, `panel.html`: execução e painel.
- `config.json`: pacote Android, serial e posições dos controles, normalizadas para a imagem.
- `routes/`: rotas e checkpoints de imagem.
- `knowledge/worlds.json`: resumos e fontes; indica explicitamente o que não foi testado.
- `knowledge/FONTES.md`: procedência da pesquisa.
- `captures/`, `logs/`: evidências e diagnósticos.
- `tools/python/`: Python portátil e dependências de visão.
- `tools/platform-tools/`: ADB oficial do Google.
- `pilot.py`, `client.py`: utilitários usados na calibração e no teste do painel.
- `test_bot.py`: testes de bloqueios e reconhecimento visual.

## Testes

Execute `tools\python\python.exe -X utf8 test_bot.py` para verificar os testes locais. Os testes não movimentam o personagem. Eles cobrem bloqueio após parada, loja, tela desconhecida, combate fora de fase, texto ambíguo, divergência de checkpoint, limites de acesso aos arquivos e reconhecimento de HUD/barras.

O painel foi verificado em navegador de desktop e em uma janela de 390 px: sem erros JavaScript e sem transbordamento horizontal. Essa verificação não prova que uma fase foi concluída.

As coordenadas foram calibradas na imagem Android de 1600 × 900. A captura funciona sem trazer a janela Windows à frente. Alterações no esquema de controles, proporção, resolução ou conta podem exigir nova calibração. O serial padrão é `127.0.0.1:5555`; instâncias diferentes podem exigir alterar `config.json`.

Os binários de Python e ADB vieram das distribuições oficiais. As bibliotecas de visão foram instaladas pelo PyPI e seus modelos ficam dentro da pasta portátil. As licenças estão nos diretórios dos componentes.
