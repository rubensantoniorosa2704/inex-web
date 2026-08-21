#!/usr/bin/env python3
"""
build_db.py — Gera data/inex.duckdb a partir dos Parquets gold.

Materializa todas as tabelas + índice de busca desnormalizado.
Roda localmente ou no CI quando os dados mudam.

Pré-requisitos:
    - Parquets gold em data/ (copiados do inex-pipelines)

Uso:
    python build_db.py

O resultado é data/inex.duckdb (~80-100MB), usado pelo app Flask.
"""

import time
from pathlib import Path

import duckdb

DATA_DIR = Path(__file__).parent / "data"
DB_FILE = DATA_DIR / "inex.duckdb"


def main():
    start = time.perf_counter()

    # Remover banco anterior se existir
    if DB_FILE.exists():
        DB_FILE.unlink()

    parquets = [f for f in sorted(DATA_DIR.glob("*.parquet")) if f.name != "idx_busca.parquet"]
    if not parquets:
        print("❌ Nenhum Parquet encontrado em data/. Copie os gold do inex-pipelines.")
        print("   Ex: cp -r /caminho/para/inex-pipelines/data/gold/* data/")
        raise SystemExit(1)

    con = duckdb.connect(str(DB_FILE))

    # ─────────────────────────────────────────────────────────────────────
    # 1. Materializar todos os Parquets como tabelas
    # ─────────────────────────────────────────────────────────────────────
    print("Materializando tabelas...")
    for f in parquets:
        name = f.stem
        con.execute(f"CREATE TABLE {name} AS SELECT * FROM read_parquet('{f}')")
        count = con.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
        print(f"  {name}: {count:,} linhas")

    # ─────────────────────────────────────────────────────────────────────
    # 2. Criar índice de busca desnormalizado
    # ─────────────────────────────────────────────────────────────────────
    print("Criando índice de busca...")
    con.execute("""
        CREATE TABLE idx_busca AS
        -- IES
        SELECT
            'ies' AS tipo,
            d.co_ies,
            NULL::INTEGER AS co_curso,
            d.no_ies_atual AS nome,
            h.sg_ies AS sigla,
            d.no_municipio AS municipio,
            d.sg_uf AS uf,
            d.org_academica_atual AS org,
            d.categoria_adm_atual AS categoria,
            g.igc_faixa,
            g.igc_continuo,
            NULL::DOUBLE AS nota,
            NULL::DOUBLE AS percentil
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

        UNION ALL

        -- Cursos
        SELECT
            'curso' AS tipo,
            cr.co_ies,
            cr.co_curso,
            cr.no_curso AS nome,
            h.sg_ies AS sigla,
            cr.no_municipio AS municipio,
            cr.sg_uf AS uf,
            d.org_academica_atual AS org,
            NULL::VARCHAR AS categoria,
            NULL::INTEGER AS igc_faixa,
            NULL::DOUBLE AS igc_continuo,
            e.nt_ger_media AS nota,
            e.percentil_grupo AS percentil
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
    """)

    idx_count = con.execute("SELECT COUNT(*) FROM idx_busca").fetchone()[0]
    print(f"  idx_busca: {idx_count:,} linhas")

    con.close()

    # Stats
    size_mb = DB_FILE.stat().st_size / 1024 / 1024
    elapsed = time.perf_counter() - start
    print(f"\n✓ {DB_FILE.name}: {size_mb:.1f} MB ({elapsed:.1f}s)")


if __name__ == "__main__":
    main()
