# Le pont kots ↔ OPDex — contrat v1

Grand Line Royale (kots) envoie à OPDex ce que les joueurs ont fait pendant une partie.
OPDex en tire des points de guerre d'équipages.

Ce fichier est **l'autorité**. Les deux côtés codent contre ce texte. Un côté qui veut le
changer le demande ; il ne le change pas seul.

État : **v1, brouillon** — les noms de champs côté kots sont à confirmer par la session kots.

## Les cinq principes

1. **kots ne donne que des points.** Jamais de baies, jamais de cartes, jamais d'équipage.
   C'est un bot de jeu à part, il n'influe sur rien d'autre.
2. **OPDex est l'autorité sur les équipages.** Le rapport dit ce qu'un joueur *a fait* ;
   OPDex décide *pour qui ça compte*, en lisant son propre `CrewMembership`. Un rapport ne
   peut pas réaffecter un joueur, même s'il le prétend.
3. **OPDex est l'autorité sur le barème.** Combien vaut un meurtre est une ligne
   `CrewWarRule` dans le panel, pas une constante dans kots. Le barème change sans
   redéployer ni l'un ni l'autre.
4. **Rien n'est exposé publiquement.** Le pont reste sur l'hôte. nginx n'est pas touché.
5. **Les deux côtés sont éteints par défaut.** Trois interrupteurs indépendants : le secret
   côté OPDex, l'activation par serveur côté kots, et l'existence d'une règle dans le panel.

## Sens 1 — kots → OPDex : le rapport de fin de partie

```
POST http://127.0.0.1:15262/webhook/kots
Authorization: Bearer <secret partagé>
Content-Type: application/json
```

L'adresse dépend de l'hébergement de kots, à confirmer :
- kots en conteneur sur le même hôte → `http://bot:15262/webhook/kots` sur un réseau Docker partagé, aucun port publié ;
- kots en simple processus sur l'hôte → OPDex publie `127.0.0.1:15262:15262` et kots poste sur `127.0.0.1`.

Dans les deux cas, rien n'est joignable de l'extérieur.

### Le corps

```json
{
  "version": 1,
  "match_id": "glr:<guild_id>:<channel_id>:<epoch_de_debut>",
  "guild_id": 123456789,
  "channel_id": 987654321,
  "mode": "normal",
  "island": "Water Seven",
  "rounds": 14,
  "started_at": "2026-11-19T19:00:00Z",
  "ended_at": "2026-11-19T19:12:30Z",
  "players": [
    {
      "discord_id": 111,
      "place": 1,
      "winner": true,
      "rounds_survived": 14,
      "kills": 3,
      "damage_dealt": 420,
      "chests_opened": 2,
      "bounties_claimed": 1
    }
  ]
}
```

### Les règles d'envoi

- **Un seul envoi par partie**, à la fin, tous les joueurs dedans. Pas un envoi par action.
- **`match_id` est stable** : généré une fois à la fin de la partie et réutilisé à chaque
  réessai. C'est lui qui garantit qu'une partie ne paie jamais deux fois.
- **Étape 1 : `mode == "normal"` seulement.** Les raids n'envoient rien.
- **File persistante** côté kots : un rapport attend un `2xx` et survit à un redémarrage du
  bot ou à une indisponibilité d'OPDex. Il n'est jamais perdu en silence.
- Pas de `partner_id`, pas de notion d'équipe en v1. Les duos formés en partie ne sortent pas
  de kots : OPDex n'en a aucun usage.
- Les champs que personne ne note encore (`damage_dealt`, `chests_opened`, `rounds_survived`…)
  voyagent quand même. Les noter plus tard sera une règle à créer dans le panel, rien à
  redéployer côté kots.

### Les réponses d'OPDex

| Code | Sens | Ce que kots fait |
|---|---|---|
| `200 {"status":"scored"}` | accepté et noté | retire de la file |
| `200 {"status":"duplicate"}` | déjà vu, rien refait | retire de la file |
| `400` | corps invalide | retire de la file, journalise — un réessai ne corrigera rien |
| `401` | secret faux ou absent | garde en file, journalise fort |
| `503` | pont désactivé côté OPDex | garde en file |
| pas de réponse | OPDex éteint | garde en file, réessaie |

## Ce qu'OPDex fait du rapport

1. Vérifie le Bearer, puis le serveur dans la liste autorisée.
2. Écrit une ligne `RoyaleMatch` avec `match_id` **unique**. Si elle existe déjà → `duplicate`,
   rien n'est refait. C'est le patron de `CrewWarPayout`, qui rend le paiement rejouable.
3. Pour chaque joueur : résout le `Player` par `discord_id`. Inconnu → journalisé et compté
   dans la ligne du match, pas d'erreur.
4. Envoie les événements sur le bus : `kills` fois `Event.ROYALE_KILL`. C'est `crew_app` qui
   note, avec le barème du panel et ses plafonds journaliers.
5. Pas de guerre vivante, ou joueur sans équipage → 0 point, en silence. C'est déjà le
   comportement de `score()`, aucun code pour ça.

## Sens 2 — OPDex → kots : l'appartenance aux équipages

Pour une seule règle de jeu : **on ne frappe pas quelqu'un de son propre équipage.** C'est la
seule raison pour laquelle kots a besoin de savoir, et ça détermine toute la forme ci-dessous.

Servi par le **même serveur, le même port et le même secret** que le rapport. Une route de plus
dans le processus du bot, qui a déjà l'accès à la base — rien de neuf à exposer.

```
POST http://127.0.0.1:15262/api/crews
Authorization: Bearer <le même secret>
Content-Type: application/json

{"guild_id": 123456789, "discord_ids": [111, 222, 333]}
```

```json
{
  "members": {
    "111": {"crew_id": 3, "name": "Straw Hat Pirates", "emoji": "🏴‍☠️", "label": "🏴‍☠️ Straw Hat Pirates"},
    "222": {"crew_id": 7, "name": "Heart Pirates", "emoji": "💛", "label": "💛 Heart Pirates"},
    "333": null
  }
}
```

Les clés sont les identifiants **en chaîne**, parce que c'est ce qu'ils deviennent en passant
par JSON : un appelant qui comparerait au nombre qu'il a envoyé les manquerait tous.

`null` veut dire « aucun équipage à signaler », et couvre les deux cas — joueur sans équipage, et
joueur qu'OPDex n'a jamais vu. kots les traite pareil : une faction d'un seul, qui ne marque rien.
Il n'y a rien à faire de la différence.

### Les trois règles d'usage

- **kots demande les joueurs de son salon, jamais toute la table.** Ce qui n'est pas nécessaire
  ne sort pas.
- **Une seule fois, au démarrage de la partie**, et la réponse est figée pour toute sa durée.
  Pas à chaque arrivée dans le salon. La raison n'est pas la simplicité : un joueur qui change
  d'équipage en pleine partie changerait de camp au milieu d'un combat.
- **kots n'écrit rien.** L'instantané vit le temps de la partie. Sinon il y aurait deux sources
  de vérité sur qui est dans quel équipage, et elles divergeraient. OPDex reste l'autorité.

### Si OPDex ne répond pas

Le raid de guerre **refuse de démarrer**, et le dit. Pas de repli silencieux vers un
chacun-pour-soi : ce serait un autre jeu, et un joueur venu pour une guerre d'équipages ne
devrait pas s'y retrouver sans le savoir. C'est pour ça qu'un échec de lecture renvoie 500 et
jamais 400 — kots doit pouvoir réessayer.

Le même interrupteur `enabled` ferme les deux portes, volontairement : le pont est une seule
chose, et un mode guerre ne doit pas continuer de tourner sur une moitié.

### Ce que ça ne change pas

Même en mode guerre, **le rapport de fin de partie ne porte aucun identifiant d'équipage.**
OPDex sait déjà qui est où : il retrouve l'équipage vainqueur depuis les identifiants Discord
des gagnants et sa propre table. Le principe 2 tient dans les deux sens.

## Nouvelles sources de points

Cinq sources sont **émises** sur le bus, une seule est censée **marquer** pour commencer.

| Source | Quand | Noté dès maintenant ? |
|---|---|---|
| `royale_kill` | un meurtre, une fois par meurtre | oui, c'est le barème de départ |
| `royale_played` | avoir joué une partie allée au bout | seulement si une règle existe |
| `royale_win` | avoir été nommé vainqueur | seulement si une règle existe |
| `royale_chest` | un coffre ouvert, une fois par coffre | seulement si une règle existe |
| `royale_bounty` | une prime encaissée, une fois par prime | seulement si une règle existe |

Pourquoi les cinq alors qu'une seule compte : une action pour laquelle aucune règle n'existe
coûte une lecture en cache et ne marque rien — `crew_app.scoring.score` vérifie la règle avant
le joueur. Donc les émettre toutes tout de suite veut dire qu'« un coffre vaut 2 » devient
**une ligne dans le panel, sans déploiement d'aucun des deux bots**. N'en émettre qu'une aurait
fait de chaque ajout un déploiement.

Le mode de guerre aura ses propres sources, pour qu'un meurtre en guerre puisse valoir autre
chose qu'un meurtre en partie normale. C'est à ça que sert `mode` dans le rapport.

---

## Allumer le pont

Rien ne marche et rien ne casse tant que ces étapes ne sont pas faites. L'ordre compte un peu :
le secret doit être le même des deux côtés avant qu'un rapport puisse passer, mais la règle de
barème peut être créée quand on veut.

1. **Côté OPDex, sur le VPS** : `git pull`, puis **ajouter le port à la main** avant de relancer.

   `docker-compose.override.yml` est dans `.gitignore` (ligne 50) : c'est volontaire, ce fichier
   est propre à chaque machine, donc le `git pull` ne l'apporte pas. Il faut coller ce bloc dans
   celui du VPS, à côté du service `proxy` qui y est déjà :

   ```yaml
   services:
     bot:
       ports:
         # Royale tourne en processus sur l'hôte, pas en conteneur : il ne peut pas joindre le
         # réseau Docker par nom de service, donc le port doit être publié. Loopback seulement.
         - "127.0.0.1:15262:15262"
   ```

   Puis `docker compose up -d`. Le service `migration` crée les tables tout seul.

   Sans ce bloc, kots tombe sur un refus de connexion — il garde ses rapports en file et
   réessaie, donc rien n'est perdu, mais rien n'arrive non plus.
2. **Panel admin → Royale settings** : coller un long secret aléatoire, cocher `Enabled`, et
   éventuellement mettre l'id du serveur dans la liste (vide = tous les serveurs).
   Sans secret, le serveur webhook ne démarre même pas.
3. **Côté kots** : la même valeur dans la variable de secret de son `.env` (son
   `.env.example` donne le nom exact), puis `/config opdex` pour l'allumer sur le serveur.
   L'adresse par défaut est déjà la bonne.
4. **Crew wars → la guerre en cours → Crew war rules** : ajouter une règle de source
   *« Killed someone in a Royale match »*, avec les points et, si besoin, un plafond journalier.
   Sans cette règle, les rapports arrivent et ne marquent rien — ce qui est un état parfaitement
   sain pour tester le pont avant d'ouvrir les vannes.

**Pour vérifier que ça passe** : panel admin → *Royale matches*. Une ligne par partie, avec
combien de joueurs le rapport portait, combien étaient connus d'OPDex, et combien de points ont
réellement été donnés. Une ligne à `0 point` avec des joueurs connus veut dire qu'il manque la
règle de l'étape 4, ou qu'aucune guerre ne tourne.
