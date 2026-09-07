"""
Módulo de lógica financeira — separado da UI (Streamlit) pra ser testável sem banco.

Todas as funções aqui são "puras": recebem dados (linhas do Supabase ou listas) e
retornam valores. Nenhuma delas sabe o que é Streamlit. Os nomes/categorias seguem
os usados no banco:

  Categorias de transação: MENSALIDADE, DEVOLUCAO, INVESTIMENTO, RESGATE,
                           RENDIMENTO, OUTRO, SAIDA
  - INVESTIMENTO: aplicação (valor NEGATIVO — saiu da conta corrente p/ investimento)
  - RESGATE:      resgate do investimento (valor POSITIVO — voltou pra conta)
  - RENDIMENTO:   rendimento creditado (valor POSITIVO, normalmente reinvestido)
  - DEVOLUCAO:    devolução a desistente (valor NEGATIVO)
"""

import datetime
from collections import defaultdict

# Categorias "econômicas" que somam para o patrimônio real (exclui as transferências
# internas conta-corrente <-> investimento, que se anulam).
CAT_INVEST   = {"INVESTIMENTO"}
CAT_RESGATE  = {"RESGATE"}
CAT_REND     = {"RENDIMENTO"}
CAT_MENSAL   = {"MENSALIDADE"}
CAT_DEVOL    = {"DEVOLUCAO"}

MESES = ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun",
         "Jul", "Ago", "Set", "Out", "Nov", "Dez"]


# ─── DATA ───────────────────────────────────────────────────────────────────
def current_ym() -> str:
    """YYYY-MM de hoje."""
    d = datetime.date.today()
    return f"{d.year}-{d.month:02d}"


def prev_ym(ym: str) -> str:
    y, m = int(ym[:4]), int(ym[5:7])
    return f"{y-1}-12" if m == 1 else f"{y}-{m-1:02d}"


def next_ym(ym: str) -> str:
    y, m = int(ym[:4]), int(ym[5:7])
    return f"{y+1}-01" if m == 12 else f"{y}-{m+1:02d}"


def fmt_mes(ym: str) -> str:
    y, m = int(ym[:4]), int(ym[5:7])
    return f"{MESES[m-1]}/{y}"


def fmt_brl(v: float) -> str:
    s = f"{abs(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {s}"


def arred(v: float) -> float:
    """Arredonda para centavos antes de comparações/somas críticas."""
    return round(float(v), 2)


# ─── FINANCEIRO ─────────────────────────────────────────────────────────────
def get_valor_mes(periodos, ym: str) -> float:
    """Valor da mensalidade vigente em ym, segundo a tabela períodos (de, valor)."""
    v = 0.0
    for de, val in periodos:
        if ym >= de:
            v = val
        else:
            break
    return v


def get_meta_acumulada(periodos, aluno: dict, ate_ym: str) -> float:
    """
    Meta acumulada até ate_ym (mês a mês desde o primeiro período), respeitando
    o teto da desistência para alunos inativos.
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


def agrupar_por_aluno(trans_rows, categorias_sel) -> dict:
    """
    Agrupa transações por aluno_id somando por categoria.
    Retorna {aluno_id: {categoria: soma}}.
    """
    agg: dict[str, dict] = defaultdict(lambda: defaultdict(float))
    for r in trans_rows:
        aid = r.get("aluno_id")
        if not aid:
            continue
        cat = r.get("categoria")
        if cat in categorias_sel:
            agg[aid][cat] += float(r.get("valor", 0.0))
    return {k: dict(v) for k, v in agg.items()}


def carregar_transacoes_agrupadas(trans_rows) -> dict:
    """
    Compatível com o uso atual: {aluno_id: {mensalidade, devolucao}}.
    Devoluções são tratadas separadamente — nunca compõem o saldo geral.
    """
    mensal = agrupar_por_aluno(trans_rows, CAT_MENSAL)
    devol = agrupar_por_aluno(trans_rows, CAT_DEVOL)
    result = {}
    for aid in set(mensal) | set(devol):
        result[aid] = {
            "mensalidade": sum(mensal.get(aid, {}).values()),
            "devolucao":   abs(sum(devol.get(aid, {}).values())),
        }
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
            restante -= v
            count += 1
            cur = next_ym(cur)
        else:
            break
    return count


def calcular_aluno(aluno, periodos, trans, ate_ym: str) -> dict:
    """
    Situação financeira de um aluno até ate_ym.

    Para desistentes: total_pago / devolucao / dev_pendente (devoluções não entram
    no saldo geral). Para ativos: meta, saldo (crédito/débito) e meses adiantados.
    """
    t = trans.get(aluno["id"], {"mensalidade": 0.0, "devolucao": 0.0})
    total_pago = arred(t["mensalidade"])
    devolucao = arred(t["devolucao"])

    if aluno["status"] == "Inativo":
        return {
            "total_pago": total_pago,
            "devolucao": devolucao,
            "dev_pendente": max(0.0, total_pago - devolucao),
            "meta": 0.0,
            "saldo": 0.0,
            "adiantados": 0,
        }

    meta = arred(get_meta_acumulada(periodos, aluno, ate_ym))
    saldo = arred(total_pago - meta)
    return {
        "total_pago": total_pago,
        "devolucao": 0.0,
        "dev_pendente": 0.0,
        "meta": meta,
        "saldo": saldo,
        "adiantados": get_meses_adiantados(periodos, saldo, ate_ym),
    }


# ─── PAINEL / CAIXA (o que faltava vs. planilha) ────────────────────────────
def resumo_por_categoria(trans_rows) -> dict:
    """Soma dos valores por categoria (usando os valores com sinal)."""
    out = defaultdict(float)
    for r in trans_rows:
        out[r.get("categoria", "OUTRO")] += float(r.get("valor", 0.0))
    return dict(out)


def calc_meta_ano(periodos, n_ativos: int, ano: int) -> float:
    """Meta esperada de um ano = nº de alunos ativos × soma do valor mensal no ano."""
    soma_ano = 0.0
    for m in range(1, 13):
        soma_ano += get_valor_mes(periodos, f"{ano}-{m:02d}")
    return round(soma_ano * n_ativos, 2)


def arrecadacao_por_ano(trans_rows) -> dict:
    """{ano: soma de MENSALIDADE}."""
    out = defaultdict(float)
    for r in trans_rows:
        if r.get("categoria") == "MENSALIDADE":
            data = r.get("data") or ""
            out[str(data)[:4]] += float(r.get("valor", 0.0))
    return {k: round(v, 2) for k, v in sorted(out.items())}


def calcular_painel(trans_rows, periodos, alunos, ate_ym: str) -> dict:
    """
    Painel de caixa consolidado (Espelha a aba "Visão Geral" da planilha).
    Semântica das transferências internas conta-corrente <-> investimento:
      - saldo_conta   = saldo da conta corrente real (soma de TODAS as linhas do extrato)
      - aportes       = total aplicado no investimento (|-INVESTIMENTO|)
      - resgates      = total resgatado do investimento (RESGATE)
      - rendimento    = rendimento creditado/acumulado (RENDIMENTO) — informativo
      - saldo_invest  = aportes - resgates   (o que está efetivamente aplicado)
      - patrimonio    = saldo_conta + saldo_invest (soma real = mensalidades - devoluções
                        + rendimento + demais, sem contar as transferências internas duas vezes)
    """
    inv = resumo_por_categoria(trans_rows)
    mensal = inv.get("MENSALIDADE", 0.0)
    devol = inv.get("DEVOLUCAO", 0.0)
    aportes = abs(sum(r["valor"] for r in trans_rows
                      if r.get("categoria") in CAT_INVEST and r["valor"] < 0))
    resgates = sum(r["valor"] for r in trans_rows
                   if r.get("categoria") in CAT_RESGATE and r["valor"] > 0)
    rendimento = inv.get("RENDIMENTO", 0.0)

    saldo_conta = sum(float(r["valor"]) for r in trans_rows)
    saldo_invest = aportes - resgates

    # Inadimplência = soma dos débitos dos ativos até ate_ym
    trans = carregar_transacoes_agrupadas(trans_rows)
    inadimplencia = 0.0
    for a in alunos:
        if a["status"] == "Inativo":
            continue
        c = calcular_aluno(a, periodos, trans, ate_ym)
        if c["saldo"] < 0:
            inadimplencia += abs(c["saldo"])

    n_ativos = sum(1 for a in alunos if a["status"] == "Ativo")

    return {
        "total_mensalidades": round(mensal, 2),
        "total_devolucoes": round(abs(devol), 2),
        "inadimplencia": round(inadimplencia, 2),
        "rendimento": round(rendimento, 2),
        "saldo_conta": round(saldo_conta, 2),
        "aportes": round(aportes, 2),
        "resgates": round(resgates, 2),
        "saldo_invest": round(saldo_invest, 2),
        "patrimonio": round(saldo_conta + saldo_invest, 2),
        "n_ativos": n_ativos,
        "arrecadacao_por_ano": arrecadacao_por_ano(trans_rows),
        "meta_ano": {str(ano): calc_meta_ano(periodos, n_ativos, ano)
                     for ano in _anos_periodo(periodos)},
    }


def _anos_periodo(periodos) -> list:
    anos = sorted({p[0][:4] for p in periodos if p[0] and len(p[0]) >= 4})
    return [int(a) for a in anos]


# ─── ORÇAMENTO / PREVISÃO ──────────────────────────────────────────────────
def total_orcamento(itens) -> float:
    """Soma dos valores do orçamento/previsão."""
    return round(sum(float(i.get("valor", 0.0)) for i in itens), 2)


# ─── MATCHING / IMPORTAÇÃO ─────────────────────────────────────────────────
def match_aluno(descricao: str, alunos_ativos: list):
    up = descricao.upper()
    for a in alunos_ativos:
        if a.get("termos_pix"):
            for t in [x.strip().upper() for x in a["termos_pix"].split(",")]:
                if t and t in up:
                    return a["id"], a["nome"]
    return None, None


def detecta_categoria(descricao: str, valor: float, tem_aluno: bool) -> str:
    up = descricao.upper()
    # REND antes de APLIC: linhas como "REND PAGO APLIC AUT" contêm "APLIC" mas são
    # rendimento, não investimento.
    if any(k in up for k in ["REND"]):
        return "RENDIMENTO"
    if any(k in up for k in ["APLIC", "PRIVILEGE", "INVEST"]):
        return "RESGATE" if valor > 0 else "INVESTIMENTO"
    if "RESGATE" in up:
        return "RESGATE"
    if tem_aluno:
        return "MENSALIDADE" if valor > 0 else "DEVOLUCAO"
    return "SAIDA" if valor < 0 else "OUTRO"