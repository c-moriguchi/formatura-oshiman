import os
import io
import csv
import re
import datetime
import urllib.parse

import streamlit as st
import pandas as pd
import requests

from supabase import create_client
from reportlab.lib.pagesizes import A4
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table,
                                TableStyle, HRFlowable)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors

import financeiro as F

# ─── CONFIGURAÇÃO (nomes/ano fora do código) ─────────────────────────────────
def _secrets_get(key: str, default=""):
    """Leitura segura de secrets: retorna default quando não há secrets configurados
    (ex.: modo demonstração ou máquina sem ~/.streamlit/secrets.toml)."""
    try:
        return st.secrets.get(key, default)
    except Exception:
        return default


@st.cache_data
def config() -> dict:
    return {
        "nome_comissao": _secrets_get("NOME_COMISSAO", "Formatura Oshiman 2028"),
        "nome_curto": _secrets_get("NOME_CURTO", "Oshiman 2028"),
    }
CFG = config()

# ─── PAGE CONFIG ────────────────────────────────────────────────────────────
st.set_page_config(page_title=CFG["nome_curto"], layout="centered",
                   page_icon="🎓", initial_sidebar_state="collapsed")

# ─── SUPABASE (service_role — nunca exposta ao browser) ─────────────────────
def _demo_ativo() -> bool:
    if os.environ.get("DEMO") == "1":
        return True
    return not (_secrets_get("SUPABASE_URL") and _secrets_get("SUPABASE_SERVICE_KEY"))


@st.cache_resource
def get_supabase():
    if _demo_ativo():
        import mock_db
        return mock_db.create_mock_client()
    return create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_SERVICE_KEY"])


def db():
    return get_supabase()


# ─── CSS ────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
[data-testid="stAppViewContainer"] { background:#f7f6f3; }
[data-testid="stHeader"]  { display:none; }
[data-testid="stSidebar"] { display:none; }
.block-container { padding:1rem 1rem 4rem; max-width:760px; }

.stat-row { display:flex; gap:10px; margin-bottom:18px; flex-wrap:wrap; }
.stat-card { flex:1; min-width:130px; background:white;
    border:1px solid #e2e0d8; border-radius:10px; padding:14px; text-align:center; }
.stat-card .lbl { font-size:11px; color:#8a877e; text-transform:uppercase;
    letter-spacing:.04em; font-weight:600; }
.stat-card .val { font-size:20px; font-weight:700; margin-top:4px; }
.green  { color:#2d6a4f; }
.red    { color:#b91c1c; }
.orange { color:#92400e; }
.blue   { color:#1e40af; }

/* Card de aluno ativo */
.aluno-card { background:white; border:1px solid #e2e0d8;
    border-radius:10px; padding:14px 16px; margin-bottom:10px; }
/* Card de desistente — cinza, sempre no final */
.aluno-card-inativo { background:#fafafa; border:1px solid #e8e6de;
    border-radius:10px; padding:14px 16px; margin-bottom:10px; opacity:.75; }
.aluno-nome  { font-weight:600; font-size:15px; margin-bottom:2px; }
.aluno-nome-inativo { font-weight:500; font-size:15px; margin-bottom:2px; color:#8a877e; }
.aluno-sub   { font-size:12px; color:#8a877e; margin-bottom:8px; }
.wa-ico { text-decoration:none; margin-left:7px; font-size:16px; opacity:.85; }
.wa-ico:hover { opacity:1; }

.progress { height:8px; background:#e9e7e0; border-radius:6px;
    overflow:hidden; margin:6px 0 12px; }
.progress > div { height:100%; background:#2d6a4f; border-radius:6px; }
.progress-hint { font-size:12px; color:#8a877e; margin-bottom:10px; }

.badge { display:inline-block; padding:3px 10px; border-radius:20px;
    font-size:12px; font-weight:600; }
.badge-green  { background:#e8f4ef; color:#1b4332; }
.badge-red    { background:#fef2f2; color:#b91c1c; }
.badge-gray   { background:#f0efe9; color:#5a5850; }
.badge-warn   { background:#fffbeb; color:#92400e; }
.badge-blue   { background:#eff6ff; color:#1e40af; }

.sec-title { font-size:13px; font-weight:600; color:#5a5850;
    text-transform:uppercase; letter-spacing:.05em;
    margin:20px 0 10px; border-bottom:1px solid #e2e0d8; padding-bottom:6px; }

.top-nav { display:flex; align-items:center; justify-content:space-between;
    background:#1b4332; color:white; padding:12px 16px;
    border-radius:10px; margin-bottom:20px; }
.top-nav h3 { margin:0; font-size:16px; }
.top-nav span { font-size:12px; opacity:.75; }

.info-box  { background:#eff6ff; border:1px solid #bfdbfe; border-radius:8px;
    padding:12px 14px; font-size:13px; color:#1e40af; margin-bottom:14px; }
.warn-box  { background:#fffbeb; border:1px solid #fde68a; border-radius:8px;
    padding:12px 14px; font-size:13px; color:#92400e; margin-bottom:14px; }
.draft-box { background:#fefce8; border:2px solid #facc15; border-radius:10px;
    padding:16px; margin-bottom:16px; }
.draft-box h4 { margin:0 0 6px; color:#78350f; font-size:15px; }
.draft-box p  { margin:0; font-size:13px; color:#92400e; }

/* Tabela HTML responsiva (substitui st.dataframe no mobile) */
.table-wrap { overflow-x:auto; -webkit-overflow-scrolling:touch; border-radius:8px; }
table.tbl { width:100%; border-collapse:collapse; background:white;
    font-size:13px; border:1px solid #e2e0d8; min-width:520px; }
table.tbl th { background:#1b4332; color:white; padding:8px 10px; text-align:left;
    font-size:12px; font-weight:600; }
table.tbl td { padding:8px 10px; border-bottom:1px solid #eee9e0; }
table.tbl td.num, table.tbl th.num { text-align:right; }
table.tbl tr:nth-child(even) td { background:#faf8f4; }
table.tbl td.empty { text-align:center; color:#8a877e; padding:14px; }

#MainMenu, footer { visibility:hidden; }
.stButton > button { width:100%; border-radius:8px !important;
    padding:.55rem 1rem !important; font-size:14px !important; }
.stTabs [data-baseweb="tab"] { font-size:13px; color:#374151; }
.stTabs [data-baseweb="tab"][aria-selected="true"] { color:#1b4332; font-weight:700; }

/* Mobile-first */
@media (max-width: 640px) {
  .block-container { padding:.6rem .6rem 3rem; }
  .stat-card { min-width:calc(50% - 10px); padding:12px 8px; }
  .stat-card .lbl { font-size:10px; }
  .stat-card .val { font-size:18px; }
  .top-nav { padding:10px 12px; }
  table.tbl { font-size:12px; min-width:0; }
  table.tbl td, table.tbl th { padding:7px 8px; }
  .stTabs [data-baseweb="tab"] { font-size:12px; }
}
</style>
""", unsafe_allow_html=True)


# ─── HELPERS DE TELA ────────────────────────────────────────────────────────
def render_table(headers, rows, right_align=(), empty="Nenhum dado.") -> str:
    """Tabela HTML responsiva — funciona bem no celular, ao contrário de st.dataframe."""
    thead = "".join(
        f'<th class="num">{h}</th>' if i in right_align else f"<th>{h}</th>"
        for i, h in enumerate(headers))
    body = ""
    for r in rows:
        tds = []
        for ci, val in enumerate(r):
            cls = ' class="num"' if ci in right_align else ""
            tds.append(f"<td{cls}>{val}</td>")
        body += "<tr>" + "".join(tds) + "</tr>"
    if not rows:
        body = f'<tr><td class="empty" colspan="{len(headers)}">{empty}</td></tr>'
    return (f'<div class="table-wrap"><table class="tbl">'
            f"<thead><tr>{thead}</tr></thead>"
            f"<tbody>{body}</tbody></table></div>")


def cards(*itens):
    """itens: (lbl, val, cor)."""
    html = '<div class="stat-row">' + "".join(
        f'<div class="stat-card"><div class="lbl">{l}</div>'
        f'<div class="val {c}">{v}</div></div>' for l, v, c in itens) + "</div>"
    st.markdown(html, unsafe_allow_html=True)


def wa_link(cel: str, msg: str) -> str:
    num = re.sub(r"\D", "", cel or "")
    return f"https://wa.me/55{num}?text={urllib.parse.quote(msg)}"


def wa_icon(cel, msg, enabled: bool) -> str:
    """Icone 📲 clicável de WhatsApp, colocado na frente do nome do aluno."""
    if not (enabled and cel):
        return ""
    return (f'<a class="wa-ico" href="{wa_link(cel, msg)}" '
            f'target="_blank" rel="noopener" title="Abrir WhatsApp">📲</a>')


# ─── ACESSO A DADOS ─────────────────────────────────────────────────────────
def get_periodos():
    rows = db().table("periodos").select("de,valor").order("de").execute().data
    return [(r["de"], float(r["valor"])) for r in rows]


def get_alunos():
    return db().table("alunos").select("*").order("turma").order("id").execute().data


def get_transacoes():
    return db().table("transacoes").select(
        "id,data,descricao,valor,categoria,aluno_id,observacao"
    ).order("data", desc=True).execute().data


def get_ultimo_mes_fechado() -> str | None:
    rows = db().table("fechamentos").select("ano_mes").eq("status", "confirmado") \
        .order("ano_mes", desc=True).limit(1).execute().data
    return rows[0]["ano_mes"] if rows else None


def get_fechamento(ym: str) -> dict | None:
    try:
        rows = db().table("fechamentos").select("*").eq("ano_mes", ym).execute().data
        return rows[0] if rows else None
    except Exception as e:
        st.error(f"Erro ao conectar no Supabase: {e}")
        st.stop()


def garantir_draft_mes_anterior():
    mes_anterior = F.prev_ym(F.current_ym())
    if not get_fechamento(mes_anterior):
        try:
            db().table("fechamentos").insert(
                {"ano_mes": mes_anterior, "status": "draft"}).execute()
        except Exception as e:
            st.error(f"Erro ao criar draft: {e}")
            st.stop()


def confirmar_fechamento(ym: str, usuario: str):
    db().table("fechamentos").update({
        "status": "confirmado",
        "confirmado_em": datetime.datetime.utcnow().isoformat(),
        "confirmado_por": usuario,
    }).eq("ano_mes", ym).execute()


def quem_pagou_no_mes(ym: str) -> set:
    """Uma query só: conjunto de aluno_id com mensalidade no mês (corrige N+1)."""
    rows = db().table("transacoes").select("aluno_id").eq("categoria", "MENSALIDADE") \
        .like("data", f"{ym}%").execute().data
    return {r["aluno_id"] for r in rows if r["aluno_id"]}


def get_orcamento():
    return db().table("orcamento").select("id,descricao,data,valor").order("data").execute().data


# ─── WHATSAPP (Meta Cloud API — gratuito) ───────────────────────────────────
def enviar_whatsapp(para: str, mensagem: str) -> bool:
    token = _secrets_get("WA_TOKEN")
    phone_id = _secrets_get("WA_PHONE_ID")
    if not token or not phone_id:
        return False
    num = re.sub(r"\D", "", para)
    resp = requests.post(
        f"https://graph.facebook.com/v19.0/{phone_id}/messages",
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": "application/json"},
        json={"messaging_product": "whatsapp", "to": num, "type": "text",
              "text": {"body": mensagem}},
        timeout=10,
    )
    return resp.status_code == 200


def notificar_tesoureiras(assunto: str, corpo: str):
    numeros = [n.strip() for n in _secrets_get("TESOUREIRAS_WA").split(",") if n.strip()]
    if not numeros:
        return False
    return all(enviar_whatsapp(n, f"🎓 *{assunto}*\\n\\n{corpo}") for n in numeros)


# ─── PDF ────────────────────────────────────────────────────────────────────
def gerar_pdf(ym, periodos, alunos, trans_rows) -> bytes:
    hoje = datetime.date.today().strftime("%d/%m/%Y")
    trans = F.carregar_transacoes_agrupadas(trans_rows)
    rows_ativos, rows_desist = [], []
    total_mensalidades = 0.0
    n_em_dia = n_dev = 0

    for a in alunos:
        calc = F.calcular_aluno(a, periodos, trans, ym)
        if a["status"] == "Inativo":
            rows_desist.append([a["id"], a["nome"], f"Turma {a['turma']}",
                                F.fmt_brl(calc["total_pago"]),
                                F.fmt_brl(calc["devolucao"]),
                                F.fmt_brl(calc["dev_pendente"])])
            continue
        total_mensalidades += calc["total_pago"]
        if calc["saldo"] >= 0:
            n_em_dia += 1
            rows_ativos.append([a["id"], a["nome"], f"Turma {a['turma']}",
                                F.fmt_brl(calc["total_pago"]), "Em dia"])
        else:
            n_dev += 1
            rows_ativos.append([a["id"], a["nome"], f"Turma {a['turma']}",
                                F.fmt_brl(abs(calc["saldo"])), "DEVEDOR"])

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
        rightMargin=36, leftMargin=36, topMargin=36, bottomMargin=36)
    styles = getSampleStyleSheet()
    H1 = ParagraphStyle("H1", parent=styles["Heading1"], fontSize=16,
        textColor=colors.HexColor("#1b4332"), spaceAfter=4)
    H2 = ParagraphStyle("H2", parent=styles["Heading2"], fontSize=12,
        textColor=colors.HexColor("#2d6a4f"), spaceBefore=14, spaceAfter=6)
    SUB = ParagraphStyle("SUB", parent=styles["Normal"], fontSize=9,
        textColor=colors.gray, spaceAfter=8)

    ts_base = TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f9fafb")),
        ("GRID", (0, 0), (-1, -1), .5, colors.HexColor("#e2e0d8")),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
    ])
    ts_al = TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1b4332")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), .5, colors.HexColor("#e2e0d8")),
        ("ALIGN", (3, 1), (3, -1), "RIGHT"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f9fafb")]),
    ])
    for i, r in enumerate(rows_ativos):
        if r[4] == "DEVEDOR":
            ts_al.add("TEXTCOLOR", (3, i + 1), (4, i + 1), colors.HexColor("#b91c1c"))
            ts_al.add("FONTNAME", (3, i + 1), (4, i + 1), "Helvetica-Bold")

    elems = [
        Paragraph(f"🎓 {CFG['nome_comissao']} — Fechamento {F.fmt_mes(ym)}", H1),
        Paragraph(f"Emitido em {hoje}  |  Referência: {F.fmt_mes(ym)}", SUB),
        HRFlowable(width="100%", thickness=1, color=colors.HexColor("#e2e0d8"), spaceAfter=10),
        Paragraph("Resumo financeiro", H2),
        Table([
        ["Total de mensalidades arrecadadas", F.fmt_brl(total_mensalidades)],
        ["Alunos em dia", str(n_em_dia)],
        ["Alunos devedores", str(n_dev)],
    ], colWidths=[300, 160], style=ts_base)]
    elems.append(Spacer(1, 12))
    elems.append(Paragraph("Situação por aluno", H2))
    elems.append(Table([["ID", "Nome", "Turma", "Valor", "Situação"]] + rows_ativos,
                  colWidths=[30, 210, 60, 90, 70], style=ts_al))

    if rows_desist:
        ts_d = TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#5a5850")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("GRID", (0, 0), (-1, -1), .5, colors.HexColor("#e2e0d8")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f9fafb")]),
        ])
        elems += [
            Spacer(1, 12),
            Paragraph("Desistentes — histórico de devoluções", H2),
            Table([["ID", "Aluno", "Turma", "Total pago", "Devolvido", "Pendente"]] + rows_desist,
                  colWidths=[30, 180, 55, 85, 85, 75], style=ts_d),
        ]
    doc.build(elems)
    buf.seek(0)
    return buf.getvalue()


# ─── IMPORT / MATCHING ──────────────────────────────────────────────────────
def parse_csv(texto: str, alunos_ativos: list) -> list:
    linhas = []
    sep = ";" if texto.count(";") > texto.count(",") else ","
    for parts in csv.reader(io.StringIO(texto), delimiter=sep):
        parts = [p.strip().strip("\"'") for p in parts]
        if len(parts) < 3:
            continue
        dm = re.match(r"(\d{2})/(\d{2})/(\d{4})", parts[0])
        if not dm:
            continue
        data = f"{dm.group(3)}-{dm.group(2)}-{dm.group(1)}"
        try:
            valor = float(parts[2].replace(".", "").replace(",", "."))
        except Exception:
            continue
        desc = parts[1]
        if db().table("transacoes").select("id").eq("data", data) \
                .eq("descricao", desc).execute().data:
            continue
        aluno_id, aluno_nome = F.match_aluno(desc, alunos_ativos)
        categoria = F.detecta_categoria(desc, valor, bool(aluno_id))
        linhas.append({"data": data, "descricao": desc, "valor": valor,
                       "aluno_id": aluno_id, "aluno_nome": aluno_nome,
                       "categoria": categoria})
    return linhas


# ─── LOGIN ──────────────────────────────────────────────────────────────────
def tela_login():
    st.markdown(f"""
    <div style="text-align:center;padding:48px 0 24px">
      <div style="font-size:52px">🎓</div>
      <h2 style="margin:8px 0 4px;color:#1b4332">{CFG['nome_comissao']}</h2>
      <p style="color:#8a877e;font-size:14px">Gestão Financeira da Comissão</p>
    </div>
    """, unsafe_allow_html=True)
    perfil = st.selectbox("Perfil de acesso", ["Tesouraria", "Consulta"])
    senha = st.text_input("Senha", type="password")
    if st.button("Entrar", type="primary"):
        chave = "SENHA_TESOURARIA" if perfil == "Tesouraria" else "SENHA_CONSULTA"
        esperada = _secrets_get(chave)
        # No modo demonstração (sem secrets) qualquer senha entra — só p/ testar.
        if senha == esperada or (_demo_ativo() and not esperada):
            st.session_state["perfil"] = perfil
            st.rerun()
        else:
            st.error("Senha incorreta")


# ─── MAIN ───────────────────────────────────────────────────────────────────
if "perfil" not in st.session_state:
    tela_login()
    st.stop()

perfil = st.session_state["perfil"]
is_admin = perfil == "Tesouraria"

if _demo_ativo():
    st.caption("⚙️ *Modo demonstração* (sem Supabase configurado). Os dados são fictícios.")

garantir_draft_mes_anterior()

st.markdown(f"""
<div class="top-nav">
  <h3>🎓 {CFG['nome_curto']}</h3>
  <span>{'🔑 Tesouraria' if is_admin else '👁 Consulta'}</span>
</div>
""", unsafe_allow_html=True)

# Banner de draft pendente (para admin)
if is_admin:
    mes_anterior = F.prev_ym(F.current_ym())
    fech = get_fechamento(mes_anterior)
    if fech and fech["status"] == "draft":
        st.markdown(f"""
        <div class="draft-box">
          <h4>⚠️ Fechamento de {F.fmt_mes(mes_anterior)} aguarda confirmação</h4>
          <p>Revise a situação dos alunos e confirme o fechamento na aba 📄 Fechamento.</p>
        </div>
        """, unsafe_allow_html=True)

if st.button("Sair", type="secondary"):
    del st.session_state["perfil"]
    st.rerun()

tabs = st.tabs(["📊 Visão geral", "📋 Mês corrente", "📊 Situação fechada",
                "📥 Extrato", "📄 Fechamento", "⚙️ Cadastros"])

# Dados carregados uma vez por execução (evita recarregar a cada aba)
periodos = get_periodos()
alunos = get_alunos()


# ─── ABA 0 — VISÃO GERAL (painel de caixa) ─────────────────────────────────
with tabs[0]:
    ate_ym = get_ultimo_mes_fechado() or F.current_ym()
    trans_rows = get_transacoes()
    p = F.calcular_painel(trans_rows, periodos, alunos, ate_ym)

    st.markdown(f'<div class="sec-title">Caixa consolidado</div>', unsafe_allow_html=True)
    cards(
        ("Saldo total", F.fmt_brl(p["patrimonio"]), "green"),
        ("Mensalidades arrecadadas", F.fmt_brl(p["total_mensalidades"]), "blue"),
        ("Inadimplência", F.fmt_brl(p["inadimplencia"]), "red" if p["inadimplencia"] else "green"),
        ("Rendimento acumulado", F.fmt_brl(p["rendimento"]), "orange"),
    )
    st.markdown(
        f'<div class="info-box">Situação de caixa até <b>{F.fmt_mes(ate_ym)}</b>. '
        f'O "saldo total" considera conta corrente + investimento.</div>',
        unsafe_allow_html=True)

    # Saldo conta vs investimento
    st.markdown('<div class="sec-title">Conta corrente × Investimento</div>',
                unsafe_allow_html=True)
    cards(
        ("Em conta corrente", F.fmt_brl(p["saldo_conta"]), "blue"),
        ("Aplicado no investimento", F.fmt_brl(p["saldo_invest"]), "orange"),
        ("Total de aportes", F.fmt_brl(p["aportes"]), "blue"),
        ("Resgates", F.fmt_brl(p["resgates"]), "green"),
    )

    # Arrecadação por ano (meta x atingido)
    st.markdown('<div class="sec-title">Arrecadação por ano</div>', unsafe_allow_html=True)
    rows = []
    for ano, pago in p["arrecadacao_por_ano"].items():
        meta = p["meta_ano"].get(ano, 0.0)
        pct = (pago / meta * 100) if meta else 0.0
        cls = "green" if pct >= 100 else ("orange" if pct >= 70 else "red")
        rows.append([
            ano, F.fmt_brl(pago), F.fmt_brl(meta),
            f'<span class="badge badge-{"green" if cls=="green" else "warn" if cls=="orange" else "red"}">{pct:.0f}%</span>'
        ])
    st.markdown(render_table(
        ["Ano", "Pago", "Meta", "Atingido"], rows,
        right_align=(1, 2)), unsafe_allow_html=True)

    # Orçamento/previsão (se houver tabela)
    itens = get_orcamento()
    if itens:
        st.markdown('<div class="sec-title">Previsão de orçamento</div>', unsafe_allow_html=True)
        rows = [[i["descricao"], i["data"], F.fmt_brl(i["valor"])] for i in itens]
        rows.append(["<b>Total</b>", "", f"<b>{F.fmt_brl(F.total_orcamento(itens))}</b>"])
        st.markdown(render_table(["Item", "Quando", "Valor"], rows,
                                 right_align=(2,)), unsafe_allow_html=True)

    st.caption("Fórmulas: total arrecadado = soma das mensalidades; "
               "saldo conta = soma do extrato; investimento = aportes − resgates. "
               "Confira com o extrato — as contas vivem centralizadas em `financeiro.py`.")


# ─── ABA 1 — MÊS CORRENTE (prévia) ─────────────────────────────────────────
with tabs[1]:
    hoje_ym = F.current_ym()
    ativos = [a for a in alunos if a["status"] == "Ativo"]

    st.markdown(f'<div class="sec-title">Prévia — {F.fmt_mes(hoje_ym)}</div>',
                unsafe_allow_html=True)
    st.markdown("""
    <div class="info-box">
    Esta é uma <b>prévia</b>. Os pais têm o mês inteiro para pagar.
    Ninguém é considerado devedor aqui — isso só acontece após o fechamento do mês.
    </div>
    """, unsafe_allow_html=True)

    pagantes = quem_pagou_no_mes(hoje_ym)  # uma query, não uma por aluno
    pagaram = [a for a in ativos if a["id"] in pagantes]
    nao_pagaram = [a for a in ativos if a["id"] not in pagantes]

    cards(
        ("Já pagaram", str(len(pagaram)), "green"),
        ("Ainda não pagaram", str(len(nao_pagaram)), "orange"),
        ("Total ativos", str(len(ativos)), "blue"),
    )
    if ativos:
        pct = len(pagaram) / len(ativos) * 100
        st.markdown(
            f'<div class="progress"><div style="width:{pct:.0f}%"></div></div>'
            f'<div class="progress-hint">{pct:.0f}% dos integrantes já pagaram '
            f'{F.fmt_mes(hoje_ym)} · prazo até dia 30.</div>',
            unsafe_allow_html=True)

    if nao_pagaram:
        st.markdown("**Ainda não pagaram este mês (lembrete):**")
        for a in nao_pagaram:
            msg = (f"Olá! Passando para lembrar da mensalidade de {F.fmt_mes(hoje_ym)} "
                   f"da Formatura. 🎓")
            ic = wa_icon(a.get("celular"), msg, is_admin)
            st.markdown(f"""
            <div class="aluno-card">
              <div class="aluno-nome">{a['nome']}{ic}</div>
              <div class="aluno-sub">ID {a['id']} · Turma {a['turma']}</div>
              <span class="badge badge-warn">⏳ Pagar até 30/{hoje_ym[5:7]}</span>
            </div>
            """, unsafe_allow_html=True)

    if pagaram:
        st.markdown("**Já pagaram:**")
        for a in pagaram:
            st.markdown(f"""
            <div class="aluno-card">
              <div class="aluno-nome">{a['nome']}</div>
              <div class="aluno-sub">ID {a['id']} · Turma {a['turma']}</div>
              <span class="badge badge-green">✓ Pago em {F.fmt_mes(hoje_ym)}</span>
            </div>
            """, unsafe_allow_html=True)


# ─── ABA 2 — SITUAÇÃO FECHADA ──────────────────────────────────────────────
with tabs[2]:
    ultimo_fechado = get_ultimo_mes_fechado()
    trans_rows = get_transacoes()
    trans = F.carregar_transacoes_agrupadas(trans_rows)

    if not ultimo_fechado:
        st.markdown('<div class="warn-box">Nenhum mês fechado ainda. '
                    'Confirme um fechamento na aba 📄 Fechamento.</div>', unsafe_allow_html=True)
    else:
        st.markdown(f'<div class="sec-title">Situação — até {F.fmt_mes(ultimo_fechado)}</div>',
                    unsafe_allow_html=True)
        st.markdown(
            '<div class="info-box"><b>Devedor</b> = quem está com algum <b>mês já '
            'fechado</b> em aberto (até ' + F.fmt_mes(ultimo_fechado)
            + '). Quem pagou em dia até o último fechamento não deve. '
            'A janela em aberto aparece na aba 📋 Mês corrente.</div>',
            unsafe_allow_html=True)

        ativos = [a for a in alunos if a["status"] == "Ativo"]
        inativos = [a for a in alunos if a["status"] == "Inativo"]

        total_mensalidades = total_debito = 0.0
        n_em_dia = n_dev = 0
        items = []
        for a in ativos:
            calc = F.calcular_aluno(a, periodos, trans, ultimo_fechado)
            total_mensalidades += calc["total_pago"]
            if calc["saldo"] >= 0:
                n_em_dia += 1
            else:
                n_dev += 1
                total_debito += abs(calc["saldo"])
            items.append((a, calc))

        cards(
            ("Mensalidades", F.fmt_brl(total_mensalidades), "green"),
            ("Em débito", F.fmt_brl(total_debito), "red"),
            ("Em dia", str(n_em_dia), "blue"),
            ("Devedores", str(n_dev), "red" if n_dev else "green"),
        )

        filtro = st.selectbox("Filtrar", ["Todos", "Só devedores", "Só em dia"],
            label_visibility="collapsed")

        for a, calc in items:
            saldo = calc["saldo"]
            if filtro == "Só devedores" and saldo >= 0:
                continue
            if filtro == "Só em dia" and saldo < 0:
                continue
            detalhe = f"Pago: {F.fmt_brl(calc['total_pago'])} | Meta: {F.fmt_brl(calc['meta'])}"
            if saldo >= 0:
                adiant_str = (f' <span class="badge badge-warn">'
                              f'{calc["adiantados"]} {"mês" if calc["adiantados"]==1 else "meses"} adiant.</span>'
                              if calc["adiantados"] > 0 else "")
                badge = f'<span class="badge badge-green">Em dia</span>{adiant_str}'
                ic = ""
            else:
                badge = f'<span class="badge badge-red">Deve {F.fmt_brl(abs(saldo))}</span>'
                msg = (f"Olá! Consta um débito de {F.fmt_brl(abs(saldo))} dos meses "
                       f"já fechados da Formatura. Podemos confirmar o pagamento? 🎓")
                ic = wa_icon(a.get("celular"), msg, is_admin)

            st.markdown(f"""
            <div class="aluno-card">
              <div class="aluno-nome">{a['nome']}{ic}</div>
              <div class="aluno-sub">ID {a['id']} · Turma {a['turma']} · {detalhe}</div>
              {badge}
            </div>
            """, unsafe_allow_html=True)

        if inativos and filtro == "Todos":
            st.markdown('<div class="sec-title">Desistentes</div>', unsafe_allow_html=True)
            for a in inativos:
                calc = F.calcular_aluno(a, periodos, trans, ultimo_fechado)
                dev_badge = (f'<span class="badge badge-warn">Devolução pendente {F.fmt_brl(calc["dev_pendente"])}</span>'
                             if calc["dev_pendente"] > 0.01
                             else '<span class="badge badge-gray">Devolução concluída</span>')
                detalhe = (f"Total pago: {F.fmt_brl(calc['total_pago'])} | "
                           f"Devolvido: {F.fmt_brl(calc['devolucao'])}")
                st.markdown(f"""
                <div class="aluno-card-inativo">
                  <div class="aluno-nome-inativo">⏹ {a['nome']}</div>
                  <div class="aluno-sub">ID {a['id']} · Turma {a['turma']} · {detalhe}</div>
                  {dev_badge}
                </div>
                """, unsafe_allow_html=True)


# ─── ABA 3 — EXTRATO / IMPORTAÇÃO ──────────────────────────────────────────
with tabs[3]:
    if not is_admin:
        st.markdown('<div class="info-box">🔒 Disponível apenas para Tesouraria.</div>',
                    unsafe_allow_html=True)
        st.stop()

    sub_import, sub_hist, sub_editar = st.tabs(["Importar CSV", "Histórico", "Corrigir transação"])

    with sub_import:
        st.markdown("""
        <div class="info-box">
        Cole o extrato do banco. Formato: <b>DD/MM/AAAA, Descrição, Valor</b>
        (vírgula ou ponto-e-vírgula). Valores negativos = saídas.
        A primeira linha pode ser cabeçalho.
        </div>
        """, unsafe_allow_html=True)

        csv_texto = st.text_area("Extrato (CSV)", height=160,
            placeholder="14/04/2025,PIX TRANSF MARGARE14/04,200.00\n15/04/2025,INT APLICACAO PRIVILEGE,-3000.00")

        if st.button("🔍 Analisar extrato", type="primary"):
            if not csv_texto.strip():
                st.warning("Cole o extrato antes de analisar.")
            else:
                with st.spinner("Analisando..."):
                    alunos_ativos = db().table("alunos").select("id,nome,termos_pix") \
                        .eq("status", "Ativo").execute().data
                    linhas = parse_csv(csv_texto, alunos_ativos)
                if not linhas:
                    st.info("Nenhuma linha nova encontrada (já importadas ou formato inválido).")
                else:
                    st.session_state["pending"] = linhas
                    st.rerun()

        if "pending" in st.session_state:
            linhas = st.session_state["pending"]
            nao_id = [l for l in linhas if not l["aluno_id"] and l["categoria"] in ("OUTRO", "SAIDA")]

            st.success(f"**{len(linhas)}** linha(s) novas. " +
                (f"**{len(nao_id)}** precisam de identificação manual."
                 if nao_id else "Todas identificadas ✓"))

            if nao_id:
                alunos_opts = db().table("alunos").select("id,nome").eq("status", "Ativo").execute().data
                opts_map = {a["nome"]: a["id"] for a in alunos_opts}
                st.markdown('<div class="sec-title">Identificar manualmente</div>',
                            unsafe_allow_html=True)
                for l in nao_id:
                    gi = linhas.index(l)
                    st.markdown(f"**{l['data']}** · {l['descricao']} · `{F.fmt_brl(l['valor'])}`")
                    opcoes = ["— não identificado —", "Investimento/Saída", "Devolução s/ aluno"] + list(opts_map.keys())
                    escolha = st.selectbox("Atribuir a:", opcoes, key=f"attr_{gi}")
                    if escolha == "Investimento/Saída":
                        linhas[gi].update({"categoria": "INVESTIMENTO" if l["valor"] < 0 else "RESGATE",
                                           "aluno_id": None})
                    elif escolha == "Devolução s/ aluno":
                        linhas[gi].update({"categoria": "DEVOLUCAO", "aluno_id": None})
                    elif escolha in opts_map:
                        linhas[gi].update({
                            "aluno_id": opts_map[escolha], "aluno_nome": escolha,
                            "categoria": "MENSALIDADE" if l["valor"] > 0 else "DEVOLUCAO"})

            st.markdown('<div class="sec-title">Prévia</div>', unsafe_allow_html=True)
            st.dataframe(pd.DataFrame([{
                "Data": l["data"], "Descrição": l["descricao"][:42],
                "Valor": F.fmt_brl(l["valor"]), "Aluno": l["aluno_nome"] or "—",
                "Categoria": l["categoria"]
            } for l in linhas]), width="stretch", hide_index=True)

            c1, c2 = st.columns(2)
            if c1.button("✓ Confirmar importação", type="primary"):
                with st.spinner("Salvando..."):
                    db().table("transacoes").insert([{
                        "data": l["data"], "descricao": l["descricao"],
                        "valor": l["valor"], "categoria": l["categoria"],
                        "aluno_id": l["aluno_id"], "observacao": ""
                    } for l in linhas]).execute()
                del st.session_state["pending"]
                st.success(f"✓ {len(linhas)} transações salvas!")
                st.rerun()
            if c2.button("Cancelar"):
                del st.session_state["pending"]
                st.rerun()

    with sub_hist:
        anos_rows = db().table("transacoes").select("data").execute().data
        anos = sorted({r["data"][:4] for r in anos_rows}, reverse=True)
        ano_filt = st.selectbox("Ano", ["Todos"] + anos, label_visibility="collapsed")
        q = db().table("transacoes").select("data,descricao,valor,categoria,aluno_id") \
            .order("data", desc=True)
        if ano_filt != "Todos":
            q = q.like("data", f"{ano_filt}%")
        hist = q.execute().data
        st.dataframe(pd.DataFrame([{
            "Data": r["data"], "Descrição": r["descricao"],
            "Valor": F.fmt_brl(r["valor"]), "Categoria": r["categoria"],
            "Aluno": r["aluno_id"] or "—"
        } for r in hist]), width="stretch", hide_index=True)
        st.caption(f"{len(hist)} transações.")

    with sub_editar:
        st.markdown("""
        <div class="warn-box">
        Correção de lançamentos: se uma importação errou o aluno/categoria/valor,
        escolha a transação abaixo e ajuste ou **exclua**.
        </div>
        """, unsafe_allow_html=True)
        # Alvos mais recentes (últimas 300)
        alvo = db().table("transacoes").select(
            "id,data,descricao,valor,categoria,aluno_id")
        alvo = alvo.order("data", desc=True).limit(300).execute().data

        if not alvo:
            st.info("Nenhuma transação cadastrada.")
        else:
            nome_map = {a["id"]: a["nome"] for a in alunos}
            sel_map = {}
            for t in alvo:
                nome = nome_map.get(t["aluno_id"], "—")
                sel_map[f'{t["data"]} · {t["descricao"][:38]} · {F.fmt_brl(t["valor"])} · {t["categoria"]}'] = t
            chave = st.selectbox("Escolher transação", list(sel_map.keys()))
            t = sel_map[chave]

            c1, c2 = st.columns(2)
            nova_data = c1.text_input("Data (AAAA-MM-DD)", value=t["data"], key="ed_data")
            novo_desc = c2.text_input("Descrição", value=t["descricao"], key="ed_desc")
            novo_valor = st.number_input("Valor (R$)", value=float(t["valor"]),
                                         step=1.0, key="ed_valor")
            categorias = ["MENSALIDADE", "DEVOLUCAO", "INVESTIMENTO", "RESGATE",
                          "RENDIMENTO", "OUTRO", "SAIDA"]
            nova_cat = st.selectbox("Categoria", categorias,
                                    index=categorias.index(t["categoria"]) if t["categoria"] in categorias else 0,
                                    key="ed_cat")
            opcoes_aluno = ["— sem aluno —"] + [f"{a['id']} · {a['nome']}" for a in alunos]
            atual = f"{t['aluno_id']} · {nome_map.get(t['aluno_id'])}" if t.get("aluno_id") else "— sem aluno —"
            novo_aluno = st.selectbox("Aluno",
                opcoes_aluno, index=opcoes_aluno.index(atual) if atual in opcoes_aluno else 0,
                key="ed_aluno")

            c3, c4 = st.columns(2)
            if c3.button("💾 Salvar alterações", type="primary"):
                novo_id = None if novo_aluno.startswith("—") else novo_aluno.split(" · ")[0]
                db().table("transacoes").update({
                    "data": nova_data, "descricao": novo_desc, "valor": novo_valor,
                    "categoria": nova_cat, "aluno_id": novo_id
                }).eq("id", t["id"]).execute()
                st.success("✓ Transação corrigida!")
                st.rerun()
            if c4.button("🗑 Excluir transação"):
                st.session_state[f"del_{t['id']}"] = True
            if st.session_state.get(f"del_{t['id']}"):
                st.warning(f"Excluir **{t['descricao']}** de {t['data']}? Isso não pode ser desfeito.")
                c5, c6 = st.columns(2)
                if c5.button("Sim, excluir", type="primary"):
                    db().table("transacoes").delete().eq("id", t["id"]).execute()
                    st.success("✓ Transação excluída!")
                    st.rerun()
                if c6.button("Cancelar exclusão"):
                    del st.session_state[f"del_{t['id']}"]
                    st.rerun()


# ─── ABA 4 — FECHAMENTO ────────────────────────────────────────────────────
with tabs[4]:
    trans_rows = get_transacoes()
    trans = F.carregar_transacoes_agrupadas(trans_rows)

    mes_anterior = F.prev_ym(F.current_ym())
    fech = get_fechamento(mes_anterior)

    if fech and fech["status"] == "draft":
        st.markdown(f"""
        <div class="draft-box">
          <h4>📋 Draft — {F.fmt_mes(mes_anterior)}</h4>
          <p>Criado automaticamente. Revise abaixo e confirme quando estiver pronto.</p>
        </div>
        """, unsafe_allow_html=True)

        rows_prev = []
        for a in alunos:
            calc = F.calcular_aluno(a, periodos, trans, mes_anterior)
            if a["status"] == "Inativo":
                sit = f"Desistente (dev. pendente: {F.fmt_brl(calc['dev_pendente'])})" \
                    if calc["dev_pendente"] > 0.01 else "Desistente (quitado)"
            elif calc["saldo"] >= 0:
                sit = "✅ Em dia"
            else:
                sit = f"🔴 Deve {F.fmt_brl(abs(calc['saldo']))}"
            rows_prev.append([
                a["id"], a["nome"], F.fmt_brl(calc["total_pago"]),
                F.fmt_brl(calc["meta"]) if a["status"] == "Ativo" else "—", sit,
            ])
        st.markdown(render_table(["ID", "Aluno", "Pago", "Meta", "Situação"],
                                rows_prev, right_align=(2, 3)),
                    unsafe_allow_html=True)

        if is_admin:
            if st.button(f"✅ Confirmar fechamento de {F.fmt_mes(mes_anterior)}", type="primary"):
                with st.spinner("Confirmando e notificando..."):
                    confirmar_fechamento(mes_anterior, perfil)
                    devedores = [r for r in rows_prev if r[4].startswith("🔴")]
                    corpo = (f"Fechamento de {F.fmt_mes(mes_anterior)} confirmado.\n"
                             f"Devedores: {len(devedores)}\n"
                             + ("\n".join(f"• {r[1]}: {r[4]}" for r in devedores) if devedores
                                else "✅ Todos em dia!"))
                    ok = notificar_tesoureiras(f"Fechamento {F.fmt_mes(mes_anterior)}", corpo)
                    if ok:
                        st.success("✓ Fechamento confirmado e WhatsApp enviado!")
                    else:
                        st.success("✓ Fechamento confirmado!")
                        st.warning("WhatsApp não enviado — verifique WA_TOKEN e WA_PHONE_ID nos secrets.")
                st.rerun()

    st.markdown('<div class="sec-title">Histórico de fechamentos</div>', unsafe_allow_html=True)
    fechs = db().table("fechamentos").select("*").order("ano_mes", desc=True).execute().data
    if not fechs:
        st.info("Nenhum fechamento registrado.")
    else:
        for f in fechs:
            icon = "✅" if f["status"] == "confirmado" else "📋"
            conf = (f.get("confirmado_em") or "")[:10] or "—"
            by = f.get("confirmado_por") or "—"
            criado = (f.get("criado_em") or "")[:10] or "—"
            with st.expander(f"{icon} {F.fmt_mes(f['ano_mes'])} — {f['status'].upper()}"):
                st.markdown(f"**Criado em:** {criado}  |  "
                    f"**Confirmado em:** {conf}  |  **Por:** {by}")
                if f["status"] == "confirmado" and is_admin:
                    if st.button(f"📥 Baixar PDF {F.fmt_mes(f['ano_mes'])}",
                                 key=f"pdf_{f['ano_mes']}"):
                        with st.spinner("Gerando PDF..."):
                            pdf = gerar_pdf(f["ano_mes"], periodos, alunos, trans_rows)
                        st.download_button(
                            f"⬇ {F.fmt_mes(f['ano_mes'])}.pdf", data=pdf,
                            file_name=f"Fechamento_{F.fmt_mes(f['ano_mes']).replace('/','_')}.pdf",
                            mime="application/pdf", key=f"dl_{f['ano_mes']}")


# ─── ABA 5 — CADASTROS ──────────────────────────────────────────────────────
with tabs[5]:
    if not is_admin:
        st.markdown('<div class="info-box">🔒 Disponível apenas para Tesouraria.</div>',
                    unsafe_allow_html=True)
        st.stop()

    sub1, sub2, sub3, sub4 = st.tabs(["Alunos ativos", "Desistentes", "Mensalidades", "Orçamento"])

    with sub1:
        for a in [x for x in alunos if x["status"] == "Ativo"]:
            with st.expander(f"✅ {a['nome']} ({a['id']})"):
                c1, c2 = st.columns(2)
                nome = c1.text_input("Nome", value=a["nome"], key=f"n_{a['id']}")
                cel = c2.text_input("Celular", value=a["celular"] or "", key=f"c_{a['id']}")
                termos = st.text_input("Apelidos PIX (vírgula)",
                    value=a["termos_pix"] or "", key=f"p_{a['id']}")
                c3, c4 = st.columns(2)
                if c3.button("Salvar", key=f"sv_{a['id']}"):
                    db().table("alunos").update({
                        "nome": nome, "celular": cel, "termos_pix": termos.upper()
                    }).eq("id", a["id"]).execute()
                    st.success("Salvo!"); st.rerun()
                if c4.button("⚠️ Registrar desistência", key=f"d_{a['id']}"):
                    st.session_state[f"des_{a['id']}"] = True
                if st.session_state.get(f"des_{a['id']}"):
                    data_d = st.date_input("Data da desistência", key=f"dd_{a['id']}")
                    if st.button("Confirmar", key=f"cd_{a['id']}", type="primary"):
                        db().table("alunos").update({
                            "status": "Inativo", "data_desistencia": str(data_d)
                        }).eq("id", a["id"]).execute()
                        del st.session_state[f"des_{a['id']}"]
                        st.rerun()

        st.divider()
        st.markdown("**Adicionar novo aluno**")
        c1, c2, c3 = st.columns(3)
        n_id = c1.text_input("ID (ex: 11A)")
        n_nome = c2.text_input("Nome completo")
        n_turma = c3.text_input("Turma (A/B)")
        n_cel = st.text_input("Celular WhatsApp")
        n_pix = st.text_input("Apelidos PIX (vírgula)")
        if st.button("Adicionar aluno", type="primary"):
            if n_id and n_nome:
                try:
                    db().table("alunos").insert({
                        "id": n_id, "nome": n_nome, "status": "Ativo",
                        "turma": n_turma, "celular": n_cel, "termos_pix": n_pix.upper()
                    }).execute()
                    st.success("Aluno adicionado!"); st.rerun()
                except Exception as e:
                    st.error(f"Erro: {e}")

    with sub2:
        inativos = [a for a in alunos if a["status"] == "Inativo"]
        trans_rows2 = get_transacoes()
        trans2 = F.carregar_transacoes_agrupadas(trans_rows2)

        if not inativos:
            st.info("Nenhum desistente registrado.")
        else:
            for a in inativos:
                calc = F.calcular_aluno(a, periodos, trans2, F.current_ym())
                with st.expander(f"⏹ {a['nome']} ({a['id']}) — desistência: {a['data_desistencia'] or '—'}"):
                    c1, c2, c3 = st.columns(3)
                    c1.metric("Total pago", F.fmt_brl(calc["total_pago"]))
                    c2.metric("Devolvido", F.fmt_brl(calc["devolucao"]))
                    c3.metric("Pendente", F.fmt_brl(calc["dev_pendente"]))

                    trans_aluno = db().table("transacoes").select("data,descricao,valor,categoria") \
                        .eq("aluno_id", a["id"]).order("data").execute().data
                    if trans_aluno:
                        rows_t = [[t["data"], t["descricao"][:38], F.fmt_brl(t["valor"]), t["categoria"]]
                                  for t in trans_aluno]
                        st.markdown(render_table(["Data", "Descrição", "Valor", "Categoria"],
                                                rows_t, right_align=(2,)),
                                    unsafe_allow_html=True)

                    if st.button("↩️ Reativar", key=f"r_{a['id']}"):
                        db().table("alunos").update({
                            "status": "Ativo", "data_desistencia": None
                        }).eq("id", a["id"]).execute()
                        st.rerun()

    with sub3:
        st.markdown("""
        <div class="info-box">
        Cada período define o valor mensal a partir de uma data (AAAA-MM).
        O sistema acumula automaticamente conforme os meses passam.
        </div>
        """, unsafe_allow_html=True)
        updated = []
        for i, (de, val) in enumerate(periodos):
            c1, c2 = st.columns([2, 2])
            nd = c1.text_input("A partir de (AAAA-MM)", value=de, key=f"pd_{i}")
            nv = c2.number_input("Valor mensal R$", value=float(val), key=f"pv_{i}", step=10.0)
            updated.append((nd, nv))
        if st.button("+ Adicionar período"):
            updated.append(("", 0.0))
        if st.button("Salvar mensalidades", type="primary"):
            db().table("periodos").upsert(
                [{"de": d, "valor": v} for d, v in updated if d]).execute()
            st.success("Salvo!"); st.rerun()

    with sub4:
        st.markdown("""
        <div class="info-box">
        Previsão de caixa do evento (abertura, mensalidades por ano, encerramento...).
        O total aparece na aba 📊 Visão geral.
        </div>
        """, unsafe_allow_html=True)
        itens = get_orcamento()
        for i in itens:
            c1, c2, c3, c4 = st.columns([3, 2, 2, 1])
            c1.write(i["descricao"])
            c2.write(i["data"])
            c3.write(F.fmt_brl(i["valor"]))
            if c4.button("🗑", key=f"od_{i['id']}"):
                db().table("orcamento").delete().eq("id", i["id"]).execute()
                st.rerun()
        st.divider()
        st.markdown("**Adicionar item**")
        c1, c2 = st.columns([3, 1])
        n_desc = c1.text_input("Descrição", key="or_desc")
        n_data = c2.text_input("Quando", key="or_data")
        n_valor = st.number_input("Valor (R$)", step=10.0, key="or_valor")
        if st.button("+ Adicionar ao orçamento", type="primary"):
            if n_desc:
                db().table("orcamento").insert({
                    "descricao": n_desc, "data": n_data, "valor": n_valor}).execute()
                st.success("Adicionado!"); st.rerun()