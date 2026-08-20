"""
inex_web/app.py — Aplicação Flask do portal INEX.
"""

import os

from flask import Flask, render_template, request, send_from_directory, abort
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from inex_web.db import (
    buscar,
    get_ies,
    get_ies_igc,
    get_ies_enade,
    get_ies_enade_todos,
    get_ies_cpc,
    get_ies_censo,
    get_ies_ranking_uf,
    get_curso,
    get_curso_perfil,
    get_dados_disponiveis,
    DATA_DIR,
)
from inex_web.search import build_index, search
from inex_web.charts import line_chart, bar_chart_horizontal, stacked_bar, faixa_badge

app = Flask(__name__)

# Config via variáveis de ambiente (sem segredos no código)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-insecure-change-me')
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 3600

# Rate limiting — proteção contra abuso
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["60 per minute"],  # global: 60 req/min por IP
    storage_uri="memory://",
)

# Registrar helpers de gráfico como funções globais do Jinja
app.jinja_env.globals.update(
    line_chart=line_chart,
    bar_chart_horizontal=bar_chart_horizontal,
    stacked_bar=stacked_bar,
    faixa_badge=faixa_badge,
)

# Construir índice de busca no startup
with app.app_context():
    build_index()


@app.after_request
def security_headers(response):
    """Headers de segurança e cache em todas as respostas."""
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    if request.is_secure:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    # Cache de páginas HTML por 5 min (browser guarda, botão voltar instantâneo)
    if response.content_type and "text/html" in response.content_type:
        response.headers["Cache-Control"] = "public, max-age=300"
    return response


@app.route("/busca_comparar")
@limiter.limit("20 per minute")
def busca_comparar():
    """Retorna resultados de busca formatados como links de comparação."""
    q = request.args.get("q_b", "").strip()
    a = request.args.get("a", "")

    if not q or len(q) < 2:
        return ""

    resultados = search(q, limite=5, tipo="ies")

    html_parts = ['<ul class="results-list">']
    for r in resultados:
        if str(r["co_ies"]) == a:
            continue
        link = f'/comparar?a={a}&b={r["co_ies"]}'
        nome = r["nome"]
        sigla = f' ({r["sigla"]})' if r.get("sigla") else ""
        meta = f'{r["org"]} · {r["municipio"]}/{r["uf"]}'
        html_parts.append(
            f'<li><a href="{link}"><strong>{nome}</strong>{sigla}'
            f'<span class="meta">{meta}</span></a></li>'
        )
    html_parts.append("</ul>")

    if len([r for r in resultados if str(r["co_ies"]) != a]) == 0:
        return '<p class="meta">Nenhum resultado.</p>'

    return "\n".join(html_parts)


@app.route("/robots.txt")
def robots():
    content = """# INEX — Indicadores do Ensino Superior
# Permitir buscadores principais, limitar crawl rate

User-agent: Googlebot
Allow: /
Crawl-delay: 2

User-agent: Bingbot
Allow: /
Crawl-delay: 2

User-agent: *
Allow: /
Allow: /ies/
Allow: /sobre
Allow: /dados
Disallow: /busca
Disallow: /busca_comparar
Disallow: /comparar
Disallow: /ies/*/cursos?*
Crawl-delay: 10

Sitemap: /sitemap.txt
"""
    return content, 200, {"Content-Type": "text/plain"}


_sitemap_cache: str | None = None

@app.route("/sitemap.txt")
def sitemap():
    """Sitemap simples em formato texto (cacheado em memória)."""
    global _sitemap_cache
    if _sitemap_cache is not None:
        return _sitemap_cache, 200, {"Content-Type": "text/plain"}

    from inex_web.db import query as db_query

    base = request.host_url.rstrip("/")
    lines = [
        base + "/",
        base + "/sobre",
        base + "/dados",
    ]

    ies_list = db_query("SELECT co_ies FROM dim_ies ORDER BY co_ies")
    for row in ies_list:
        lines.append(f"{base}/ies/{row['co_ies']}")

    _sitemap_cache = "\n".join(lines)
    return _sitemap_cache, 200, {"Content-Type": "text/plain"}


@app.route("/")
def home():
    return render_template("home.html")


@app.route("/busca")
@limiter.limit("30 per minute")
def busca_page():
    q = request.args.get("q", "").strip()
    if not q:
        # HTMX: retorna fragmento vazio (limpa os resultados)
        if request.headers.get("HX-Request"):
            return ""
        return render_template("busca.html", resultados={"ies": [], "cursos": [], "page": 1, "total_pages": 0, "page_range": [], "q": ""}, q="")

    # Validar paginação
    try:
        page = max(1, int(request.args.get("p", 1)))
    except (ValueError, TypeError):
        page = 1

    # Limitar tamanho da query (previne abuso)
    q = q[:100]

    limite = 10
    offset = (page - 1) * limite

    resultados = search(q, limite=limite + 1, offset=offset)  # +1 to check if more

    has_more = len(resultados) > limite
    if has_more:
        resultados = resultados[:limite]

    # Separar em IES e cursos
    ies_results = [r for r in resultados if r["tipo"] == "ies"]
    curso_results = [r for r in resultados if r["tipo"] == "curso"]

    # Calcular total de páginas (busca completa sem limite pra contar)
    total_results = len(search(q, limite=1000))
    total_pages = max(1, (total_results + limite - 1) // limite)

    # Range de páginas pra exibir (max 7 ao redor da atual)
    page_start = max(1, page - 3)
    page_end = min(total_pages, page + 3)
    page_range = list(range(page_start, page_end + 1))

    data = {
        "ies": ies_results,
        "cursos": curso_results,
        "page": page,
        "total_pages": total_pages,
        "page_range": page_range,
        "q": q,
    }

    # Se requisição HTMX, retorna só o fragmento
    if request.headers.get("HX-Request"):
        return render_template("_partials/resultados.html", resultados=data, q=q)

    return render_template("busca.html", resultados=data, q=q)


@app.route("/ies/<int:co_ies>")
def pagina_ies(co_ies: int):
    ies = get_ies(co_ies)
    if not ies:
        abort(404)

    igc = get_ies_igc(co_ies)
    enade = get_ies_enade(co_ies)
    cpc = get_ies_cpc(co_ies)
    censo = get_ies_censo(co_ies)
    ranking = get_ies_ranking_uf(co_ies)

    return render_template(
        "ies.html",
        ies=ies,
        igc=igc,
        enade=enade,
        cpc=cpc,
        censo=censo,
        ranking=ranking,
    )


@app.route("/ies/<int:co_ies>/cursos")
def pagina_ies_cursos(co_ies: int):
    ies = get_ies(co_ies)
    if not ies:
        abort(404)

    ano_param = request.args.get("ano", "")
    ordem = request.args.get("ordem", "nota")

    # Whitelist de ordens válidas
    if ordem not in ("nota", "nome", "ano"):
        ordem = "nota"

    enade = get_ies_enade_todos(co_ies)

    # Anos disponíveis
    anos_disponiveis = sorted(set(e["ano"] for e in enade), reverse=True)

    # Filtrar por ano se selecionado; senão mostrar só o mais recente de cada curso
    if ano_param and ano_param != "todos":
        try:
            ano_filtro = int(ano_param)
            enade = [e for e in enade if e["ano"] == ano_filtro]
        except ValueError:
            pass
    elif ano_param != "todos":
        # Default: mais recente de cada curso
        seen = set()
        filtrado = []
        for e in enade:  # já vem ordenado por ano DESC
            if e["co_curso"] not in seen:
                seen.add(e["co_curso"])
                filtrado.append(e)
        enade = filtrado

    # Ordenar
    if ordem == "nome":
        enade = sorted(enade, key=lambda e: (e.get("no_curso") or "zzz").lower())
    elif ordem == "nota":
        enade = sorted(enade, key=lambda e: -(e.get("nt_ger_media") or 0))
    elif ordem == "ano":
        enade = sorted(enade, key=lambda e: -e["ano"])

    return render_template(
        "ies_cursos.html",
        ies=ies,
        enade=enade,
        anos_disponiveis=anos_disponiveis,
        ano_selecionado=ano_param,
        ordem=ordem,
    )


@app.route("/ies/<int:co_ies>/curso/<int:co_curso>")
def pagina_curso(co_ies: int, co_curso: int):
    ies = get_ies(co_ies)
    if not ies:
        abort(404)

    historico = get_curso(co_ies, co_curso)

    # Nome do curso (via censo)
    from inex_web.db import query as db_query
    nome_rows = db_query("""
        SELECT no_curso FROM fact_censo_cursos
        WHERE co_ies = $1 AND co_curso = $2
        ORDER BY ano DESC LIMIT 1
    """, [co_ies, co_curso])
    curso_nome = nome_rows[0]["no_curso"] if nome_rows else f"Curso {co_curso}"

    # Se não tem ENADE, mostrar dados do censo ao menos
    censo_curso = None
    if not historico:
        censo_rows = db_query("""
            SELECT ano, qt_vg_total as vagas, qt_ing as ingressantes,
                   qt_mat as matriculas, qt_conc as concluintes
            FROM fact_censo_cursos
            WHERE co_ies = $1 AND co_curso = $2
            ORDER BY ano
        """, [co_ies, co_curso])
        censo_curso = censo_rows if censo_rows else None
        if not censo_curso:
            abort(404)

    # Pegar perfil do ano mais recente
    perfil = None
    if historico:
        ano_recente = historico[-1]["ano"]
        perfil = get_curso_perfil(co_ies, co_curso, ano_recente)

    return render_template(
        "curso.html",
        ies=ies,
        co_curso=co_curso,
        curso_nome=curso_nome,
        historico=historico,
        perfil=perfil,
        censo_curso=censo_curso,
    )


@app.route("/comparar")
def comparar():
    """Compara dois cursos ou duas IES. Params: a=co_ies:co_curso, b=co_ies:co_curso (ou a=co_ies, b=co_ies para IES)"""
    from inex_web.db import query as db_query

    a_param = request.args.get("a", "")
    b_param = request.args.get("b", "")

    if not a_param or not b_param:
        return render_template("comparar_form.html")

    def parse_param(param):
        parts = param.split(":")
        try:
            if len(parts) == 2:
                return int(parts[0]), int(parts[1])  # IES:curso
            elif len(parts) == 1:
                return int(parts[0]), None  # só IES
        except ValueError:
            pass
        return None, None

    a_ies, a_curso = parse_param(a_param)
    b_ies, b_curso = parse_param(b_param)

    if not a_ies or not b_ies:
        abort(400)

    # Comparação de IES (sem curso específico)
    if a_curso is None and b_curso is None:
        ies_a = get_ies(a_ies)
        ies_b = get_ies(b_ies)
        if not ies_a or not ies_b:
            abort(404)
        igc_a = get_ies_igc(a_ies)
        igc_b = get_ies_igc(b_ies)
        censo_a = get_ies_censo(a_ies)
        censo_b = get_ies_censo(b_ies)
        return render_template("comparar_ies.html",
                               ies_a=ies_a, ies_b=ies_b,
                               igc_a=igc_a, igc_b=igc_b,
                               censo_a=censo_a, censo_b=censo_b)

    # Comparação de cursos
    def get_curso_info(co_ies, co_curso):
        ies = get_ies(co_ies)
        historico = get_curso(co_ies, co_curso)
        nome_rows = db_query("""
            SELECT no_curso FROM fact_censo_cursos
            WHERE co_ies = $1 AND co_curso = $2
            ORDER BY ano DESC LIMIT 1
        """, [co_ies, co_curso])
        nome = nome_rows[0]["no_curso"] if nome_rows else f"Curso {co_curso}"
        perfil = None
        if historico:
            perfil = get_curso_perfil(co_ies, co_curso, historico[-1]["ano"])
        return {"ies": ies, "nome": nome, "historico": historico, "perfil": perfil,
                "co_ies": co_ies, "co_curso": co_curso}

    curso_a = get_curso_info(a_ies, a_curso)
    curso_b = get_curso_info(b_ies, b_curso)

    return render_template("comparar.html", curso_a=curso_a, curso_b=curso_b)


@app.route("/sobre")
def sobre():
    return render_template("sobre.html")


@app.route("/dados")
def dados():
    arquivos = get_dados_disponiveis()
    return render_template("dados.html", arquivos=arquivos)


@app.route("/dados/<filename>")
@limiter.limit("5 per minute")
def download_dado(filename: str):
    # Validar: só parquets, sem path traversal
    if not filename.endswith(".parquet") or "/" in filename or ".." in filename:
        abort(404)
    return send_from_directory(DATA_DIR, filename, as_attachment=True)
