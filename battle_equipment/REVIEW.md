# Équipement du mode combat — document de relecture

Ce dossier contient les données d'équipement du nouveau mode combat, produites à partir du dump du
18 novembre 2026 (560 trésors actifs). Rien n'a été exécuté en base : `weapon_groups.sql` est à lancer à la main.

| Fichier | Rôle |
|---|---|
| `weapon_groups.sql` | crée les groupes d'armes précis et range les 4 trésors sans groupe |
| `affinities.csv` | part des stats d'un objet que reçoit le personnage qui l'équipe (3 couches) |
| `resistances.csv` | multiplicateurs de dégâts subis, selon l'équipement des deux camps |
| `relations.csv` | multiplicateurs de dégâts entre deux personnages précis ou entre membres d'un même équipage |
| `validate.py` | contrôle de cohérence des quatre fichiers ci-dessus et de ce document (`python validate.py`) |

## En bref

- **7 groupes d'armes** pour 31 armes (29 du groupe `Weapons` + `Hassaikai` + `God Staff`).
- **Affinités : 433 lignes** — couche 1 (défauts) : 12 ; couche 2 (personnage + objet) : 184, dont 172 à 200 % et 12 à 150 % ; couche 3 (personnage + catégorie) : 237 lignes pour 144 personnages.
- **Résistances : 52 règles.**
- **Relations entre personnages : 14 règles** (2 sur un équipage, 12 entre deux personnages), plus 5 en attente.
- **Objets sans propriétaire : 28** (27 fruits, 1 arme).
- **Personnages : 328**, dont 83 en « défauts seulement ».
- **Doutes encore ouverts : 11**, listés en fin de document, après les 17 décisions que tu as validées le 28 novembre.

## Barème

| Pourcentage | Sens |
|---|---|
| 200 | l'objet canonique du personnage |
| 150 (couche 2) | lien réel mais indirect : réplique du pouvoir (Seraphim, fruit artificiel) ou fruit mangé par l'arme du personnage |
| 150 | maître de la catégorie, niveau mondial |
| 140 | combattant d'élite avec cette catégorie |
| 130 | pratiquant confirmé, c'est son arme de combat |
| 120 | s'en sert régulièrement |
| 110 | s'en sert à l'occasion |
| 50 | défaut : l'objet n'est pas le sien |
| 25 à 30 | ne sait pas ou refuse de s'en servir (Luffy et les épées, Sanji et Zeff, un cheval) |

Report entre lames : un sabreur noté 130 ou plus dans sa catégorie reçoit 20 points de moins dans les deux
autres catégories de lames (`Katanas`, `Western Swords`, `Cane Swords`). Mihawk a 150 partout.

## Comment lire les multiplicateurs

Un multiplicateur s'applique aux dégâts d'une attaque. ×1 ne change rien ; en dessous de 1 le coup fait moins
mal, au-dessus il fait plus mal.

| Multiplicateur | Effet sur le coup |
|---|---|
| ×0.1 | il ne fait plus que 10 % de ses dégâts |
| ×0.25 | un quart des dégâts |
| ×0.5 | la moitié des dégâts |
| ×0.75 | un quart de dégâts en moins |
| ×1.2 | 20 % de dégâts en plus |
| ×1.5 | 50 % de dégâts en plus |

- `resistances.csv` se lit du côté de celui qui **reçoit** le coup, et dépend de l'équipement. La ligne « porteur
  du Mera Mera, contre le Magu Magu, ×1.5 » veut dire : quiconque porte le Mera Mera prend 50 % de dégâts en
  plus d'un attaquant qui porte le Magu Magu. C'est la faiblesse du feu face au magma.
- `relations.csv` se lit du côté de celui qui **donne** le coup, et ne dépend que des deux personnages. La ligne
  « Boa Hancock contre Luffy, ×0.1 » veut dire : Boa ne fait que 10 % de ses dégâts à Luffy, quoi qu'elle porte.
- Les deux se multiplient. Akainu avec le Magu Magu qui frappe Ace avec le Mera Mera : 1.3 (relation) × 1.5
  (résistance) = ×1.95.

## Groupes d'armes

| Groupe | Contenu | Membres |
|---|---|---|
| `Katanas` (13) | lames japonaises : katana et nodachi | Shodai Kitetsu, Nidai Kitetsu, Sandai Kitetsu, Wado Ichimonji, Shusui, Enma, Ame No Habakiri, Yubashiri, Shigure, Kikoku, Raiu, Shirauo, Oto and Kogarashi |
| `Western Swords` (10) | sabres, coutelas, rapières et épées longues | Yoru, Ace, Eclipse, Gryphon, Cerberus (Sword), Durandal, Kaken, Napoleon, Pretzel, Warabide |
| `Cane Swords` (2) | cannes-épées (shikomizue) | Yakuza Kasen, Soul Solid |
| `Polearms` (1) | armes d'hast : naginata, bisento, lances, tridents | Murakumogiri |
| `Blunt Weapons` (2) | armes contondantes : kanabo, masses, marteaux, gourdins | Ragnir, Hassaikai |
| `Staves` (2) | bâtons et perches | Sorcery Clima Tact, God Staff |
| `Ranged Weapons` (1) | armes de jet et de tir : lance-pierre, puis armes à feu et arcs quand le dex en aura | Kabuto |

Le script range aussi `Hassaikai` et `God Staff` dans `Weapons`, et `Shimotsuki Ryuma` et `Shachi & Penguin`
dans `Characters`. `venustoken` n'est pas touché.

## Personnages (328)

Une ligne par personnage, du plus rare au plus commun. Un pourcentage entre parenthèses après un objet signale
une ligne de couche 2 qui n'est pas à 200 %. La dernière colonne reprend les résistances propres au personnage,
celles que déclenche son objet canonique, et ses relations avec d'autres personnages.

<!-- characters:start -->
| Rareté | Personnage | Fruit canonique | Arme canonique | Maîtrises (couche 3) | Résistances et relations |
|---|---|---|---|---|---|
| 1 | JoyBoy | Gomu Gomu no Mi (Gum Gum) | — | — | avec Gomu Gomu no Mi (Gum Gum) : ×0.25 contre Goro Goro no Mi (Thunder Thunder), ×0.5 contre Blunt Weapons, ×0.5 contre Staves, ×0.5 contre Ranged Weapons |
| 1 | Saint Nerona Imu | Akuma no Mi (Devil's Fruit) | — | — | — |
| 2 | Gol D. Roger | — | Ace | Katanas 130 %, Western Swords 150 %, Cane Swords 130 % | en attaque contre Edward Newgate (Whitebeard) : ×1.2<br>en défense face à Edward Newgate (Whitebeard) : ×1.2 |
| 2 | Rocks D. Xebec | — | Eclipse | Katanas 120 %, Western Swords 140 %, Cane Swords 120 % | — |
| 4 | Edward Newgate (Whitebeard) | Gura Gura no Mi (Quake Quake) | Murakumogiri | Polearms 150 % | entre membres de Whitebeard Pirates : ×0.5<br>en défense face à Gol D. Roger : ×1.2<br>en attaque contre Gol D. Roger : ×1.2 |
| 5 | Marshall D. Teach (Blackbeard) | Yami Yami no Mi (Dark Dark)<br>Gura Gura no Mi (Quake Quake) | — | Devil fruits 120 %, Ranged Weapons 110 % | avec Yami Yami no Mi (Dark Dark) : ×1.25 contre Devil fruits, ×1.25 contre Weapons |
| 5 | Monkey D. Luffy | Gomu Gomu no Mi (Gum Gum) | — | Katanas 30 %, Western Swords 30 %, Cane Swords 30 % | toujours : ×0.75 contre Doku Doku no Mi (Venom Venom), ×0.5 contre Mero Mero no Mi (Love Love)<br>avec Gomu Gomu no Mi (Gum Gum) : ×0.25 contre Goro Goro no Mi (Thunder Thunder), ×0.5 contre Blunt Weapons, ×0.5 contre Staves, ×0.5 contre Ranged Weapons<br>entre membres de Straw Hats : ×0.75<br>en défense face à Boa Hancock : ×0.1 |
| 6 | "Red-Haired" Shanks | — | Gryphon | Katanas 130 %, Western Swords 150 %, Cane Swords 130 % | en attaque contre Eustass "Captain" Kidd : ×1.2 |
| 6 | Dracule Mihawk | — | Yoru | Katanas 150 %, Western Swords 150 %, Cane Swords 150 % | — |
| 6 | Loki | Nidhöggr<br>Ratatoskr (150 %) | Ragnir | Blunt Weapons 150 % | — |
| 8 | Monkey D. Garp | — | — | défauts seulement | — |
| 8 | Sakazuki (Akainu) | Magu Magu no Mi (Magma Magma) | — | — | avec Magu Magu no Mi (Magma Magma) : ×0.5 contre Mera Mera no Mi (Fire Fire), ×1.5 contre Yami Yami no Mi (Dark Dark)<br>en attaque contre Portgas D. Ace : ×1.3 |
| 9 | Kaido | Seiryu (Azure Dragon) | Hassaikai | Blunt Weapons 150 % | — |
| 9 | King Harald | — | — | Polearms 130 % | — |
| 10 | Charlotte Linlin (Big Mom) | Soru Soru no Mi (Soul Soul) | Napoleon | Katanas 110 %, Western Swords 130 %, Cane Swords 110 % | — |
| 10 | Monkey D. Dragon | — | — | défauts seulement | — |
| 11 | Scopper Gaban | — | — | Polearms 140 % | — |
| 11 | Silvers Rayleigh | — | — | Katanas 130 %, Western Swords 150 %, Cane Swords 130 % | — |
| 13 | Borsalino (Kizaru) | Pika Pika no Mi (Light Light) | — | — | avec Pika Pika no Mi (Light Light) : ×1.5 contre Yami Yami no Mi (Dark Dark) |
| 13 | Kuzan | Hie Hie no Mi (Chilly Chilly) | — | — | avec Hie Hie no Mi (Chilly Chilly) : ×1.5 contre Yami Yami no Mi (Dark Dark) |
| 16 | Kozuki Oden | — | Enma<br>Ame No Habakiri | Katanas 150 %, Western Swords 130 %, Cane Swords 130 % | — |
| 16 | St. Figarland Shamrock | Cerberus (150 %) | Cerberus (Sword) | Katanas 120 %, Western Swords 140 %, Cane Swords 120 % | — |
| 17 | Fujitora (Issho) | Zushi Zushi no Mi (Press Press) | Yakuza Kasen | Katanas 130 %, Western Swords 130 %, Cane Swords 150 % | — |
| 17 | Greenbull (Aramaki) | Mori Mori no Mi (Forest Forest) | — | — | avec Mori Mori no Mi (Forest Forest) : ×1.5 contre Yami Yami no Mi (Dark Dark), ×1.25 contre Mera Mera no Mi (Fire Fire), ×1.25 contre Magu Magu no Mi (Magma Magma) |
| 18 | Roronoa Zoro | — | Shusui<br>Wado Ichimonji<br>Enma<br>Sandai Kitetsu<br>Yubashiri | Katanas 150 %, Western Swords 130 %, Cane Swords 130 % | entre membres de Straw Hats : ×0.75<br>en défense face à Vinsmoke Sanji : ×1.2<br>en attaque contre Vinsmoke Sanji : ×1.2 |
| 18 | Sabo | Mera Mera no Mi (Fire Fire) | — | Staves 140 % | avec Mera Mera no Mi (Fire Fire) : ×1.5 contre Magu Magu no Mi (Magma Magma), ×0.5 contre Moku Moku no Mi (Smoke Smoke), ×1.5 contre Yami Yami no Mi (Dark Dark) |
| 18 | Vinsmoke Sanji | — | — | Weapons 25 % | entre membres de Straw Hats : ×0.75<br>en attaque contre Roronoa Zoro : ×1.2<br>en défense face à Roronoa Zoro : ×1.2 |
| 19 | Eustass "Captain" Kidd | Jiki Jiki no Mi (Magnet Magnet) | — | — | avec Jiki Jiki no Mi (Magnet Magnet) : ×0.75 contre Ranged Weapons<br>en défense face à "Red-Haired" Shanks : ×1.2 |
| 19 | Marco | Tori Tori:Phoenix | — | — | avec Tori Tori:Phoenix : ×0.5 contre Weapons<br>entre membres de Whitebeard Pirates : ×0.5 |
| 19 | Trafalgar D. Water Law | Ope Ope no Mi | Kikoku | Katanas 130 %, Western Swords 110 %, Cane Swords 110 % | en défense face à Donquixote Rosinante "Corazon" : ×0.1<br>en défense face à Bepo : ×0.1<br>en attaque contre Bepo : ×0.1 |
| 20 | Sengoku | Hito Hito: Buddha | — | — | — |
| 21 | Benn Beckman | — | — | Ranged Weapons 150 % | — |
| 21 | Lucky Roux | — | — | Ranged Weapons 120 % | — |
| 22 | Portgas D. Ace | Mera Mera no Mi (Fire Fire) | — | — | avec Mera Mera no Mi (Fire Fire) : ×1.5 contre Magu Magu no Mi (Magma Magma), ×0.5 contre Moku Moku no Mi (Smoke Smoke), ×1.5 contre Yami Yami no Mi (Dark Dark)<br>entre membres de Whitebeard Pirates : ×0.5<br>en défense face à Sakazuki (Akainu) : ×1.3 |
| 22 | Yamato | Okuchi no Makami | — | Blunt Weapons 140 % | — |
| 23 | Yasopp | — | — | Ranged Weapons 150 % | — |
| 24 | Buggy the Clown | Bara Bara no Mi (Chop Chop) | — | Ranged Weapons 110 % | avec Bara Bara no Mi (Chop Chop) : ×0.25 contre Katanas, ×0.25 contre Western Swords, ×0.25 contre Cane Swords |
| 24 | Sir Crocodile | Suna Suna no Mi (Sand Sand) | — | — | avec Suna Suna no Mi (Sand Sand) : ×1.5 contre Yami Yami no Mi (Dark Dark) |
| 27 | St. Manmayer Gunko | Aro Aro no Mi (Arrow Arrow) | — | — | — |
| 27 | St. Rimoshifu Killingham | Kirin | — | — | — |
| 27 | St. Shepherd Sommers | Iba Iba no Mi (Thorn Thorn) | — | — | — |
| 29 | St. Ethanbaron V. Nusjuro | Bakotsu | Shodai Kitetsu | Katanas 140 %, Western Swords 120 %, Cane Swords 120 % | — |
| 29 | St. Figarland Garling | — | — | Katanas 120 %, Western Swords 140 %, Cane Swords 120 % | — |
| 29 | St. Jaygarcia Saturn | Gyuki | — | — | — |
| 29 | St. Marcus Mars | Itsumade | — | — | — |
| 29 | St. Shepherd Ju Peter | Sandworm | — | — | — |
| 29 | St. Topman Warcury | Fengxi | — | — | — |
| 30 | Charlotte Katakuri | Mochi Mochi no Mi | — | Polearms 140 % | — |
| 30 | King (Alber) | Pteranodon | — | Katanas 140 %, Western Swords 120 %, Cane Swords 120 % | — |
| 30 | Queen (Scien) | Brachiosaurus | — | Ranged Weapons 120 % | — |
| 31 | Shiryu | Suke Suke no Mi (Clear Clear) | Raiu | Katanas 140 %, Western Swords 120 %, Cane Swords 120 % | — |
| 31 | Van Augur | Wapu Wapu no Mi (Warp Warp) | — | Ranged Weapons 150 % | — |
| 32 | Donquixote Doflamingo | Ito Ito no Mi (String String) | — | Ranged Weapons 110 % | — |
| 32 | Enel | Goro Goro no Mi (Thunder Thunder) | God Staff | Staves 140 % | avec Goro Goro no Mi (Thunder Thunder) : ×1.5 contre Gomu Gomu no Mi (Gum Gum), ×1.5 contre Yami Yami no Mi (Dark Dark) |
| 33 | Brook | Yomi Yomi no Mi (Revive Revive) | Soul Solid | Katanas 120 %, Western Swords 120 %, Cane Swords 140 % | avec Yomi Yomi no Mi (Revive Revive) : ×0.5 contre Soru Soru no Mi (Soul Soul)<br>entre membres de Straw Hats : ×0.75 |
| 33 | Franky | — | — | Ranged Weapons 130 % | entre membres de Straw Hats : ×0.75 |
| 33 | Jimbei | — | — | — | toujours : ×0.75 contre Soru Soru no Mi (Soul Soul)<br>entre membres de Straw Hats : ×0.75 |
| 33 | Nami | — | Sorcery Clima Tact | Staves 140 % | entre membres de Straw Hats : ×0.75 |
| 33 | Nico Robin | Hana Hana no Mi (Flower Flower) | — | — | entre membres de Straw Hats : ×0.75 |
| 33 | Tony Tony Chopper | Hito Hito no Mi (Human Human) | — | — | entre membres de Straw Hats : ×0.75 |
| 33 | Usopp | — | Kabuto | Ranged Weapons 150 % | toujours : ×0.5 contre Horo Horo no Mi<br>entre membres de Straw Hats : ×0.75 |
| 35 | Bartholomew Kuma | Nikyu Nikyu no Mi (Paw Paw) | — | — | — |
| 35 | Boa Hancock | Mero Mero no Mi (Love Love) | — | — | en attaque contre Monkey D. Luffy : ×0.1 |
| 35 | Rob Lucci | Neko:Leopard | — | — | — |
| 38 | Koby | — | — | défauts seulement | — |
| 39 | Jewelry Bonney | Toshi Toshi no Mi (Age Age) | — | — | — |
| 43 | "Golden Lion" Shiki | Fuwa Fuwa no Mi (Float Float) | Oto and Kogarashi | Katanas 140 %, Western Swords 120 %, Cane Swords 120 % | — |
| 43 | Gecko Moria | Kage Kage no Mi (Shadow Shadow) | — | — | — |
| 43 | Ulti | Pachycephalosaurus | — | — | — |
| 46 | Catarina Devon | Kyubi no Kitsune (Nine Tailed Fox) | — | Polearms 120 % | — |
| 46 | Emporio Ivankov | Horu Horu no Mi (Hormone Hormone) | — | — | — |
| 46 | Jesus Burgess | Riki Riki no Mi (Strong Strong) | — | — | — |
| 46 | Laffitte | Hapi Hapi no Mi (Harpy) | — | Polearms 120 % | — |
| 47 | Killer | — | — | Western Swords 120 % | — |
| 48 | Charlotte Cracker | Bisu Bisu no Mi (Biscuit Biscuit) | Pretzel | Katanas 120 %, Western Swords 140 %, Cane Swords 120 % | avec Bisu Bisu no Mi (Biscuit Biscuit) : ×1.5 contre Sorcery Clima Tact |
| 48 | Charlotte Perospero | Pero Pero no Mi (Lick Lick) | — | — | avec Pero Pero no Mi (Lick Lick) : ×1.5 contre Mera Mera no Mi (Fire Fire), ×1.5 contre Magu Magu no Mi (Magma Magma) |
| 48 | Kaku | Ushi Ushi no Mi (Giraffe) | — | Katanas 130 %, Western Swords 110 %, Cane Swords 110 % | — |
| 50 | Smoker | Moku Moku no Mi (Smoke Smoke) | — | Staves 130 % | avec Moku Moku no Mi (Smoke Smoke) : ×0.5 contre Mera Mera no Mi (Fire Fire), ×1.5 contre Yami Yami no Mi (Dark Dark) |
| 52 | Basil Hawkins | Wara Wara no Mi (Straw Straw) | Warabide | Western Swords 120 % | — |
| 52 | Capone Bege | Shiro Shiro no Mi (Castle Castle) | — | Ranged Weapons 130 % | — |
| 52 | Scratchmen Apoo | Oto Oto no Mi (Tone Tone) | — | — | — |
| 52 | Urouge | Kyo Kyo no Mi (Buff Buff) | — | Blunt Weapons 130 % | — |
| 52 | X Drake | Allosaurus | — | Katanas 110 %, Western Swords 130 %, Cane Swords 110 % | — |
| 55 | Donquixote Rosinante "Corazon" | Nagi Nagi no Mi (Calm Calm) | — | Ranged Weapons 110 % | en attaque contre Trafalgar D. Water Law : ×0.1 |
| 57 | Karasu | Susu Susu no Mi (Soot Soot) | — | — | avec Susu Susu no Mi (Soot Soot) : ×1.5 contre Yami Yami no Mi (Dark Dark) |
| 57 | Magellan | Doku Doku no Mi (Venom Venom) | — | — | — |
| 59 | Carrot | — | — | défauts seulement | — |
| 59 | Koala | — | — | défauts seulement | — |
| 59 | Nefertari Vivi | — | — | défauts seulement | — |
| 59 | Perona | Horo Horo no Mi | — | — | — |
| 59 | Shirahoshi | — | — | défauts seulement | — |
| 59 | Vinsmoke Reiju | — | — | — | toujours : ×0.5 contre Doku Doku no Mi (Venom Venom) |
| 60 | Bepo | — | — | — | en attaque contre Trafalgar D. Water Law : ×0.1<br>en défense face à Trafalgar D. Water Law : ×0.1 |
| 61 | "Diamond" Jozu | Kira Kira no Mi (Diamond Diamond) | — | — | avec Kira Kira no Mi (Diamond Diamond) : ×0.5 contre Katanas, ×0.5 contre Western Swords, ×0.5 contre Cane Swords<br>entre membres de Whitebeard Pirates : ×0.5 |
| 61 | Izo | — | — | Ranged Weapons 140 % | entre membres de Whitebeard Pirates : ×0.5 |
| 61 | Vista | — | Kaken | Katanas 120 %, Western Swords 140 %, Cane Swords 120 % | entre membres de Whitebeard Pirates : ×0.5 |
| 63 | Bartolomeo | Bari Bari no Mi (Barrier Barrier) | — | — | en défense face à Cavendish : ×1.2<br>en attaque contre Cavendish : ×1.2 |
| 63 | Cavendish | — | Durandal | Katanas 120 %, Western Swords 140 %, Cane Swords 120 % | en attaque contre Bartolomeo : ×1.2<br>en défense face à Bartolomeo : ×1.2 |
| 63 | Hajrudin | — | — | défauts seulement | — |
| 64 | Inuarashi | — | — | Katanas 120 %, Western Swords 140 %, Cane Swords 120 % | — |
| 64 | Jack the Drought | Mammoth | — | Western Swords 120 % | — |
| 64 | Nekomamushi | — | — | Polearms 140 % | — |
| 65 | Black Maria | Rosamygale Grauvogeli (Ancient Spider) | — | — | — |
| 65 | Page One | Spinosaurus | — | — | — |
| 65 | Sasaki | Triceratops | — | Western Swords 120 % | — |
| 65 | Who's Who | Saber Tiger | — | Katanas 120 %, Western Swords 120 % | — |
| 66 | Charlotte Smoothie | Shibo Shibo no Mi (Squeeze Squeeze) | — | Katanas 110 %, Western Swords 130 %, Cane Swords 110 % | — |
| 67 | Jabra | Inu:Wolf | — | — | — |
| 70 | Avalo Pizarro | Shima Shima no Mi (Island Island) | — | — | — |
| 70 | Doc Q | Shiku Shiku no Mi (Sick Sick) | — | Polearms 120 % | — |
| 70 | Vasco Shot | Gabu Gabu no Mi (Glug Glug) | — | — | — |
| 72 | Sanjuan Wolf | Deka Deka no Mi (Huge Huge) | — | — | — |
| 74 | "Foxfire" Kinemon | Fuku Fuku no Mi (Clothes Clothes) | — | Katanas 140 %, Western Swords 120 %, Cane Swords 120 % | — |
| 74 | Kozuki Momonosuke | Seiryu (Azure Dragon) (150 %) | — | — | — |
| 75 | Denjiro | — | — | Katanas 140 %, Western Swords 120 %, Cane Swords 120 % | — |
| 75 | Kawamatsu | — | — | Katanas 130 %, Western Swords 110 %, Cane Swords 110 % | — |
| 76 | Ashura Doji | — | — | Katanas 130 %, Western Swords 110 %, Cane Swords 110 % | — |
| 76 | Kikunojo | — | — | Katanas 130 %, Western Swords 110 %, Cane Swords 110 % | — |
| 78 | Brogy | — | — | Polearms 130 % | — |
| 78 | Dorry | — | — | Katanas 110 %, Western Swords 130 %, Cane Swords 110 % | — |
| 79 | Mr.2 (Bon Clay) | Mane Mane no Mi (Clone Clone) | — | — | — |
| 81 | Tashigi | — | Shigure | Katanas 130 %, Western Swords 110 %, Cane Swords 110 % | — |
| 81 | Tsuru | Woshu Woshu no Mi (Wash Wash) | — | — | — |
| 84 | Belo Betty | Kobu Kobu no Mi (Pump Pump) | — | — | — |
| 84 | Ginny | — | — | défauts seulement | — |
| 84 | Inazuma | Choki Choki no Mi (Snip Snip) | — | — | — |
| 84 | Lindbergh | — | — | Ranged Weapons 130 % | — |
| 84 | Morley | Oshi Oshi no Mi (Push Push) | — | Polearms 120 % | — |
| 86 | Shakuyaku | — | — | défauts seulement | — |
| 86 | Stussy (clone) | Batto Batto no Mi (Bat Bat) | — | — | — |
| 87 | Buckingham Stussy | — | — | défauts seulement | — |
| 87 | Gloriosa | — | — | défauts seulement | — |
| 88 | Gerd | — | — | défauts seulement | — |
| 88 | Ripley | — | — | défauts seulement | — |
| 91 | Helmeppo | — | — | Western Swords 120 % | — |
| 91 | Hibari | — | — | Ranged Weapons 130 % | — |
| 91 | Prince Grus | Gunyo Gunyo no Mi (Clay Clay) | — | — | — |
| 93 | Mr.1 (Daz Bones) | Supa Supa no Mi (Dice Dice) | — | — | avec Supa Supa no Mi (Dice Dice) : ×0.5 contre Katanas, ×0.5 contre Western Swords, ×0.5 contre Cane Swords |
| 93 | Mr.3 (Galdino) | Doru Doru no Mi (Wax Wax) | — | — | avec Doru Doru no Mi (Wax Wax) : ×1.5 contre Mera Mera no Mi (Fire Fire), ×1.5 contre Magu Magu no Mi (Magma Magma), ×0.5 contre Doku Doku no Mi (Venom Venom) |
| 95 | Goldberg | — | — | défauts seulement | — |
| 95 | Road | — | — | défauts seulement | — |
| 95 | Stansen | — | — | défauts seulement | — |
| 98 | Captain John | — | — | défauts seulement | — |
| 98 | Ganzui | — | — | défauts seulement | — |
| 98 | Gill Bastar | — | — | Ranged Weapons 130 % | — |
| 98 | Kyo "Silver Axe" | — | — | Polearms 120 % | — |
| 100 | Caribou | Numa Numa no Mi (Swamp Swamp) | — | — | avec Numa Numa no Mi (Swamp Swamp) : ×1.5 contre Yami Yami no Mi (Dark Dark) |
| 100 | Don Marlon | — | — | défauts seulement | — |
| 100 | Ochoku "Wang Zhi" | — | — | défauts seulement | — |
| 100 | Polo Graham | — | — | défauts seulement | — |
| 101 | Bonk Punch | — | — | défauts seulement | — |
| 101 | Building Snake | — | — | Western Swords 120 % | — |
| 101 | Hongo | — | — | défauts seulement | — |
| 101 | Howling Gab | — | — | défauts seulement | — |
| 101 | Limejuice | — | — | Staves 120 % | — |
| 103 | S-Bat | Kage Kage no Mi (Shadow Shadow) (150 %) | — | — | — |
| 103 | S-Bear | Nikyu Nikyu no Mi (Paw Paw) (150 %) | — | — | — |
| 103 | S-Croc | Suna Suna no Mi (Sand Sand) (150 %) | — | — | avec Suna Suna no Mi (Sand Sand) : ×1.5 contre Yami Yami no Mi (Dark Dark) |
| 103 | S-Flamingo | Ito Ito no Mi (String String) (150 %) | — | — | — |
| 103 | S-Hawk | Supa Supa no Mi (Dice Dice) (150 %) | Yoru (150 %) | Katanas 120 %, Western Swords 140 %, Cane Swords 120 % | avec Supa Supa no Mi (Dice Dice) : ×0.5 contre Katanas, ×0.5 contre Western Swords, ×0.5 contre Cane Swords |
| 103 | S-Shark | Sui Sui no Mi (Swim Swim) (150 %) | — | — | — |
| 103 | S-Snake | Mero Mero no Mi (Love Love) (150 %) | — | — | — |
| 105 | Pedro | — | — | Katanas 110 %, Western Swords 130 %, Cane Swords 110 % | — |
| 105 | Raizo | Maki Maki no Mi (Scroll Scroll) | — | — | — |
| 105 | Shinobu | Juku Juku no Mi (Ripe Ripe) | — | — | — |
| 107 | Vegapunk - Atlas | — | — | défauts seulement | — |
| 107 | Vegapunk - Lilith | — | — | Ranged Weapons 120 % | — |
| 107 | Vegapunk - Shaka | — | — | défauts seulement | — |
| 109 | "Warrior" Leo | Nui Nui no Mi (Stitch Stitch) | — | — | — |
| 109 | Blue Gilly | — | — | défauts seulement | — |
| 109 | Don Sai | — | — | défauts seulement | — |
| 109 | Ideo | — | — | défauts seulement | — |
| 109 | Orlumbus | — | — | défauts seulement | — |
| 110 | Uta | Uta Uta no Mi (Sing Sing) | — | — | — |
| 112 | Doll | — | — | défauts seulement | — |
| 112 | Gion | — | — | Katanas 130 %, Western Swords 110 %, Cane Swords 110 % | — |
| 112 | Hina | Ori Ori no Mi (Bind Bind) | — | — | — |
| 112 | Kujaku | Muchi Muchi no Mi (Whip Whip) | — | — | — |
| 115 | Vegapunk - Edison | — | — | défauts seulement | — |
| 115 | Vegapunk - Pythagoras | — | — | défauts seulement | — |
| 115 | Vegapunk - York | — | — | Ranged Weapons 110 % | — |
| 116 | Dr. Vegapunk (Stella) | Nomi Nomi no Mi (Brain Brain) | — | — | — |
| 117 | Shimotsuki Ryuma | — | Shusui | Katanas 150 %, Western Swords 130 %, Cane Swords 130 % | — |
| 118 | Bogard | — | — | Katanas 120 %, Western Swords 120 % | — |
| 118 | Sentomaru | — | — | Polearms 130 % | — |
| 120 | Kyros | — | — | Katanas 120 %, Western Swords 140 %, Cane Swords 120 % | — |
| 120 | Rebecca | — | — | Western Swords 110 % | — |
| 120 | Viola | Giro Giro no Mi (Glare Glare) | — | — | — |
| 121 | Baby 5 | Buki Buki no Mi (Arms Arms) | — | — | — |
| 121 | Monet | Yuki Yuki no Mi (Snow Snow) | — | — | avec Yuki Yuki no Mi (Snow Snow) : ×1.5 contre Yami Yami no Mi (Dark Dark) |
| 121 | Señor Pink | Sui Sui no Mi (Swim Swim) | — | — | — |
| 121 | Vergo | — | — | Staves 130 % | — |
| 123 | Bellamy | Bane Bane no Mi (Spring Spring) | — | — | — |
| 123 | King Elizabello II | — | — | défauts seulement | — |
| 126 | Caesar Clown | Gasu Gasu no Mi (Gas Gas) | — | — | avec Gasu Gasu no Mi (Gas Gas) : ×1.5 contre Yami Yami no Mi (Dark Dark) |
| 126 | Vinsmoke Ichiji | — | — | défauts seulement | — |
| 126 | Vinsmoke Judge | — | — | Polearms 130 % | — |
| 126 | Vinsmoke Niji | — | — | Western Swords 120 % | — |
| 126 | Vinsmoke Yonji | — | — | défauts seulement | — |
| 129 | Kalgara | — | — | Polearms 130 % | — |
| 129 | Mont Blanc Cricket | — | — | défauts seulement | — |
| 129 | Mont Blanc Noland | — | — | Western Swords 120 % | — |
| 129 | Wyper | — | — | Ranged Weapons 130 % | — |
| 132 | Chaka | Inu:Jackal | — | Western Swords 120 % | — |
| 132 | Pell | Falcon | — | Western Swords 110 % | — |
| 134 | Jaguar D. Saul | — | — | défauts seulement | — |
| 135 | Dalton | Bison | — | — | — |
| 137 | Charlotte Pudding | Memo Memo no Mi (Memory Memory) | — | — | — |
| 137 | Kozuki Hiyori | — | — | défauts seulement | — |
| 137 | Kozuki Toki | Toki Toki no Mi (Time Time) | — | — | — |
| 139 | Iceburg | — | — | défauts seulement | — |
| 139 | Paulie | — | — | défauts seulement | — |
| 141 | Charlotte Amande | — | Shirauo | Katanas 130 %, Western Swords 110 %, Cane Swords 110 % | — |
| 141 | Charlotte Brulee | Mira Mira no Mi (Mirror Mirror) | — | — | — |
| 141 | Charlotte Daifuku | Hoya Hoya no Mi (Lamp Lamp) | — | — | — |
| 141 | Charlotte Oven | Netsu Netsu no Mi (Heat Heat) | — | — | — |
| 141 | Charlotte Praline | — | — | défauts seulement | — |
| 142 | Sugar | Hobi Hobi no Mi | — | — | — |
| 143 | Diamante | Hira Hira no Mi (Ripple Ripple) | — | Katanas 110 %, Western Swords 130 %, Cane Swords 110 % | — |
| 143 | Pica | Ishi Ishi no Mi (Stone Stone) | — | Katanas 110 % | — |
| 143 | Trebol | Beta Beta no Mi (Sticky Sticky) | — | — | — |
| 145 | Dellinger | — | — | défauts seulement | — |
| 145 | Gladius | Pamu Pamu no Mi (Pop Pop) | — | — | — |
| 146 | Buffalo | Guru Guru no Mi (Spin Spin) | — | — | — |
| 146 | Giolla | Ato Ato no Mi (Art Art) | — | — | — |
| 146 | Lao G | — | — | défauts seulement | — |
| 146 | Machvise | Ton Ton no Mi (Ton Ton) | — | — | — |
| 148 | Miss Doublefinger (Zala) | Toge Toge no Mi (Spike Spike) | — | — | — |
| 148 | Miss Goldenweek (Marianne) | — | — | défauts seulement | — |
| 148 | Miss Valentine (Mikita) | Kiro Kiro no Mi (Kilo Kilo) | — | — | — |
| 148 | Mr.5 (Gem) | Bomu Bomu no Mi (Bomb Bomb) | — | Ranged Weapons 110 % | — |
| 150 | Fisher Tiger | — | — | défauts seulement | — |
| 150 | Queen Otohime | — | — | défauts seulement | — |
| 151 | "Big News" Morgans | Tori:Albatross | — | — | — |
| 151 | Don Chinjao | — | — | défauts seulement | — |
| 153 | Blueno | Doa Doa no Mi (Door Door) | — | — | — |
| 153 | Fukurou | — | — | défauts seulement | — |
| 153 | Kalifa | Awa Awa no Mi (Bubble Bubble) | — | — | — |
| 153 | Kumadori | — | — | Staves 120 % | — |
| 155 | Edward Weevil | — | — | Polearms 140 % | — |
| 157 | Blenheim | — | — | — | entre membres de Whitebeard Pirates : ×0.5 |
| 157 | Curiel | — | — | Ranged Weapons 130 % | entre membres de Whitebeard Pirates : ×0.5 |
| 157 | Fossa | — | — | Katanas 120 %, Western Swords 120 % | entre membres de Whitebeard Pirates : ×0.5 |
| 157 | Rakuyo | — | — | Blunt Weapons 120 % | entre membres de Whitebeard Pirates : ×0.5 |
| 157 | Thatch | — | — | Western Swords 120 % | entre membres de Whitebeard Pirates : ×0.5 |
| 158 | Squard | — | — | Katanas 120 %, Western Swords 120 % | entre membres de Whitebeard Pirates : ×0.5 |
| 158 | Whitey Bay | — | — | — | entre membres de Whitebeard Pirates : ×0.5 |
| 159 | Jacksonbanner | — | — | défauts seulement | — |
| 159 | Millet Pine | — | — | défauts seulement | — |
| 159 | Spencer | — | — | défauts seulement | — |
| 161 | Boa Marigold | King Cobra | — | Polearms 120 % | — |
| 161 | Boa Sandersonia | Hebi:Anaconda | — | — | — |
| 163 | Camie | — | — | défauts seulement | — |
| 163 | Fukaboshi | — | — | Polearms 130 % | — |
| 163 | Hatchan | — | — | Katanas 120 %, Western Swords 120 % | — |
| 164 | Madam Shyarly | — | — | défauts seulement | — |
| 165 | T-Bone | — | — | Katanas 110 %, Western Swords 130 %, Cane Swords 110 % | — |
| 166 | Streusen | Kuku Kuku no Mi (Cook Cook) | — | Western Swords 120 % | — |
| 167 | Barbel | — | — | défauts seulement | — |
| 167 | Sunbell | — | — | Polearms 120 % | — |
| 169 | Doctor Hiriluk | — | — | défauts seulement | — |
| 169 | Dr. Kureha | — | — | défauts seulement | — |
| 171 | Marguerite | — | — | Ranged Weapons 130 % | — |
| 174 | Hyogoro | — | — | Katanas 130 %, Western Swords 110 %, Cane Swords 110 % | — |
| 174 | Onimaru | Onyudo | — | Polearms 130 % | — |
| 177 | Baron Tamago | Tama Tama no Mi (Egg Egg) | — | — | — |
| 177 | Hack | — | — | défauts seulement | — |
| 177 | Pekoms | Kame Kame no Mi (Turtle Turtle) | — | — | — |
| 177 | Wanda | — | — | Western Swords 120 % | — |
| 178 | Zeus | — | Sorcery Clima Tact | — | — |
| 179 | Arlong | — | — | Western Swords 120 % | — |
| 179 | Don Krieg | — | — | Polearms 120 %, Ranged Weapons 130 % | — |
| 179 | Kuro | — | — | défauts seulement | — |
| 180 | Gin | — | — | Blunt Weapons 130 % | — |
| 180 | Jango | — | — | défauts seulement | — |
| 182 | Foxy | Noro Noro no Mi (Slow Slow) | — | — | — |
| 182 | Kurozumi Kanjuro | Fude Fude no Mi (Brush Brush) | — | Katanas 120 % | — |
| 182 | Wapol | Baku Baku no Mi (Munch Munch) | — | — | — |
| 185 | King Neptune | — | — | Polearms 130 % | — |
| 185 | Nefertari Cobra | — | — | défauts seulement | — |
| 185 | Princess Mansherry | Chiyu Chiyu no Mi (Heal Heal) | — | — | — |
| 185 | Riku Doldo III | — | — | Western Swords 120 % | — |
| 186 | Koza | — | — | Katanas 110 %, Western Swords 110 % | — |
| 188 | Oimo and Kashii | — | — | Western Swords 120 %, Blunt Weapons 120 % | — |
| 189 | Gedatsu | — | — | défauts seulement | — |
| 189 | Ohm | — | — | Western Swords 120 % | — |
| 189 | Satori | — | — | défauts seulement | — |
| 189 | Shura | — | — | Polearms 130 % | — |
| 190 | Alvida | Sube Sube no Mi (Slip Slip) | — | Blunt Weapons 130 % | avec Sube Sube no Mi (Slip Slip) : ×0.75 contre Blunt Weapons, ×0.75 contre Katanas, ×0.75 contre Western Swords, ×0.75 contre Cane Swords |
| 190 | Jarul | — | — | défauts seulement | — |
| 191 | Babe | Dachshund (150 %) | — | Blunt Weapons 130 % | — |
| 191 | Miss Merry Christmas (Drophy) | Mogu Mogu no Mi (Mole Mole) | — | — | — |
| 191 | Miss Monday | — | — | défauts seulement | — |
| 193 | Crocus | — | — | défauts seulement | — |
| 193 | Gaimon | — | — | Ranged Weapons 110 % | — |
| 193 | Igaram | — | — | Ranged Weapons 120 % | — |
| 194 | Little Oars Jr. | — | — | Western Swords 110 % | entre membres de Whitebeard Pirates : ×0.5 |
| 196 | "Curly" Dadan | — | — | Polearms 110 % | — |
| 196 | Bellmere | — | — | Ranged Weapons 120 % | — |
| 196 | Nojiko | — | — | défauts seulement | — |
| 196 | Tom | — | — | défauts seulement | — |
| 196 | Zeff | — | — | Weapons 25 % | — |
| 197 | Kuina | — | Wado Ichimonji | Katanas 120 % | — |
| 199 | Cabaji | — | — | Western Swords 120 % | — |
| 199 | Duval | — | — | Ranged Weapons 120 % | — |
| 199 | Mohji | — | — | défauts seulement | — |
| 201 | Shachi & Penguin | — | — | défauts seulement | — |
| 204 | Heat | — | — | défauts seulement | — |
| 204 | Wire | — | — | Polearms 120 % | — |
| 205 | Clou D. Clover | — | — | défauts seulement | — |
| 207 | Aisa | — | — | défauts seulement | — |
| 207 | Chimney | — | — | défauts seulement | — |
| 207 | Conis | — | — | Ranged Weapons 110 % | — |
| 207 | Kokoro | — | — | défauts seulement | — |
| 207 | Kurozumi Tama | Kibi Kibi no Mi (Kibi Dango) | — | — | — |
| 207 | Toko | — | — | défauts seulement | — |
| 209 | "Axehand" Morgan | — | — | Polearms 120 % | — |
| 209 | Johnny and Yosaku | — | — | Katanas 110 %, Western Swords 110 % | — |
| 211 | "Calico" Yorki | — | — | défauts seulement | — |
| 211 | Kaya | — | — | défauts seulement | — |
| 211 | Makino | — | — | défauts seulement | — |
| 214 | Domino | — | — | défauts seulement | — |
| 214 | Sadi | — | — | défauts seulement | — |
| 217 | Hannyabal | — | — | Polearms 130 % | — |
| 219 | Pandaman | — | — | défauts seulement | — |
| 219 | Speed | — | — | Ranged Weapons 120 % | — |
| 221 | Stronger | Pegasus | — | Weapons 25 % | — |
| 224 | Abdullah and Jeet | — | — | Katanas 110 %, Western Swords 110 % | — |
<!-- characters:end -->

## Objets sans propriétaire (28)

L'objet existe dans le dex, mais aucun personnage actif n'en est l'utilisateur canonique. Ils restent
équipables par n'importe qui au pourcentage par défaut.

<!-- ownerless:start -->
- `Nidai Kitetsu` (arme) — gardé par Tenguyama Hitetsu (absent du dex) ; Luffy l'a seulement emprunté à Wano
- `Yamata Orochi` (fruit) — Kurozumi Orochi, absent du dex
- `Inu:Dalmatian` (fruit) — vice-amiral Dalmatian, absent du dex
- `Inu:Hound` (fruit) — utilisateur absent du dex (le vice-amiral Hound d'Egghead, à confirmer)
- `Buku Buku no Mi (Book Book)` (fruit) — Charlotte Mont-d'Or, absent du dex
- `Beri Beri no Mi` (fruit) — capitaine Very Good, absent du dex
- `Kumo Kumo no Mi (Spider Spider)` (fruit) — la description correspond au vice-amiral Onigumo, absent du dex
- `Nori Nori no Mi (Ride Ride)` (fruit) — utilisatrice absente du dex (la vice-amirale Bluegrass, à confirmer)
- `Shari Shari no Mi (Wheel Wheel)` (fruit) — Sharinguru, absent du dex
- `Inu:Tanuki` (fruit) — mangé par la bouilloire Bunbuku, absente du dex
- `Zou Zou no Mi (Elephant)` (fruit) — mangé par l'épée Funkfreed de Spandam, absent du dex
- `Sara:Axolotl` (fruit) — mangé par Smiley, la créature de gaz de Caesar, absente du dex
- `Kyubu Kyubu no Mi (Cube Cube)` (fruit) — personnage de jeu vidéo, absent du dex
- `Poke Poke no Mi (Pocket Pocket)` (fruit) — Blamenco, absent du dex
- `Bata Bata no Mi (Butter Butter)` (fruit) — Charlotte Galette, absente du dex
- `Rako Rako no Mi (Sea Otter)` (fruit) — utilisateur absent du dex (un vice-amiral d'Egghead, à confirmer)
- `Gocha Gocha no Mi (Merge Merge)` (fruit) — utilisateur absent du dex (un enfant Charlotte, Newshi, à confirmer)
- `Iku Iku no Mi (Growth Growth)` (fruit) — utilisateur non identifié
- `Kuri Kuri no Mi (Cream Cream)` (fruit) — Charlotte Opera, absent du dex
- `Mato Mato no Mi (Mark Mark)` (fruit) — Vander Decken IX, absent du dex
- `Sabi Sabi no Mi (Rust Rust)` (fruit) — capitaine Shu, absent du dex
- `Uma Uma no Mi (Horse)` (fruit) — Pierre, l'oiseau de Gan Fall, absent du dex (Speed a mangé un SMILE, pas ce fruit)
- `Hornet` (fruit) — Bian, absente du dex
- `Tsutsu Tsutsu no Mi (Cannon Cannon)` (fruit) — utilisateur absent du dex (un vice-amiral d'Egghead, à confirmer)
- `Kabutomushi` (fruit) — Kabu, absent du dex
- `Kyatapira` (fruit) — utilisateur non identifié
- `Gutsu Gutsu no Mi (Smelt Smelt)` (fruit) — Bill (arc hors-série Silver Mine), absent du dex
- `Jake Jake no Mi (Jacket Jacket)` (fruit) — Kelly Funk, absent du dex
<!-- ownerless:end -->

## Résistances (52 règles)

Défenseur vide = n'importe qui. « Objet porté » vide = la règle vaut toujours. La note est celle du CSV.

| Défenseur | Objet porté | Contre (objet ou groupe de l'attaquant) | × | Note |
|---|---|---|---|---|
| n’importe qui | Gomu Gomu no Mi (Gum Gum) | Goro Goro no Mi (Thunder Thunder) | 0.25 | Rubber does not conduct lightning: Enel could not hurt Luffy |
| n’importe qui | Gomu Gomu no Mi (Gum Gum) | `Blunt Weapons` | 0.5 | A rubber body shrugs off blunt impacts |
| n’importe qui | Gomu Gomu no Mi (Gum Gum) | `Staves` | 0.5 | Staff blows are blunt impacts, and rubber insulates from the Clima-Tact's lightning |
| n’importe qui | Gomu Gomu no Mi (Gum Gum) | `Ranged Weapons` | 0.5 | Bullets and cannonballs bounce off rubber |
| n’importe qui | Goro Goro no Mi (Thunder Thunder) | Gomu Gomu no Mi (Gum Gum) | 1.5 | A lightning body cannot slip through rubber: its natural enemy |
| n’importe qui | Mera Mera no Mi (Fire Fire) | Magu Magu no Mi (Magma Magma) | 1.5 | Magma burns fire: Akainu's fruit is the superior one |
| n’importe qui | Magu Magu no Mi (Magma Magma) | Mera Mera no Mi (Fire Fire) | 0.5 | Fire cannot burn magma |
| n’importe qui | Mera Mera no Mi (Fire Fire) | Moku Moku no Mi (Smoke Smoke) | 0.5 | Fire and smoke cancel each other out (Ace vs Smoker in Alabasta) |
| n’importe qui | Moku Moku no Mi (Smoke Smoke) | Mera Mera no Mi (Fire Fire) | 0.5 | Fire and smoke cancel each other out (Ace vs Smoker in Alabasta) |
| n’importe qui | Magu Magu no Mi (Magma Magma) | Yami Yami no Mi (Dark Dark) | 1.5 | Darkness cancels the fruit: a Logia body cannot turn intangible against it |
| n’importe qui | Hie Hie no Mi (Chilly Chilly) | Yami Yami no Mi (Dark Dark) | 1.5 | Darkness cancels the fruit: a Logia body cannot turn intangible against it |
| n’importe qui | Pika Pika no Mi (Light Light) | Yami Yami no Mi (Dark Dark) | 1.5 | Darkness cancels the fruit: a Logia body cannot turn intangible against it |
| n’importe qui | Goro Goro no Mi (Thunder Thunder) | Yami Yami no Mi (Dark Dark) | 1.5 | Darkness cancels the fruit: a Logia body cannot turn intangible against it |
| n’importe qui | Mera Mera no Mi (Fire Fire) | Yami Yami no Mi (Dark Dark) | 1.5 | Darkness cancels the fruit: a Logia body cannot turn intangible against it |
| n’importe qui | Mori Mori no Mi (Forest Forest) | Yami Yami no Mi (Dark Dark) | 1.5 | Darkness cancels the fruit: a Logia body cannot turn intangible against it |
| n’importe qui | Suna Suna no Mi (Sand Sand) | Yami Yami no Mi (Dark Dark) | 1.5 | Darkness cancels the fruit: a Logia body cannot turn intangible against it |
| n’importe qui | Gasu Gasu no Mi (Gas Gas) | Yami Yami no Mi (Dark Dark) | 1.5 | Darkness cancels the fruit: a Logia body cannot turn intangible against it |
| n’importe qui | Moku Moku no Mi (Smoke Smoke) | Yami Yami no Mi (Dark Dark) | 1.5 | Darkness cancels the fruit: a Logia body cannot turn intangible against it |
| n’importe qui | Susu Susu no Mi (Soot Soot) | Yami Yami no Mi (Dark Dark) | 1.5 | Darkness cancels the fruit: a Logia body cannot turn intangible against it |
| n’importe qui | Yuki Yuki no Mi (Snow Snow) | Yami Yami no Mi (Dark Dark) | 1.5 | Darkness cancels the fruit: a Logia body cannot turn intangible against it |
| n’importe qui | Numa Numa no Mi (Swamp Swamp) | Yami Yami no Mi (Dark Dark) | 1.5 | Darkness cancels the fruit: a Logia body cannot turn intangible against it |
| n’importe qui | Yami Yami no Mi (Dark Dark) | `Devil fruits` | 1.25 | Darkness draws every attack in: its user cannot dodge and feels more pain |
| n’importe qui | Yami Yami no Mi (Dark Dark) | `Weapons` | 1.25 | Darkness draws every attack in: its user cannot dodge and feels more pain |
| n’importe qui | Doru Doru no Mi (Wax Wax) | Mera Mera no Mi (Fire Fire) | 1.5 | Wax melts under fire (Little Garden) |
| n’importe qui | Doru Doru no Mi (Wax Wax) | Magu Magu no Mi (Magma Magma) | 1.5 | Wax melts under heat |
| n’importe qui | Doru Doru no Mi (Wax Wax) | Doku Doku no Mi (Venom Venom) | 0.5 | Wax walls block Magellan's venom (Impel Down) |
| n’importe qui | Bara Bara no Mi (Chop Chop) | `Katanas` | 0.25 | A splitting body cannot be cut: slashes pass through, even Mihawk's |
| n’importe qui | Bara Bara no Mi (Chop Chop) | `Western Swords` | 0.25 | A splitting body cannot be cut: slashes pass through, even Mihawk's |
| n’importe qui | Bara Bara no Mi (Chop Chop) | `Cane Swords` | 0.25 | A splitting body cannot be cut: slashes pass through, even Mihawk's |
| n’importe qui | Kira Kira no Mi (Diamond Diamond) | `Katanas` | 0.5 | Diamond body: Jozu stopped Mihawk's slash |
| n’importe qui | Kira Kira no Mi (Diamond Diamond) | `Western Swords` | 0.5 | Diamond body: Jozu stopped Mihawk's slash |
| n’importe qui | Kira Kira no Mi (Diamond Diamond) | `Cane Swords` | 0.5 | Diamond body: Jozu stopped Mihawk's slash |
| n’importe qui | Supa Supa no Mi (Dice Dice) | `Katanas` | 0.5 | Steel body: an ordinary sword stroke does not cut it |
| n’importe qui | Supa Supa no Mi (Dice Dice) | `Western Swords` | 0.5 | Steel body: an ordinary sword stroke does not cut it |
| n’importe qui | Supa Supa no Mi (Dice Dice) | `Cane Swords` | 0.5 | Steel body: an ordinary sword stroke does not cut it |
| n’importe qui | Sube Sube no Mi (Slip Slip) | `Blunt Weapons` | 0.75 | Slippery skin: blows and blades slide off |
| n’importe qui | Sube Sube no Mi (Slip Slip) | `Katanas` | 0.75 | Slippery skin: blows and blades slide off |
| n’importe qui | Sube Sube no Mi (Slip Slip) | `Western Swords` | 0.75 | Slippery skin: blows and blades slide off |
| n’importe qui | Sube Sube no Mi (Slip Slip) | `Cane Swords` | 0.75 | Slippery skin: blows and blades slide off |
| Monkey D. Luffy | — | Doku Doku no Mi (Venom Venom) | 0.75 | Built antibodies after surviving Magellan's venom |
| Vinsmoke Reiju | — | Doku Doku no Mi (Venom Venom) | 0.5 | Poison Pink: immune to poison, she feeds on it |
| n’importe qui | Bisu Bisu no Mi (Biscuit Biscuit) | Sorcery Clima Tact | 1.5 | Nami's rain softens biscuit: how Cracker's armor fell |
| Usopp | — | Horo Horo no Mi | 0.5 | Already negative: Perona's hollows have no effect on him |
| Monkey D. Luffy | — | Mero Mero no Mi (Love Love) | 0.5 | Feels no lust: Hancock's petrification does not work on him |
| n’importe qui | Yomi Yomi no Mi (Revive Revive) | Soru Soru no Mi (Soul Soul) | 0.5 | Soul power overrides Big Mom's homies |
| Jimbei | — | Soru Soru no Mi (Soul Soul) | 0.75 | Fearless: Big Mom could not take his lifespan |
| n’importe qui | Jiki Jiki no Mi (Magnet Magnet) | `Ranged Weapons` | 0.75 | Repel sends bullets and cannonballs back |
| n’importe qui | Tori Tori:Phoenix | `Weapons` | 0.5 | Phoenix flames regenerate the body: most weapons leave no lasting wound (owner's rule) |
| n’importe qui | Mori Mori no Mi (Forest Forest) | Mera Mera no Mi (Fire Fire) | 1.25 | A forest burns: heat is what hurt Greenbull in Wano |
| n’importe qui | Mori Mori no Mi (Forest Forest) | Magu Magu no Mi (Magma Magma) | 1.25 | A forest burns: heat is what hurt Greenbull in Wano |
| n’importe qui | Pero Pero no Mi (Lick Lick) | Mera Mera no Mi (Fire Fire) | 1.5 | Candy melts under heat |
| n’importe qui | Pero Pero no Mi (Lick Lick) | Magu Magu no Mi (Magma Magma) | 1.5 | Candy melts under heat |

## Relations entre personnages (14 règles)

Le multiplicateur s'applique aux dégâts que l'attaquant inflige au défenseur, quel que soit leur équipement.
Une ligne d'équipage vaut entre deux membres du groupe ; une ligne entre deux personnages précis l'emporte sur
elle (Sanji contre Zoro : ×1.2, pas ×0.75).

| Attaquant | Défenseur | × | Note |
|---|---|---|---|
| tout membre de `Whitebeard Pirates` | tout autre membre de `Whitebeard Pirates` (14 : Edward Newgate (Whitebeard), Marco, Portgas D. Ace, "Diamond" Jozu, Izo, Vista, Blenheim, Curiel, Fossa, Rakuyo, Thatch, Squard, Whitey Bay, Little Oars Jr.) | 0.5 | Brothers of one family: they hold back against each other |
| tout membre de `Straw Hats` | tout autre membre de `Straw Hats` (10 : Monkey D. Luffy, Roronoa Zoro, Vinsmoke Sanji, Brook, Franky, Jimbei, Nami, Nico Robin, Tony Tony Chopper, Usopp) | 0.75 | Crewmates do not go all out against each other |
| Vinsmoke Sanji | Roronoa Zoro | 1.2 | Rivals: squabbling fires them both up |
| Roronoa Zoro | Vinsmoke Sanji | 1.2 | Rivals: squabbling fires them both up |
| Cavendish | Bartolomeo | 1.2 | Rivals: squabbling fires them both up |
| Bartolomeo | Cavendish | 1.2 | Rivals: squabbling fires them both up |
| Gol D. Roger | Edward Newgate (Whitebeard) | 1.2 | Lifelong rivals who fought as equals |
| Edward Newgate (Whitebeard) | Gol D. Roger | 1.2 | Lifelong rivals who fought as equals |
| "Red-Haired" Shanks | Eustass "Captain" Kidd | 1.2 | Shanks defeated Kidd twice |
| Sakazuki (Akainu) | Portgas D. Ace | 1.3 | Akainu killed Ace at Marineford |
| Boa Hancock | Monkey D. Luffy | 0.1 | In love with Luffy: she can hardly bring herself to strike him |
| Donquixote Rosinante "Corazon" | Trafalgar D. Water Law | 0.1 | Gave his life to save Law |
| Bepo | Trafalgar D. Water Law | 0.1 | Friends since childhood: neither would hurt the other |
| Trafalgar D. Water Law | Bepo | 0.1 | Friends since childhood: neither would hurt the other |

En attente : `Vinsmoke Sora` est désactivée dans le dex, donc ces 5 lignes ne sont pas dans
`relations.csv`. Elles sont prêtes à y être collées le jour où elle est activée.

```csv
Vinsmoke Sora,Vinsmoke Reiju,,0.1,A mother who gave her life for her children
Vinsmoke Sora,Vinsmoke Ichiji,,0.1,A mother who gave her life for her children
Vinsmoke Sora,Vinsmoke Niji,,0.1,A mother who gave her life for her children
Vinsmoke Sora,Vinsmoke Sanji,,0.1,A mother who gave her life for her children
Vinsmoke Sora,Vinsmoke Yonji,,0.1,A mother who gave her life for her children
```

## Décisions validées le 28 novembre 2026 (17)

Ce qui figurait dans les doutes et que tu as tranché. Les fichiers en tiennent compte.

- Attributions fondées sur la carte du dex ou sur les chapitres récents : `Akuma no Mi (Devil's Fruit)` à Imu, `Kyo Kyo no Mi (Buff Buff)` à Urouge, `Eclipse` à Rocks, `Yakuza Kasen` à Fujitora, `Kaken` à Vista, `Gomu Gomu no Mi (Gum Gum)` à JoyBoy, `Nidhöggr` et `Ratatoskr` à Loki.
- Fruits mangés par une arme (`Ratatoskr`, `Cerberus`, `Dachshund`) : le porteur de l'arme est à 150 %.
- Répliques à 150 % : les Seraphim, Momonosuke avec `Seiryu (Azure Dragon)`, `S-Hawk` avec `Yoru`.
- `Zeus` avec `Sorcery Clima Tact` à 200 %.
- Résistances liées au corps que donne un fruit : sans nom de personnage, elles valent pour quiconque porte le fruit.
- Malus du `Yami Yami no Mi (Dark Dark)` écrit sur les groupes `Devil fruits` et `Weapons`.
- Lignes filet `Devil fruits` et `Weapons` en couche 1, tous les défauts à 50 %.
- Sous le défaut : Luffy 30 % sur les lames, Sanji et Zeff 25 % sur `Weapons`, `Stronger` 25 % sur `Weapons`.
- Teach à 120 % sur `Devil fruits`.
- Report entre lames (20 points de moins sur les deux autres groupes de lames).
- Multiplicateur 0.25 comme quasi-immunité dans les résistances.
- `S-Bat`, `S-Croc`, `S-Flamingo` reçoivent Kage Kage, Suna Suna et Ito Ito, à 150 % comme les autres Seraphim.
- `Hapi Hapi no Mi (Harpy)` est attribué à `Laffitte`, à 200 %.
- `Sunbell`, `King Harald`, `Catarina Devon` et `Laffitte` reçoivent la maîtrise `Polearms`.
- `Shodai Kitetsu` est attribué à `St. Ethanbaron V. Nusjuro`, à 200 %. `Nidai Kitetsu` reste sans propriétaire.
- Les manieurs de hache (`Scopper Gaban`, `Sentomaru`, `Brogy`, `Kyo "Silver Axe"`, `"Curly" Dadan`, `"Axehand" Morgan`) reçoivent `Polearms` en attendant un groupe `Axes`. Fouets, griffes et ciseaux restent sans maîtrise.
- Anomalies de données (fruits sans groupe de type, fruits dans deux groupes) : tu les corriges toi-même.

## Doutes (11)

Ce qui reste ouvert : une réponse à préciser, les valeurs que j'ai choisies pour les relations, et les
classements que tu n'as pas commentés.


### En attente de ta réponse

1. `Ame No Habakiri` et Momonosuke : ta réponse « oui » peut se lire de deux façons (« oui, Oden seul » ou « oui, donne-la aussi à Momonosuke »). En attendant, seul Oden est à 200 %.

### Relations entre personnages : valeurs et limites

2. Trois valeurs sont de moi, tu n'avais pas donné de chiffre : `Whitebeard Pirates` entre eux ×0.5 (« beaucoup moins fort »), `Straw Hats` entre eux ×0.75 (« moins fort »), Akainu contre Ace ×1.3. Shanks contre Kidd est à ×1.2, le minimum que tu as donné.
3. `Vinsmoke Sora` est désactivée dans le dex : ses 5 lignes (×0.1 contre chacun de ses enfants) ne sont pas dans `relations.csv`, elles sont listées plus haut, prêtes à ajouter le jour où elle est activée.
4. Sens unique : Boa contre Luffy, Corazon contre Law, Shanks contre Kidd et Akainu contre Ace ne valent que dans ce sens (Luffy frappe Boa normalement). Seuls Bepo et Law, et les trois paires de rivaux, sont écrits dans les deux sens.
5. Le groupe `Whitebeard Pirates` contient `Squard`, qui a pourtant poignardé Barbe Blanche : la règle des frères vaut aussi pour lui. Teach n'est pas dans le groupe, donc rien ne le retient. `Portgas D. Ace` y est, donc Ace et Barbe Blanche se ménagent.
6. Cumul avec les résistances d'équipement : Akainu avec son fruit contre Ace avec le sien donne 1.3 × 1.5 = ×1.95 ; Boa avec son fruit contre Luffy donne 0.1 × 0.5 = ×0.05. Si le moteur borne le total à 0.25, le ×0.1 que tu veux pour Boa disparaît : la borne basse doit descendre à 0.1 ou ne pas s'appliquer aux relations.

### Classements et niveaux discutables

7. Type d'épée incertain (katana ou épée occidentale) : `Who's Who`, `Squard`, `Hatchan`, `Fossa`, `Bogard`, `Koza`, `Johnny and Yosaku`, `Abdullah and Jeet`. Je leur ai donné les deux groupes au même pourcentage.
8. Armes rangées par approximation : la jitte de Smoker et le bambou de Vergo en `Staves` ; les Punishers de Killer, la Kiribachi d'Arlong et les shotels de Jack en `Western Swords` ; la faux de Doc Q en `Polearms`. Côté objets : `Yoru` en `Western Swords`, les nodachi (`Kikoku`, `Raiu`, `Shirauo`) et `Oto and Kogarashi` en `Katanas`. La canne de `Laffitte` est en `Polearms` comme tu l'as demandé ; `Staves` collerait mieux à une canne.
9. Niveaux estimés pour des personnages peu vus au combat : `Gion`, `Bogard`, `St. Figarland Garling`, `St. Ethanbaron V. Nusjuro`, `Rocks D. Xebec`, `Thatch`. `Building Snake` et `Limejuice` reposent sur Film Red. Pour les armes d'hast que tu viens d'accorder, j'ai choisi : `Scopper Gaban` 140, `Sentomaru`, `Brogy` et `King Harald` 130, `Kyo "Silver Axe"`, `"Axehand" Morgan`, `Sunbell`, `Catarina Devon` et `Laffitte` 120, `"Curly" Dadan` 110.
10. Résistances de confiance moyenne : `Mori Mori` contre feu et magma (×1.25), `Pero Pero` contre feu et magma (×1.5), `Doru Doru` contre magma (extension de la faiblesse au feu), `Jiki Jiki` contre `Ranged Weapons`, `Sube Sube` contre lames et armes contondantes.
11. Fruits sans propriétaire dont je n'identifie pas sûrement l'utilisateur : `Iku Iku`, `Kyatapira`, `Rako Rako`, `Tsutsu Tsutsu`, `Inu:Hound`, `Nori Nori`, `Kumo Kumo`, `Kyubu Kyubu`, `Gocha Gocha`. Sans effet tant que ces personnages ne sont pas dans le dex ; à vérifier le jour où ils y entrent.

## Anomalies de données relevées (tu as indiqué les corriger toi-même)

- 4 fruits sont à la fois dans `Logia` et dans `Paramecia` : Gasu Gasu no Mi (Gas Gas), Mori Mori no Mi (Forest Forest), Suna Suna no Mi (Sand Sand), Susu Susu no Mi (Soot Soot). Une règle écrite sur
  ces deux groupes s'appliquerait deux fois à ces fruits.
- 8 fruits n'ont aucun groupe de type (`Logia`, `Zoan`, `Paramecia`) : Akuma no Mi (Devil's Fruit), Gura Gura no Mi (Quake Quake), Ope Ope no Mi, Bakotsu, Fengxi, Gyuki, Itsumade, Sandworm. Les lignes
  de couche 1 par type ne les couvrent pas : c'est la raison de la ligne filet `Devil fruits`.
