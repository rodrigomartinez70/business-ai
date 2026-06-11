"""
Helpers de render HTML compartidos por los dashboards de todos los verticales.
"""

from src.agents._common import fmt_moneda

_CSS = """
body{margin:0;background:#f4f5f7;font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;color:#1a1a1a;}
.wrap{max-width:760px;margin:0 auto;padding:24px 16px;}
.head{text-align:center;padding:8px 0 20px;}
.head h1{margin:0;font-size:22px;}
.head .sub{color:#6b7280;font-size:13px;margin-top:4px;}
.card{background:#fff;border:1px solid #e5e7eb;border-radius:10px;margin:0 0 16px;overflow:hidden;}
.card>h2{margin:0;padding:12px 16px;font-size:15px;background:#1f2937;color:#fff;}
.card .body{padding:14px 16px;}
.kpis{width:100%;border-collapse:collapse;}
.kpis td{padding:6px 8px;font-size:13px;border-bottom:1px solid #f0f0f0;vertical-align:top;}
.kpis td.k{color:#6b7280;width:55%;}
.kpis td.v{text-align:right;font-weight:600;}
.attn{border-radius:10px;padding:4px 0;margin:0 0 16px;}
.attn.ok{background:#ecfdf5;border:1px solid #a7f3d0;}
.attn.bad{background:#fef2f2;border:1px solid #fecaca;}
.attn h2{margin:0;padding:12px 16px;font-size:15px;}
.attn.ok h2{color:#047857;}
.attn.bad h2{color:#b91c1c;}
.attn ul{margin:0;padding:4px 16px 12px 34px;}
.attn li{font-size:13px;margin:4px 0;}
.tag{display:inline-block;font-size:11px;font-weight:700;padding:1px 7px;border-radius:10px;color:#fff;margin-right:6px;}
.tag.c{background:#dc2626;} .tag.a{background:#f59e0b;}
.ins{background:#eef2ff;border-left:3px solid #6366f1;border-radius:4px;padding:8px 12px;margin-top:10px;}
.ins .t{font-size:12px;font-weight:700;color:#4338ca;margin-bottom:4px;}
.ins li{font-size:12px;margin:3px 0;color:#3730a3;}
table.dt{width:100%;border-collapse:collapse;margin-top:8px;}
table.dt th,table.dt td{font-size:12px;padding:4px 6px;border-bottom:1px solid #eee;text-align:right;}
table.dt th:first-child,table.dt td:first-child{text-align:left;}
table.dt th{color:#6b7280;font-weight:600;}
.pos{color:#047857;} .neg{color:#b91c1c;}
.foot{text-align:center;color:#9ca3af;font-size:11px;padding:8px 0 0;}
"""


def _fm(v, cfg):
    s = fmt_moneda(v, cfg)
    try:
        neg = float(v) < 0
    except (TypeError, ValueError):
        neg = False
    return f'<span style="color:#dc2626;">{s}</span>' if neg else s


def _kpis(rows: list[tuple[str, str]]) -> str:
    trs = "".join(f'<tr><td class="k">{k}</td><td class="v">{v}</td></tr>' for k, v in rows)
    return f'<table class="kpis">{trs}</table>'


def _card(titulo: str, body: str) -> str:
    return f'<div class="card"><h2>{titulo}</h2><div class="body">{body}</div></div>'


def _subt(titulo: str) -> str:
    """Encabezado de subsección dentro de una tarjeta."""
    return (f'<div style="margin-top:14px;margin-bottom:4px;font-size:12px;'
            f'font-weight:700;color:#374151;border-bottom:1px solid #e5e7eb;'
            f'padding-bottom:4px;">{titulo}</div>')


def _aviso(nivel: str, titulo: str, desc: str, extra: str = "") -> str:
    """Caja de alerta/inconsistencia coloreada por nivel."""
    bg     = "#fef2f2" if nivel == "critico" else "#fffbeb" if nivel == "alerta" else "#eff6ff"
    border = "#dc2626" if nivel == "critico" else "#f59e0b" if nivel == "alerta" else "#3b82f6"
    ico    = "🚨" if nivel == "critico" else "⚠️" if nivel == "alerta" else "ℹ️"
    extra_html = (f'<div style="font-size:11px;color:#9ca3af;margin-top:4px;'
                  f'font-style:italic;">{extra}</div>') if extra else ""
    return (f'<div style="margin:8px 0;padding:8px;background:{bg};'
            f'border-left:3px solid {border};border-radius:4px;">'
            f'<div style="font-weight:600;font-size:13px;">{ico} {titulo}</div>'
            f'<div style="font-size:12px;color:#6b7280;margin-top:3px;">{desc}</div>'
            f'{extra_html}</div>')


_MESES_ABBR = {1: "ene", 2: "feb", 3: "mar", 4: "abr", 5: "may", 6: "jun",
               7: "jul", 8: "ago", 9: "sep", 10: "oct", 11: "nov", 12: "dic"}


def renderizar_ipc_html(ipc: dict | None) -> str:
    """
    Gráfico de barras (CSS puro) de la variación mensual del IPC de Chile,
    con eje cero real: los meses con inflación crecen hacia arriba y los de
    deflación hacia abajo del eje. Horizontal — usado por todos los verticales.
    """
    if not ipc or not ipc.get("serie"):
        return ""
    serie    = ipc["serie"]
    valores  = [p["valor"] for p in serie]
    escala   = max((abs(v) for v in valores), default=0) or 1
    alto_max = 46  # px por cada mitad (arriba del eje / abajo del eje)

    pos_cells = neg_cells = eje_cells = mes_cells = ""
    for p in serie:
        v   = p["valor"]
        mes = _MESES_ABBR.get(int(p["mes"][5:7]), p["mes"][5:7])
        if v > 0:   # inflación → barra hacia arriba (celda superior, pegada al eje)
            h = max(2, round(v / escala * alto_max))
            pos_cells += (
                '<td style="vertical-align:bottom;text-align:center;padding:0 2px;">'
                f'<div style="font-size:9px;color:#6b7280;">{v:+.1f}</div>'
                f'<div style="height:{h}px;background:#F39C12;border-radius:2px 2px 0 0;"></div></td>'
            )
            neg_cells += '<td></td>'
        elif v < 0:  # deflación → barra hacia abajo (celda inferior, pegada al eje)
            h = max(2, round(abs(v) / escala * alto_max))
            pos_cells += '<td></td>'
            neg_cells += (
                '<td style="vertical-align:top;text-align:center;padding:0 2px;">'
                f'<div style="height:{h}px;background:#3b82f6;border-radius:0 0 2px 2px;"></div>'
                f'<div style="font-size:9px;color:#6b7280;">{v:+.1f}</div></td>'
            )
        else:        # 0.0 → marca sobre el eje
            pos_cells += ('<td style="vertical-align:bottom;text-align:center;">'
                          '<div style="font-size:9px;color:#9ca3af;">0.0</div></td>')
            neg_cells += '<td></td>'
        eje_cells += '<td style="border-top:2px solid #cbd5e1;font-size:0;line-height:0;">&nbsp;</td>'
        mes_cells += f'<td style="text-align:center;font-size:9px;color:#9ca3af;padding-top:3px;">{mes}</td>'

    acum = ipc.get("acumulado_pct")
    sub  = (f"Inflación mensual (última medición): <b>{acum:+.1f}%</b> · "
            if acum is not None else "")
    body = (
        f'<div style="font-size:12px;color:#6b7280;margin-bottom:8px;">'
        f'{sub}variación mensual (%) · fuente: {ipc["fuente"]}</div>'
        '<table style="width:100%;border-collapse:collapse;table-layout:fixed;">'
        f'<tr style="height:{alto_max + 12}px">{pos_cells}</tr>'
        f'<tr>{eje_cells}</tr>'
        f'<tr style="height:{alto_max + 12}px">{neg_cells}</tr>'
        f'<tr>{mes_cells}</tr>'
        '</table>'
    )
    return _card("📉 Contexto económico — Inflación Chile", body)
