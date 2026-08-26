import streamlit as st
import pandas as pd
import datetime
import urllib.parse
import re
import io
import csv
import requests
from supabase import create_client, Client
from reportlab.lib.pagesizes import A4
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer,
                                 Table, TableStyle, HRFlowable)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors

# ─── PAGE CONFIG ─────────────────────────────────────────────
st.set_page_config(
    page_title="Formatura Oshiman 2028",
    layout="centered",
    page_icon="🎓",
    initial_sidebar_state="collapsed",
)

# ─── SUPABASE (service_role — nunca exposta ao browser) ──────
@st.cache_resource
def get_supabase() -> Client:
    return create_client(
        st.secrets["SUPABASE_URL"],
        st.secrets["SUPABASE_SERVICE_KEY"],
    )

def db() -> Client:
    return get_supabase()

# ─── CSS ─────────────────────────────────────────────────────
st.markdown("""
<style>
[data-testid="stAppViewContainer"] { background:#f7f6f3; }
[data-testid="stHeader"]  { display:none; }
[data-testid="stSidebar"] { display:none; }
.block-container { padding:1rem 1rem 4rem; max-width:700px; }

.stat-row { display:flex; gap:10px; margin-bottom:18px; flex-wrap:wrap; }
.stat-card { flex:1; min-width:130px; background:white;
    border:1px solid #e2e0d8; border-radius:10px; padding:14px; text-align:center; }
.stat-card .lbl { font-size:11px; color:#8a877e; text-transform:uppercase;
    letter-spacing:.04em; font-weight:600; }
.stat-card .val { font-size:20px; font-weight:700; margin-top:4px; }
.green  { color:#2d6a4f; }
.red    { color:#b91c1c; }
.orange { color:#92400e; }

/* Card de aluno ativo */
.aluno-card { background:white; border:1px solid #e2e0d8;
    border-radius:10px; padding:14px 16px; margin-bottom:10px; }
/* Card de desistente — cinza, sempre no final */
.aluno-card-inativo { background:#fafafa; border:1px solid #e8e6de;
    border-radius:10px; padding:14px 16px; margin-bottom:10px; opacity:.75; }
.aluno-nome  { font-weight:600; font-size:15px; margin-bottom:2px; }
.aluno-nome-inativo { font-weight:500; font-size:15px; margin-bottom:2px; color:#8a877e; }
.aluno-sub   { font-size:12px; color:#8a877e; margin-bottom:8px; }

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

#MainMenu, footer { visibility:hidden; }
.stButton > button { width:100%; border-radius:8px !important;
    padding:.55rem 1rem !important; font-size:14px !important; }
.stTabs [data-baseweb="tab"] { font-size:13px; }
</style>
""", unsafe_allow_html=True)

# ═════════════════════════════════════════════════════════════
# HELPERS DE DATA
# ═════════════════════════════════════════════════════════════

def current_ym() -> str:
    d = datetime.date.today()
    return f"{d.year}-{d.month:02d}"

def prev_ym(ym: str) -> str:
    y, m = int(ym[:4]), int(ym[5:7])
    return f"{y-1}-12" if m == 1 else f"{y}-{m-1:02d}"

def next_ym(ym: str) -> str:
    y, m = int(ym[:4]), int(ym[5:7])
    return f"{y+1}-01" if m == 12 else f"{y}-{m+1:02d}"

def fmt_mes(ym: str) -> str:
    MESES = ["Jan","Fev","Mar","Abr","Mai","Jun",
             "Jul","Ago","Set","Out","Nov","Dez"]
    y, m = int(ym[:4]), int(ym[5:7])
    return f"{MESES[m-1]}/{y}"

def fmt_brl(v: float) -> str:
    s = f"{abs(v):,.2f}".replace(",","X").replace(".",",").replace("X",".")
    return f"R$ {s}"

# ═════════════════════════════════════════════════════════════
# FECHAMENTOS — lógica central
# ═════════════════════════════════════════════════════════════

def get_ultimo_mes_fechado() -> str | None:
    """Retorna o YYYY-MM do último mês com status='confirmado'."""
    rows = db().table("fechamentos") \
        .select("ano_mes") \
        .eq("status", "confirmado") \
        .order("ano_mes", desc=True) \
        .limit(1).execute().data
    return rows[0]["ano_mes"] if rows else None

def get_fechamento(ym: str) -> dict | None:
    rows = db().table("fechamentos").select("*").eq("ano_mes", ym).execute().data
    return rows[0] if rows else None

def garantir_draft_mes_anterior():
    """
    Chamado ao abrir o app.
    Se hoje é dia 1° (ou o draft ainda não existe), cria o draft do mês anterior.
    """
    hoje = datetime.date.today()
    mes_anterior = prev_ym(current_ym())
    existente = get_fechamento(mes_anterior)
    if not existente:
        db().table("fechamentos").insert({
            "ano_mes": mes_anterior,
            "status": "draft",
        }).execute()

def confirmar_fechamento(ym: str, usuario: str):
    db().table("fechamentos").update({
        "status": "confirmado",
        "confirmado_em": datetime.datetime.utcnow().isoformat(),
        "confirmado_por": usuario,
    }).eq("ano_mes", ym).execute()

# ═════════════════════════════════════════════════════════════
# FINANCEIRO
# ═════════════════════════════════════════════════════════════

def get_periodos():
    rows = db().table("periodos").select("de,valor").order("de").execute().data
    return [(r["de"], float(r["valor"])) for r in rows]

def get_valor_mes(periodos, ym: str) -> float:
    v = 0.0
    for de, val in periodos:
        if ym >= de:
            v = val
        else:
            break
    return v

def get_meta_acumulada(periodos, aluno: dict, ate_ym: str) -> float:
    """
    Meta até ate_ym, respeitando:
    - Início no primeiro período configurado
    - Teto = min(ate_ym, mês da desistência) para desistentes
    """
    if not periodos:
        return 0.0
    inicio = periodos[0][0]
    teto = ate_ym
    if aluno.get("data_desistencia"):
        des_ym = aluno["data_desistencia"][:7]
        if des_ym < teto:
            teto = des_ym
    total, cur = 0.0, inicio
    while cur <= teto:
        total += get_valor_mes(periodos, cur)
        cur = next_ym(cur)
    return total

def carregar_transacoes_agrupadas():
    """
    Uma query: retorna dict {aluno_id: {mensalidade, devolucao}}
    Devoluções são tratadas separadamente — nunca compõem o saldo geral.
    """
    rows = db().table("transacoes") \
        .select("aluno_id,valor,categoria") \
        .in_("categoria", ["MENSALIDADE","DEVOLUCAO"]) \
        .execute().data
    result: dict[str, dict] = {}
    for r in rows:
        aid = r["aluno_id"]
        if not aid:
            continue
        if aid not in result:
            result[aid] = {"mensalidade": 0.0, "devolucao": 0.0}
        if r["categoria"] == "MENSALIDADE":
            result[aid]["mensalidade"] += float(r["valor"])
        else:
            result[aid]["devolucao"] += abs(float(r["valor"]))
    return result

def get_meses_adiantados(periodos, credito: float, ate_ym: str) -> int:
    if credito <= 0:
        return 0
    cur, restante, count = next_ym(ate_ym), credito, 0
    while restante > 0 and count < 60:
        v = get_valor_mes(periodos, cur)
        if v == 0:
            break
        if restante >= v:
            restante -= v; count += 1; cur = next_ym(cur)
        else:
            break
    return count

def calcular_aluno(aluno, periodos, trans, ate_ym: str) -> dict:
    """
    Retorna dict com todos os campos financeiros de um aluno.

    Para desistentes:
      - total_pago   = tudo que pagou (independente do mês)
      - devolucao    = o que já foi devolvido
      - dev_pendente = total_pago - devolucao  (o que ainda falta devolver)
      - Devoluções NÃO entram no saldo geral do caixa

    Para ativos:
      - meta         = acumulado até ate_ym
      - saldo        = total_pago - meta  (positivo=crédito, negativo=débito)
      - adiantados   = meses cobertos pelo crédito extra
    """
    t = trans.get(aluno["id"], {"mensalidade": 0.0, "devolucao": 0.0})
    total_pago  = t["mensalidade"]
    devolucao   = t["devolucao"]

    if aluno["status"] == "Inativo":
        dev_pendente = max(0.0, total_pago - devolucao)
        return {
            "total_pago":   total_pago,
            "devolucao":    devolucao,
            "dev_pendente": dev_pendente,
            "meta":         0.0,
            "saldo":        0.0,
            "adiantados":   0,
        }

    meta   = get_meta_acumulada(periodos, aluno, ate_ym)
    saldo  = total_pago - meta
    adiant = get_meses_adiantados(periodos, saldo, ate_ym)
    return {
        "total_pago":   total_pago,
        "devolucao":    0.0,
        "dev_pendente": 0.0,
        "meta":         meta,
        "saldo":        saldo,
        "adiantados":   adiant,
    }

def pagou_mes_corrente(aluno_id: str, ym: str) -> bool:
    """Verifica se houve mensalidade no mês YYYY-MM."""
    rows = db().table("transacoes") \
        .select("id") \
        .eq("aluno_id", aluno_id) \
        .eq("categoria", "MENSALIDADE") \
        .like("data", f"{ym}%") \
        .execute().data
    return len(rows) > 0

# ═════════════════════════════════════════════════════════════
# WHATSAPP (Meta Cloud API — gratuito)
# ═════════════════════════════════════════════════════════════

def enviar_whatsapp(para: str, mensagem: str) -> bool:
    """Envia mensagem via Meta WhatsApp Cloud API."""
    token    = st.secrets.get("WA_TOKEN", "")
    phone_id = st.secrets.get("WA_PHONE_ID", "")
    if not token or not phone_id:
        return False
    numero = re.sub(r"\D", "", para)
    payload = {
        "messaging_product": "whatsapp",
        "to": numero,
        "type": "text",
        "text": {"body": mensagem},
    }
    resp = requests.post(
        f"https://graph.facebook.com/v19.0/{phone_id}/messages",
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": "application/json"},
        json=payload,
        timeout=10,
    )
    return resp.status_code == 200

def notificar_tesoureiras(assunto: str, corpo: str):
    numeros = [n.strip() for n in
               st.secrets.get("TESOUREIRAS_WA", "+5511982159674").split(",")]
    ok = all(enviar_whatsapp(n, f"🎓 *{assunto}*\n\n{corpo}") for n in numeros)
    return ok

# ═════════════════════════════════════════════════════════════
# PDF
# ═════════════════════════════════════════════════════════════

def gerar_pdf(ym: str, periodos, alunos, trans) -> bytes:
    hoje = datetime.date.today().strftime("%d/%m/%Y")
    rows_ativos, rows_desist = [], []
    total_mensalidades = 0.0
    n_em_dia = n_dev = 0

    for a in alunos:
        calc = calcular_aluno(a, periodos, trans, ym)
        if a["status"] == "Inativo":
            rows_desist.append([
                a["id"], a["nome"], f"Turma {a['turma']}",
                fmt_brl(calc["total_pago"]),
                fmt_brl(calc["devolucao"]),
                fmt_brl(calc["dev_pendente"]),
            ])
            continue
        total_mensalidades += calc["total_pago"]
        if calc["saldo"] >= 0:
            n_em_dia += 1
            rows_ativos.append([a["id"], a["nome"], f"Turma {a['turma']}",
                                 fmt_brl(calc["total_pago"]), "Em dia"])
        else:
            n_dev += 1
            rows_ativos.append([a["id"], a["nome"], f"Turma {a['turma']}",
                                 fmt_brl(abs(calc["saldo"])), "DEVEDOR"])

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
        rightMargin=36, leftMargin=36, topMargin=36, bottomMargin=36)
    styles = getSampleStyleSheet()
    H1  = ParagraphStyle("H1",  parent=styles["Heading1"], fontSize=16,
            textColor=colors.HexColor("#1b4332"), spaceAfter=4)
    H2  = ParagraphStyle("H2",  parent=styles["Heading2"], fontSize=12,
            textColor=colors.HexColor("#2d6a4f"), spaceBefore=14, spaceAfter=6)
    SUB = ParagraphStyle("SUB", parent=styles["Normal"], fontSize=9,
            textColor=colors.gray, spaceAfter=8)

    ts_base = TableStyle([
        ("BACKGROUND",(0,0),(-1,-1),colors.HexColor("#f9fafb")),
        ("GRID",(0,0),(-1,-1),.5,colors.HexColor("#e2e0d8")),
        ("FONTNAME",(0,0),(0,-1),"Helvetica-Bold"),
        ("ALIGN",(1,0),(1,-1),"RIGHT"),
        ("FONTSIZE",(0,0),(-1,-1),10),
    ])
    ts_al = TableStyle([
        ("BACKGROUND",(0,0),(-1,0),colors.HexColor("#1b4332")),
        ("TEXTCOLOR",(0,0),(-1,0),colors.white),
        ("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),
        ("FONTSIZE",(0,0),(-1,-1),9),
        ("GRID",(0,0),(-1,-1),.5,colors.HexColor("#e2e0d8")),
        ("ALIGN",(3,1),(3,-1),"RIGHT"),
        ("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white,colors.HexColor("#f9fafb")]),
    ])
    for i, r in enumerate(rows_ativos):
        if r[4] == "DEVEDOR":
            ts_al.add("TEXTCOLOR",(3,i+1),(4,i+1),colors.HexColor("#b91c1c"))
            ts_al.add("FONTNAME",(3,i+1),(4,i+1),"Helvetica-Bold")

    elems = [
        Paragraph(f"🎓 Formatura Oshiman 2028 — Fechamento {fmt_mes(ym)}", H1),
        Paragraph(f"Emitido em {hoje}  |  Referência: {fmt_mes(ym)}", SUB),
        HRFlowable(width="100%",thickness=1,color=colors.HexColor("#e2e0d8"),spaceAfter=10),
        Paragraph("Resumo financeiro", H2),
        Table([
            ["Total de mensalidades arrecadadas", fmt_brl(total_mensalidades)],
            ["Alunos em dia",                     str(n_em_dia)],
            ["Alunos devedores",                  str(n_dev)],
        ], colWidths=[300,160], style=ts_base),
        Spacer(1,12),
        Paragraph("Situação por aluno", H2),
        Table([["ID","Nome","Turma","Valor","Situação"]] + rows_ativos,
              colWidths=[30,210,60,90,70], style=ts_al),
    ]
    if rows_desist:
        ts_d = TableStyle([
            ("BACKGROUND",(0,0),(-1,0),colors.HexColor("#5a5850")),
            ("TEXTCOLOR",(0,0),(-1,0),colors.white),
            ("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),
            ("FONTSIZE",(0,0),(-1,-1),9),
            ("GRID",(0,0),(-1,-1),.5,colors.HexColor("#e2e0d8")),
            ("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white,colors.HexColor("#f9fafb")]),
        ])
        elems += [
            Spacer(1,12),
            Paragraph("Desistentes — histórico de devoluções", H2),
            Table(
                [["ID","Aluno","Turma","Total pago","Devolvido","Pendente"]] + rows_desist,
                colWidths=[30,180,55,85,85,75], style=ts_d
            ),
        ]
    doc.build(elems)
    buf.seek(0)
    return buf.getvalue()

# ═════════════════════════════════════════════════════════════
# MATCHING / IMPORTAÇÃO
# ═════════════════════════════════════════════════════════════

def match_aluno(descricao: str, alunos_ativos: list):
    up = descricao.upper()
    for a in alunos_ativos:
        if a["termos_pix"]:
            for t in [x.strip().upper() for x in a["termos_pix"].split(",")]:
                if t and t in up:
                    return a["id"], a["nome"]
    return None, None

def detecta_categoria(descricao: str, valor: float, tem_aluno: bool) -> str:
    up = descricao.upper()
    if any(k in up for k in ["APLIC","PRIVILEGE","INVEST"]):
        return "RESGATE" if valor > 0 else "INVESTIMENTO"
    if "RESGATE" in up:
        return "RESGATE"
    if any(k in up for k in ["REND","APLIC AUT"]):
        return "RENDIMENTO"
    if tem_aluno:
        return "MENSALIDADE" if valor > 0 else "DEVOLUCAO"
    return "SAIDA" if valor < 0 else "OUTRO"

def parse_csv(texto: str, alunos_ativos: list) -> list:
    linhas = []
    sep = ";" if texto.count(";") > texto.count(",") else ","
    for parts in csv.reader(io.StringIO(texto), delimiter=sep):
        parts = [p.strip().strip('"\'') for p in parts]
        if len(parts) < 3:
            continue
        dm = re.match(r"(\d{2})/(\d{2})/(\d{4})", parts[0])
        if not dm:
            continue
        data = f"{dm.group(3)}-{dm.group(2)}-{dm.group(1)}"
        try:
            valor = float(parts[2].replace(".", "").replace(",", "."))
        except:
            continue
        desc = parts[1]
        dup = db().table("transacoes").select("id") \
            .eq("data", data).eq("descricao", desc).execute().data
        if dup:
            continue
        aluno_id, aluno_nome = match_aluno(desc, alunos_ativos)
        categoria = detecta_categoria(desc, valor, bool(aluno_id))
        linhas.append({"data": data, "descricao": desc, "valor": valor,
                        "aluno_id": aluno_id, "aluno_nome": aluno_nome,
                        "categoria": categoria})
    return linhas

# ═════════════════════════════════════════════════════════════
# LOGIN
# ═════════════════════════════════════════════════════════════

def tela_login():
    st.markdown("""
    <div style="text-align:center;padding:48px 0 24px">
      <div style="font-size:52px">🎓</div>
      <h2 style="margin:8px 0 4px;color:#1b4332">Formatura Oshiman 2028</h2>
      <p style="color:#8a877e;font-size:14px">Gestão Financeira da Comissão</p>
    </div>
    """, unsafe_allow_html=True)
    perfil = st.selectbox("Perfil de acesso", ["Tesouraria","Consulta"])
    senha  = st.text_input("Senha", type="password")
    if st.button("Entrar", type="primary"):
        chave = "SENHA_TESOURARIA" if perfil == "Tesouraria" else "SENHA_CONSULTA"
        if senha == st.secrets.get(chave, ""):
            st.session_state["perfil"] = perfil
            st.rerun()
        else:
            st.error("Senha incorreta")

# ═════════════════════════════════════════════════════════════
# MAIN
# ═════════════════════════════════════════════════════════════

if "perfil" not in st.session_state:
    tela_login()
    st.stop()

perfil   = st.session_state["perfil"]
is_admin = perfil == "Tesouraria"

# Garante draft do mês anterior sempre que o app abre
garantir_draft_mes_anterior()

st.markdown(f"""
<div class="top-nav">
  <h3>🎓 Oshiman 2028</h3>
  <span>{'🔑 Tesouraria' if is_admin else '👁 Consulta'}</span>
</div>
""", unsafe_allow_html=True)

# Banner de draft pendente (para admin)
if is_admin:
    mes_anterior = prev_ym(current_ym())
    fech = get_fechamento(mes_anterior)
    if fech and fech["status"] == "draft":
        st.markdown(f"""
        <div class="draft-box">
          <h4>⚠️ Fechamento de {fmt_mes(mes_anterior)} aguarda confirmação</h4>
          <p>Revise a situação dos alunos e confirme o fechamento na aba 📄 Fechamento.</p>
        </div>
        """, unsafe_allow_html=True)

if st.button("Sair", type="secondary"):
    del st.session_state["perfil"]
    st.rerun()

tabs = st.tabs(["📋 Mês corrente", "📊 Situação fechada", "📥 Extrato",
                "📄 Fechamento", "⚙️ Cadastros"])

# ════════════════════════════════════════════════════════════
# ABA 0 — MÊS CORRENTE (prévia — quem já pagou este mês)
# ════════════════════════════════════════════════════════════
with tabs[0]:
    hoje_ym  = current_ym()
    alunos   = db().table("alunos").select("*").order("turma").order("id").execute().data
    ativos   = [a for a in alunos if a["status"] == "Ativo"]

    st.markdown(f'<div class="sec-title">Prévia — {fmt_mes(hoje_ym)}</div>',
        unsafe_allow_html=True)
    st.markdown("""
    <div class="info-box">
    Esta é uma <b>prévia</b>. Os pais têm o mês inteiro para pagar.
    Ninguém é considerado devedor aqui — isso só acontece após o fechamento do mês.
    </div>
    """, unsafe_allow_html=True)

    pagaram, nao_pagaram = [], []
    for a in ativos:
        if pagou_mes_corrente(a["id"], hoje_ym):
            pagaram.append(a)
        else:
            nao_pagaram.append(a)

    st.markdown(f"""
    <div class="stat-row">
      <div class="stat-card">
        <div class="lbl">Já pagaram</div>
        <div class="val green">{len(pagaram)}</div>
      </div>
      <div class="stat-card">
        <div class="lbl">Ainda não pagaram</div>
        <div class="val orange">{len(nao_pagaram)}</div>
      </div>
      <div class="stat-card">
        <div class="lbl">Total ativos</div>
        <div class="val">{len(ativos)}</div>
      </div>
    </div>
    """, unsafe_allow_html=True)

    if nao_pagaram:
        st.markdown("**Ainda não pagaram este mês:**")
        for a in nao_pagaram:
            cel  = re.sub(r"\D", "", a["celular"] or "")
            msg  = (f"Olá! Passando para lembrar da mensalidade de {fmt_mes(hoje_ym)} "
                    f"da Formatura Oshiman. 🎓")
            link = f"https://wa.me/55{cel}?text={urllib.parse.quote(msg)}"
            st.markdown(f"""
            <div class="aluno-card">
              <div class="aluno-nome">{a['nome']}</div>
              <div class="aluno-sub">ID {a['id']} · Turma {a['turma']}</div>
              <span class="badge badge-warn">Não pagou {fmt_mes(hoje_ym)}</span>
            </div>
            """, unsafe_allow_html=True)
            if is_admin:
                st.link_button(f"📲 Lembrete WhatsApp — {a['nome'].split()[0]}", link)

    if pagaram:
        st.markdown("**Já pagaram:**")
        for a in pagaram:
            st.markdown(f"""
            <div class="aluno-card">
              <div class="aluno-nome">{a['nome']}</div>
              <div class="aluno-sub">ID {a['id']} · Turma {a['turma']}</div>
              <span class="badge badge-green">✓ Pago em {fmt_mes(hoje_ym)}</span>
            </div>
            """, unsafe_allow_html=True)

# ════════════════════════════════════════════════════════════
# ABA 1 — SITUAÇÃO FECHADA (baseada no último mês confirmado)
# ════════════════════════════════════════════════════════════
with tabs[1]:
    ultimo_fechado = get_ultimo_mes_fechado()
    periodos = get_periodos()
    alunos   = db().table("alunos").select("*").order("turma").order("id").execute().data
    trans    = carregar_transacoes_agrupadas()

    if not ultimo_fechado:
        st.markdown('<div class="warn-box">Nenhum mês fechado ainda. '
            'Confirme um fechamento na aba 📄 Fechamento.</div>', unsafe_allow_html=True)
    else:
        st.markdown(f'<div class="sec-title">Situação — até {fmt_mes(ultimo_fechado)}</div>',
            unsafe_allow_html=True)

        ativos   = [a for a in alunos if a["status"] == "Ativo"]
        inativos = [a for a in alunos if a["status"] == "Inativo"]

        total_mensalidades = total_debito = 0.0
        n_em_dia = n_dev = 0
        items = []

        for a in ativos:
            calc = calcular_aluno(a, periodos, trans, ultimo_fechado)
            total_mensalidades += calc["total_pago"]
            if calc["saldo"] >= 0:
                n_em_dia += 1
            else:
                n_dev += 1
                total_debito += abs(calc["saldo"])
            items.append((a, calc))

        st.markdown(f"""
        <div class="stat-row">
          <div class="stat-card">
            <div class="lbl">Mensalidades</div>
            <div class="val green">{fmt_brl(total_mensalidades)}</div>
          </div>
          <div class="stat-card">
            <div class="lbl">Em débito</div>
            <div class="val red">{fmt_brl(total_debito)}</div>
          </div>
          <div class="stat-card">
            <div class="lbl">Em dia</div>
            <div class="val">{n_em_dia}</div>
          </div>
          <div class="stat-card">
            <div class="lbl">Devedores</div>
            <div class="val red">{n_dev}</div>
          </div>
        </div>
        """, unsafe_allow_html=True)

        filtro = st.selectbox("Filtrar", ["Todos","Só devedores","Só em dia"],
            label_visibility="collapsed")

        # Alunos ativos
        for a, calc in items:
            saldo  = calc["saldo"]
            adiant = calc["adiantados"]
            if filtro == "Só devedores" and saldo >= 0: continue
            if filtro == "Só em dia"   and saldo <  0: continue

            detalhe = f"Pago: {fmt_brl(calc['total_pago'])} | Meta: {fmt_brl(calc['meta'])}"
            if saldo >= 0:
                adiant_str = (f' <span class="badge badge-warn">'
                    f'{adiant} {"mês" if adiant==1 else "meses"} adiant.</span>'
                    if adiant > 0 else "")
                badge = f'<span class="badge badge-green">Em dia</span>{adiant_str}'
            else:
                badge = f'<span class="badge badge-red">Deve {fmt_brl(abs(saldo))}</span>'

            st.markdown(f"""
            <div class="aluno-card">
              <div class="aluno-nome">{a['nome']}</div>
              <div class="aluno-sub">ID {a['id']} · Turma {a['turma']} · {detalhe}</div>
              {badge}
            </div>
            """, unsafe_allow_html=True)

            if saldo < 0 and is_admin:
                cel  = re.sub(r"\D", "", a["celular"] or "")
                msg  = (f"Olá! Consta um débito de {fmt_brl(abs(saldo))} referente "
                        f"às mensalidades da Formatura Oshiman. "
                        f"Podemos confirmar o pagamento? 🎓")
                link = f"https://wa.me/55{cel}?text={urllib.parse.quote(msg)}"
                st.link_button(f"📲 Cobrar {fmt_brl(abs(saldo))} — {a['nome'].split()[0]}", link)

        # Desistentes — sempre visíveis, em cinza, no final
        if inativos and filtro == "Todos":
            st.markdown('<div class="sec-title">Desistentes</div>', unsafe_allow_html=True)
            for a in inativos:
                calc = calcular_aluno(a, periodos, trans, ultimo_fechado)
                dev_badge = (
                    f'<span class="badge badge-warn">Devolução pendente {fmt_brl(calc["dev_pendente"])}</span>'
                    if calc["dev_pendente"] > 0.01
                    else '<span class="badge badge-gray">Devolução concluída</span>'
                )
                detalhe = (f"Total pago: {fmt_brl(calc['total_pago'])} | "
                           f"Devolvido: {fmt_brl(calc['devolucao'])}")
                st.markdown(f"""
                <div class="aluno-card-inativo">
                  <div class="aluno-nome-inativo">⏹ {a['nome']}</div>
                  <div class="aluno-sub">ID {a['id']} · Turma {a['turma']} · {detalhe}</div>
                  {dev_badge}
                </div>
                """, unsafe_allow_html=True)

# ════════════════════════════════════════════════════════════
# ABA 2 — EXTRATO / IMPORTAÇÃO
# ════════════════════════════════════════════════════════════
with tabs[2]:
    if not is_admin:
        st.markdown('<div class="info-box">🔒 Disponível apenas para Tesouraria.</div>',
            unsafe_allow_html=True)
        st.stop()

    st.markdown('<div class="sec-title">Importar extrato (CSV)</div>', unsafe_allow_html=True)
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
                    .eq("status","Ativo").execute().data
                linhas = parse_csv(csv_texto, alunos_ativos)
            if not linhas:
                st.info("Nenhuma linha nova encontrada (já importadas ou formato inválido).")
            else:
                st.session_state["pending"] = linhas
                st.rerun()

    if "pending" in st.session_state:
        linhas = st.session_state["pending"]
        nao_id = [l for l in linhas
                  if not l["aluno_id"] and l["categoria"] in ("OUTRO","SAIDA")]

        st.success(f"**{len(linhas)}** linha(s) novas. " +
            (f"**{len(nao_id)}** precisam de identificação manual."
             if nao_id else "Todas identificadas ✓"))

        if nao_id:
            alunos_opts = db().table("alunos").select("id,nome") \
                .eq("status","Ativo").execute().data
            opts_map = {a["nome"]: a["id"] for a in alunos_opts}
            st.markdown('<div class="sec-title">Identificar manualmente</div>',
                unsafe_allow_html=True)
            for l in nao_id:
                gi = linhas.index(l)
                st.markdown(f"**{l['data']}** · {l['descricao']} · `{fmt_brl(l['valor'])}`")
                opcoes = (["— não identificado —","Investimento/Saída","Devolução s/ aluno"]
                          + list(opts_map.keys()))
                escolha = st.selectbox("Atribuir a:", opcoes, key=f"attr_{gi}")
                if escolha == "Investimento/Saída":
                    linhas[gi].update({"categoria": "INVESTIMENTO" if l["valor"] < 0 else "RESGATE",
                                       "aluno_id": None})
                elif escolha == "Devolução s/ aluno":
                    linhas[gi].update({"categoria": "DEVOLUCAO", "aluno_id": None})
                elif escolha in opts_map:
                    linhas[gi].update({
                        "aluno_id": opts_map[escolha], "aluno_nome": escolha,
                        "categoria": "MENSALIDADE" if l["valor"] > 0 else "DEVOLUCAO"
                    })

        st.markdown('<div class="sec-title">Prévia</div>', unsafe_allow_html=True)
        st.dataframe(pd.DataFrame([{
            "Data": l["data"], "Descrição": l["descricao"][:42],
            "Valor": fmt_brl(l["valor"]),
            "Aluno": l["aluno_nome"] or "—",
            "Categoria": l["categoria"]
        } for l in linhas]), use_container_width=True, hide_index=True)

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

    st.markdown('<div class="sec-title">Histórico de transações</div>', unsafe_allow_html=True)
    anos_rows = db().table("transacoes").select("data").order("data",desc=True).execute().data
    anos = sorted({r["data"][:4] for r in anos_rows}, reverse=True)
    ano_filt = st.selectbox("Ano", ["Todos"] + anos, label_visibility="collapsed")
    q = db().table("transacoes").select("data,descricao,valor,categoria,aluno_id") \
        .order("data", desc=True)
    if ano_filt != "Todos":
        q = q.like("data", f"{ano_filt}%")
    st.dataframe(pd.DataFrame([{
        "Data": r["data"], "Descrição": r["descricao"],
        "Valor": fmt_brl(r["valor"]),
        "Categoria": r["categoria"], "Aluno": r["aluno_id"] or "—"
    } for r in q.execute().data]), use_container_width=True, hide_index=True)

# ════════════════════════════════════════════════════════════
# ABA 3 — FECHAMENTO
# ════════════════════════════════════════════════════════════
with tabs[3]:
    periodos = get_periodos()
    alunos   = db().table("alunos").select("*").order("turma").order("id").execute().data
    trans    = carregar_transacoes_agrupadas()

    # Draft pendente
    mes_anterior = prev_ym(current_ym())
    fech = get_fechamento(mes_anterior)

    if fech and fech["status"] == "draft":
        st.markdown(f"""
        <div class="draft-box">
          <h4>📋 Draft — {fmt_mes(mes_anterior)}</h4>
          <p>Criado automaticamente. Revise abaixo e confirme quando estiver pronto.</p>
        </div>
        """, unsafe_allow_html=True)

        # Preview do fechamento
        rows_prev = []
        for a in alunos:
            calc = calcular_aluno(a, periodos, trans, mes_anterior)
            if a["status"] == "Inativo":
                sit = f"Desistente (dev. pendente: {fmt_brl(calc['dev_pendente'])})" \
                    if calc["dev_pendente"] > 0.01 else "Desistente (quitado)"
            elif calc["saldo"] >= 0:
                sit = "✅ Em dia"
            else:
                sit = f"🔴 Deve {fmt_brl(abs(calc['saldo']))}"
            rows_prev.append({
                "ID": a["id"], "Aluno": a["nome"],
                "Pago": fmt_brl(calc["total_pago"]),
                "Meta": fmt_brl(calc["meta"]) if a["status"]=="Ativo" else "—",
                "Situação": sit
            })
        st.dataframe(pd.DataFrame(rows_prev), use_container_width=True, hide_index=True)

        if is_admin:
            if st.button(f"✅ Confirmar fechamento de {fmt_mes(mes_anterior)}", type="primary"):
                with st.spinner("Confirmando e notificando..."):
                    confirmar_fechamento(mes_anterior, perfil)
                    # Notifica tesoureiras via WhatsApp
                    devedores = [r for r in rows_prev
                                 if r["Situação"].startswith("🔴")]
                    corpo = (
                        f"Fechamento de {fmt_mes(mes_anterior)} confirmado.\n"
                        f"Devedores: {len(devedores)}\n"
                        + ("\n".join(f"• {r['Aluno']}: {r['Situação']}"
                                     for r in devedores) if devedores
                           else "✅ Todos em dia!")
                    )
                    ok = notificar_tesoureiras(
                        f"Fechamento {fmt_mes(mes_anterior)}", corpo)
                    if ok:
                        st.success("✓ Fechamento confirmado e WhatsApp enviado!")
                    else:
                        st.success("✓ Fechamento confirmado!")
                        st.warning("WhatsApp não enviado — verifique WA_TOKEN e WA_PHONE_ID nos secrets.")
                st.rerun()

    # Histórico de fechamentos
    st.markdown('<div class="sec-title">Histórico de fechamentos</div>', unsafe_allow_html=True)
    fechs = db().table("fechamentos").select("*").order("ano_mes", desc=True).execute().data
    if not fechs:
        st.info("Nenhum fechamento registrado.")
    else:
        for f in fechs:
            icon = "✅" if f["status"] == "confirmado" else "📋"
            conf = f["confirmado_em"][:10] if f["confirmado_em"] else "—"
            by   = f["confirmado_por"] or "—"
            with st.expander(f"{icon} {fmt_mes(f['ano_mes'])} — {f['status'].upper()}"):
                st.markdown(f"**Criado em:** {f['criado_em'][:10]}  |  "
                    f"**Confirmado em:** {conf}  |  **Por:** {by}")
                if f["status"] == "confirmado":
                    if st.button(f"📥 Baixar PDF {fmt_mes(f['ano_mes'])}",
                                 key=f"pdf_{f['ano_mes']}"):
                        with st.spinner("Gerando PDF..."):
                            pdf = gerar_pdf(f["ano_mes"], periodos, alunos, trans)
                        st.download_button(
                            f"⬇ {fmt_mes(f['ano_mes'])}.pdf", data=pdf,
                            file_name=f"Fechamento_Oshiman_{f['ano_mes']}.pdf",
                            mime="application/pdf", key=f"dl_{f['ano_mes']}"
                        )

# ════════════════════════════════════════════════════════════
# ABA 4 — CADASTROS
# ════════════════════════════════════════════════════════════
with tabs[4]:
    if not is_admin:
        st.markdown('<div class="info-box">🔒 Disponível apenas para Tesouraria.</div>',
            unsafe_allow_html=True)
        st.stop()

    sub1, sub2, sub3 = st.tabs(["Alunos ativos", "Desistentes", "Mensalidades"])

    with sub1:
        alunos = db().table("alunos").select("*").order("turma").order("id").execute().data
        for a in [x for x in alunos if x["status"] == "Ativo"]:
            with st.expander(f"✅ {a['nome']} ({a['id']})"):
                c1, c2 = st.columns(2)
                nome   = c1.text_input("Nome",    value=a["nome"],          key=f"n_{a['id']}")
                cel    = c2.text_input("Celular", value=a["celular"] or "",  key=f"c_{a['id']}")
                termos = st.text_input("Apelidos PIX (vírgula)",
                    value=a["termos_pix"] or "", key=f"p_{a['id']}")
                c3, c4 = st.columns(2)
                if c3.button("Salvar", key=f"sv_{a['id']}"):
                    db().table("alunos").update({
                        "nome": nome, "celular": cel,
                        "termos_pix": termos.upper()
                    }).eq("id", a["id"]).execute()
                    st.success("Salvo!"); st.rerun()
                if c4.button("⚠️ Registrar desistência", key=f"d_{a['id']}"):
                    st.session_state[f"des_{a['id']}"] = True
                if st.session_state.get(f"des_{a['id']}"):
                    data_d = st.date_input("Data da desistência", key=f"dd_{a['id']}")
                    if st.button("Confirmar", key=f"cd_{a['id']}", type="primary"):
                        db().table("alunos").update({
                            "status": "Inativo",
                            "data_desistencia": str(data_d)
                        }).eq("id", a["id"]).execute()
                        del st.session_state[f"des_{a['id']}"]
                        st.rerun()

        st.divider()
        st.markdown("**Adicionar novo aluno**")
        c1, c2, c3 = st.columns(3)
        n_id    = c1.text_input("ID (ex: 11A)")
        n_nome  = c2.text_input("Nome completo")
        n_turma = c3.text_input("Turma (A/B)")
        n_cel   = st.text_input("Celular WhatsApp")
        n_pix   = st.text_input("Apelidos PIX (vírgula)")
        if st.button("Adicionar aluno", type="primary"):
            if n_id and n_nome:
                try:
                    db().table("alunos").insert({
                        "id": n_id, "nome": n_nome, "status": "Ativo",
                        "turma": n_turma, "celular": n_cel,
                        "termos_pix": n_pix.upper()
                    }).execute()
                    st.success("Aluno adicionado!"); st.rerun()
                except Exception as e:
                    st.error(f"Erro: {e}")

    with sub2:
        alunos   = db().table("alunos").select("*").order("data_desistencia",desc=True).execute().data
        inativos = [a for a in alunos if a["status"] == "Inativo"]
        trans    = carregar_transacoes_agrupadas()
        periodos = get_periodos()

        if not inativos:
            st.info("Nenhum desistente registrado.")
        else:
            for a in inativos:
                calc = calcular_aluno(a, periodos, trans, current_ym())
                with st.expander(f"⏹ {a['nome']} ({a['id']}) — desistência: {a['data_desistencia'] or '—'}"):
                    c1, c2, c3 = st.columns(3)
                    c1.metric("Total pago", fmt_brl(calc["total_pago"]))
                    c2.metric("Devolvido",  fmt_brl(calc["devolucao"]))
                    c3.metric("Pendente",   fmt_brl(calc["dev_pendente"]))

                    trans_aluno = db().table("transacoes").select("data,descricao,valor,categoria") \
                        .eq("aluno_id", a["id"]).order("data").execute().data
                    if trans_aluno:
                        st.dataframe(pd.DataFrame([{
                            "Data": t["data"], "Descrição": t["descricao"][:38],
                            "Valor": fmt_brl(t["valor"]), "Categoria": t["categoria"]
                        } for t in trans_aluno]), use_container_width=True, hide_index=True)

                    if st.button("↩️ Reativar", key=f"r_{a['id']}"):
                        db().table("alunos").update({
                            "status": "Ativo", "data_desistencia": None
                        }).eq("id", a["id"]).execute()
                        st.rerun()

    with sub3:
        periodos = get_periodos()
        st.markdown("""
        <div class="info-box">
        Cada período define o valor mensal a partir de uma data (AAAA-MM).
        O sistema acumula automaticamente conforme os meses passam.
        </div>
        """, unsafe_allow_html=True)
        updated = []
        for i, (de, val) in enumerate(periodos):
            c1, c2 = st.columns([2,2])
            nd = c1.text_input("A partir de (AAAA-MM)", value=de,        key=f"pd_{i}")
            nv = c2.number_input("Valor mensal R$",      value=float(val), key=f"pv_{i}", step=10.0)
            updated.append((nd, nv))
        if st.button("+ Adicionar período"):
            updated.append(("", 0.0))
        if st.button("Salvar mensalidades", type="primary"):
            db().table("periodos").upsert(
                [{"de": d, "valor": v} for d, v in updated if d]
            ).execute()
            st.success("Salvo!")
