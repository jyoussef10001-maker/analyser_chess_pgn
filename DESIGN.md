# Conception

## Les six questions, pour ce projet

1. **Contexte.** Programme local pour une personne. Une requête HTTP lance une analyse longue (secondes à minutes)
   à une charge très faible (une analyse à la fois). Serveur simple, un seul processus, un seul fil.
2. **Données.** Une partie = en-têtes + liste de coups. Un coup = SAN, UCI, FEN, évaluation, mat éventuel,
   perte, verdict, meilleur coup (SAN et UCI) et début de la ligne principale de Stockfish. En-têtes facultatifs
   (Elo, ouverture, ECO, événement) : `null` s'ils manquent, la page n'invente rien. Rien n'est stocké : tout est recalculé. Règles qui ne doivent jamais être fausses :
   l'évaluation est toujours du point de vue des Blancs et plafonnée à ±1000 ; la perte est toujours ≥ 0
   et se calcule du point de vue du joueur qui vient de jouer.
3. **Pannes.** Mauvaise demande (PGN vide, trop gros, mauvaise profondeur) : 4xx, rien dans le journal.
   Panne du serveur (Stockfish absent, démarrage raté, plantage, python-chess absent) : 503, avec la cause
   écrite dans le terminal. Bug imprévu : 500 avec message générique, détail dans le terminal. Aucune erreur avalée.
4. **Accès.** Serveur sur 127.0.0.1 seulement. Le Host est vérifié (contre les pages web malveillantes), le contenu
   doit être du JSON, et la taille, le nombre de parties, de demi-coups et la profondeur sont limités.
   Dans la page, le texte du PGN n'est jamais interprété comme du HTML.
5. **Rejouer / en parallèle.** Analyser deux fois le même PGN donne le même résultat et ne change rien.
   Le serveur traite une requête à la fois : pas de concurrence sur Stockfish.
6. **Observabilité.** Le terminal affiche l'état au démarrage (python-chess, Stockfish) et chaque erreur serveur
   avec sa trace. Le « healthcheck » est `GET /api/status`, que la page appelle à l'ouverture.

## Décisions

| Décision | Choix | Pourquoi | À revoir si |
| --- | --- | --- | --- |
| Fichiers Python | un seul (`app.py`) | ce qu'on demande : le minimum | le fichier dépasse ~400 lignes |
| Interface | une page HTML, JavaScript sans bibliothèque | rien à installer, rien à compiler | il faut des comptes, un historique |
| Serveur | `http.server` de la bibliothèque standard | zéro dépendance en plus | plusieurs utilisateurs en même temps |
| Analyse | Stockfish uniquement ; seuils sur la perte pour nommer un coup | pas de code d'analyse maison | on veut un pourcentage de précision |
| Moteur | un Stockfish lancé par analyse | pas d'état partagé, pas de fuite | le démarrage devient trop lent |
| Chess.com | retiré | on garde uniquement le PGN | — |

## Interface

Même charte que la version précédente (bleu-vert sobre, mode clair et sombre selon le système).

- Couleurs : fond `#eef1f4`, surface `#ffffff`, texte `#14202b`, action `#0b5c7a`.
  Verdicts : excellent `#17724a`, bon `#4e6b80`, imprécision `#8a6400`, erreur `#b4500f`, gaffe `#c62f3a`.
  Mode sombre (soigné en priorité) : fond `#0c131a`, surface `#141e28`, texte `#e6ecf2`, action `#5bb4d6`.
  Échec : halo rouge sur le roi. Flèche du coup de Stockfish : couleur « excellent » semi-transparente.
- Polices : Bricolage Grotesque (titres), Public Sans (texte), avec polices système en secours.
- Les verdicts ne reposent jamais sur la couleur seule : texte (« Gaffe ») et signes (`?!`, `?`, `??`).
- Disposition : barre du haut (état de Stockfish, « Nouvelle analyse ») ; à gauche l'échiquier avec la barre
  d'évaluation, les joueurs, les pièces prises et la navigation, puis la courbe ; à droite la partie (joueurs, Elo,
  résultat, ouverture, profondeur), l'analyse du coup affiché et la liste des coups.
- Analyse du coup : trois blocs séparés (coup joué, choix de Stockfish, évaluation après le coup) et une phrase
  construite uniquement avec les chiffres du serveur.
- Les pièces prises et l'avance de matériel sont comptées sur la FEN (valeurs usuelles 1/3/3/5/9) : affichage seulement.
- Clavier : flèches, Début/Fin, `F`, `N`/`P` (erreur suivante/précédente). Les raccourcis ignorent Ctrl/Alt/Cmd.
  Focus visible. Mouvement réduit respecté.
- Écran étroit : une seule colonne (partie, échiquier, analyse, coups, courbe), aucun défilement horizontal.
