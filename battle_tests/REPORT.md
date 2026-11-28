# Mode combat : rapport de test

Deuxième passe, le 28 novembre 2026, sur `extra/battle/battle_app` après correction des 24 bugs de la première
(`sessions.py` branché, plus les deux retouches qui ont suivi, voir section 4). Toujours sans Discord : le vrai cog, piloté par de fausses
interactions, sur la base `battle_test`. Aucun fichier modifié hors de `battle_tests/`.

## 1. Bilan

| | |
|---|---|
| Tests | **513** |
| Passent | **513** |
| Échouent | **0** |
| Bugs de la première passe | 24, **tous corrigés et vérifiés** (un test de non-régression chacun, voir section 3) |
| Nouveau bug trouvé dans le code corrigé | aucun |

Rejouer tout (3 min 30) :

```
bash battle_tests/run_all.sh
```

Rejouer une partie : `bash battle_tests/run_all.sh t04 t07`. La sortie complète de chaque fichier reste dans
`battle_tests/out/<fichier>.txt`. Les tests écrits pour un bug gardent son étiquette : si le bug revient, la
ligne `FAIL` la porte, par exemple `[B06]`.

| Fichier | Tests | Sujet |
|---|---|---|
| `test_loadout.py`, `test_capacity.py` | 52 | règles pures (tenus par la session principale) |
| `t00_django` (dans `run_all.sh`) | 3 | `manage.py check`, migrations à jour, chargeur d'équipement à blanc |
| `t01_proposal_deck.py` | 74 | `/battle start`, `/battle leave`, `/battle add`, `/battle remove`, cartes perdues |
| `t02_equipment.py` | 53 | `/battle equip`, `/battle unequip`, les trois couches |
| `t03_start.py` | 47 | Ready, séquestre de la mise, clics simultanés |
| `t04_turns.py` | 93 | actions, esquive, soin, Capacity, objets, mort, fin |
| `t05_multipliers.py` | 56 | paliers, paires, liens de groupe, résistances |
| `t06_end.py` | 65 | paiement, gains, `BattleRecord`, événements, forfait, horloge, classement |
| `t07_robustness.py` | 65 | redémarrage, rechargement, clics simultanés, menus, messages supprimés, jeton de 15 minutes |
| `t08_balance.py` | 5 | simulation d'équilibrage |

### Style

`ruff check battle_tests` et `ruff format --check battle_tests` passent tous les deux (ruff 0.14.1, la version
du projet, installé sur ce PC seulement, à la demande de l'utilisateur ; rien n'a été ajouté à l'image).

### Le barème de rareté a changé entre les deux passes

À la demande de l'utilisateur, l'écart de dégâts lié à la rareté passe de 30 % à 10 % au plus : 0.9 / 0.925 /
0.95 / 0.975 / 1.0, au lieu de 0.7 à 1.0. Les bornes des paliers et le bonus de critique à 0 ne bougent pas.
Tous les chiffres de ce rapport, équilibrage compris, sont ceux du nouveau barème ; `t05` vérifie les cinq
valeurs en base et que rien ne descend sous 0.9.

## 2. Ce qui est couvert

**Proposition.** Refus contre soi-même et contre un bot, mise impayable, taille de deck négative ou au-delà de
10. Joueur déjà engagé refusé des deux côtés. Un joueur seulement invité peut lancer son propre combat, ce qui
ferme l'invitation (message barré, boutons arrêtés) ; dès qu'il a ajouté une carte, il est engagé. Un plan
intouché depuis 31 minutes ne bloque plus un nouveau combat et se ferme avec un mot sur son message.
`/battle leave` : annule un plan, abandonne un combat, répond « You aren't in a battle right now. » sinon.

**Deck.** Seuls les personnages actifs entrent, messages vérifiés mot pour mot (arme, fruit, bateau, trésor sans
rôle, `Vinsmoke Sora` désactivé). Deck plein, même exemplaire deux fois, carte d'un autre, modification après
« prêt ». Une carte donnée, un objet donné ou une carte supprimée après `/battle add` sont retirés au Ready,
chez soi comme chez l'adversaire, et le porteur d'un objet perdu retrouve ses stats.

**Équipement (53).** Emplacements, remplacement, objet déjà porté, objet désactivé, gel après « prêt ».
Pourcentages demandés (Luffy + Gomu Gomu 200, + Wado Ichimonji 30 ; Zoro + Wado 200, + Yoru 130 ; Kaido +
Hassaikai 200 ; Sanji + une arme 25) et 1 684 paires comparées à une relecture indépendante de la table. Stats
avant, pendant et après, bonus de set compris.

**Démarrage.** Séquestre une fois chez chacun, inscrit `battle_wager_hold`. Mise impayable par l'un ou par
l'autre : personne n'est débité, les deux redeviennent non prêts, le ✅ disparaît. Deck vide refusé au Ready.
Deux Ready simultanés, Ready recliqué pendant celui de l'autre (latence simulée de 100 ms), Ready et
`/battle add` au même moment : un seul combat, un seul tableau, un seul prélèvement.

**Tours.** Attaque aux deux bouts de la fourchette, critique réussi et raté, esquive, soin borné et compté par
carte, boutons Heal et Capacity grisés une fois épuisés, attaque de repli réelle pour un clic déjà parti.
Capacity par défaut et les trois effets de `Buff`, esquive d'une Capacity offensive, jamais d'une Capacity de
soin. Les trois objets de boutique ; un objet de soin refusé sans être consommé quand la carte n'a plus de soin.

**Multiplicateurs (56).** Cinq paliers et leurs bornes, Akainu → Ace 1.3 à sens unique, Straw Hats 0.75, paire
avant lien de groupe, miroir neutre, Boa → Luffy 0.1. Les 12 paires et les 1 018 paires couvertes par un lien.
Gomu Gomu contre Goro Goro + Hassaikai tenu à 0.25, phénix contre une arme 0.5, plafond. « (lore advantage!) »
seulement quand c'est la relation qui avantage, plus quand seul l'équipement joue.

**Fin.** Pot et récompense payés une fois sous `battle_payout`, un seul `BattleRecord`, événements avec le bon
`lost_count`. Anti-abus inchangé et revérifié. Forfait permis aux deux joueurs à tout moment, `lost_count` d'au
moins 1 pour les deux et pour les deux événements. Horloge du cog : un tour non joué part en attaque, le combat
laissé seul se termine et se règle. Classement : ordre, V–D, page 2 propre, retour en page 1 sans doublon.

**Robustesse.** État JSON relu à l'identique, carte d'avant l'équipement relue et jouée. `setup()` réel dans
ses deux cas : au démarrage du processus tout ce qui est ouvert est fermé et remboursé (`battle_wager_refund`) ;
au rechargement du package un long combat en cours continue, son horloge repart sur le nouveau cog et un clic
sur l'ancien tableau joue le tour. Deux actions sur un tour, coup fatal en double, clic au moment où l'horloge
tombe : une seule action. Menu d'objets utilisé hors de son tour : refusé, objet gardé. Tableau supprimé : le
combat continue sur un nouveau message, par clic comme par l'horloge ; sans aucun endroit où poster, il est
annulé et remboursé. Quinze minutes après le début (jeton d'interaction expiré), l'horloge édite toujours le
tableau en place.

## 3. Les 24 bugs de la première passe : corrigés

| | Ce que c'était | Ce qui le garde maintenant |
|---|---|---|
| **B01** | le menu d'objets jouait le tour de l'adversaire | `t07` « an item picked during the opponent's turn… », `t04` « one that was already on its way… » |
| **B02** | combat bloqué, mise séquestrée après un redémarrage | `t07` « after a restart the running battle is closed… » |
| **B03** | cartes et « prêt » perdus par écritures simultanées | `t01` « both players adding at once », `t03` « both pressing Ready… » |
| **B04** | tableau supprimé = combat bloqué | `t07` « a deleted board: the battle goes on… » |
| **B05** | Ready avec un deck vide = impasse | `t03` « Ready with an empty deck is refused on the spot » |
| **B06** | « attacks instead » n'attaquait pas | `t04` « "attacks instead" is a real attack » |
| **B07** | double Ready = double séquestre, deux tableaux | `t03` « the wager was taken ONCE from each » |
| **B08** | `Buff.save()` plantait | `t04` « a Buff row can be saved » |
| **B09** | `updated_at` figé, rechargement qui annulait un combat en cours | `t07` « a long battle still being played is not cancelled by a reload » |
| **B10** | une proposition verrouillait l'invité | `t01` « a player who was only INVITED can start a battle of their own » |
| **B11** | deux `/battle start` simultanés = deux sessions | `t01` « two /battle start at once… » |
| **B12** | aucune commande pour sortir d'un combat | `t01`, `t06`, `t07` « /battle leave… » |
| **B13** | carte donnée après `/battle add` qui se battait quand même | `t01` « cards that left their owner » |
| **B14** | `max_size` sans plafond | `t01` « a deck of 11 is refused » |
| **B15** | ✅ resté affiché après un refus de mise | `t03` « the proposal no longer shows anybody as ready » |
| **B16** | Capacity jamais esquivée | `t04` « a damaging Capacity is dodged like any other hit » |
| **B17** | erreur non rattrapée sur un objet épuisé | `t07` « an item that is gone: said plainly… » |
| **B18** | double achat = un objet pour deux paiements | `t07` « two purchases at once: two items, paid twice » |
| **B19** | clic sans réponse sur un combat clos | `t07` « a click on the board of a closed battle gets an answer » |
| **B20** | horloge repoussée à chaque clic, pas de forfait hors tour | `t07` « stalling », `t06` « forfeit by the player whose turn it is not… » |
| **B21** | deux actions sur un tour = double paiement, boutons fantômes | `t07` « actions landing together » |
| **B22** | classement : page 2 polluée, doublon au retour | `t06` « page 2 shows page 2 only » |
| **B23** | vue de proposition jamais libérée | `t06` « nothing of the battle is left listening… » |
| **B24** | mouvements de berries inscrits « unknown » | `t03`, `t04`, `t06`, `t07` (les quatre motifs) |

## 4. Remarques sur le code corrigé (aucun test en échec)

Deux remarques de cette passe ont été reprises aussitôt par la session principale, et sont maintenant testées :
les boutons de tour d'avant un rechargement sont arrêtés une fois le tour joué (`t07`, « ONE set of turn
buttons is listening afterwards »), et le panneau refuse une durée de tour sous 10 secondes (`t06`, « the panel
takes a turn length of 10 seconds and nothing under »). Restent :

- **Un joueur invité reste « occupé » pour les tiers** tant que l'invitation tient, au plus 30 minutes. Lui peut
  s'en libérer (`/battle start` ou `/battle leave`), un tiers ne peut pas l'inviter entre-temps.
- **Un forfait avant le premier tour paie toujours la récompense entière** (50), une fois par adversaire et par
  jour.
- **Une victoire non payée consomme toujours une des trois victoires garanties** : dans le scénario, deux ont
  payé 50, pas trois.
- **Le spécial d'un objet ne compte pas** : une arme Shiny donne autant qu'une arme simple.
- Le dump ne contient toujours ni `Buff` ni `BattleItem` : la boutique répond « empty ».

## 5. Équilibrage

Simulateur : `engine.resolve_action` avec les multiplicateurs du cog, sur des cartes construites par
`serialize_ball`, `equip_percent`, `serialize_item` et `apply_equipment`. Vérifié contre le vrai cog : mêmes
decks, même graine, même politique → même gagnant au même tour, 12 combats sur 12. Chaque chiffre porte sur
1 000 combats, les deux decks ouvrant à tour de rôle sauf mention contraire. Chiffres refaits avec le barème de
rareté de 0.9 à 1.0 et la Capacity esquivable.

Decks types, choisis par règle : dans un palier, les quatre personnages actifs dotés d'un fruit canonique les
plus proches de la médiane du palier. Politique : attaque sûre si elle suffit à tuer, sinon Capacity, sinon Crit
Gamble.

| Palier | Deck | Puissance nue | Avec leurs fruits |
|---|---|---|---|
| T1-15 | Loki, Kuzan, Barbe Noire, Kizaru | 2 592 | 11 730 |
| T16-35 | Ace, Kuma, Saturn, Sengoku | 1 438 | 7 008 |
| T36-85 | Morley, Perona, Jabra, Ivankov | 720 | 2 754 |
| T86-140 | Caribou, Shinobu, Caesar Clown, Hina | 562 | 2 802 |
| T141-180 | Streusen, Tamago, Pekoms, Machvise | 487 | 1 537 |
| T181+ | Babe, Tama, Miss Merry Christmas, Alvida | 335 | 1 205 |

(Puissance = attaque + vie de tout le deck.)

**La rareté seule.** Sans équipement, un deck bat le palier du dessous 99,9 % du temps en haut de l'échelle
(T1-15 contre T16-35, T16-35 contre T36-85). Plus bas l'écart se resserre : T36-85 bat T86-140 à 94,7 %, T86-140
bat T141-180 à 81,9 %. Le nouveau barème n'y change presque rien en haut : la médiane des stats passe de 325 à
178 entre les deux premiers paliers, et 10 % de dégâts ne pèsent pas face à cela.

**L'équipement rattrape-t-il un deck rare ? Seulement s'il est nu.**

| Deck modeste | Deck rare | Victoires du modeste | Puissances |
|---|---|---|---|
| T36-85, ses fruits | T16-35 nu | 99,7 % | 2 754 / 1 438 |
| T36-85, ses fruits | T1-15 nu | 56,6 % | 2 754 / 2 592 |
| T36-85, ses fruits + une arme | T1-15 nu | 84,5 % | 3 373 / 2 592 |
| T36-85, objets quelconques | T16-35 nu | 77,3 % | 1 665 / 1 438 |
| T36-85, objets quelconques | T1-15 nu | 1,6 % | 1 665 / 2 592 |
| T141-180, ses fruits | T36-85 nu | 100,0 % | 1 537 / 720 |
| T141-180, ses fruits | T16-35 nu | 60,1 % | 1 537 / 1 438 |
| T141-180, ses fruits | T1-15 nu | 0,6 % | 1 537 / 2 592 |
| T36-85, ses fruits | T1-15, objets quelconques | 0,0 % | 2 754 / 6 063 |
| T36-85, ses fruits | T1-15, ses fruits | 0,0 % | 2 754 / 11 730 |
| T16-35, ses fruits | T1-15, ses fruits | 2,3 % | 7 008 / 11 730 |
| T141-180, ses fruits | T36-85, objets quelconques | 36,6 % | 1 537 / 1 665 |
| T141-180, objets T1-15 à 50 % | T1-15 nu | 83,1 % | 3 286 / 2 592 |
| T141-180, objets T1-15 à 50 % | T1-15, ses fruits | 0,0 % | 3 286 / 11 730 |

Un deck modeste dans ses propres fruits remonte d'environ deux paliers face à des decks nus, et fait jeu égal
avec un T1-15 nu quand il vient de T36-85. Dès que le deck rare porte quoi que ce soit, même des objets qui ne
sont pas les siens, le modeste retombe à 0 %. L'équipement multiplie la puissance par 4,5 en T1-15 contre 3,2 en
T141-180 : il creuse l'écart au lieu de le réduire, parce que les fruits des personnages rares sont eux-mêmes
les plus forts (médiane 414/377 en T1-15 contre 146/146 en T36-85).

**Objet canonique contre objet quelconque.** Mêmes personnages, mêmes fruits, distribués à leur propriétaire
(200 %) ou au voisin (50 %) : le canonique gagne 99,7 à 100 %. N'importe quel objet contre rien : 97,6 à 100 %.
Ajouter une arme à son fruit : 61,2 % en T1-15, 80,4 à 92,8 % ailleurs.

**La puissance totale prédit le résultat.** Sur 301 confrontations de decks :

| Rapport de puissance | Victoires |
|---|---|
| 0,50 à 0,70 | 1,5 % |
| 0,70 à 0,85 | 12,6 % |
| 0,85 à 0,95 | 34,0 % |
| 0,95 à 1,05 | 49,5 % |
| 1,05 à 1,18 | 68,0 % |
| 1,18 à 1,43 | 87,1 % |
| 1,43 à 2,00 | 98,7 % |

**Déroulement d'un combat (deck contre lui-même).**

- Durée : 9 à 13 tours à quatre cartes contre quatre, pour un minimum possible de 7. Une carte tombe en un coup
  ou deux.
- Celui qui ouvre gagne 57,3 % à 64,1 % selon le palier, et **78,4 %** entre deux decks T1-15 dans leurs fruits.
  C'est toujours l'auteur de `/battle start` qui ouvre.
- Crit Gamble à chaque tour bat Attack à chaque tour 68,1 % du temps.
- Un joueur présent bat un joueur absent (l'horloge attaque pour lui) 92,9 % du temps.
- Se soigner sous 35 % de vie fait perdre : 38,5 % de victoires contre la même politique sans soin (46,1 %
  équipé). Un soin rend 25 à 45 % de la vie, un coup en retire davantage.

## 6. Ce qui n'a pas été testé

- **L'API Discord réelle.** Permissions, limites de débit, refus côté serveur (menu de plus de 25 options si la
  boutique grossit, longueurs). L'expiration du jeton d'interaction est simulée, pas vécue.
- **Les courses entre clics** sont reproduites dans une seule boucle d'événements, avec une latence simulée.
- **Un vrai redémarrage.** Simulé en rappelant le `setup()` du package avec un bot non connecté.
- **Deux processus** servant le même combat : les verrous du cog sont en mémoire, seules les transactions de
  `sessions.py` protègent entre processus, et cela n'est pas exercé.
- **L'autocomplétion** des trésors et la **liste noire** (le faux bot laisse passer tout le monde). La
  vérification du propriétaire faite par `BallInstanceTransform` est rejouée à l'identique par le harnais.
- **Les emojis** (`get_emoji` rend toujours rien ici).
- **L'admin** au-delà de `manage.py check`.
- **Le chargeur d'équipement** n'a tourné qu'à blanc (`--dry-run`).
- **Les écouteurs du bus** (succès, pass) : seul l'envoi de `BATTLE_WIN` et `BATTLE_PLAYED` est vérifié.
- **L'équilibrage avec `Buff` et objets de boutique** : les deux tables sont vides dans le dump.

## 7. Le harnais

`battle_tests/harness.py` : `django.setup()`, les caches remplis comme `BallsDexBot.load_cache`, puis de faux
objets Discord qui enregistrent ce que le cog envoie et refusent ce que Discord refuserait : répondre deux fois
à une interaction, suivre avant d'avoir répondu, éditer un message supprimé, cliquer un bouton grisé, éditer un
message de suivi quinze minutes après. Un clic passe par `View._scheduled_task` de discord.py ; les horloges de
tour sont les vraies tâches du cog.

Le hasard du moteur est remplacé par une suite de tirages écrite d'avance dans les tests de règles, et rendu au
vrai `random` avec une graine dans la simulation. Les réglages ne sont jamais modifiés en base : un test qui en
veut d'autres les surcharge pour son cog seulement.

Un seul fichier de test tourne à la fois sur la base : chacun prend un verrou PostgreSQL (`pg_advisory_lock`)
avant de commencer et attend son tour s'il est pris. Sans cela, deux sessions qui rejouent la suite en même
temps se font échouer l'une l'autre, le classement lisant tous les combats et le test de redémarrage fermant
tous les combats ouverts.

Chaque fichier possède mille identifiants Discord à partir de 9 000 000 000 000 000 000 et efface ses joueurs
avant et après (cartes, sessions, combats, registre de berries suivent en cascade). Les lignes `Buff` créées par
les tests portent une marque dans `capacity_value` (partie décimale 0,0625), les objets de boutique le préfixe
`ZZTEST ` ; les deux sont effacés avant et après.
