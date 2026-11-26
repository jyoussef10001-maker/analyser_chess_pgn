"""Analyseur de parties d'échecs : le serveur local (le seul fichier Python du projet).

Ce que fait ce fichier :
  1. il sert la page web `index.html` ;
  2. il lit les parties d'un texte PGN (avec python-chess) ;
  3. il demande à Stockfish d'évaluer chaque position (c'est Stockfish qui analyse) ;
  4. il renvoie le résultat à la page en JSON.

Lancement :  python app.py
Stockfish est cherché dans cet ordre :
  - la variable d'environnement STOCKFISH_PATH ;
  - un fichier « stockfish* » placé dans le dossier du projet ;
  - la commande « stockfish » du système (PATH).
"""

import io
import json
import os
import shutil
import sys
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

try:
    import chess
    import chess.engine
    import chess.pgn
except ImportError:  # python-chess n'est pas installé : on le dira à l'utilisateur
    chess = None

# --- Réglages ------------------------------------------------------------------

HOST = "127.0.0.1"          # uniquement cet ordinateur : personne d'autre sur le réseau ne peut s'y connecter
PORT = 8000
FOLDER = Path(__file__).resolve().parent

MAX_BODY = 2_000_000        # taille maximale du texte envoyé (octets)
MAX_GAMES = 50              # nombre maximal de parties dans un PGN
MAX_PLIES = 300             # nombre maximal de demi-coups par partie analysée
DEFAULT_DEPTH = 12          # profondeur Stockfish par défaut (12 = rapide, 18 = précis)
MAX_DEPTH = 20
SECONDS_PER_POSITION = 5    # Stockfish s'arrête au bout de ce temps, même si la profondeur n'est pas atteinte
MATE_SCORE = 10_000         # valeur donnée à un mat avant d'être plafonnée
PV_PLIES = 6                # demi-coups gardés de la ligne principale de Stockfish (affichage seulement)
CLAMP_CP = 1000             # les évaluations sont plafonnées à ±10 pions

# Seuils sur la perte en centipions (100 = 1 pion) : (perte maximale, nom du verdict).
# C'est le seul calcul ajouté au-dessus de Stockfish : il sert uniquement à donner un nom à un coup.
LABELS = [(10, "best"), (50, "good"), (100, "inaccuracy"), (200, "mistake")]
WORST_LABEL = "blunder"


# --- Erreurs --------------------------------------------------------------------

class AppError(Exception):
    """Erreur prévue. `status` suit la règle : 4xx = la demande est mauvaise, 5xx = le serveur ne peut pas."""

    def __init__(self, status, code, message):
        super().__init__(message)
        self.status = status
        self.code = code      # code stable, la page peut s'en servir
        self.message = message  # phrase lisible, affichée à l'utilisateur


# --- Stockfish -----------------------------------------------------------------

def find_stockfish():
    """Retourne le chemin de Stockfish, ou None s'il est introuvable."""
    from_env = os.environ.get("STOCKFISH_PATH")
    if from_env and Path(from_env).expanduser().is_file():
        return str(Path(from_env).expanduser())
    for candidate in sorted(FOLDER.glob("stockfish*")):
        if candidate.is_file() and candidate.suffix.lower() in ("", ".exe"):
            return str(candidate)
    return shutil.which("stockfish")


def open_stockfish(path):
    """Démarre Stockfish (à utiliser avec `with`). Traduit les pannes en messages clairs."""
    try:
        return chess.engine.SimpleEngine.popen_uci(path)
    except (FileNotFoundError, PermissionError) as error:
        raise AppError(503, "STOCKFISH_START_FAILED",
                       f"Impossible de lancer Stockfish ({path}). Vérifie le chemin et les droits d'exécution.") from error
    except (OSError, TimeoutError, chess.engine.EngineError) as error:
        raise AppError(503, "STOCKFISH_START_FAILED",
                       "Stockfish ne démarre pas. Vérifie que c'est la bonne version pour ton système.") from error


# --- Lecture du PGN ---------------------------------------------------------------

def read_games(pgn_text):
    """Lit les parties d'un texte PGN. Ignore ce qui n'a aucun coup. Erreur 400 s'il n'y en a aucune."""
    stream = io.StringIO(pgn_text)
    games = []
    while True:
        game = chess.pgn.read_game(stream)
        if game is None:
            break
        if not game.variations:  # pas un seul coup : ce n'est pas une partie
            continue
        games.append(game)
        if len(games) > MAX_GAMES:
            raise AppError(400, "TOO_MANY_GAMES", f"Ce PGN contient plus de {MAX_GAMES} parties. Découpe-le en plusieurs fichiers.")
    if not games:
        raise AppError(400, "NO_GAME", "Aucune partie trouvée. Colle un texte PGN contenant au moins un coup.")
    return games


def count_plies(game):
    return sum(1 for _ in game.mainline_moves())


def header_or_none(game, name):
    """Valeur d'un en-tête PGN, ou None s'il est absent ou inconnu (« ? ») : la page n'invente rien."""
    value = game.headers.get(name, "").strip()
    return value if value and value != "?" else None


def game_summary(index, game):
    return {
        "index": index,
        "white": game.headers.get("White", "?"),
        "black": game.headers.get("Black", "?"),
        "result": game.headers.get("Result", "*"),
        "date": game.headers.get("Date", "?"),
        "plies": count_plies(game),
        "white_elo": header_or_none(game, "WhiteElo"),
        "black_elo": header_or_none(game, "BlackElo"),
        "event": header_or_none(game, "Event"),
        "eco": header_or_none(game, "ECO"),
        "opening": header_or_none(game, "Opening"),
    }


# --- Analyse (c'est Stockfish qui évalue) -------------------------------------------

def clamp(centipawns):
    return max(-CLAMP_CP, min(CLAMP_CP, centipawns))


def label_for(loss):
    """Nom du verdict d'un coup selon ce qu'il fait perdre (en centipions)."""
    for limit, name in LABELS:
        if loss <= limit:
            return name
    return WORST_LABEL


def evaluate(board, engine, depth):
    """Demande à Stockfish l'évaluation d'une position.

    Retourne (évaluation en centipions du point de vue des Blancs, mat en N coups ou None,
    ligne principale de Stockfish : liste de coups, le premier est le meilleur coup).
    """
    info = engine.analyse(board, chess.engine.Limit(depth=depth, time=SECONDS_PER_POSITION))
    white_score = info["score"].white()
    centipawns = clamp(white_score.score(mate_score=MATE_SCORE))
    return centipawns, white_score.mate(), list(info.get("pv") or [])


def line_san(board, line):
    """Les premiers coups d'une ligne de Stockfish, en notation SAN (s'arrête au premier coup illisible)."""
    board = board.copy(stack=False)
    sans = []
    for move in line[:PV_PLIES]:
        if not board.is_legal(move):
            break
        sans.append(board.san(move))
        board.push(move)
    return sans


def finished_game_eval(board):
    """Évaluation d'une position terminée (mat, pat, nulle) : pas besoin de Stockfish."""
    winner = board.outcome().winner
    if winner is None:
        return 0
    return CLAMP_CP if winner == chess.WHITE else -CLAMP_CP


def analyze_game(game, engine, depth):
    """Évalue la position avant la partie puis après chaque coup, et en déduit le verdict de chaque coup."""
    board = game.board()
    before_cp, _, best_line = evaluate(board, engine, depth)  # position de départ
    start_cp = before_cp
    moves = []

    for ply, move in enumerate(game.mainline_moves(), start=1):
        mover_is_white = board.turn == chess.WHITE
        pv_san = line_san(board, best_line)  # le meilleur coup se note AVANT de jouer
        best_san = pv_san[0] if pv_san else None
        best_uci = best_line[0].uci() if best_san else None
        san = board.san(move)
        board.push(move)

        if board.is_game_over():
            after_cp, mate, best_line = finished_game_eval(board), None, []
        else:
            after_cp, mate, best_line = evaluate(board, engine, depth)

        # Perte du joueur qui vient de jouer : ce que sa position a perdu, de son point de vue.
        loss = max(0, (before_cp - after_cp) if mover_is_white else (after_cp - before_cp))
        moves.append({
            "ply": ply,
            "san": san,
            "uci": move.uci(),         # sert à surligner le coup sur l'échiquier
            "fen": board.fen(),
            "eval": after_cp,          # centipions, point de vue des Blancs
            "mate": mate,              # mat en N coups (positif = Blancs matent), sinon None
            "loss": loss,
            "label": label_for(loss),
            "best_san": best_san,      # le meilleur coup de Stockfish dans la position d'avant
            "best_uci": best_uci,      # le même coup en UCI : sert à dessiner la flèche
            "pv_san": pv_san,          # la ligne principale de Stockfish depuis la position d'avant (SAN)
        })
        before_cp = after_cp

    result = game_summary(0, game)
    result.update({
        "start_fen": game.board().fen(),
        "start_eval": start_cp,        # évaluation de la position de départ (centipions, point de vue des Blancs)
        "moves": moves,
        "warning": "Le PGN contient un coup illisible ou illégal : la partie est coupée à cet endroit."
        if game.errors else None,
    })
    return result


# --- Requêtes (validation à la frontière : ici on vérifie tout ce qui vient de la page) --------------

def get_pgn(data):
    pgn = data.get("pgn")
    if not isinstance(pgn, str) or not pgn.strip():
        raise AppError(400, "PGN_MISSING", "Le champ « pgn » est vide.")
    return pgn


def games_request(data):
    """POST /api/games : liste les parties d'un PGN (sans Stockfish)."""
    games = read_games(get_pgn(data))
    return {"games": [game_summary(i, g) for i, g in enumerate(games)]}


def analyze_request(data):
    """POST /api/analyze : analyse une partie du PGN avec Stockfish."""
    games = read_games(get_pgn(data))

    index = data.get("game", 0)
    if not isinstance(index, int) or isinstance(index, bool) or not 0 <= index < len(games):
        raise AppError(400, "BAD_GAME_INDEX", "Numéro de partie invalide.")

    depth = data.get("depth", DEFAULT_DEPTH)
    if not isinstance(depth, int) or isinstance(depth, bool) or not 1 <= depth <= MAX_DEPTH:
        raise AppError(400, "BAD_DEPTH", f"La profondeur doit être un nombre entre 1 et {MAX_DEPTH}.")

    game = games[index]
    if count_plies(game) > MAX_PLIES:
        raise AppError(400, "GAME_TOO_LONG", f"Cette partie dépasse {MAX_PLIES} demi-coups.")

    # Les erreurs de la demande sont vérifiées avant : si on arrive ici, la demande est bonne.
    path = find_stockfish()
    if path is None:
        raise AppError(503, "STOCKFISH_NOT_FOUND",
                       "Stockfish est introuvable. Définis STOCKFISH_PATH ou place l'exécutable dans le dossier du projet.")

    try:
        with open_stockfish(path) as engine:
            report = analyze_game(game, engine, depth)
    except chess.engine.EngineTerminatedError as error:
        raise AppError(503, "STOCKFISH_CRASHED", "Stockfish s'est arrêté pendant l'analyse. Relance l'analyse.") from error
    except chess.engine.EngineError as error:
        raise AppError(503, "STOCKFISH_ERROR", "Stockfish a renvoyé une erreur pendant l'analyse.") from error

    report["index"] = index
    return {"game": report}


def status_request():
    """GET /api/status : la page vérifie que tout est prêt avant que l'utilisateur lance une analyse."""
    return {"chess": chess is not None, "stockfish": chess is not None and find_stockfish() is not None}


ROUTES = {"/api/games": games_request, "/api/analyze": analyze_request}


# --- Serveur HTTP -----------------------------------------------------------------

def read_page():
    """Lit index.html. S'il manque, c'est une panne du serveur (500) : on la note dans le terminal."""
    try:
        return (FOLDER / "index.html").read_bytes()
    except OSError as error:
        raise AppError(500, "INDEX_MISSING", "index.html est introuvable à côté de app.py.") from error


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # pas de journal des requêtes normales : le terminal ne montre que les vraies erreurs

    def send_json(self, status, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def send_error_json(self, error):
        self.send_json(error.status, {"error": {"code": error.code, "message": error.message}})

    def host_is_local(self):
        """Refuse les requêtes dont l'adresse n'est pas celle de cet ordinateur (protège contre les pages web malveillantes)."""
        return self.headers.get("Host", "") in (f"localhost:{PORT}", f"127.0.0.1:{PORT}")

    def do_GET(self):
        try:
            if not self.host_is_local():
                raise AppError(403, "BAD_HOST", "Adresse non autorisée.")
            if self.path in ("/", "/index.html"):
                body = read_page()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif self.path == "/api/status":
                self.send_json(200, status_request())
            else:
                raise AppError(404, "NOT_FOUND", "Page introuvable.")
        except AppError as error:
            if error.status >= 500:
                traceback.print_exc()
            self.send_error_json(error)

    def do_POST(self):
        try:
            if not self.host_is_local():
                raise AppError(403, "BAD_HOST", "Adresse non autorisée.")
            route = ROUTES.get(self.path)
            if route is None:
                raise AppError(404, "NOT_FOUND", "Adresse inconnue.")
            if not self.headers.get("Content-Type", "").startswith("application/json"):
                raise AppError(415, "BAD_CONTENT_TYPE", "Le contenu doit être du JSON.")
            try:
                length = int(self.headers.get("Content-Length", ""))
            except ValueError:
                raise AppError(411, "LENGTH_REQUIRED", "Taille du contenu manquante.") from None
            if length < 0 or length > MAX_BODY:
                raise AppError(413, "BODY_TOO_LARGE", f"Le texte dépasse {MAX_BODY // 1_000_000} Mo.")
            try:
                data = json.loads(self.rfile.read(length))
            except (ValueError, UnicodeDecodeError):
                raise AppError(400, "BAD_JSON", "JSON invalide.") from None
            if not isinstance(data, dict):
                raise AppError(400, "BAD_JSON", "Le JSON doit être un objet.")
            if chess is None:
                raise AppError(503, "CHESS_MISSING", "python-chess n'est pas installé. Lance : pip install python-chess")
            self.send_json(200, route(data))
        except AppError as error:
            if error.status >= 500:  # panne côté serveur : on la garde dans le terminal avec sa cause
                traceback.print_exc()
            self.send_error_json(error)
        except Exception:  # bug imprévu : on l'écrit en entier dans le terminal, la page reçoit un message générique
            traceback.print_exc()
            self.send_error_json(AppError(500, "INTERNAL_ERROR", "Erreur interne. Les détails sont dans le terminal."))


def main():
    try:
        server = HTTPServer((HOST, PORT), Handler)
    except OSError:
        print(f"Le port {PORT} est déjà utilisé. Ferme l'autre programme ou change PORT dans app.py.", file=sys.stderr)
        return 1

    print(f"Analyseur prêt : http://localhost:{PORT}")
    print("  python-chess :", "OK" if chess else "MANQUANT (pip install python-chess)")
    path = find_stockfish() if chess else None
    print("  Stockfish    :", path or "INTROUVABLE (définis STOCKFISH_PATH ou place-le dans ce dossier)")
    print("Ctrl+C pour arrêter.")
    webbrowser.open(f"http://localhost:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nArrêt.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
