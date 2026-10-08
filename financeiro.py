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
import html as _html
import io
import csv
import re
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


# ─── SANITIZAÇÃO HTML (usada na hora de renderizar com unsafe_allow_html) ───
class Html(str):
    """Marca uma string como HTML JÁ SEGURO (não escapar) em render_table."""

    pass


def esc(v) -> str:
    """Escape HTML de dados vindos do banco/usuario antes de exibir no app."""
    return _html.escape(str(v) if v is not None else "", quote=True)


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


# ─── ATRIBUIÇÃO POR MÊS (regra FIFO dos pagamentos) ─────────────────────────
# A regra da comissao: cada pagamento quita o mês mais antigo em aberto primeiro
# e o valor excedente rola para o proximo mês. Ex.: pagou 1200 num ano de 100/mês
# -> 100 em cada mês. Pagou 240 com 2 meses devendo -> 100 jan, 100 fev, 40 mar.
# O resultado final depende apenas do TOTAL pago (a ordem dos lançamentos não
# muda a alocação), entao usamos total_pago para montar o calendário.

def alocacao_mensal(periodos, total_pago: float, ate_ym: str) -> list:
    """Distribui o total pago nos meses (FIFO) e devolve [{ym, devido, pago}] até ate_ym."""
    if not periodos:
        return []
    out = []
    restante = float(total_pago)
    ym = periodos[0][0]
    while ym <= ate_ym:
        v = arred(get_valor_mes(periodos, ym))
        if v > 0:
            pago = min(v, restante)
            restante = max(0.0, restante - v)
        else:
            pago = 0.0
        out.append({"ym": ym, "devido": arred(v), "pago": arred(pago)})
        ym = next_ym(ym)
    return out


def analise_mensal(periodos, total_pago: float, ate_ym: str) -> dict:
    """Interpreta o calendário FIFO até ate_ym.

    Retorna:
      - calendario        : [{ym, devido, pago}]
      - mes_inicial_debito: primeiro mês (<= ate_ym) não integralmente pago, ou None
      - mes_atual_pago    : bool — o próprio mês de ate_ym está integralmente pago
      - divida            : total não pago até ate_ym
    """
    cal = alocacao_mensal(periodos, total_pago, ate_ym)
    primeiro = None
    for m in cal:
        if m["devido"] > 0 and m["pago"] < m["devido"]:
            primeiro = m["ym"]
            break
    mes_atual_pago = True
    if cal:
        ult = cal[-1]
        mes_atual_pago = ult["pago"] >= ult["devido"] if ult["devido"] > 0 else True
    divida = arred(sum(max(0.0, m["devido"] - m["pago"]) for m in cal))
    return {"calendario": cal, "mes_inicial_debito": primeiro,
            "mes_atual_pago": mes_atual_pago, "divida": divida}


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
    ana = analise_mensal(periodos, total_pago, ate_ym)
    return {
        "total_pago": total_pago,
        "devolucao": 0.0,
        "dev_pendente": 0.0,
        "meta": meta,
        "saldo": saldo,
        "adiantados": get_meses_adiantados(periodos, saldo, ate_ym),
        # atribuição por mês (regra FIFO)
        "mes_atual_pago": ana["mes_atual_pago"],
        "mes_inicial_debito": ana["mes_inicial_debito"],
        "divida_mensal": ana["divida"],
    }


# ─── PAINEL / CAIXA (o que faltava vs. planilha) ────────────────────────────
def resumo_por_categoria(trans_rows) -> dict:
    """Soma dos valores por categoria (usando os valores com sinal)."""
    out = defaultdict(float)
    for r in trans_rows:
        out[r.get("categoria", "OUTRO")] += float(r.get("valor", 0.0))
    return dict(out)


def investimento_resumo(trans_rows, saldo_informado=None) -> dict:
    """Monitor do investimento.

    - aportes  = soma das aplicações que saíram da conta corrente (INVESTIMENTO)
    - resgates = soma do que voltou do investimento para a conta (RESGATE)
    - rendimento = saldo informado − aportes + resgates
                  (se não informou o saldo ainda, rendimento = None)
    """
    inv = resumo_por_categoria(trans_rows)
    aportes = round(-inv.get("INVESTIMENTO", 0.0), 2)
    resgates = round(inv.get("RESGATE", 0.0), 2)
    rend = None
    if saldo_informado is not None:
        rend = round(float(saldo_informado) - aportes + resgates, 2)
    return {"aportes": aportes, "resgates": resgates,
            "saldo_informado": saldo_informado, "rendimento": rend}


def calc_meta_ano(periodos, n_ativos: int, ano: int) -> float:
    """Meta esperada de um ano = nº de alunos ativos × soma do valor mensal no ano."""
    soma_ano = 0.0
    for m in range(1, 13):
        soma_ano += get_valor_mes(periodos, f"{ano}-{m:02d}")
    return round(soma_ano * n_ativos, 2)


def arrecadacao_por_ano(trans_rows) -> dict:
    """{ano: arrecadação LÍQUIDA} — mensalidades menos o que foi devolvido no ano."""
    out = defaultdict(float)
    for r in trans_rows:
        ano = str(r.get("data") or "")[:4]
        cat = r.get("categoria")
        v = float(r.get("valor", 0.0))
        if cat == "MENSALIDADE":
            out[ano] += v
        elif cat == "DEVOLUCAO":
            out[ano] -= abs(v)
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

    # despesas = saídas reais (despesas do evento) + débitos não identificados
    despesas = abs(sum(float(r["valor"]) for r in trans_rows
                       if r["categoria"] in ("SAIDA", "OUTRO") and r["valor"] < 0))

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
        "arrecadacao_liquida": round(mensal - abs(devol), 2),
        "inadimplencia": round(inadimplencia, 2),
        "rendimento": round(rendimento, 2),
        "saldo_conta": round(saldo_conta, 2),
        "aportes": round(aportes, 2),
        "resgates": round(resgates, 2),
        "saldo_invest": round(saldo_invest, 2),
        "despesas": round(despesas, 2),
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


# ─── CONCILIAÇÃO BANCÁRIA ──────────────────────────────────────────────────
def concatenar(saldo_calculado: float, saldo_informado: float) -> float:
    """Diferença (ajuste) entre o saldo calculado pelo app e o saldo real do banco.

    Positivo = o banco tem MAIS do que o app calculou (falta lançar entrada no extrato).
    Negativo = o banco tem MENOS (falta lançar saída/estorno no extrato).
    """
    return round(float(saldo_informado) - float(saldo_calculado), 2)


def calcular_saldo_conta(trans_rows) -> float:
    """Saldo da conta corrente = soma de TODAS as transações (o que o banco deveria mostrar)."""
    return round(sum(float(r.get("valor", 0.0)) for r in trans_rows), 2)


# ─── INVENTÁRIO DE DESPESAS ────────────────────────────────────────────────
def resumo_despesas(itens) -> dict:
    """Resumo do inventário: previstas x concretizadas (com nota)."""
    real = sum(float(i.get("valor", 0.0)) for i in itens
               if i.get("status") == "concretizada")
    prev = sum(float(i.get("valor", 0.0)) for i in itens
               if i.get("status") == "prevista")
    return {"concretizado": round(real, 2), "previsto": round(prev, 2),
            "total": round(real + prev, 2), "n": len(itens)}


# ─── MATCHING / IMPORTAÇÃO ─────────────────────────────────────────────────
def emails_lista(aluno) -> list:
    """Contas de acesso (emails) vinculadas a um aluno, limpas e minúsculas."""
    return [e.strip().lower() for e in (aluno.get("emails_acesso") or "").split(",")
            if e.strip()]


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


# ─── IMPORTAÇÃO DE EXTRATO (robusta) ────────────────────────────────────────
# "informativas" = linhas que o banco coloca no extrato mas não são lançamentos
# (ex.: SALDO, EXTRATO, LIMITE). São ignoradas na importação.
INFORMATIVAS = ("SALDO", "EXTRATO", "LIMITE", "ENC.EMP", "ANIVERSARIO")


def linha_informativa(descricao: str) -> bool:
    up = descricao.upper()
    return any(k in up for k in INFORMATIVAS)


def _parse_valor(s: str) -> float:
    """Converte valor do extrato aceitando pt-BR e padrão ponto:
    '1.234,56' -> 1234.56 | '1234.56' -> 1234.56 | '250,00' -> 250.0"""
    s = s.strip().replace(" ", "")
    if "," in s and "." in s:      # pt-BR: '.' milhar e ',' decimal
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:                 # só vírgula: decimal é vírgula
        s = s.replace(",", ".")
    return float(s)                # só ponto (ou nenhum): deixa o ponto como decimal


def parse_extrato(texto: str, alunos_ativos: list, ja_existem: set) -> tuple:
    """Parseia um extrato CSV e devolve (novas, duplicadas, ignoradas).

    - novas     : lançamentos novos, já classificados (data/valor/aluno/categoria)
    - duplicadas: já existem no banco (data+descricao+valor) ou se repetem no próprio arquivo
    - ignoradas : linhas informativas (SALDO etc.) ou sem valor numérico
    - "ja_existem": set de (data, descricao, valor) que já estão no banco
    """
    linhas, duplicadas, ignoradas = [], [], []
    sep = ";" if texto.count(";") > texto.count(",") else ","
    visto = set()
    for parts in csv.reader(io.StringIO(texto), delimiter=sep):
        parts = [p.strip().strip("\"'") for p in parts]
        if len(parts) < 3:
            continue
        dm = re.match(r"(\d{2})/(\d{2})/(\d{4})", parts[0])
        if not dm:
            continue
        data = f"{dm.group(3)}-{dm.group(2)}-{dm.group(1)}"
        desc = parts[1]
        try:
            valor = _parse_valor(parts[2])
        except Exception:
            continue  # sem valor numérico -> não é lançamento
        if linha_informativa(desc):
            ignoradas.append({"data": data, "descricao": desc, "valor": valor})
            continue
        chave = (data, desc, round(valor, 2))
        if chave in ja_existem or chave in visto:
            duplicadas.append({"data": data, "descricao": desc, "valor": valor})
            continue
        visto.add(chave)
        aluno_id, aluno_nome = match_aluno(desc, alunos_ativos)
        categoria = detecta_categoria(desc, valor, bool(aluno_id))
        linhas.append({"data": data, "descricao": desc, "valor": valor,
                       "aluno_id": aluno_id, "aluno_nome": aluno_nome,
                       "categoria": categoria})
    return linhas, duplicadas, ignoradas