#!/usr/bin/env python3
"""
build_index.py — Gera idx_busca.parquet a partir dos Parquets gold.

Roda localmente (ou no CI) quando os dados mudam.
Executa os JOINs pesados uma única vez e salva o resultado desnormalizado.

Uso:
    python build_index.py
"""

import time
from pathlib import Path

import duckdb

DATA_DIR = Path(__file__).parent / "data"
OUTPUT = DATA_DIR / "idx_busca.parquet"


def main():
    start = time.perf_counter()
    con = duckdb.connect(":memory:")

    # Registrar views dos Parquets
    for f in DATA_DIR.glob("*.parquet"):
        if f.name == "idx_busca.parquet":
            continue
        con.execute(f"CREATE VIEW {f.stem} AS SELECT * FROM read_parquet('{f}')")

    # IES desnormalizado
    con.execute("""
        CREATE TABLE idx_ies AS
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
    """)

    # Cursos desnormalizado
    con.execute("""
        CREATE TABLE idx_cursos AS
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

    # Unir e exportar
    con.execute(f"""
        COPY (
            SELECT * FROM idx_ies
            UNION ALL
            SELECT * FROM idx_cursos
        ) TO '{OUTPUT}' (FORMAT PARQUET, COMPRESSION ZSTD)
    """)

    # Stats
    count = con.execute(f"SELECT COUNT(*) FROM read_parquet('{OUTPUT}')").fetchone()[0]
    size_mb = OUTPUT.stat().st_size / 1024 / 1024
    elapsed = time.perf_counter() - start

    print(f"✓ {OUTPUT.name}: {count:,} registros, {size_mb:.1f} MB ({elapsed:.1f}s)")


if __name__ == "__main__":
    main()
