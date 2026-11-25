# Analyseur d'échecs (PGN + Stockfish)

Colle une partie au format PGN : Stockfish évalue chaque coup, et la page affiche l'échiquier, la barre
d'évaluation, la courbe et la liste des coups avec leur verdict (excellent, bon, imprécision, erreur, gaffe).

**Toute l'analyse vient de Stockfish.** Le seul calcul ajouté : la perte d'un coup (évaluation avant moins
évaluation après, en centipions) est comparée à des seuils pour lui donner un nom (voir `LABELS` dans `app.py`).

## Installer (une seule fois)

1. Python 3.9 ou plus récent : https://www.python.org/downloads/
2. python-chess : `pip install python-chess`
3. Stockfish : https://stockfishchess.org/download/ (version « universelle » de ton système).
   Puis **soit** place l'exécutable dans ce dossier (son nom doit commencer par `stockfish`),
   **soit** donne son chemin :
   - Windows : `set STOCKFISH_PATH=C:\stockfish\stockfish-windows-x86-64.exe`
   - macOS / Linux : `export STOCKFISH_PATH=~/stockfish/stockfish`

## Lancer

```
python app.py
```

Le navigateur s'ouvre sur http://localhost:8000. Le terminal indique si python-chess et Stockfish sont trouvés.

## Utiliser

1. Colle le PGN (ou ouvre un fichier `.pgn`, ou clique « Essayer avec un exemple »).
2. Choisis la précision : Rapide (profondeur 10), Normale (12), Précise (16, plus lente).
3. Clique **Analyser**. Une partie prend de quelques secondes à une minute.
4. Navigue avec les flèches du clavier, `F` retourne l'échiquier, « Erreur suivante » va aux coups à revoir,
   un clic sur la courbe saute au coup. Si le PGN contient plusieurs parties, un menu permet de choisir.

## Tests

```
python -m pytest
```

Sans python-chess, seuls les tests du serveur tournent. Avec python-chess, les tests utilisent un faux Stockfish.
Le dernier test utilise le vrai Stockfish s'il est trouvé.

## Fichiers

| Fichier | Rôle |
| --- | --- |
| `app.py` | Le serveur : lit le PGN, lance Stockfish, renvoie les résultats |
| `index.html` | L'interface : la page que tu vois dans le navigateur |
| `test_app.py` | Les tests automatiques |
| `requirements.txt` | Les bibliothèques Python à installer |
| `DESIGN.md` | Les choix de conception et la charte graphique |

## En cas de problème

- **« Stockfish est introuvable »** : voir « Installer », étape 3, puis relance `python app.py`.
- **« python-chess n'est pas installé »** : `pip install python-chess`, puis relance.
- **« Le serveur ne répond pas »** : `python app.py` n'est pas lancé (ou a été arrêté).
- **Port 8000 déjà pris** : change `PORT` en haut de `app.py`.
- **Analyse trop lente** : choisis « Rapide ». Une position ne dépasse jamais 5 secondes (`SECONDS_PER_POSITION`).
- Une seule analyse à la fois : le serveur est volontairement simple (un seul utilisateur, sur ton ordinateur).
