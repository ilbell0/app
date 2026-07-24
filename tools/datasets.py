# -*- coding: utf-8 -*-
"""Utilità condivise per i dataset tattici.

I dataset vivono come letterali Python in backend/server.py (fonte di verità)
e vengono esportati in frontend/src/data/*.json per l'app offline.
"""
import ast
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER_PY = os.path.join(ROOT, "backend", "server.py")
DATA_DIR = os.path.join(ROOT, "frontend", "src", "data")

# nome variabile in server.py -> nome file JSON (senza estensione)
DATASETS = {
    "FORMATIONS": "formations",
    "COUNTER_ENGINE": "counterEngine",
    "COUNTER_QUICK": "counterQuick",
    "MATCHUP_MATRIX": "matchupMatrix",
    "SCOUT_TIPS": "scoutTips",
    "PLAYER_ROLES": "playerRoles",
    "META_TACTICS": "metaTactics",
    "SPECIAL_ABILITIES": "specialAbilities",
    "TRAINING_GUIDE": "trainingGuide",
    "ARROW_TACTICS": "arrowTactics",
    "REAL_TEAMS": "realTeams",
    "SEASON_STORIES": "seasonStories",
    "FAQ": "faq",
    "ABBREVIATIONS": "abbreviations",
    "CAREER_PATHS": "careerPaths",
    "MY_PLAYBOOK": "myPlaybook",
    "SET_PIECE": "setPiece",
    "BATTLE_CARDS": "battleCards",
    "GAME_GUIDE": "gameGuide",
    "FORMATION_LAB": "formationLab",
    "REAL_TACTICS": "realTactics",
}

# dataset derivati/di servizio: restano in server.py e nei JSON (per validatore e
# motore counter) ma NON vengono esportati in index.ts, quindi Metro non li
# include nel bundle dell'app (nessuna schermata li usa piu').
FRONTEND_EXCLUDE = {"COUNTER_QUICK", "MATCHUP_MATRIX", "ARROW_TACTICS",
                    "REAL_TEAMS", "SEASON_STORIES"}


def read_server_text():
    with open(SERVER_PY, encoding="utf-8") as f:
        return f.read()


def extract_assignments(text=None):
    """Ritorna {nome: (valore, nodo_ast)} per ogni dataset in server.py."""
    if text is None:
        text = read_server_text()
    tree = ast.parse(text)
    found = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            t = node.targets[0]
            if isinstance(t, ast.Name) and t.id in DATASETS:
                found[t.id] = (ast.literal_eval(node.value), node)
    missing = set(DATASETS) - set(found)
    if missing:
        raise RuntimeError(f"Dataset non trovati in server.py: {sorted(missing)}")
    return found


def load_datasets_from_server():
    return {k: v for k, (v, _) in extract_assignments().items()}


def load_json(name):
    with open(os.path.join(DATA_DIR, f"{name}.json"), encoding="utf-8") as f:
        return json.load(f)


def py_literal(obj, indent=0, step=4):
    """Serializza obj come letterale Python leggibile (dict/list/str/num/bool/None)."""
    pad = " " * indent
    pad2 = " " * (indent + step)
    if isinstance(obj, dict):
        if not obj:
            return "{}"
        items = [f"{pad2}{py_literal(k)}: {py_literal(v, indent + step, step)}" for k, v in obj.items()]
        return "{\n" + ",\n".join(items) + f"\n{pad}}}"
    if isinstance(obj, list):
        if not obj:
            return "[]"
        simple = all(isinstance(x, (str, int, float, bool)) or x is None for x in obj)
        if simple and sum(len(repr(x)) for x in obj) < 80:
            return "[" + ", ".join(py_literal(x) for x in obj) + "]"
        items = [f"{pad2}{py_literal(x, indent + step, step)}" for x in obj]
        return "[\n" + ",\n".join(items) + f"\n{pad}]"
    if obj is True:
        return "True"
    if obj is False:
        return "False"
    if obj is None:
        return "None"
    return repr(obj)


def replace_assignment(text, name, new_value):
    """Sostituisce il letterale di `name` in server.py con new_value. Ritorna il nuovo testo."""
    assigns = extract_assignments(text)
    _, node = assigns[name]
    lines = text.splitlines(keepends=True)
    start = node.lineno - 1          # riga di "NAME = ["
    end = node.end_lineno            # ultima riga del letterale (1-based, inclusiva)
    block = f"{name} = {py_literal(new_value)}\n"
    new_text = "".join(lines[:start]) + block + "".join(lines[end:])
    ast.parse(new_text)  # validazione: il file deve restare Python valido
    return new_text


def write_server_text(text):
    ast.parse(text)
    with open(SERVER_PY, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
