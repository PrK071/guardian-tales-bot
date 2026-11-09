"""Gera índice de referências. Não converte vídeos em rotas executáveis."""
import json
from pathlib import Path
from urllib.parse import quote_plus
BASE=Path(__file__).resolve().parent
def link(label,url): return {'label':label,'url':url}
def yt(query): return 'https://www.youtube.com/results?search_query='+quote_plus(query)
names=['Floresta Kanterbury','Reino Teatan','Escola de Magia','Deserto da Loucura','Cidade de Shen','Pousada','Reino das Masmorras','Monte Shivering','Império Rah','Mundo não registrado','Mundo não registrado — parte 2','Mundo Demoníaco','Cidade de Lilith','Demonshire','Saul','Laboratório','Dois Heróis','Dois Heróis — parte 2','Floresta Pixie','Montanha Motori','La Ventura','Monte Volver','Kanterbury (referência de planejamento oficial)']
worlds=[]
for number,name in enumerate(names,1):
    worlds.append({'id':number,'name':name,'execution':'Sem rota executável validada para este mundo.',
        'notes':['Índice de pesquisa por mundo. Não representa um walkthrough analisado nem uma fase concluída.','Para programar uma fase, registrar o ponto de partida, as ações e as condições visuais de saída.'],
        'links':[link('Buscar guia no YouTube',yt(f'Guardian Tales world {number} walkthrough Lx Shiriga')),link('Canal Lx Shiriga','https://www.youtube.com/@LxShiriga')]})
article='https://www.gamechosun.co.kr/webzine/article/view.php?no=166807'
blog='https://kmobilegames.blogspot.com/2021/01/guardian-tales-world-1-kanterbury.html'
worlds[0]['notes']=['Priorizar a história principal. Certas tarefas opcionais exigem voltar após mundos posteriores.']
stages=[
 ('1-1 · Pousada','exxLlr0vX0U',[
  'Estado observado nesta conta: fase principal concluída, com uma estrela.',
  'O caminho principal leva à saída após os encontros. Itens opcionais incluem tochas, lanternas e uma passagem com mapa para a Floresta Secreta.',
  'Colecionáveis de referência: 4 tesouros, 3 fragmentos e 26 moedas.'],
  [link('Vídeo com marcações','https://www.youtube.com/watch?v=mdlLM4hHM48'),link('Wiki 1-1','https://guardian-tales.fandom.com/wiki/1-1_Inn')]),
 ('1-2 · Entrada da Floresta','ag99O5RVJVM',[
  'Há um caminho opcional relacionado a uma borboleta. A missão da fada tem dependências em mundos posteriores; não é condição para seguir a história.',
  'Separar a rota da missão principal da coleta de itens para evitar retornos desnecessários.'],[link('Guia escrito do Mundo 1',blog)]),
 ('1-3 · Dentro da Floresta','JgsHRdllGHo',[
  'Os blocos passam a ter função em interruptores e obstáculos. Tratar cada bloco como parte do estado do puzzle, não como ponto fixo de clique.',
  'A missão opcional da floresta abre uma subfase; programar esse desvio separadamente.'],[link('Guia escrito do Mundo 1',blog)]),
 ('1-4 · Limite da Floresta','Ma0i03RGOXk',[
  'A habilidade de corrida entra na progressão. Alguns desafios de velocidade devem ser revisitados após obter os tênis.',
  'Programar a travessia cronometrada com conferência da porta antes e depois da corrida.'],[link('Guia escrito do Mundo 1',blog)]),
 ('1-5 · Entrada das Ruínas Antigas','jhF_X1t8yG4',[
  'O guia em vídeo separa placas, missões do ferreiro e acessos opcionais.',
  'Referência de coleta: 4 tesouros, 3 fragmentos e 30 moedas.',
  'Marcações úteis do vídeo: 0:00 primeira placa; 1:05 ferreiro; 2:00 mapa opcional; 4:19 traje; 4:40 guarda.'],[link('Vídeo com marcações','https://www.youtube.com/watch?v=1oAJRK4iFBo')]),
 ('1-6 · Profundezas das Ruínas Antigas','E5rNCYV29mk',[
  'Vídeo de referência catalogado. Navegação e puzzles ainda não transcritos nem testados nesta conta.',
  'Não executar um roteiro de outra fase neste mapa; registrar seus próprios checkpoints.'],[]),
 ('1-7 · Espada do Campeão','dGKERJo18Ms',[
  'Para a história, seguir os lenços deixados pela princesa no labirinto. Uma saída errada reinicia o trecho.',
  'A sequência ↑ ↑ ↓ ↓ ← → ← → abre o acesso opcional à masmorra desconhecida; não é a rota principal.',
  'Referência de coleta: 1 tesouro, 2 fragmentos e 25 moedas.',
  'Vídeo: 0:00 primeiro labirinto; 2:26 segundo; 2:59 portal opcional; 3:54 trio; 5:14 encontro final.'],[link('Vídeo com marcações','https://www.youtube.com/watch?v=KFFtkDJ6MDI'),link('Wiki 1-7','https://guardian-tales.fandom.com/wiki/1-7_Champion%27s_Sword')]),
 ('Decolagem da Pousada','i3nGObHPgPY',['Trecho posterior à Espada do Campeão. Referência catalogada; execução ainda não testada.'],[])
]
worlds[0]['stages']=[]
for title,video,notes,links in stages:
    worlds[0]['stages'].append({'title':title,'execution':'Referência pesquisada; sem rota completa validada.',
        'notes':notes,'links':[link('Vídeo do guia GameChosun','https://www.youtube.com/watch?v='+video),*links]})
worlds[0]['stages'].insert(1,{'title':'Passagem 1 · teste de controle','execution':'Calibração de movimento e interação efetuada nesta conta. Veja as rotas para a cobertura atual.',
    'notes':['A passagem exige derrotar os monstros. O NPC na entrada pode bloquear a passagem em linha reta; é preciso contorná-lo.','O estado e as imagens de calibração ficam em logs/calibration.jsonl e captures/.'],
    'links':[link('Artigo do Mundo 1',article)]})
worlds[15]['notes']=['Um vídeo de referência da fase 16-13 inclui um mapa de coletáveis ao final. Não foi convertido em rota.']
worlds[15]['links'].append(link('16-13 · guia Lx Shiriga','https://www.youtube.com/watch?v=2EWahA1ueD8'))
worlds[21]['notes']=['O anúncio oficial registra o Mundo 22 e uma restrição de reviver na segunda fase de seu chefe final. Ainda sem navegação ou combate validado.']
worlds[21]['links'].append(link('Atualização oficial','https://www.guardiantales.com/news/4705'))
worlds[22]['notes']=['O planejamento oficial de 2026 cita o Mundo 23. Esta entrada não confirma a versão instalada nem que o mundo esteja disponível nesta conta.']
worlds[22]['links'].append(link('Planejamento oficial 2026','https://www.guardiantales.com/news/4745?lang=en'))
sources=[
 {'kind':'youtube','url':'https://www.youtube.com/@LxShiriga','note':'Canal de guias recomendado pela comunidade; vídeos não assistidos integralmente nesta sessão.'},
 {'kind':'reddit','url':'https://www.reddit.com/r/GuardianTales/comments/1la5fvp/','note':'Discussão aponta guias por fase; serve como descoberta de fontes, não como validação de rotas.'},
 {'kind':'reddit','url':'https://www.reddit.com/r/GuardianTales/comments/1frxovg/','note':'Recomendações de criadores para iniciantes.'},
 {'kind':'forum','url':'https://forum.gamer.com.tw/G2.php?bsn=38113&sn=543','note':'Índice de vídeos localizado na busca; acesso direto retornou 403. Conteúdo não importado.'},
 {'kind':'article','url':article,'note':'Coleção de vídeos 1-1 a 1-7 e final. Links extraídos do artigo; não são comandos executáveis.'},
 {'kind':'official','url':'https://gdtsglobal.zendesk.com/hc/en-us/articles/54689657878809-Content-Unlock-Requirements','note':'Requisitos de desbloqueio, sujeitos à versão e região.'}
]
(BASE/'worlds.json').write_text(json.dumps({'researched_at':'2026-11-07','worlds':worlds,'sources':sources},ensure_ascii=False,indent=2),encoding='utf-8')
(BASE/'FONTES.md').write_text('# Fontes consultadas\n\n'+'\n\n'.join(f"- {s['kind']}: {s['url']}\n  {s['note']}" for s in sources)+'\n\nNão foram baixados vídeos completos nem copiados artigos integrais. Os resumos e a catalogação não treinam um modelo e não habilitam uma fase sem rota.\n',encoding='utf-8')
print('Biblioteca gerada: 23 entradas, com cobertura declarada por fase.')
if __name__=='__main__': pass
