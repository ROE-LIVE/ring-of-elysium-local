# ROE local — o que o servidor faz

Servidor caseiro e **não oficial** para jogar o **Ring of Elysium (build 2022, 0.2.989.0)** depois do fim dos servidores oficiais. Ele roda no seu PC, sozinho ou numa sala para a rede local, e usa o jogo da Steam **sem alterar nenhum arquivo do jogo**.

Esta é a lista do que a branch `mapas-locais` acrescenta ao launcher de Training deste repositório: mapas, multijogador na rede local, veículos, táticos, clima e painel.

> **Antes de baixar:** o jogo não vem no pacote. Cada PC precisa do Ring of Elysium da Steam na versão 2022, com o `Europa_Client.exe` 0.2.989.0 (o launcher confere). É um projeto experimental, para uso pessoal em casa, fornecido "como está".
>
> O instalador e o painel descritos abaixo ainda são distribuídos à parte. Eles usam dados extraídos do cliente do jogo, que, pelas regras deste repositório ([RIGHTS.md](RIGHTS.md)), não podem ser publicados aqui.

Legenda: ✅ testado no jogo · 🧪 implementado, ainda sem teste completo no jogo · ⏳ ainda não funciona

---

## Instalação (pacote à parte)

- Um instalador para Windows 10/11 x64 (~60 MB), com duas opções:
  - **Servidor e cliente:** o PC abre as partidas, sozinho ou como sala da rede, e também joga.
  - **Apenas cliente:** o PC só entra na sala aberta por outro PC da rede.
- Acha sozinho a pasta do jogo na Steam, inclusive em outras bibliotecas e discos, e confere a versão do executável.
- Já traz Python e o runtime do .NET 8: não precisa instalar nada além do jogo, nem de internet.
- Pode liberar as portas da sala no Firewall do Windows, só para a rede local. A desinstalação remove essas regras.

## Mapas

| Mapa | Situação |
|---|---|
| **Mt. Dione (Iceland)**, com as variantes do mesmo terreno (16008, 16015 Sniper Assassin, 16016, 16030) | ✅ |
| **KillZone** (16007): índice de regiões, zona e relevo próprios | ✅ |
| **Vera / Desert** (16021) | ✅ experimental |

Em cada mapa:
- **Loot** dos pontos originais do mapa.
- **Pontos de nascimento** na altura real do terreno (sem cair pelo mapa). O sorteio evita a água.
- **Tela de escolha do ponto de salto**, com cronômetro.

## Partida

- **Zona segura que fecha** em fases, no calendário do original (~32 min), com dano fora da zona e o visual de "área de risco" ✅.
  - A velocidade é ajustável, para testes mais rápidos.
- **Clima sorteado como no original:** clima do mapa → grupo → sequência de tempos com duração (sol, chuva, neblina, neve, cinzas de vulcão…). Troca durante a partida 🧪.
  - No KillZone as cinzas do vulcão saem pelo clima ✅.
- **Suprimento (airdrop):** balão que desce num ponto aberto sorteado e caixa com loot de suprimento do original ✅.
- **Evacuação:** helicóptero de resgate com 4 lugares, contagem de vivos e de abates no HUD, e o jornal (placar) de resgatado ou não resgatado no fim ✅.
- **Dano de queda** pela velocidade vertical (curva calibrada por vídeo do original) ✅.
- **Água:** nado, oxigênio debaixo d'água e afogamento ✅.
- **Portas e janelas:** abrir e quebrar ✅.

## Equipamento de salto (kit de mobilidade)

| Kit | Situação |
|---|---|
| Asa-delta (planador), com jato e recarga de 60 s | ✅ |
| Snowboard / esqui | ✅ |
| Gancho (escalada), com recarga | ✅ |
| BMX, moto e mochilas de Vera/Europa | ✅ |

## Táticos

| Tático | Situação |
|---|---|
| Deployable Shield (barricada) | ✅ |
| Biosignal Detector (scanner): marca e aviso ao detectado | ✅ |
| Vehicle modification (kit de modificação de veículo) | ✅ |
| Holographic Decoy (holograma) | 🧪 (os outros jogadores ainda não veem) |
| Stealth Cloak (capa de invisibilidade) | 🧪 (energia da capa não simulada) |
| Medgun (curar a si mesmo) | 🧪 |
| Recon Drone, DPV | ⏳ |

## Veículos

- **Modelos originais** de cada mapa (Jeep, Fiat, SnowMotor, barco…) nos pontos originais ✅.
- **Vários ocupantes:** motorista e passageiros, inclusive no multijogador ✅.
- **Kit de modificação:** o veículo sobe de nível, com mais vida ✅.
  - Função especial no **Shift**: radar no Jeep e invisibilidade no Fiat, com tempo e recarga da tabela 🧪.

## Combate

- **Armas com o dano da tabela do jogo:** queda por distância, tiro na cabeça, braços e pernas com dano menor, e alcance de cada arma ✅.
- **Capacete e colete** protegem pela tabela, por parte do corpo ✅.
- **Munição de todos os calibres**, recarga, bandagens e kits ✅.
- **Mochila do morto** com o loot. O corpo some após 30 s ✅.
- **Alvos de treino** (modo sozinho), com vida e colete ✅.

## Multijogador na rede local (experimental)

- **Sala para até 60 jogadores** (o host e 59 convidados), como as partidas originais. Testado com 2 PCs ✅.
- **Os outros PCs acham o servidor sozinhos** na rede. Não precisa digitar IP.
- Cada jogador tem **nome e aparência próprios**: o nome aparece em cima do boneco, na mochila do morto, na lista de sobreviventes e no aviso de abate.
- **Movimento dos outros jogadores suave**: correr, pular, mirar, atirar, recarregar, curar, nadar, voar de asa-delta, BMX e snowboard ✅.
- **Mundo compartilhado:** a sala divide o mesmo estado ✅.
  - O loot do chão é comum: quem pega some para todos.
  - Portas e janelas.
  - Suprimento, veículos e zona.
- **PvP opcional** (dano entre jogadores, de 1 a 100 %) ✅.
- **Evacuação conjunta:** o helicóptero sai com quem embarcou e a partida termina para todos ✅.

## Painel (navegador, só neste PC)

- Escolher mapa, variante, modo (sozinho ou multijogador), PvP, dano da zona e duração. Iniciar e parar a partida.
- **Acompanhar a partida:** jogadores com vida e posição, mapa com a posição de cada um, e eventos (abates, mortes, entradas).
- **Comandos ao vivo:**
  - teleportar (clicando no mapa ou até outro jogador);
  - curar e dar munição;
  - mandar um suprimento;
  - observar outro jogador;
  - expulsar e banir.

## O que ainda não existe

- **Bots / IA de inimigos:** os alvos de treino são parados.
- **Servidor pela internet:** a sala é só para a rede local.
- Recon Drone e DPV; algumas funções de veículos modificados (as que não são radar ou invisibilidade).
- O balanceamento e a distribuição de loot não são idênticos ao original em todos os mapas.

## Avisos

- **Não oficial**, sem ligação com a Tencent/Aurora Studio. Os nomes do jogo pertencem aos donos.
- O instalador **não altera o jogo** nem desativa antivírus ou proteções do Windows.
- Uso pessoal e doméstico, por sua conta e risco, sem garantias.
