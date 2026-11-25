"""Tests de app.py.

Lancer :  python -m pytest

- Les tests « sans python-chess » tournent partout.
- Les tests avec un faux Stockfish demandent python-chess (pip install python-chess) : sans lui, ils sont ignorés.
- Le dernier test utilise le vrai Stockfish : il est ignoré tant que Stockfish est introuvable.

On remplace seulement Stockfish (qu'on ne contrôle pas) par un faux moteur qui répond avec des évaluations
écrites à l'avance. Tout le reste est le vrai code : lecture du PGN, verdicts, serveur HTTP.
"""

import http.client
import json
import threading
from http.server import HTTPServer

import pytest

import app

try:
    import chess
    import chess.engine
except ImportError:  # sans python-chess, seuls les tests de la première partie tournent
    chess = None

needs_chess = pytest.mark.skipif(chess is None, reason="python-chess n'est pas installé (pip install python-chess)")

# --- Sans python-chess --------------------------------------------------------------


@pytest.mark.parametrize(
    "loss, expected",
    [(0, "best"), (10, "best"), (11, "good"), (50, "good"), (51, "inaccuracy"),
     (100, "inaccuracy"), (101, "mistake"), (200, "mistake"), (201, "blunder"), (5000, "blunder")],
)
def test_label_thresholds(loss, expected):
    assert app.label_for(loss) == expected


def test_clamp_limits_huge_evaluations():
    assert app.clamp(9990) == app.CLAMP_CP
    assert app.clamp(-9990) == -app.CLAMP_CP
    assert app.clamp(42) == 42


@pytest.mark.parametrize("data", [{}, {"pgn": ""}, {"pgn": "   "}, {"pgn": 12}, {"pgn": None}])
def test_missing_pgn_is_a_400(data):
    with pytest.raises(app.AppError) as error:
        app.get_pgn(data)
    assert (error.value.status, error.value.code) == (400, "PGN_MISSING")


# --- Serveur HTTP (vrai serveur, vrai Handler) -----------------------------------------


@pytest.fixture
def server(monkeypatch):
    httpd = HTTPServer(("127.0.0.1", 0), app.Handler)
    monkeypatch.setattr(app, "PORT", httpd.server_address[1])  # le contrôle du Host utilise PORT
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield httpd.server_address[1]
    httpd.shutdown()
    httpd.server_close()


def call(port, method, path, body=None, headers=None):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    raw = body if isinstance(body, bytes) else (json.dumps(body).encode() if body is not None else None)
    all_headers = dict(headers or {})
    if raw is not None:
        all_headers.setdefault("Content-Type", "application/json")
    connection.request(method, path, body=raw, headers=all_headers)
    response = connection.getresponse()
    payload = response.read()
    connection.close()
    return response.status, payload


def error_code(payload):
    return json.loads(payload)["error"]["code"]


def test_home_page_is_served(server):
    status, payload = call(server, "GET", "/")
    assert status == 200 and b"<title>Analyseur" in payload


def test_unknown_page_is_404(server):
    assert call(server, "GET", "/secret")[0] == 404


def test_wrong_host_is_refused(server):
    status, payload = call(server, "GET", "/api/status", headers={"Host": "evil.example"})
    assert (status, error_code(payload)) == (403, "BAD_HOST")


def test_post_needs_json_content_type(server):
    status, payload = call(server, "POST", "/api/games", b'{"pgn": "1. e4"}', {"Content-Type": "text/plain"})
    assert (status, error_code(payload)) == (415, "BAD_CONTENT_TYPE")


def test_post_with_invalid_json_is_400(server):
    status, payload = call(server, "POST", "/api/games", b"{pas du json")
    assert (status, error_code(payload)) == (400, "BAD_JSON")


def test_post_with_json_list_is_400(server):
    status, payload = call(server, "POST", "/api/games", b"[1, 2]")
    assert (status, error_code(payload)) == (400, "BAD_JSON")


def test_oversized_body_is_refused_before_reading_it(server, monkeypatch):
    monkeypatch.setattr(app, "MAX_BODY", 10)
    status, payload = call(server, "POST", "/api/games", b'{"pgn": "1. e4 e5 2. Nf3"}')
    assert (status, error_code(payload)) == (413, "BODY_TOO_LARGE")


def test_missing_python_chess_is_a_503_with_the_fix(server, monkeypatch):
    monkeypatch.setattr(app, "chess", None)
    status, payload = call(server, "POST", "/api/games", {"pgn": "1. e4 *"})
    assert (status, error_code(payload)) == (503, "CHESS_MISSING")
    assert "pip install python-chess" in json.loads(payload)["error"]["message"]


# --- Avec python-chess ------------------------------------------------------------------

SCHOLARS_MATE = "1. e4 e5 2. Bc4 Nc6 3. Qh5 Nf6 4. Qxf7# 1-0"


class FakeEngine:
    """Faux Stockfish : renvoie à chaque appel l'évaluation suivante de la liste.

    Chaque élément est (score, meilleur coup en UCI). Le score est vu du côté des Blancs.
    """

    def __init__(self, script):
        self.script = list(script)

    def analyse(self, board, limit):
        score, best_move = self.script.pop(0)
        return {"score": chess.engine.PovScore(score, chess.WHITE), "pv": [chess.Move.from_uci(best_move)]}


def first_game(pgn_text):
    return app.read_games(pgn_text)[0]


@needs_chess
def test_read_games_ignores_text_without_moves():
    with pytest.raises(app.AppError) as error:
        app.read_games("n'importe quoi")
    assert error.value.code == "NO_GAME"


@needs_chess
def test_read_games_refuses_too_many_games(monkeypatch):
    monkeypatch.setattr(app, "MAX_GAMES", 2)
    with pytest.raises(app.AppError) as error:
        app.read_games("1. e4 *\n\n1. d4 *\n\n1. c4 *")
    assert error.value.code == "TOO_MANY_GAMES"


@needs_chess
def test_illegal_move_cuts_the_game_and_warns():
    report = app.analyze_game(first_game("1. e4 e5 2. Ke5 *"), FakeEngine([(chess.engine.Cp(0), "e2e4")] * 3), depth=5)
    assert [m["san"] for m in report["moves"]] == ["e4", "e5"]
    assert report["warning"]


@needs_chess
def test_black_blunder_is_found():
    # 1. e4 (le meilleur coup de Stockfish) a6 (les Blancs passent à +400 : gaffe des Noirs).
    engine = FakeEngine([
        (chess.engine.Cp(30), "e2e4"),   # position de départ
        (chess.engine.Cp(30), "e7e5"),   # après 1. e4
        (chess.engine.Cp(400), "d2d4"),  # après 1... a6
    ])
    report = app.analyze_game(first_game("1. e4 a6 *"), engine, depth=10)

    assert [m["san"] for m in report["moves"]] == ["e4", "a6"]
    assert [m["label"] for m in report["moves"]] == ["best", "blunder"]
    assert report["moves"][1]["best_san"] == "e5"  # ce que les Noirs auraient dû jouer
    assert report["moves"][1]["loss"] == 370


@needs_chess
def test_white_blunder_is_found_too():
    # Le même test du côté des Blancs : l'évaluation passe de 0 à -300, c'est une gaffe des Blancs.
    engine = FakeEngine([(chess.engine.Cp(0), "e2e4"), (chess.engine.Cp(-300), "e7e5")])
    report = app.analyze_game(first_game("1. f3 *"), engine, depth=10)
    assert report["moves"][0]["label"] == "blunder"


@needs_chess
def test_improving_the_position_is_never_a_loss():
    engine = FakeEngine([(chess.engine.Cp(0), "e2e4"), (chess.engine.Cp(500), "e7e5")])
    report = app.analyze_game(first_game("1. e4 *"), engine, depth=10)
    assert report["moves"][0]["loss"] == 0 and report["moves"][0]["label"] == "best"


@needs_chess
def test_mate_score_is_clamped_and_reported():
    engine = FakeEngine([(chess.engine.Cp(0), "e2e4"), (chess.engine.Mate(3), "d1h5")])
    move = app.analyze_game(first_game("1. e4 *"), engine, depth=10)["moves"][0]
    assert (move["eval"], move["mate"]) == (app.CLAMP_CP, 3)


@needs_chess
def test_checkmate_needs_no_engine_call():
    # Mat du fou : à la fin, la partie est terminée et Stockfish n'est pas appelé.
    engine = FakeEngine([
        (chess.engine.Cp(20), "e2e4"),
        (chess.engine.Cp(-20), "e7e5"),
        (chess.engine.Cp(-30), "d2d4"),
        (chess.engine.Mate(-1), "d8h4"),
    ])
    report = app.analyze_game(first_game("1. f3 e5 2. g4 Qh4#"), engine, depth=10)
    last = report["moves"][-1]
    assert last["san"] == "Qh4#"
    assert last["eval"] == -app.CLAMP_CP and last["mate"] is None
    assert engine.script == []  # toutes les évaluations prévues ont été utilisées, aucune de plus


# --- Requêtes complètes avec un faux Stockfish ---------------------------------------------


class FakeEngineContext:
    def __init__(self, engine):
        self.engine = engine

    def __enter__(self):
        return self.engine

    def __exit__(self, *exc):
        return False


@pytest.fixture
def fake_stockfish(monkeypatch):
    evals = [(chess.engine.Cp(30), "e2e4")] * 20
    monkeypatch.setattr(app, "find_stockfish", lambda: "/faux/stockfish")
    monkeypatch.setattr(app, "open_stockfish", lambda path: FakeEngineContext(FakeEngine(evals)))


@needs_chess
def test_games_request_lists_the_games():
    result = app.games_request({"pgn": '[White "Alice"]\n[Black "Bob"]\n\n1. e4 e5 *\n\n[White "C"]\n\n1. d4 *'})
    assert [(g["white"], g["plies"]) for g in result["games"]] == [("Alice", 2), ("C", 1)]


@needs_chess
@pytest.mark.parametrize(
    "extra, code",
    [({"game": 5}, "BAD_GAME_INDEX"), ({"game": -1}, "BAD_GAME_INDEX"), ({"game": True}, "BAD_GAME_INDEX"),
     ({"depth": 0}, "BAD_DEPTH"), ({"depth": 999}, "BAD_DEPTH"), ({"depth": "12"}, "BAD_DEPTH")],
)
@needs_chess
def test_bad_analyze_parameters_are_400(extra, code):
    with pytest.raises(app.AppError) as error:
        app.analyze_request({"pgn": "1. e4 *", **extra})
    assert (error.value.status, error.value.code) == (400, code)


@needs_chess
def test_too_long_game_is_refused(monkeypatch):
    monkeypatch.setattr(app, "MAX_PLIES", 3)
    with pytest.raises(app.AppError) as error:
        app.analyze_request({"pgn": "1. e4 e5 2. Nf3 Nc6 *"})
    assert error.value.code == "GAME_TOO_LONG"


@needs_chess
def test_missing_stockfish_is_a_503(monkeypatch):
    monkeypatch.setattr(app, "find_stockfish", lambda: None)
    with pytest.raises(app.AppError) as error:
        app.analyze_request({"pgn": "1. e4 *"})
    assert (error.value.status, error.value.code) == (503, "STOCKFISH_NOT_FOUND")


@needs_chess
def test_engine_crash_is_a_503(monkeypatch):
    class Crashing:
        def analyse(self, board, limit):
            raise chess.engine.EngineTerminatedError("plantage")

    monkeypatch.setattr(app, "find_stockfish", lambda: "/faux/stockfish")
    monkeypatch.setattr(app, "open_stockfish", lambda path: FakeEngineContext(Crashing()))
    with pytest.raises(app.AppError) as error:
        app.analyze_request({"pgn": "1. e4 *"})
    assert (error.value.status, error.value.code) == (503, "STOCKFISH_CRASHED")


@needs_chess
def test_full_http_round_trip(server, fake_stockfish):
    status, payload = call(server, "POST", "/api/analyze", {"pgn": SCHOLARS_MATE, "game": 0, "depth": 8})
    game = json.loads(payload)["game"]
    assert status == 200
    assert [m["san"] for m in game["moves"]][-1] == "Qxf7#"
    assert game["white"] == "?" and game["index"] == 0


@needs_chess
def test_http_error_hides_internal_details(server, monkeypatch):
    def boom(data):
        raise RuntimeError("secret interne")

    monkeypatch.setitem(app.ROUTES, "/api/games", boom)
    status, payload = call(server, "POST", "/api/games", {"pgn": "1. e4 *"})
    assert (status, error_code(payload)) == (500, "INTERNAL_ERROR")
    assert b"secret interne" not in payload


# --- Avec le vrai Stockfish ---------------------------------------------------------------


@pytest.mark.skipif(app.find_stockfish() is None, reason="Stockfish introuvable (définis STOCKFISH_PATH)")
def test_real_stockfish_finds_the_scholars_mate():
    # Les Blancs peuvent mater en un coup avec Dxf7.
    board = chess.Board("r1bqkb1r/pppp1ppp/2n2n2/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR w KQkq - 4 4")
    with app.open_stockfish(app.find_stockfish()) as engine:
        cp, mate, best = app.evaluate(board, engine, depth=8)
    assert mate == 1
    assert best.uci() == "h5f7"
