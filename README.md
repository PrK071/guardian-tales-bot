# Guardian Tales Bot — MSI App Player

Bot local experimental para Windows, com painel, controles contínuos, planejamento por segmentos e memória SQLite. O projeto está em desenvolvimento: **não é um solucionador validado de todo o modo história**.

## Estado deste snapshot

- Arquitetura V1/V2 preservada; controlador V3 integrado à mesma fila e memória.
- Movimento/ataque mantidos pelo protocolo scrcpy, com cancelamento e liberação dos controles.
- Ganho medido de **2,56×** em uma rota conhecida de 80 pixels de referência, três repetições por modo. Não representa aceleração de toda a história.
- Dois pares de combates comparáveis não demonstraram ganho consistente de tempo. Falhas de preparação e de percepção estão registradas.
- Quatro entradas da Passagem 1 tiveram conclusão confirmada após calibrações e retomadas, com duas capturas independentes. O ensaio integral com todas as alterações mais recentes ainda está pendente.
- Compilador de walkthrough executável específico da Passagem 1 normal; outros mundos não têm conclusão automática validada.

Detalhes e limitações: [relatório V3](docs/V3_GAMEPLAY_ACCELERATION.md). O documento [LEIA-ME.md](LEIA-ME.md) descreve a base original; o relatório V3 tem o estado mais recente.

## Arquivos completos e reprodução

O Git contém código, testes, documentação, guias, assets de visão, rotas, manifestos e resumos de avaliação. Os arquivos volumosos ficam nos anexos da [release de snapshot](https://github.com/PrK071/guardian-tales-bot/releases/tag/snapshot-2026-11-09):

- `guardian-tales-evidence-2026-11-09.zip`: banco SQLite, capturas, dados dos ensaios, logs e backups.
- `guardian-tales-runtime-2026-11-09.zip`: Python portátil, dependências, ferramentas e pesos locais já instalados, com seus manifestos/licenças.

Extraia ambos na raiz do checkout, preferencialmente `E:\GuardianTalesBot`, preservando as pastas. Os testes de replay e os controladores usam evidências históricas desse conjunto. A instalação do MSI Player e os dados Android existentes não estão incluídos.

Quando houver um anexo `guardian-tales-evidence-delta-*.zip`, extraia-o depois do arquivo de evidências base, sobrepondo os arquivos. Ele inclui uma cópia consistente do SQLite e os dados novos ou modificados; não propaga exclusões. O corpo da release informa o commit e o SHA256 de cada atualização.

1. Abra Guardian Tales no MSI Player e habilite ADB.
2. Ajuste `config.json` se o serial ou os controles forem diferentes.
3. Execute `Iniciar.cmd` para abrir o painel local.
4. V3 exige a Passagem 1 identificada e pausada antes de executar o plano.

Os testes de jogo foram feitos no ambiente autorizado informado pelo usuário. O botão Parar e os arquivos STOP são respeitados. Telas desconhecidas, compras e reviver interrompem a execução.

## Verificação

Com o runtime e as evidências restaurados:

```powershell
tools/python/python.exe -X utf8 evaluations/v3/run_tests.py
tools/python/python.exe -X utf8 evaluations/v2/test_scenarios.py
tools/python/python.exe -X utf8 evaluations/run_tests.py
```

Essas suítes cobrem contratos, simuladores e capturas registradas; não substituem validação no jogo. Os resultados reais e as versões dos arquivos ficam nos reports dos ensaios.
