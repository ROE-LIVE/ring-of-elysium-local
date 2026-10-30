# ROE local — tudo o que o servidor e o launcher fazem

Servidor caseiro e **não oficial** para jogar o **Ring of Elysium (build 2022, 0.2.989.0)** depois do fim dos servidores oficiais. Ele roda no seu PC, sozinho ou numa sala para a rede local, e usa o jogo da Steam **sem alterar nenhum arquivo do jogo**.

> **Download:** [instalador para Windows](https://github.com/streamnestapp/ring-of-elysium-local/releases/latest) (~37 MB).
>
> **Antes de baixar**
> - O jogo **não vem** no pacote. Cada PC precisa do cliente completo da versão 2022, com o `Europa_Client.exe` de SHA-256 `2dca9b1e…6ba18`. Outras versões não conectam, e o launcher confere o arquivo.
> - Precisa de Windows 10/11 x64.
> - É um projeto experimental, para uso pessoal em casa, fornecido "como está" (veja [RIGHTS.md](RIGHTS.md)).

Legenda:
- ✅ testado no jogo
- 🧪 implementado, ainda sem teste completo no jogo
- ⏳ ainda não funciona
- 📦 vem no **instalador** ([download em Releases](https://github.com/streamnestapp/ring-of-elysium-local/releases/latest)): o painel, os scripts de mapa (`jogar-mapa.ps1`) e os catálogos de cada mapa. O instalador não traz nenhum arquivo do jogo: ele os lê do seu Ring of Elysium durante a instalação.

---

## 1. Launcher

### Como iniciar

| Jeito | O que faz |
|---|---|
| `play.cmd` | Partida de Training em Mt. Dione, com o ciclo acelerado (~9,5 min). Pergunta a pasta do jogo só na primeira vez. |
| `run-roe-2022.cmd [opções]` | O mesmo launcher, com todas as opções da tabela abaixo. |
| `jogar-mapa.ps1 <mapa>` 📦 | Monta as opções certas para cada mapa (Mt. Dione e variantes, KillZone, Vera/Desert): loot, nascimento, zona, clima, veículos e suprimento. |
| Painel 📦 | Página no navegador (só neste PC) para configurar, iniciar e acompanhar a partida (seção 11). |
| Instalador 📦 | Escolhe se o PC é **servidor e cliente** ou **apenas cliente** (seção 12). |

### Como ele trata o seu PC

- **Não mexe no jogo:** roda direto da pasta escolhida, sem copiar, sem backup e sem alterar EXE, DLL ou arquivos de recursos ✅.
  - O endereço do servidor local vai como argumento de inicialização.
- **Instala as dependências sozinho**, na pasta `.tools` do repositório: Python e .NET 8. Não precisa de `py` no sistema.
- **Isola o jogo da internet** com regras de firewall só para a pasta escolhida (pede UAC). Os serviços do modo sozinho escutam só em localhost.
- **Uma sessão por vez**, com trava. Ao fechar, ele encerra só os próprios processos.
- **Arquivos temporários:** os de depuração que o launcher cria são apagados ao sair, e os seus são preservados.
- **Registros:** cada partida grava os seus em `runs/`.
  - `export-report.cmd` gera um relatório compacto, sem chaves nem pacotes brutos.
- **`reset.cmd`:** desfaz as regras de firewall, o cache e o build do lobby.
  - `-FreshProfile` apaga os perfis locais; `-ReinstallDependencies` baixa Python e .NET de novo.
- **`-VerifyOnly`:** confere cliente, chaves, catálogos e mapa sem abrir o jogo.

### Opções do `run-roe-2022.cmd`

| Opção | Para que serve |
|---|---|
| `-Client <pasta>` | Pasta do jogo; fica lembrada em `.tools/client-path.txt`. |
| `-Profile <nome>` | Perfil local separado: aparência e cosméticos. |
| `-PlayerName`, `-GuestName` | Seu nome e o nome padrão dos convidados (aparecem no jogo). |
| `-Mode walk\|cycle`, `-CycleScale 1..10` | Partida com o calendário de zona, suprimento e evacuação. 10 é o tempo do original (~32 min); menor é mais rápido. |
| `-Duration <s>` | Tempo máximo da sessão. |
| `-StartHour 7\|8\|15\|16`, `-TemperatureRaw` | Hora do dia e temperatura inicial. |
| `-Kit snowboard\|glider\|climb` | Equipamento de salto: snowboard, asa-delta ou gancho. |
| `-WeaponProfile citori\|m4\|ak47\|r700\|mosin\|usp45` | Arma inicial. |
| `-MapId`, `-MapAnchor`, `-MapSpawnCells` | Mapa, origem e células de nascimento. |
| `-MapZoneProfile`, `-MapZoneIndex`, `-MapZoneSeed` | Zona do mapa: fases, índice de regiões e sorteio da região final. |
| `-LootCatalog <json>` | Loot dos pontos do mapa. |
| `-NativeAirDrop`, `-AirdropTable`, `-AirdropPoints` | Suprimento com balão, conteúdo da caixa e pontos de queda. |
| `-NativeEvacuation` | Evacuação pelo helicóptero do jogo. |
| `-OriginalJeeps`, `-VehicleProfile jeep\|snowmotor` | Veículos originais e modelo do veículo de treino. |
| `-WinterDoors`, `-WinterWindows` | Portas que abrem e janelas que quebram. |
| `-ZoneDamage <0..1000>` | Dano por segundo fora da zona segura. |
| `-DeathOnZero` | Morrer ao zerar a vida (sem isso, o treino não mata). |
| `-SharedRoom`, `-SharedPvP 1..100` | Sala para vários PCs e dano entre jogadores (%). |
| `-Target none\|plain\|armored`, `-PracticeTargets 1..10`, `-TargetLOS` | Alvos de treino, com ou sem colete, e linha de visão pelo relevo. |
| `-Bots`, `-BotGroundRoute`, `-BotBehavior` | Bot experimental com rota fixa (não é a IA original). |
| `-ClimbPractice`, `-BoatPractice`, `-VehicleDamagePractice` | Cenários de treino de escalada, barco e dano em veículo. |
| `-FragDamage`, `-OwnArmorAbsorbPercent` | Dano da granada e proteção do próprio colete no treino. |
| `-LiveControl` | Comandos ao vivo durante a partida (seção 11). |
| `-ReliableUDP`, `-IdleHandoff` | Rede mais robusta (reenvio de UDP, troca de conexão ociosa). |
| `-DebugConsole`, `-DiagnosticHazard`, `-DiagnosticDeparture` | Diagnóstico. |
| `-RemotePeer <user@ip>` | Cliente Windows com o servidor numa máquina Linux da rede, via SSH. |
| `-VerifyOnly` | Só confere tudo, sem abrir o jogo. |

## 2. Lobby

- Login local com o handshake fixo do emulador (os arquivos `private/`). Não usa conta Steam nem os servidores oficiais ✅.
- Personagem e aparência:
  - o perfil do personagem é criado e a aparência fica salva por perfil local ✅;
  - na sala, cada conta tem a sua aparência ✅.
- Nome do jogador no lobby e na partida ✅.
- Fila de **Training** e **Start Matchmaking** levando para a partida local ✅.
- Tela de escolha do ponto de salto, com cronômetro e mapa de células. Na sala, cada jogador fica com uma célula ✅.

## 3. Mapas

| Mapa | Situação |
|---|---|
| **Mt. Dione (Iceland, 16010)** | ✅ |
| Variantes no mesmo terreno: 16008, 16015 Sniper Assassin, 16016, 16030 | ✅ |
| **KillZone (16007)**, com índice de regiões, zona e relevo próprios | ✅ |
| **Vera / Desert (16021)** | ✅ experimental |

- **Loot** dos pontos originais de cada mapa 📦.
- **Nascimento** na altura real do terreno, para não cair pelo mapa. O sorteio evita a água ✅.

## 4. Partida

- **Zona segura que fecha** em fases, com dano fora da zona e o visual de área de risco ✅.
  - O visual some ao voltar, a pé, de asa-delta ou de carro ✅.
- **Clima sorteado como no original**, pelas tabelas EnvrMapWeatherTable e EnvrClimateTable: clima do mapa → grupo → sequência de tempos (sol, chuva, neblina, neve, cinzas…).
  - Clima inicial ✅; troca durante a partida 🧪.
  - As cinzas do vulcão no KillZone vêm do clima ✅.
- **Suprimento (airdrop):** balão que desce num ponto aberto sorteado e solta a caixa no chão ✅.
  - A caixa traz o loot de suprimento do original: arma, munição, colete e capacete nível 4, caixa médica.
- **Evacuação:** helicóptero de resgate com 4 lugares ✅.
  - Ele sai 60 s após o primeiro embarque.
  - No fim vem o jornal: resgatado ou não resgatado, com abates e distância.
- **HUD:** contagem de vivos, de abates e o aviso de abate para a sala ✅.
- **Dano de queda** pela velocidade vertical (curva calibrada por vídeo do original) ✅.
- **Água:** nadar, oxigênio debaixo d'água e afogamento ✅.
- **Portas e janelas:** abrir e quebrar ✅.

## 5. Equipamento de salto

| Kit | Situação |
|---|---|
| Asa-delta (planador), com jato e recarga de 60 s | ✅ |
| Snowboard / esqui | ✅ |
| Gancho (escalada), com recarga de 10 s | ✅ |
| Mochilas de Vera/Europa: asa da ilha, BMX, gancho, moto | ✅ |

## 6. Táticos

| Tático | Situação |
|---|---|
| Deployable Shield (barricada), que some após 30 s | ✅ |
| Biosignal Detector (scanner), com aviso para o detectado | ✅ |
| Vehicle modification (kit de modificação de veículo) | ✅ |
| Holographic Decoy (holograma) | 🧪 os outros jogadores ainda não o veem |
| Stealth Cloak (capa de invisibilidade) | 🧪 a energia da capa não é simulada |
| Medgun (curar a si mesmo) | 🧪 |
| Recon Drone, DPV | ⏳ |

O contador de usos e a recarga aparecem no HUD ✅.

## 7. Veículos

- **Modelos originais** de cada mapa (Jeep, Fiat, SnowMotor, barco…), nos pontos originais ✅.
- **Vários ocupantes**, com troca de banco, inclusive no multijogador ✅.
- **Kit de modificação:** o veículo sobe de nível e ganha mais vida ✅.
  - Função especial no **Shift**: radar no Jeep e invisibilidade no Fiat, com tempo e recarga da tabela 🧪.
- **Dano em veículo** (cenário de treino).

## 8. Combate e itens

- **Armas:** o dano vem da tabela do jogo, com queda por distância, tiro na cabeça, menos dano em braços e pernas, e alcance de cada arma ✅.
- **Proteção:** capacete e colete protegem pela tabela, por parte do corpo ✅.
- **Mira e tiro:** três slots de arma, acessórios, recarga e retorno de acerto (som de corpo, cabeça e abate) ✅.
- **Munição e cura:** todos os calibres, bandagens e kits médicos ✅.
- **Morte:** fica a mochila do morto com o loot; o corpo some para os outros após 30 s ✅.
- **Alvos de treino** (até 10), com vida, colete e mochila própria ✅.
- **Granada** com dano configurável.

## 9. Multijogador na rede local (experimental)

- **Sala para até 60 jogadores** (o host e 59 convidados), como as partidas originais. Testado com 2 PCs ✅.
- **Os outros PCs acham o servidor sozinhos** na rede (busca automática), sem digitar IP ✅.
- **Nomes:** cada jogador tem o seu. Ele aparece em cima do boneco, na mochila do morto, na lista de sobreviventes e no aviso de abate ✅.
- **Os outros jogadores se mexem de forma suave** ✅:
  - correr, pular, mirar e atirar;
  - recarregar e curar;
  - nadar e voar de asa-delta;
  - BMX e snowboard.
- **Mundo compartilhado:** a sala divide o mesmo estado ✅.
  - O loot do chão é comum: quem pega some para todos.
  - Portas e janelas.
  - Suprimento, veículos e zona.
- **PvP opcional**, com dano entre jogadores de 1 a 100 % ✅.
- **Evacuação conjunta:** o helicóptero sai com quem embarcou e a partida termina para todos ✅.
- **Partidas separadas:** quem entra com a partida em andamento abre outra partida.
- **Host não derruba a sala:** se o jogo do host fechar, os serviços continuam e os convidados seguem até o fim.

## 10. Rede

- **Relé para a rede local:** TCP 28001, UDP 28002, e UDP 28003 para a busca automática 📦. Aceita só IPs da rede local, ou uma lista de IPs.
- **Reenvio de UDP e troca de conexão ociosa**, opcionais, para redes instáveis.
- **Servidor Linux:** o servidor pode rodar numa máquina Linux da rede, com o cliente no Windows (`-RemotePeer`).

## 11. Painel e comandos ao vivo

- **Comandos ao vivo** (`-LiveControl`), em todos os modos ✅:
  - teleporte;
  - dar munição e curar;
  - mandar um suprimento (um voo completo num ponto escolhido);
  - observar outro jogador;
  - expulsar e banir (a lista de banidos fica em `runtime/banidos.json`).
- **Painel no navegador** 📦:
  - escolher mapa, variante, modo, PvP, dano da zona e duração;
  - iniciar e parar a partida;
  - ver jogadores com vida e posição no mapa do jogo, e os eventos da partida;
  - teleportar clicando no mapa e mandar os comandos acima com um clique.

## 12. Instalador 📦

[Baixar a versão mais recente](https://github.com/streamnestapp/ring-of-elysium-local/releases/latest).


- Duas opções:
  - **servidor e cliente:** o PC abre as partidas e também joga;
  - **apenas cliente:** o PC só entra na sala de outro PC.
- Acha a pasta do jogo na Steam, inclusive em outras bibliotecas e discos, e confere a versão do executável.
- Já traz Python e o runtime do .NET 8 (~37 MB no total) e não precisa de internet.
- **Não traz nenhum arquivo do jogo.** Na opção servidor ele lê do seu Ring of Elysium, sem alterar nada, 13 arquivos e confere cada um pelo SHA-256:
  - tabelas e pontos de respawn;
  - relevo de Mt. Dione, KillZone e Vera;
  - índices de região;
  - imagens dos mapas.
  Se algum faltar depois, a próxima partida extrai de novo.
- Pede o nome do jogador e pode liberar as portas da sala no firewall, só para a rede local. A desinstalação remove essas regras.

## 13. O que ainda não existe

- **IA dos inimigos:** o bot opcional segue uma rota fixa, e os alvos de treino são parados.
- **Servidor pela internet:** a sala é só para a rede local.
- **Táticos e veículos:** faltam Recon Drone, DPV e as outras funções de veículo modificado além do radar e da invisibilidade.
- **Balanceamento:** a distribuição de loot não é idêntica ao original em todos os mapas.
- **Progressão:** não há loja, passe nem progressão online.

## Avisos

- **Não oficial**, sem ligação com a Tencent/Aurora Studio. Os nomes do jogo pertencem aos donos.
- Não altera o jogo nem desativa antivírus ou proteções do Windows.
- Uso pessoal e doméstico, por sua conta e risco, sem garantias ([RIGHTS.md](RIGHTS.md), [README.md](README.md)).
