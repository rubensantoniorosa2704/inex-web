"""
inex_web/search.py — Busca com índice invertido por prefixo de palavra.

Carrega a tabela idx_busca do inex.duckdb (gerado por build_db.py).
Build: ~0.3-0.5s para 76k entradas (leitura direta, sem JOINs).
Busca: <5ms (interseção de sets por token prefix).
"""

import time
from collections import defaultdict

from inex_web.db import get_db

_INDEX: list[tuple] = []
_PREFIX_MAP: dict[str, set[int]] = defaultdict(set)
_READY = False

# Campos na ordem da tuple: tipo, co_ies, co_curso, nome, sigla, municipio, uf, org,
#                            categoria, igc_faixa, igc_continuo, nota, percentil
_FIELDS = ("tipo", "co_ies", "co_curso", "nome", "sigla", "municipio", "uf", "org",
            "categoria", "igc_faixa", "igc_continuo", "nota", "percentil")


def _tokenize(*fields) -> set[str]:
    """Extrai tokens lowercase de campos textuais."""
    tokens = set()
    for field in fields:
        if field:
            for word in str(field).lower().split():
                word = word.strip(".,;:()[]'\"–-")
                if word and len(word) >= 2:
                    tokens.add(word)
    return tokens


def build_index() -> None:
    """Carrega idx_busca do banco e constrói índice invertido. ~0.3-0.5s para 76k docs."""
    global _INDEX, _PREFIX_MAP, _READY

    if _READY:
        return

    start = time.perf_counter()

    con = get_db()
    rows = con.execute("""
        SELECT tipo, co_ies, co_curso, nome, sigla, municipio, uf, org,
               categoria, igc_faixa, igc_continuo, nota, percentil
        FROM idx_busca
    """).fetchall()

    index = []
    prefix_map: dict[str, set[int]] = defaultdict(set)

    for row in rows:
        # row: (tipo, co_ies, co_curso, nome, sigla, municipio, uf, org, ...)
        nome = row[3]
        sigla = row[4]
        municipio = row[5]
        uf = row[6]
        org = row[7]

        tokens = _tokenize(nome, sigla, municipio, uf, org)
        idx = len(index)
        index.append(row)
        for tok in tokens:
            prefix_map[tok].add(idx)

    _INDEX = index
    _PREFIX_MAP = prefix_map
    _READY = True

    elapsed = time.perf_counter() - start
    print(f"Índice de busca: {len(_INDEX):,} entradas, {len(_PREFIX_MAP):,} tokens ({elapsed:.1f}s)")


def _row_to_dict(row: tuple) -> dict:
    """Converte tuple do índice pra dict (usado no retorno)."""
    return dict(zip(_FIELDS, row))


def search(termo: str, limite: int = 10, offset: int = 0, tipo: str | None = None) -> list[dict]:
    """
    Busca por prefixo de palavra. Cada termo do usuário casa com tokens
    que começam com aquele prefixo. Todos os termos devem casar (AND).
    Retorna ordenado: IES primeiro (por IGC desc), depois cursos (por nota desc).
    """
    if not _READY:
        build_index()

    termos = [t.strip().lower() for t in termo.split() if len(t.strip()) >= 2]
    if not termos:
        return []

    # Para cada termo, juntar indices de todos os tokens que começam com ele
    candidate_sets = []
    for t in termos:
        matches = set()
        for token, indices in _PREFIX_MAP.items():
            if token.startswith(t):
                matches |= indices
        candidate_sets.append(matches)
        if not matches:
            return []

    # Interseção: docs que casam com TODOS os termos
    result_indices = candidate_sets[0]
    for s in candidate_sets[1:]:
        result_indices &= s

    if not result_indices:
        return []

    # Filtrar por tipo e ordenar
    results = []
    for idx in result_indices:
        entry = _INDEX[idx]
        entry_tipo = entry[0]  # tipo
        if tipo and entry_tipo != tipo:
            continue
        results.append(entry)

    results.sort(key=lambda r: (
        0 if r[0] == "ies" else 1,      # tipo
        -(r[9] or 0),                     # igc_faixa
        -(r[11] or 0),                    # nota
    ))

    return [_row_to_dict(r) for r in results[offset:offset + limite]]
