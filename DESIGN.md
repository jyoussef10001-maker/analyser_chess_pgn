# Conception

## Les six questions, pour ce projet

1. **Contexte.** Programme local pour une personne. Une requête HTTP lance une analyse longue (secondes à minutes)
   à une charge très faible (une analyse à la fois). Serveur simple, un seul processus, un seul fil.
2. **Données.** Une partie = en-têtes + liste de coups. Un coup = SAN, UCI, FEN, évaluation, mat éventuel,
   perte, verdict, meilleur coup. Rien n'est stocké : tout est recalculé. Règles qui ne doivent jamais être fausses :
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
- Polices : Bricolage Grotesque (titres), Public Sans (texte), avec polices système en secours.
- Les verdicts ne reposent jamais sur la couleur seule : texte (« Gaffe ») et signes (`?!`, `?`, `??`).
- Clavier : flèches, Début/Fin, `F`. Focus visible. Mouvement réduit respecté.
- Écran étroit : une seule colonne, aucun défilement horizontal.
