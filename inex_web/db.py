"""
inex_web/db.py — Conexão DuckDB e queries nomeadas.

Lê os Parquets gold diretamente. Todas as queries retornam listas de dicts.
"""

from pathlib import Path

import duckdb

DATA_DIR = Path(__file__).parent.parent / "data"


def _conn() -> duckdb.DuckDBPyConnection:
    """Cria conexão DuckDB in-memory com tabelas indexadas a partir dos Parquets."""
    con = duckdb.connect(":memory:", read_only=False)
    # Carregar parquets como tabelas (permite criação de índices)
    for f in DATA_DIR.glob("*.parquet"):
        name = f.stem
        con.execute(f"CREATE TABLE {name} AS SELECT * FROM read_parquet('{f}')")

    # Índices nas tabelas grandes usadas em JOINs e filtros frequentes
    con.execute("CREATE INDEX idx_fact_censo_cursos_ies ON fact_censo_cursos (co_ies, co_curso, ano)")
    con.execute("CREATE INDEX idx_fact_enade_ies ON fact_enade (co_ies, co_curso, ano)")
    con.execute("CREATE INDEX idx_fact_enade_perfil_pk ON fact_enade_perfil (co_ies, co_curso, ano)")
    con.execute("CREATE INDEX idx_fact_cpc_ies ON fact_cpc (co_ies, ano)")
    return con


# Conexão singleton (reusada entre requests)
_db: duckdb.DuckDBPyConnection | None = None


def get_db() -> duckdb.DuckDBPyConnection:
    global _db
    if _db is None:
        _db = _conn()
    return _db


def query(sql: str, params: list | None = None) -> list[dict]:
    """Executa query e retorna lista de dicts."""
    con = get_db()
    if params:
        result = con.execute(sql, params)
    else:
        result = con.execute(sql)
    columns = [desc[0] for desc in result.description]
    rows = result.fetchall()
    return [dict(zip(columns, row)) for row in rows]


# ─────────────────────────────────────────────────────────────────────────────
# Queries nomeadas
# ─────────────────────────────────────────────────────────────────────────────


def buscar_ies(termo: str, limite: int = 15) -> list[dict]:
    """Busca IES por nome ou sigla (fuzzy via ILIKE)."""
    termos = [t.strip() for t in termo.split() if t.strip()]
    if not termos:
        return []

    # Busca no nome atual OU na sigla (via hist_ies, mais recente)
    where_clauses = " AND ".join([
        f"(d.no_ies_atual ILIKE '%' || ${i+1} || '%' OR h.sg_ies ILIKE '%' || ${i+1} || '%'"
        f" OR d.no_municipio ILIKE '%' || ${i+1} || '%')"
        for i in range(len(termos))
    ])

    sql = f"""
        SELECT d.co_ies, d.no_ies_atual, d.sg_uf, d.org_academica_atual,
               d.categoria_adm_atual, d.no_municipio,
               h.sg_ies,
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
        WHERE {where_clauses}
        ORDER BY g.igc_faixa DESC NULLS LAST, d.no_ies_atual
        LIMIT {limite}
    """
    return query(sql, termos)


def buscar_cursos(termo: str, limite: int = 15) -> list[dict]:
    """Busca cursos por nome, cidade, IES ou sigla."""
    termos = [t.strip() for t in termo.split() if t.strip()]
    if not termos:
        return []

    where_clauses = " AND ".join([
        f"(cr.no_curso ILIKE '%' || ${i+1} || '%'"
        f" OR cr.no_municipio ILIKE '%' || ${i+1} || '%'"
        f" OR d.no_ies_atual ILIKE '%' || ${i+1} || '%'"
        f" OR h.sg_ies ILIKE '%' || ${i+1} || '%')"
        for i in range(len(termos))
    ])

    sql = f"""
        WITH cursos_recentes AS (
            SELECT c.co_ies, c.co_curso, c.no_curso, c.no_municipio, c.sg_uf,
                   c.ano,
                   ROW_NUMBER() OVER (PARTITION BY c.co_ies, c.co_curso ORDER BY c.ano DESC) as rn
            FROM fact_censo_cursos c
            WHERE c.no_curso IS NOT NULL
        )
        SELECT cr.co_ies, cr.co_curso, cr.no_curso, cr.no_municipio, cr.sg_uf,
               d.no_ies_atual, d.org_academica_atual,
               e.nt_ger_media, e.percentil_grupo, e.ano as ano_enade
        FROM cursos_recentes cr
        JOIN dim_ies d ON cr.co_ies = d.co_ies
        LEFT JOIN (
            SELECT co_ies, sg_ies,
                   ROW_NUMBER() OVER (PARTITION BY co_ies ORDER BY ano DESC) as rn
            FROM hist_ies WHERE sg_ies IS NOT NULL
        ) h ON cr.co_ies = h.co_ies AND h.rn = 1
        LEFT JOIN (
            SELECT co_ies, co_curso, nt_ger_media, percentil_grupo, ano,
                   ROW_NUMBER() OVER (PARTITION BY co_ies, co_curso ORDER BY ano DESC) as rn
            FROM fact_enade
            WHERE qt_presentes > 0
        ) e ON cr.co_ies = e.co_ies AND cr.co_curso = e.co_curso AND e.rn = 1
        WHERE cr.rn = 1 AND {where_clauses}
        ORDER BY e.nt_ger_media DESC NULLS LAST
        LIMIT {limite}
    """
    return query(sql, termos)


def buscar(termo: str, limite: int = 10) -> dict:
    """Busca unificada: retorna IES e cursos."""
    return {
        "ies": buscar_ies(termo, limite=limite),
        "cursos": buscar_cursos(termo, limite=limite),
    }


def get_ies(co_ies: int) -> dict | None:
    """Retorna dados de uma IES."""
    rows = query("""
        SELECT * FROM dim_ies WHERE co_ies = $1
    """, [co_ies])
    return rows[0] if rows else None


def get_ies_igc(co_ies: int) -> list[dict]:
    """Histórico de IGC de uma IES."""
    return query("""
        SELECT ano, igc_continuo, igc_faixa, qt_cursos_cpc,
               conceito_graduacao, conceito_mestrado
        FROM fact_igc
        WHERE co_ies = $1
        ORDER BY ano
    """, [co_ies])


def get_ies_enade(co_ies: int) -> list[dict]:
    """Cursos avaliados pelo ENADE (mais recente de cada curso, top 10 por nota)."""
    return query("""
        WITH ultimo_por_curso AS (
            SELECT e.co_curso, e.ano, e.co_grupo, e.qt_inscritos, e.qt_presentes,
                   e.tx_participacao, e.nt_ger_media, e.nt_fg_media, e.nt_ce_media,
                   e.percentil_grupo,
                   ROW_NUMBER() OVER (PARTITION BY e.co_curso ORDER BY e.ano DESC) as rn
            FROM fact_enade e
            WHERE e.co_ies = $1 AND e.qt_presentes > 0
        )
        SELECT u.co_curso, u.ano, u.co_grupo, u.qt_inscritos, u.qt_presentes,
               u.tx_participacao, u.nt_ger_media, u.nt_fg_media, u.nt_ce_media,
               u.percentil_grupo, c.no_curso
        FROM ultimo_por_curso u
        LEFT JOIN (
            SELECT co_ies, co_curso, no_curso,
                   ROW_NUMBER() OVER (PARTITION BY co_ies, co_curso ORDER BY ano DESC) as rn
            FROM fact_censo_cursos
        ) c ON c.co_ies = $1 AND u.co_curso = c.co_curso AND c.rn = 1
        WHERE u.rn = 1
        ORDER BY u.nt_ger_media DESC NULLS LAST
        LIMIT 10
    """, [co_ies])


def get_ies_enade_todos(co_ies: int) -> list[dict]:
    """Todos os cursos-ano ENADE de uma IES (para pagina expandida)."""
    return query("""
        SELECT e.co_curso, e.ano, e.co_grupo, e.qt_inscritos, e.qt_presentes,
               e.tx_participacao, e.nt_ger_media, e.nt_fg_media, e.nt_ce_media,
               e.percentil_grupo,
               c.no_curso
        FROM fact_enade e
        LEFT JOIN (
            SELECT co_ies, co_curso, no_curso,
                   ROW_NUMBER() OVER (PARTITION BY co_ies, co_curso ORDER BY ano DESC) as rn
            FROM fact_censo_cursos
        ) c ON e.co_ies = c.co_ies AND e.co_curso = c.co_curso AND c.rn = 1
        WHERE e.co_ies = $1 AND e.qt_presentes > 0
        ORDER BY e.ano DESC, e.nt_ger_media DESC
    """, [co_ies])


def get_ies_cpc(co_ies: int) -> list[dict]:
    """Histórico de CPC por curso."""
    return query("""
        SELECT ano, area_avaliacao, cpc_continuo, cpc_faixa,
               enade_continuo, qt_participantes, co_curso
        FROM fact_cpc
        WHERE co_ies = $1
        ORDER BY ano DESC, area_avaliacao
    """, [co_ies])


def get_ies_censo(co_ies: int) -> list[dict]:
    """Evolução de vagas e matrículas."""
    return query("""
        SELECT ano,
               SUM(qt_vg_total) as vagas,
               SUM(qt_ing) as ingressantes,
               SUM(qt_mat) as matriculas,
               SUM(qt_conc) as concluintes,
               COUNT(*) as cursos
        FROM fact_censo_cursos
        WHERE co_ies = $1
        GROUP BY ano
        ORDER BY ano
    """, [co_ies])


def get_ies_ranking_uf(co_ies: int, ano: int | None = None) -> dict | None:
    """Posição da IES no ranking do estado (IGC)."""
    if ano is None:
        # Pegar ano mais recente
        rows = query("SELECT MAX(ano) as ano FROM fact_igc WHERE co_ies = $1", [co_ies])
        if not rows or rows[0]["ano"] is None:
            return None
        ano = rows[0]["ano"]

    rows = query("""
        WITH ies_info AS (
            SELECT sg_uf FROM dim_ies WHERE co_ies = $1
        ),
        ranking AS (
            SELECT f.co_ies, f.igc_continuo,
                   RANK() OVER (ORDER BY f.igc_continuo DESC) as posicao,
                   COUNT(*) OVER () as total
            FROM fact_igc f
            JOIN dim_ies d ON f.co_ies = d.co_ies
            WHERE f.ano = $2 AND d.sg_uf = (SELECT sg_uf FROM ies_info)
        )
        SELECT posicao, total, igc_continuo FROM ranking WHERE co_ies = $1
    """, [co_ies, ano])
    if rows:
        rows[0]["ano"] = ano
    return rows[0] if rows else None


def get_curso(co_ies: int, co_curso: int) -> list[dict]:
    """Histórico ENADE de um curso específico."""
    return query("""
        SELECT e.ano, e.qt_inscritos, e.qt_presentes, e.tx_participacao,
               e.nt_ger_media, e.nt_fg_media, e.nt_ce_media,
               e.nt_ger_dp, e.percentil_grupo
        FROM fact_enade e
        WHERE e.co_ies = $1 AND e.co_curso = $2
        ORDER BY e.ano
    """, [co_ies, co_curso])


def get_curso_perfil(co_ies: int, co_curso: int, ano: int) -> dict | None:
    """Perfil socioeconômico de um curso em um ano."""
    rows = query("""
        SELECT * FROM fact_enade_perfil
        WHERE co_ies = $1 AND co_curso = $2 AND ano = $3
    """, [co_ies, co_curso, ano])
    return rows[0] if rows else None


def get_dados_disponiveis() -> list[dict]:
    """Lista parquets disponíveis para download."""
    files = []
    for f in sorted(DATA_DIR.glob("*.parquet")):
        size_mb = f.stat().st_size / 1024 / 1024
        files.append({
            "nome": f.stem,
            "arquivo": f.name,
            "tamanho_mb": round(size_mb, 1),
        })
    return files
