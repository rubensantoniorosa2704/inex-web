"""
inex_web/search.py — Busca com índice invertido por prefixo de palavra (Python puro).

Build: ~1.5s para 76k entradas.
Busca: <5ms (interseção de sets por token prefix).

Não casa substring falso (ex: "usp" não casa "esuspe"),
pois faz match por início de palavra tokenizada.
"""

import time
from collections import defaultdict
from inex_web.db import get_db


_INDEX: list[dict] = []
_PREFIX_MAP: dict[str, set[int]] = defaultdict(set)
_READY = False


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
    """Constrói índice invertido em memória. ~1.5s para 76k docs."""
    global _INDEX, _PREFIX_MAP, _READY

    if _READY:
        return

    start = time.perf_counter()
    con = get_db()

    # IES
    ies_rows = con.execute("""
        SELECT d.co_ies, d.no_ies_atual, h.sg_ies, d.no_municipio,
               d.sg_uf, d.org_academica_atual, d.categoria_adm_atual,
               g.igc_faixa, g.igc_continuo
        FROM dim_ies d
        LEFT JOIN (
            SELECT co_ies, sg_ies,
                   ROW_NUMBER() OVER (PARTITION BY co_ies ORDER BY ano DESC) as rn
            FROM hist_ies WHERE sg_ies IS NOT NULL
        ) h ON d.co_ies = h.co_ies AND h.rn = 1
        LEFT JOIN (
            SELECT co_ies, igc_faixa, igc_continuo,
                   ROW_NUMBER() OVER (PARTITION BY co_ies ORDER BY ano DESC) as rn
            FROM fact_igc
        ) g ON d.co_ies = g.co_ies AND g.rn = 1
    """).fetchall()

    for row in ies_rows:
        co_ies, nome, sigla, municipio, uf, org, categoria, igc_faixa, igc_continuo = row
        tokens = _tokenize(nome, sigla, municipio, uf, org)
        idx = len(_INDEX)
        _INDEX.append({
            "tipo": "ies",
            "co_ies": co_ies,
            "co_curso": None,
            "tokens": tokens,
            "nome": nome,
            "sigla": sigla,
            "municipio": municipio,
            "uf": uf,
            "org": org,
            "categoria": categoria,
            "igc_faixa": igc_faixa,
            "igc_continuo": igc_continuo,
            "nota": None,
            "percentil": None,
        })
        for tok in tokens:
            _PREFIX_MAP[tok].add(idx)

    # Cursos
    curso_rows = con.execute("""
        SELECT cr.co_ies, cr.co_curso, cr.no_curso, cr.no_municipio, cr.sg_uf,
               d.no_ies_atual, h.sg_ies, d.org_academica_atual,
               e.nt_ger_media, e.percentil_grupo
        FROM (
            SELECT co_ies, co_curso, no_curso, no_municipio, sg_uf,
                   ROW_NUMBER() OVER (PARTITION BY co_ies, co_curso ORDER BY ano DESC) as rn
            FROM fact_censo_cursos WHERE no_curso IS NOT NULL
        ) cr
        JOIN dim_ies d ON cr.co_ies = d.co_ies
        LEFT JOIN (
            SELECT co_ies, sg_ies,
                   ROW_NUMBER() OVER (PARTITION BY co_ies ORDER BY ano DESC) as rn
            FROM hist_ies WHERE sg_ies IS NOT NULL
        ) h ON cr.co_ies = h.co_ies AND h.rn = 1
        LEFT JOIN (
            SELECT co_ies, co_curso, nt_ger_media, percentil_grupo,
                   ROW_NUMBER() OVER (PARTITION BY co_ies, co_curso ORDER BY ano DESC) as rn
            FROM fact_enade WHERE qt_presentes > 0
        ) e ON cr.co_ies = e.co_ies AND cr.co_curso = e.co_curso AND e.rn = 1
        WHERE cr.rn = 1
    """).fetchall()

    for row in curso_rows:
        co_ies, co_curso, no_curso, municipio, uf, no_ies, sigla, org, nota, percentil = row
        tokens = _tokenize(no_curso, no_ies, sigla, municipio, uf)
        idx = len(_INDEX)
        _INDEX.append({
            "tipo": "curso",
            "co_ies": co_ies,
            "co_curso": co_curso,
            "tokens": tokens,
            "nome": no_curso,
            "sigla": sigla,
            "municipio": municipio,
            "uf": uf,
            "org": org,
            "categoria": None,
            "igc_faixa": None,
            "igc_continuo": None,
            "nota": nota,
            "percentil": percentil,
        })
        for tok in tokens:
            _PREFIX_MAP[tok].add(idx)

    elapsed = time.perf_counter() - start
    _READY = True
    print(f"Índice de busca: {len(_INDEX):,} entradas, {len(_PREFIX_MAP):,} tokens ({elapsed:.1f}s)")


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
        if tipo and entry["tipo"] != tipo:
            continue
        results.append(entry)

    results.sort(key=lambda r: (
        0 if r["tipo"] == "ies" else 1,
        -(r["igc_faixa"] or 0),
        -(r["nota"] or 0),
    ))

    return results[offset:offset + limite]
