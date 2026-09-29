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
from financeiro import esc, Html

# ─── Proteção simples contra força bruta no login (senhas compartilhadas) ───
import time as _time

_SEG_LOGIN = {"falhas": 0, "travar_ate": 0.0}


def _login_espera() -> float:
    """Segundos restantes de bloqueio global (0 = liberado)."""
    return max(0.0, _SEG_LOGIN["travar_ate"] - _time.time())


def _login_falha():
    now = _time.time()
    if now < _SEG_LOGIN["travar_ate"]:
        return
    _SEG_LOGIN["falhas"] += 1
    if _SEG_LOGIN["falhas"] >= 20:   # spray: trava login global por 60s
        _SEG_LOGIN["travar_ate"] = now + 60
        _SEG_LOGIN["falhas"] = 0


def _login_ok():
    _SEG_LOGIN["falhas"] = 0


# ─── Auth: Supabase (produção) ─────────────────────────────────────────────
def _login_supabase(email: str, senha: str) -> str | None:
    """Autentica no Supabase Auth e retorna o perfil (Tesouraria/Consulta) ou None."""
    url = _secrets_get("SUPABASE_URL")
    key = _secrets_get("SUPABASE_SERVICE_KEY")
    email = (email or "").strip().lower()
    if not url or not key or not email or not senha:
        return None
    try:
        client = create_client(url, key)
        resp = client.auth.sign_in_with_password({"email": email, "password": senha})
    except Exception:
        return None
    user_email = (resp.user.email if resp.user else email)
    try:
        rows = db().table("perfis").select("perfil,nome").eq("email", user_email.lower()).execute().data
        if not rows:
            return None  # conta válida, mas sem papel atribuído
        perfil = rows[0]["perfil"]
    except Exception:
        return None
    st.session_state["auth_user"] = user_email.lower()
    st.session_state["auth_name"] = (rows[0].get("nome") or "").strip()
    try:
        if resp.session and resp.session.access_token:
            st.session_state["auth_token"] = resp.session.access_token
    except Exception:
        pass
    return perfil


def _sign_out():
    """Encerra a sessão no Supabase (melhor esforço) e limpa o estado local."""
    url, key = _secrets_get("SUPABASE_URL"), _secrets_get("SUPABASE_SERVICE_KEY")
    if url and key:
        try:
            create_client(url, key).auth.sign_out()
        except Exception:
            pass
    for k in ("perfil", "auth_user", "auth_name", "auth_token"):
        st.session_state.pop(k, None)

def _auth_client():
    return create_client(_secrets_get("SUPABASE_URL"), _secrets_get("SUPABASE_SERVICE_KEY"))


def _enviar_link_recuperacao(email: str) -> bool:
    """Dispara o email de recuperação do Supabase (link p/ definir nova senha)."""
    if not email or not email.strip():
        return False
    try:
        _auth_client().auth.reset_password_for_email(email.strip().lower())
        return True
    except Exception:
        return False


def _trocar_senha_por_recovery(code: str, nova_senha: str):
    """Troca a senha usando o token do link de recuperação e faz login."""
    try:
        c = _auth_client()
        c.auth.exchange_code_for_session(code)          # valida o token do link
        c.auth.update_user({"password": nova_senha})    # grava a nova senha
        user = c.auth.get_user().user
        email = (user.email or "").lower() if user else ""
        rows = db().table("perfis").select("perfil,nome").eq("email", email).execute().data
        if not rows:
            return None
        st.session_state["auth_user"] = email
        st.session_state["auth_name"] = (rows[0].get("nome") or "").strip()
        return rows[0]["perfil"]
    except Exception:
        return None


def _qp(key: str):
    """Lê um parâmetro de URL (primeiro valor)."""
    v = st.query_params.get(key)
    if isinstance(v, list):
        return v[0] if v else None
    return v


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
st.set_page_config(page_title=CFG["nome_curto"], layout="wide",
                   page_icon="🎓", initial_sidebar_state="expanded")

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


# ─── CSS — novo design (verde profundo, cartões claros, DM Sans/Manrope) ────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:opsz,wght@9..40,400;9..40,500;9..40,600;9..40,700&family=Manrope:wght@500;600;700;800&display=swap');

html, body, .stApp {
  font-family: 'DM Sans', sans-serif;
  background: #f4f5f2;
  color: #1c2823;
}
h1, h2, h3, .stat-card .val, .page-head h1, .login-card h2, .sb-name {
  font-family: 'Manrope', 'DM Sans', sans-serif;
}

[data-testid="stHeader"] { display:none; }
.block-container { padding:1.6rem 2rem 4rem; max-width:1060px; margin:0 auto; }

/* ── Sidebar ─────────────────────────────────────────────── */
[data-testid="stSidebar"] {
  background:#17332a;
  border-right:none;
}
[data-testid="stSidebar"] .block-container { padding:1.4rem 1rem 2rem; max-width:none; }
.sb-logo { display:flex; align-items:center; gap:12px; margin-bottom:20px; }
.sb-logo-ico {
  width:44px; height:44px; border-radius:12px; background:rgba(255,255,255,.1);
  display:flex; align-items:center; justify-content:center; font-size:22px;
}
.sb-name { color:#fff; font-weight:800; font-size:16px; line-height:1.2; }
.sb-sub { color:#9db8ac; font-size:12px; }
[data-testid="stSidebar"] .stRadio [role="radiogroup"] { gap:2px; align-items:stretch; }
[data-testid="stSidebar"] .stRadio label {
  background:transparent; border-radius:9px; padding:9px 12px;
  color:#cfe0d8; font-size:14px; transition:background .15s;
}
[data-testid="stSidebar"] .stRadio label:hover { background:rgba(255,255,255,.07); color:#fff; }
[data-testid="stSidebar"] .stRadio label:has(input:checked) {
  background:rgba(255,255,255,.13); color:#fff; font-weight:600;
}
[data-testid="stSidebar"] .stRadio label > div:first-child { display:none; }
.sb-badge {
  display:inline-block; margin-top:14px; padding:4px 10px; border-radius:999px;
  background:rgba(255,255,255,.1); color:#d7e6de; font-size:11.5px; font-weight:600;
  letter-spacing:.02em;
}
[data-testid="stSidebar"] .stButton > button {
  background:transparent !important; border:1px solid rgba(255,255,255,.28) !important;
  color:#e7f0ec !important; border-radius:9px !important;
}
[data-testid="stSidebar"] .stButton > button:hover {
  background:rgba(255,255,255,.08) !important;
}
[data-testid="stSidebar"] hr { border-color:rgba(255,255,255,.14); }

/* ── Cabeçalho da seção ──────────────────────────────────── */
.page-head { display:flex; align-items:center; justify-content:space-between;
  gap:10px; flex-wrap:wrap; margin-bottom:6px; }
.page-head h1 { font-size:22px; font-weight:800; margin:0; color:#1c2823; }
.page-sub { font-size:13px; color:#6d7a72; margin-bottom:16px; }

/* ── Cartões de métrica ──────────────────────────────────── */
.stat-row { display:flex; gap:12px; margin:6px 0 18px; flex-wrap:wrap; }
.stat-card { flex:1; min-width:150px; background:#fff;
  border:1px solid #e3e6e0; border-radius:12px; padding:14px 16px; }
.stat-card .lbl { font-size:11px; color:#6d7a72; text-transform:uppercase;
  letter-spacing:.05em; font-weight:600; }
.stat-card .val { font-size:22px; font-weight:800; margin-top:6px; }
.green  { color:#1f7a4d; }
.red    { color:#b3372f; }
.orange { color:#a16207; }
.blue   { color:#2b5fb8; }

/* ── Títulos de bloco ────────────────────────────────────── */
.sec-title { font-size:12px; font-weight:700; color:#6d7a72; text-transform:uppercase;
  letter-spacing:.06em; margin:22px 0 10px; }

/* ── Cartões de aluno ────────────────────────────────────── */
.aluno-card { background:#fff; border:1px solid #e3e6e0;
  border-radius:12px; padding:14px 16px; margin-bottom:10px; }
.aluno-card-inativo { background:#f7f8f6; border:1px solid #e6e9e4;
  border-radius:12px; padding:14px 16px; margin-bottom:10px; opacity:.75; }
.aluno-top { display:flex; align-items:center; justify-content:space-between;
  gap:8px; flex-wrap:wrap; }
.aluno-nome { font-weight:600; font-size:15px; }
.aluno-nome-inativo { font-weight:500; font-size:15px; color:#6d7a72; }
.aluno-sub { font-size:12.5px; color:#6d7a72; margin-top:3px; }
.wa-ico { text-decoration:none; margin-left:8px; font-size:15px; opacity:.85; }
.wa-ico:hover { opacity:1; }

/* ── Barra de progresso ──────────────────────────────────── */
.progress { height:8px; background:#e7e9e4; border-radius:999px;
  overflow:hidden; margin:8px 0 6px; }
.progress > div { height:100%; background:#2a5747; border-radius:999px; }
.progress-hint { font-size:12px; color:#6d7a72; margin-bottom:12px; }

/* ── Badges ──────────────────────────────────────────────── */
.badge { display:inline-block; padding:3px 10px; border-radius:999px;
  font-size:12px; font-weight:600; white-space:nowrap; }
.badge-green { background:#e3f2ea; color:#186a43; }
.badge-red   { background:#fbeae8; color:#a83a31; }
.badge-gray  { background:#eef0ec; color:#5c6a62; }
.badge-warn  { background:#fdf3dd; color:#8f5f0a; }
.badge-blue  { background:#e7eefc; color:#2b5fb8; }

/* ── Caixas de destaque ──────────────────────────────────── */
.info-box { background:#e7eefc; border:1px solid #cddcf7; border-radius:10px;
  padding:12px 14px; font-size:13px; color:#2b5fb8; margin-bottom:14px; }
.warn-box { background:#fdf3dd; border:1px solid #f0dfae; border-radius:10px;
  padding:12px 14px; font-size:13px; color:#8f5f0a; margin-bottom:14px; }
.draft-box { background:#fdf7e3; border:1.5px solid #e3c96b; border-radius:12px;
  padding:16px; margin-bottom:16px; }
.draft-box h4 { margin:0 0 6px; color:#6e4c0a; font-size:15px; }
.draft-box p  { margin:0; font-size:13px; color:#8f5f0a; }

/* ── Tabela HTML responsiva (melhor que st.dataframe no celular) ── */
.table-wrap { overflow-x:auto; -webkit-overflow-scrolling:touch; border-radius:10px;
  border:1px solid #e3e6e0; }
table.tbl { width:100%; border-collapse:collapse; background:#fff;
  font-size:13px; min-width:520px; }
table.tbl th { background:#17332a; color:#fff; padding:9px 12px; text-align:left;
  font-size:12px; font-weight:600; }
table.tbl td { padding:9px 12px; border-bottom:1px solid #eef0ec; color:#1c2823; }
table.tbl td.num, table.tbl th.num { text-align:right; }
table.tbl tr:nth-child(even) td { background:#f8f9f6; }
table.tbl td.empty { text-align:center; color:#6d7a72; padding:16px; }

/* ── Widgets ─────────────────────────────────────────────── */
#MainMenu, footer { visibility:hidden; }
.stButton > button { border-radius:9px !important; padding:.5rem 1.1rem !important;
  font-size:14px !important; font-weight:600 !important; }
.stButton > button[kind="primary"] {
  background:#2a5747 !important; border:none !important; color:#fff !important; }
.stButton > button[kind="primary"]:hover { background:#22483a !important; }
.stButton > button[kind="secondary"] {
  background:#fff !important; color:#2a5747 !important; border:1px solid #d6dcd6 !important; }
.stTextInput input, .stTextArea textarea, .stNumberInput input {
  border-radius:9px !important; }
.stTabs [data-baseweb="tab"] { font-size:13px; color:#5c6a62; }
.stTabs [data-baseweb="tab"][aria-selected="true"] { color:#2a5747 !important; font-weight:700; }
.stTabs [data-baseweb="tab-highlight"] { background-color:#2a5747 !important; }

/* ── Login ───────────────────────────────────────────────── */
.login-wrap { display:flex; justify-content:center; padding-top:5vh; }
.login-head { text-align:center; margin-bottom:6px; }
.login-logo {
  width:58px; height:58px; border-radius:16px; background:#17332a; color:#fff;
  font-size:28px; display:flex; align-items:center; justify-content:center;
  margin:0 auto 14px;
}
.login-head h2 { font-size:20px; font-weight:800; margin:0 0 4px; color:#1c2823; }
.login-head p { font-size:13px; color:#6d7a72; margin:0 0 18px; }

/* ── Mobile-first ────────────────────────────────────────── */
@media (max-width: 640px) {
  .block-container { padding:.8rem .8rem 3rem; }
  .stat-card { min-width:calc(50% - 8px); padding:12px 10px; }
  .stat-card .lbl { font-size:10px; }
  .stat-card .val { font-size:19px; }
  .page-head h1 { font-size:19px; }
  table.tbl { font-size:12px; min-width:0; }
  table.tbl td, table.tbl th { padding:7px 8px; }
  .stTabs [data-baseweb="tab"] { font-size:12px; }
}
</style>
""", unsafe_allow_html=True)


# ─── HELPERS DE TELA ────────────────────────────────────────────────────────
def sec(t: str) -> str:
    return f'<div class="sec-title">{t}</div>'


def render_table(headers, rows, right_align=(), empty="Nenhum dado.") -> str:
    """Tabela HTML responsiva. Células são ESCAPADAS por padrão; envolva com
    Html(...) para injetar HTML intencional (ex.: badges) de forma segura."""
    thead = "".join(
        f'<th class="num">{esc(h)}</th>' if i in right_align else f"<th>{esc(h)}</th>"
        for i, h in enumerate(headers))
    body = ""
    for r in rows:
        tds = []
        for ci, val in enumerate(r):
            cls = ' class="num"' if ci in right_align else ""
            if isinstance(val, Html):
                cell = str(val)
            else:
                cell = esc(val)
            tds.append(f"<td{cls}>{cell}</td>")
        body += "<tr>" + "".join(tds) + "</tr>"
    if not rows:
        body = f'<tr><td class="empty" colspan="{len(headers)}">{esc(empty)}</td></tr>'
    return (f'<div class="table-wrap"><table class="tbl">'
            f"<thead><tr>{thead}</tr></thead><tbody>{body}</tbody></table></div>")


def cards(*itens):
    """itens: (lbl, val, cor)."""
    html = '<div class="stat-row">' + "".join(
        f'<div class="stat-card"><div class="lbl">{l}</div>'
        f'<div class="val {c}">{v}</div></div>' for l, v, c in itens) + "</div>"
    st.markdown(html, unsafe_allow_html=True)


def aluno_card(nome: str, sub: str, badge_html: str = "", ic: str = "",
               inativo: bool = False) -> str:
    cls = "aluno-card-inativo" if inativo else "aluno-card"
    ncls = "aluno-nome-inativo" if inativo else "aluno-nome"
    return (f'<div class="{cls}"><div class="aluno-top">'
            f'<span class="{ncls}">{esc(nome)}{ic}</span>{badge_html}</div>'
            f'<div class="aluno-sub">{esc(sub)}</div></div>')


def wa_link(cel: str, msg: str) -> str:
    num = re.sub(r"\D", "", cel or "")
    return f"https://wa.me/55{num}?text={urllib.parse.quote(msg)}"


def wa_icon(cel, msg, enabled: bool) -> str:
    """Ícone 📲 clicável de WhatsApp, colocado na frente do nome do aluno."""
    if not (enabled and cel):
        return ""
    return (f'<a class="wa-ico" href="{wa_link(cel, msg)}" target="_blank" '
            f'title="Enviar lembrete no WhatsApp">📲</a>')


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
    return all(enviar_whatsapp(n, f"🎓 *{assunto}*\n\n{corpo}") for n in numeros)


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
        textColor=colors.HexColor("#17332a"), spaceAfter=4)
    H2 = ParagraphStyle("H2", parent=styles["Heading2"], fontSize=12,
        textColor=colors.HexColor("#2a5747"), spaceBefore=14, spaceAfter=6)
    SUB = ParagraphStyle("SUB", parent=styles["Normal"], fontSize=9,
        textColor=colors.gray, spaceAfter=8)

    ts_base = TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f8f9f6")),
        ("GRID", (0, 0), (-1, -1), .5, colors.HexColor("#e3e6e0")),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
    ])
    ts_al = TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#17332a")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), .5, colors.HexColor("#e3e6e0")),
        ("ALIGN", (3, 1), (3, -1), "RIGHT"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8f9f6")]),
    ])
    for i, r in enumerate(rows_ativos):
        if r[4] == "DEVEDOR":
            ts_al.add("TEXTCOLOR", (3, i + 1), (4, i + 1), colors.HexColor("#b3372f"))
            ts_al.add("FONTNAME", (3, i + 1), (4, i + 1), "Helvetica-Bold")

    elems = [
        Paragraph(f"🎓 {CFG['nome_comissao']} — Fechamento {F.fmt_mes(ym)}", H1),
        Paragraph(f"Emitido em {hoje}  |  Referência: {F.fmt_mes(ym)}", SUB),
        HRFlowable(width="100%", thickness=1, color=colors.HexColor("#e3e6e0"), spaceAfter=10),
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
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#5c6a62")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("GRID", (0, 0), (-1, -1), .5, colors.HexColor("#e3e6e0")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8f9f6")]),
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
    # Esconde a sidebar enquanto não há sessão aberta
    st.markdown("""
    <style>
      [data-testid="stSidebar"],
      [data-testid="stSidebarCollapsedControl"] { display:none; }
    </style>
    """, unsafe_allow_html=True)

    _, meio, _ = st.columns([1, 1.1, 1])
    with meio:
        st.markdown(f"""
        <div class="login-wrap"><div class="login-head">
          <div class="login-logo">🎓</div>
          <h2>{esc(CFG['nome_comissao'])}</h2>
          <p>Gestão Financeira da Comissão</p>
        </div></div>
        """, unsafe_allow_html=True)

        if _demo_ativo():
            # Modo demonstração: sem Supabase, qualquer senha entra (pra testar).
            perfil = st.selectbox("Perfil de acesso", ["Tesouraria", "Consulta"])
            senha = st.text_input("Senha", type="password")
            if st.button("Entrar", type="primary", width="stretch"):
                espera = _login_espera()
                if espera > 0:
                    st.warning(f"Muitas tentativas. Aguarde {int(espera)}s "
                               "antes de tentar de novo.")
                else:
                    esperada = _secrets_get("SENHA_TESOURARIA" if perfil == "Tesouraria"
                                            else "SENHA_CONSULTA")
                    if not esperada or senha == esperada:
                        _login_ok()
                        st.session_state["perfil"] = perfil
                        st.rerun()
                    else:
                        _login_falha()
                        st.error("Senha incorreta")
        else:
            qcode = _qp("code")
            if qcode:  # pessoa clicou no link de recuperação -> define nova senha
                st.markdown(
                    '<p style="color:#6d7a72;font-size:13px;margin:-6px 0 6px">'
                    'Defina sua <b>nova senha</b>:</p>', unsafe_allow_html=True)
                nova = st.text_input("Nova senha", type="password", key="rec_pass")
                nova2 = st.text_input("Confirme a nova senha", type="password", key="rec_pass2")
                confere = bool(nova) and nova == nova2 and len(nova) >= 6
                if st.button("Salvar nova senha", type="primary", width="stretch"):
                    if confere:
                        perfil = _trocar_senha_por_recovery(qcode, nova)
                        if perfil:
                            _login_ok()
                            st.session_state["perfil"] = perfil
                            st.rerun()
                        else:
                            st.error("Não foi possível concluir. Verifique se o link é "
                                     "válido/recente e se a conta tem perfil definido.")
                    else:
                        st.warning("As senhas não coincidem ou são muito curtas (mínimo 6).")
            elif st.session_state.get("recuperar"):
                st.markdown(
                    '<p style="color:#6d7a72;font-size:13px;margin:-6px 0 6px">'
                    'Recuperação de senha — informe o email da sua conta:</p>',
                    unsafe_allow_html=True)
                remail = st.text_input("E-mail")
                if st.button("Enviar link de recuperação", type="primary", width="stretch"):
                    if _enviar_link_recuperacao(remail):
                        st.info("Link enviado! Confira seu email para definir a nova senha.")
                    else:
                        st.error("Não foi possível enviar. Confira o email digitado.")
                if st.button("Voltar ao login"):
                    st.session_state.pop("recuperar", None)
                    st.rerun()
            else:
                st.markdown(
                    '<p style="color:#6d7a72;font-size:13px;margin:-6px 0 6px">'
                    'Entre com a conta da comissão (email + senha).</p>',
                    unsafe_allow_html=True)
                email = st.text_input("E-mail")
                senha = st.text_input("Senha", type="password")
                if st.button("Entrar", type="primary", width="stretch"):
                    espera = _login_espera()
                    if espera > 0:
                        st.warning(f"Muitas tentativas. Aguarde {int(espera)}s "
                                   "antes de tentar de novo.")
                    else:
                        perfil = _login_supabase(email, senha)
                        if perfil:
                            _login_ok()
                            st.session_state["perfil"] = perfil
                            st.rerun()
                        else:
                            _login_falha()
                            st.error("E-mail ou senha inválidos — ou conta sem perfil definido.")
                if st.button("Esqueci minha senha"):
                    st.session_state["recuperar"] = True
                    st.rerun()


# ─── MAIN ───────────────────────────────────────────────────────────────────
if "perfil" not in st.session_state:
    tela_login()
    st.stop()

perfil = st.session_state["perfil"]
is_admin = perfil == "Tesouraria"

SECOES = ["Visão geral", "Mês corrente", "Situação dos alunos",
          "Extrato", "Fechamentos", "Cadastros"]

# ─── Sidebar: logo + navegação + sessão ─────────────────────────────────────
with st.sidebar:
    st.markdown(f"""
    <div class="sb-logo">
      <div class="sb-logo-ico">🎓</div>
      <div>
        <div class="sb-name">{esc(CFG['nome_curto'])}</div>
        <div class="sb-sub">Gestão financeira</div>
      </div>
    </div>
    """, unsafe_allow_html=True)

    secao = st.radio("Navegação", SECOES, label_visibility="collapsed", key="nav")

    st.markdown(f"""
    <span class="badge {'badge-green' if is_admin else 'badge-blue'}"
          style="margin-top:16px">{'🔑 Tesouraria' if is_admin else '👁 Consulta'}</span>
    """, unsafe_allow_html=True)
    if st.session_state.get("auth_user"):
        _quem = st.session_state.get("auth_name") or st.session_state["auth_user"]
        st.caption(f"👋 {esc(_quem)}")
    if _demo_ativo():
        st.markdown('<span class="sb-badge">Ambiente de demonstração</span>',
                    unsafe_allow_html=True)
    if st.button("Sair"):
        _sign_out()
        st.rerun()

# ─── Cabeçalho da área principal ────────────────────────────────────────────
st.markdown(f"""
<div class="page-head">
  <h1>{secao}</h1>
  <span class="badge {'badge-green' if is_admin else 'badge-blue'}">
    {'🔑 Tesouraria' if is_admin else '👁 Consulta'}</span>
</div>
""", unsafe_allow_html=True)

# Cria o draft do fechamento apenas para Tesouraria (Consulta nunca grava no banco)
if is_admin:
    garantir_draft_mes_anterior()

# Banner de draft pendente (para admin)
if is_admin:
    mes_anterior = F.prev_ym(F.current_ym())
    fech = get_fechamento(mes_anterior)
    if fech and fech["status"] == "draft":
        st.markdown(f"""
        <div class="draft-box">
          <h4>⚠️ Fechamento de {F.fmt_mes(mes_anterior)} aguarda confirmação</h4>
          <p>Revise a situação dos alunos e confirme o fechamento na seção Fechamentos.</p>
        </div>
        """, unsafe_allow_html=True)

# Dados carregados uma vez por execução (evita recarregar a cada seção)
periodos = get_periodos()
alunos = get_alunos()


# ─── SEÇÃO 0 — VISÃO GERAL (painel de caixa) ────────────────────────────────
if secao == "Visão geral":
    ate_ym = get_ultimo_mes_fechado() or F.current_ym()
    trans_rows = get_transacoes()
    p = F.calcular_painel(trans_rows, periodos, alunos, ate_ym)

    st.markdown(sec("Caixa consolidado"), unsafe_allow_html=True)
    cards(
        ("Saldo total", F.fmt_brl(p["patrimonio"]), "green"),
        ("Mensalidades arrecadadas", F.fmt_brl(p["total_mensalidades"]), "blue"),
        ("Inadimplência", F.fmt_brl(p["inadimplencia"]), "red" if p["inadimplencia"] else "green"),
        ("Rendimento acumulado", F.fmt_brl(p["rendimento"]), "orange"),
    )
    st.markdown(
        f'<div class="page-sub">Situação de caixa até {F.fmt_mes(ate_ym)}. '
        f'O "saldo total" considera conta corrente + investimento.</div>',
        unsafe_allow_html=True)

    # Saldo conta vs investimento
    st.markdown(sec("Conta corrente × Investimento"), unsafe_allow_html=True)
    cards(
        ("Em conta corrente", F.fmt_brl(p["saldo_conta"]), "blue"),
        ("Aplicado no investimento", F.fmt_brl(p["saldo_invest"]), "orange"),
        ("Total de aportes", F.fmt_brl(p["aportes"]), "blue"),
        ("Resgates", F.fmt_brl(p["resgates"]), "green"),
    )

    # Arrecadação por ano (meta x atingido)
    st.markdown(sec("Arrecadação por ano"), unsafe_allow_html=True)
    rows = []
    for ano, pago in p["arrecadacao_por_ano"].items():
        meta = p["meta_ano"].get(ano, 0.0)
        pct = (pago / meta * 100) if meta else 0.0
        cls = "green" if pct >= 100 else ("orange" if pct >= 70 else "red")
        rows.append([
            ano, F.fmt_brl(pago), F.fmt_brl(meta),
            Html(f'<span class="{cls}" style="font-weight:700">{pct:.0f}%</span>')
        ])
    st.markdown(render_table(
        ["Ano", "Pago", "Meta", "Atingido"], rows,
        right_align=(1, 2)), unsafe_allow_html=True)

    # Orçamento/previsão (se houver tabela)
    itens = get_orcamento()
    if itens:
        st.markdown(sec("Previsão de orçamento"), unsafe_allow_html=True)
        rows = [[i["descricao"], i["data"], F.fmt_brl(i["valor"])] for i in itens]
        rows.append([Html("<strong>Total</strong>"), "",
                     Html(f"<strong>{F.fmt_brl(F.total_orcamento(itens))}</strong>")])
        st.markdown(render_table(["Item", "Quando", "Valor"], rows,
                                 right_align=(2,)), unsafe_allow_html=True)

    st.caption("Fórmulas: total arrecadado = soma das mensalidades; "
               "saldo conta = soma do extrato; investimento = aportes − resgates. "
               "Confira com o extrato — as contas vivem centralizadas em `financeiro.py`.")


# ─── SEÇÃO 1 — MÊS CORRENTE (prévia) ────────────────────────────────────────
elif secao == "Mês corrente":
    hoje_ym = F.current_ym()
    ativos = [a for a in alunos if a["status"] == "Ativo"]

    st.markdown("""
    <div class="info-box">Esta é uma prévia. Os pais têm o mês inteiro para pagar.
    Ninguém é considerado devedor aqui — isso só acontece após o fechamento do mês.</div>
    """, unsafe_allow_html=True)

    trans_rows = get_transacoes()
    trans = F.carregar_transacoes_agrupadas(trans_rows)
    # Em dia neste mês = o mês atual já está integralmente coberto pelo total pago
    # (regra FIFO: o dinheiro quita desde o mês mais antigo). Isso inclui quem pagou
    # o ano inteiro ou vários meses de uma vez — e não gera lembrete errado.
    pagaram = [a for a in ativos
               if F.calcular_aluno(a, periodos, trans, hoje_ym)["mes_atual_pago"]]
    nao_pagaram = [a for a in ativos if a not in pagaram]

    cards(
        ("Em dia até hoje", str(len(pagaram)), "green"),
        ("Pendente", str(len(nao_pagaram)), "orange"),
        ("Total ativos", str(len(ativos)), "blue"),
    )
    if ativos:
        pct = len(pagaram) / len(ativos) * 100
        st.markdown(
            f'<div class="progress"><div style="width:{pct:.0f}%"></div></div>'
            f'<div class="progress-hint">{pct:.0f}% já cobriram {F.fmt_mes(hoje_ym)} '
            f'(quem pagou adiantado/à vista conta como pago). Prazo até dia 30.</div>',
            unsafe_allow_html=True)

    if nao_pagaram:
        st.markdown(sec("Ainda não pagaram este mês (lembrete)"), unsafe_allow_html=True)
        for a in nao_pagaram:
            msg = (f"Olá! Passando para lembrar da mensalidade de {F.fmt_mes(hoje_ym)} "
                   f"da Formatura. 🎓")
            ic = wa_icon(a.get("celular"), msg, is_admin)
            st.markdown(aluno_card(
                a["nome"], f"ID {a['id']} · Turma {a['turma']}",
                badge_html=f'<span class="badge badge-warn">⏳ Pagar até 30/{hoje_ym[5:7]}</span>',
                ic=ic), unsafe_allow_html=True)

    if pagaram:
        st.markdown(sec("Já pagaram"), unsafe_allow_html=True)
        for a in pagaram:
            st.markdown(aluno_card(
                a["nome"], f"ID {a['id']} · Turma {a['turma']}",
                badge_html=f'<span class="badge badge-green">✓ Pago em {F.fmt_mes(hoje_ym)}</span>'),
                unsafe_allow_html=True)


# ─── SEÇÃO 2 — SITUAÇÃO DOS ALUNOS (fechada) ────────────────────────────────
elif secao == "Situação dos alunos":
    ultimo_fechado = get_ultimo_mes_fechado()
    trans_rows = get_transacoes()
    trans = F.carregar_transacoes_agrupadas(trans_rows)

    if not ultimo_fechado:
        st.markdown('<div class="info-box">Nenhum mês fechado ainda. '
                    'Confirme um fechamento na seção Fechamentos.</div>',
                    unsafe_allow_html=True)
    else:
        st.markdown(f'<div class="page-sub">Situação fechada — até '
                    f'{F.fmt_mes(ultimo_fechado)}.</div>', unsafe_allow_html=True)
        st.markdown(
            '<div class="info-box">Devedor = quem está com algum mês já fechado em aberto '
            '(até ' + F.fmt_mes(ultimo_fechado) + '). Quem pagou em dia até o último '
            'fechamento não deve. A janela em aberto aparece na seção Mês corrente.</div>',
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
            detalhe = f"ID {a['id']} · Turma {a['turma']} · Pago: {F.fmt_brl(calc['total_pago'])} | Meta: {F.fmt_brl(calc['meta'])}"
            if saldo >= 0:
                adiant_str = (f' · {calc["adiantados"]} '
                              f'{"mês" if calc["adiantados"]==1 else "meses"} adiant.'
                              if calc["adiantados"] > 0 else "")
                badge = f'<span class="badge badge-green">Em dia{adiant_str}</span>'
                ic = ""
            else:
                desde = (f'desde {F.fmt_mes(calc["mes_inicial_debito"])} '
                         if calc.get("mes_inicial_debito") else "")
                badge = (f'<span class="badge badge-red">Deve {F.fmt_brl(abs(saldo))} '
                         f'{desde}</span>')
                msg = (f"Olá! Consta um débito de {F.fmt_brl(abs(saldo))} dos meses "
                       f"já fechados da Formatura. Podemos confirmar o pagamento? 🎓")
                ic = wa_icon(a.get("celular"), msg, is_admin)

            st.markdown(aluno_card(a["nome"], detalhe, badge_html=badge, ic=ic),
                        unsafe_allow_html=True)

        if inativos and filtro == "Todos":
            st.markdown(sec("Desistentes"), unsafe_allow_html=True)
            for a in inativos:
                calc = F.calcular_aluno(a, periodos, trans, ultimo_fechado)
                dev_badge = (f'<span class="badge badge-warn">Devolução pendente '
                             f'{F.fmt_brl(calc["dev_pendente"])}</span>'
                             if calc["dev_pendente"] > 0.01
                             else '<span class="badge badge-gray">Devolução concluída</span>')
                detalhe = (f"ID {a['id']} · Turma {a['turma']} · Total pago: "
                           f"{F.fmt_brl(calc['total_pago'])} | Devolvido: {F.fmt_brl(calc['devolucao'])}")
                st.markdown(aluno_card(a["nome"], detalhe, badge_html=dev_badge,
                                       ic="⏹ ", inativo=True),
                            unsafe_allow_html=True)


# ─── SEÇÃO 3 — EXTRATO / IMPORTAÇÃO ────────────────────────────────────────
elif secao == "Extrato":
    if not is_admin:
        st.markdown('<div class="info-box">🔒 Disponível apenas para Tesouraria.</div>',
                    unsafe_allow_html=True)
        st.stop()

    sub_import, sub_hist, sub_editar = st.tabs(["Importar CSV", "Histórico", "Corrigir transação"])

    with sub_import:
        st.markdown("""
        <div class="info-box">Cole o extrato do banco. Formato: <strong>DD/MM/AAAA; Descrição; Valor</strong>
        (vírgula ou ponto-e-vírgula). Valores negativos = saídas. A primeira linha pode ser cabeçalho.</div>
        """, unsafe_allow_html=True)

        csv_texto = st.text_area("Extrato (CSV)", height=160,
            placeholder="14/04/2025,PIX TRANSF MARGARE14/04,200.00\n15/04/2025,INT APLICACAO PRIVILEGE,-3000.00")

        if st.button("Analisar extrato", type="primary"):
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
                st.markdown(sec("Identificar manualmente"), unsafe_allow_html=True)
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

            st.markdown(sec("Prévia"), unsafe_allow_html=True)
            st.dataframe(pd.DataFrame([{
                "Data": l["data"], "Descrição": l["descricao"][:42],
                "Valor": F.fmt_brl(l["valor"]), "Aluno": l["aluno_nome"] or "—",
                "Categoria": l["categoria"]
            } for l in linhas]), width="stretch", hide_index=True)

            c1, c2 = st.columns(2)
            if c1.button("Confirmar importação", type="primary"):
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
        <div class="info-box">Correção de lançamentos: se uma importação errou o aluno/categoria/valor,
        escolha a transação abaixo e ajuste ou <strong>exclua</strong>.</div>
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
            if c3.button("Salvar alterações", type="primary"):
                novo_id = None if novo_aluno.startswith("—") else novo_aluno.split(" · ")[0]
                db().table("transacoes").update({
                    "data": nova_data, "descricao": novo_desc, "valor": novo_valor,
                    "categoria": nova_cat, "aluno_id": novo_id
                }).eq("id", t["id"]).execute()
                st.success("✓ Transação corrigida!")
                st.rerun()
            if c4.button("Excluir transação"):
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


# ─── SEÇÃO 4 — FECHAMENTOS ─────────────────────────────────────────────────
elif secao == "Fechamentos":
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
            if st.button(f"Confirmar fechamento de {F.fmt_mes(mes_anterior)}", type="primary"):
                with st.spinner("Confirmando e notificando..."):
                    confirmar_fechamento(mes_anterior, st.session_state.get("auth_user") or perfil)
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

    st.markdown(sec("Histórico de fechamentos"), unsafe_allow_html=True)
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
                    if st.button(f"Baixar PDF {F.fmt_mes(f['ano_mes'])}",
                                 key=f"pdf_{f['ano_mes']}"):
                        with st.spinner("Gerando PDF..."):
                            pdf = gerar_pdf(f["ano_mes"], periodos, alunos, trans_rows)
                        st.download_button(
                            f"⬇ {F.fmt_mes(f['ano_mes'])}.pdf", data=pdf,
                            file_name=f"Fechamento_{F.fmt_mes(f['ano_mes']).replace('/','_')}.pdf",
                            mime="application/pdf", key=f"dl_{f['ano_mes']}")


# ─── SEÇÃO 5 — CADASTROS ────────────────────────────────────────────────────
elif secao == "Cadastros":
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
        <div class="info-box">Cada período define o valor mensal a partir de uma data (AAAA-MM).
        O sistema acumula automaticamente conforme os meses passam.</div>
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
        <div class="info-box">Previsão de caixa do evento (abertura, mensalidades por ano,
        encerramento...). O total aparece na seção Visão geral.</div>
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
