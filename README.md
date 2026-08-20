# inex-web

Portal público de indicadores do ensino superior brasileiro.

Consulta interativa dos dados processados pelo [inex-pipelines](https://github.com/rubensantoniorosa2704/inex-pipelines), derivados dos microdados públicos do [INEP/MEC](https://www.gov.br/inep).

## Stack

- **Python + Flask** — servidor web
- **DuckDB** — consultas nos Parquets gold
- **Jinja2** — templates HTML
- **HTMX** — interatividade mínima (busca sem reload)
- **CSS classless** — estilização sem framework

Zero build step. Zero npm. Funciona sem JavaScript (degrada graciosamente).

## Rodar localmente

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .

# Copiar os parquets gold para data/
cp -r /caminho/para/inex-pipelines/data/gold data/

# Rodar
flask --app inex_web run --debug
```

Acesse http://localhost:5000

## Estrutura

```
inex_web/
  app.py              → aplicação Flask, rotas
  db.py               → conexão DuckDB, queries
  templates/
    base.html         → layout comum
    home.html         → página inicial (busca)
    busca.html        → resultados da busca
    ies.html          → página da IES
    curso.html        → página do curso
    sobre.html        → sobre o projeto
    dados.html        → download dos dados
    _partials/
      resultados.html → fragmento HTMX dos resultados
  static/
    style.css         → estilos próprios (mínimo)
data/
  *.parquet           → gold tables (não versionados, vêm do inex-pipelines)
```

## Dados

Os Parquets gold estão disponíveis para download direto em `/dados`.
Licença: [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).

Para dados oficiais, consulte [gov.br/inep](https://www.gov.br/inep).

## Licença

Código: [MIT](LICENSE)
Dados derivados: [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)
