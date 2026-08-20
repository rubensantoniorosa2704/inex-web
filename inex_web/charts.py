"""
inex_web/charts.py — Geração de gráficos SVG inline (zero dependências).

Cada função retorna uma string SVG que pode ser inserida direto no template.
"""

from markupsafe import Markup


def line_chart(
    data: list[dict],
    x_key: str,
    y_key: str,
    width: int = 500,
    height: int = 150,
    color: str = "#0645ad",
    label: str = "",
) -> Markup:
    """
    Gráfico de linha simples.
    data: lista de dicts com x_key (label) e y_key (valor numérico).
    """
    values = [(d[x_key], d[y_key]) for d in data if d[y_key] is not None]
    if len(values) < 2:
        return Markup("")

    padding_x = 40
    padding_y = 25
    chart_w = width - padding_x * 2
    chart_h = height - padding_y * 2

    y_vals = [v[1] for v in values]
    y_min = min(y_vals)
    y_max = max(y_vals)
    y_range = y_max - y_min if y_max != y_min else 1

    # Normalizar pontos
    points = []
    for i, (x_label, y_val) in enumerate(values):
        px = padding_x + (i / (len(values) - 1)) * chart_w
        py = padding_y + (1 - (y_val - y_min) / y_range) * chart_h
        points.append((px, py, x_label, y_val))

    # Construir SVG
    polyline = " ".join(f"{p[0]:.1f},{p[1]:.1f}" for p in points)

    svg_parts = [
        f'<svg viewBox="0 0 {width} {height}" class="chart line-chart"'
        f' xmlns="http://www.w3.org/2000/svg" role="img" aria-label="{label}">',
        # Eixo X (linha base)
        f'<line x1="{padding_x}" y1="{height - padding_y}" '
        f'x2="{width - padding_x}" y2="{height - padding_y}" '
        f'stroke="#ccc" stroke-width="1"/>',
        # Linha do gráfico
        f'<polyline points="{polyline}" fill="none" stroke="{color}" stroke-width="2"/>',
    ]

    # Pontos e labels
    for i, (px, py, x_label, y_val) in enumerate(points):
        svg_parts.append(
            f'<circle cx="{px:.1f}" cy="{py:.1f}" r="3" fill="{color}"/>'
        )
        # Label X (apenas alguns para não poluir)
        if i == 0 or i == len(points) - 1 or i % max(1, len(points) // 5) == 0:
            svg_parts.append(
                f'<text x="{px:.1f}" y="{height - 5}" text-anchor="middle" '
                f'font-size="10" fill="#555">{x_label}</text>'
            )
        # Valor no ponto (primeiro e último)
        if i == 0 or i == len(points) - 1:
            svg_parts.append(
                f'<text x="{px:.1f}" y="{py - 8:.1f}" text-anchor="middle" '
                f'font-size="10" fill="{color}" font-weight="bold">{y_val:.1f}</text>'
            )

    # Label Y min/max
    svg_parts.append(
        f'<text x="{padding_x - 5}" y="{padding_y + 4}" text-anchor="end" '
        f'font-size="9" fill="#999">{y_max:.1f}</text>'
    )
    svg_parts.append(
        f'<text x="{padding_x - 5}" y="{height - padding_y + 4}" text-anchor="end" '
        f'font-size="9" fill="#999">{y_min:.1f}</text>'
    )

    svg_parts.append("</svg>")
    return Markup("\n".join(svg_parts))


def bar_chart_horizontal(
    data: list[dict],
    label_key: str,
    value_key: str,
    width: int = 500,
    height: int | None = None,
    color: str = "#0645ad",
    max_val: float | None = None,
    format_value: str = "{:.1f}",
) -> Markup:
    """
    Gráfico de barras horizontais.
    data: lista de dicts com label_key e value_key.
    Cor degrada do mais escuro (maior valor) ao mais claro (menor valor).
    """
    items = [(d[label_key], d[value_key]) for d in data if d[value_key] is not None]
    if not items:
        return Markup("")

    bar_height = 22
    gap = 6
    padding_left = 160
    padding_right = 60
    padding_y = 10

    if height is None:
        height = padding_y * 2 + len(items) * (bar_height + gap)

    chart_w = width - padding_left - padding_right
    if max_val is None:
        max_val = max(v for _, v in items) or 1

    # Calcular range de valores pra gradiente
    values = [v for _, v in items]
    v_min = min(values) if values else 0
    v_max = max(values) if values else 1
    v_range = v_max - v_min if v_max != v_min else 1

    svg_parts = [
        f'<svg viewBox="0 0 {width} {height}" class="chart bar-chart"'
        f' xmlns="http://www.w3.org/2000/svg">',
    ]

    for i, (label, value) in enumerate(items):
        y = padding_y + i * (bar_height + gap)
        bar_w = (value / max_val) * chart_w if max_val > 0 else 0

        # Gradiente: azul escuro (maior) → azul claro (menor)
        t = (value - v_min) / v_range  # 0=menor, 1=maior
        r = int(180 + (20 - 180) * t)
        g = int(210 + (60 - 210) * t)
        b = int(240 + (140 - 240) * t)
        bar_color = f"rgb({r}, {g}, {b})"

        # Label
        svg_parts.append(
            f'<text x="{padding_left - 8}" y="{y + bar_height / 2 + 4}" '
            f'text-anchor="end" font-size="11" fill="#333">{label}</text>'
        )
        # Bar
        svg_parts.append(
            f'<rect x="{padding_left}" y="{y}" width="{bar_w:.1f}" '
            f'height="{bar_height}" fill="{bar_color}" rx="2"/>'
        )
        # Value
        formatted = format_value.format(value)
        svg_parts.append(
            f'<text x="{padding_left + bar_w + 5:.1f}" y="{y + bar_height / 2 + 4}" '
            f'font-size="11" fill="#555">{formatted}</text>'
        )

    svg_parts.append("</svg>")
    return Markup("\n".join(svg_parts))


def stacked_bar(
    segments: list[tuple[str, float, str]],
    width: int = 400,
    height: int = 30,
) -> Markup:
    """
    Barra empilhada horizontal (100%).
    segments: lista de (label, proporção 0-1, cor).
    """
    if not segments:
        return Markup("")

    # Palette sóbria: tons de cinza/azul
    svg_parts = [
        f'<svg viewBox="0 0 {width} {height + 20}" class="chart stacked-bar"'
        f' xmlns="http://www.w3.org/2000/svg">',
    ]

    x = 0
    for label, proportion, color in segments:
        if proportion <= 0:
            continue
        seg_w = proportion * width
        svg_parts.append(
            f'<rect x="{x:.1f}" y="0" width="{seg_w:.1f}" '
            f'height="{height}" fill="{color}" />'
        )
        # Label inside if big enough
        if seg_w > 30:
            pct = f"{proportion * 100:.0f}%"
            svg_parts.append(
                f'<text x="{x + seg_w / 2:.1f}" y="{height / 2 + 4}" '
                f'text-anchor="middle" font-size="10" fill="white" '
                f'font-weight="bold">{pct}</text>'
            )
        x += seg_w

    svg_parts.append("</svg>")
    return Markup("\n".join(svg_parts))


def faixa_badge(faixa: int | None, max_faixa: int = 5) -> Markup:
    """Renderiza faixa como estrelas SVG inline. Suporta decimal (ex: 3.7 → 3 cheias + 1 parcial + 1 vazia)."""
    if faixa is None:
        return Markup('<span class="faixa-badge">—</span>')

    faixa_f = float(faixa)

    # SVG path de uma estrela 5 pontas (16x16 viewbox)
    star_path = "M8 0l2.5 5.1 5.5.8-4 3.9.9 5.5L8 12.9l-4.9 2.4.9-5.5-4-3.9 5.5-.8z"

    stars = ""
    for i in range(1, max_faixa + 1):
        if faixa_f >= i:
            # Cheia — preto
            stars += (
                f'<svg class="star-icon" viewBox="0 0 16 16" width="14" height="14">'
                f'<path d="{star_path}" fill="#1a1a1a"/></svg>'
            )
        elif faixa_f > i - 1:
            # Parcial — usar clip pra preencher proporcionalmente
            pct = (faixa_f - (i - 1)) * 100
            clip_id = f"clip-{id(faixa)}-{i}"
            stars += (
                f'<svg class="star-icon" viewBox="0 0 16 16" width="14" height="14">'
                f'<defs><clipPath id="{clip_id}"><rect x="0" y="0" width="{pct:.0f}%" height="16"/></clipPath></defs>'
                f'<path d="{star_path}" fill="#ccc"/>'
                f'<path d="{star_path}" fill="#1a1a1a" clip-path="url(#{clip_id})"/>'
                f'</svg>'
            )
        else:
            # Vazia — cinza claro
            stars += (
                f'<svg class="star-icon" viewBox="0 0 16 16" width="14" height="14">'
                f'<path d="{star_path}" fill="#ccc"/></svg>'
            )

    return Markup(f'<span class="faixa-badge">{stars}</span>')
