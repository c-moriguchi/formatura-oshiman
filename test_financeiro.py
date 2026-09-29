"""Testes da lógica financeira (sem Streamlit, sem banco)."""
import pytest
import financeiro as F

# Períodos espelhando a planilha: valor 200 a partir de 2025-04, 250 a partir de 2026-01
PERIODOS = [("2025-01", 0.0), ("2025-02", 0.0), ("2025-03", 0.0),
            ("2025-04", 200.0), ("2026-01", 250.0)]

ALUNOS = [
    {"id": "01A", "nome": "Aluno Um",       "status": "Ativo",   "data_desistencia": None},
    {"id": "02B", "nome": "Aluno Dois",     "status": "Ativo",   "data_desistencia": None},
    {"id": "03A", "nome": "Desistente",     "status": "Inativo", "data_desistencia": "2025-12-15"},
]


def aluno_a1_em_dia() -> list:
    """01A pagou tudo até 2026-01 (meta 2050): 9x200 (2025-04..12) + 250 (2026-01)."""
    rows = []
    for m in range(4, 13):
        rows.append({"data": f"2025-{m:02d}-10", "valor": 200.0,
                     "aluno_id": "01A", "categoria": "MENSALIDADE"})
    rows.append({"data": "2026-01-10", "valor": 250.0, "aluno_id": "01A",
                 "categoria": "MENSALIDADE"})
    return rows


def aluno_a2_devedor() -> list:
    """02B pagou só 2025-04 (200). Meta 2026-01 = 2050 -> deve 1850."""
    return [{"data": "2025-04-10", "valor": 200.0,
             "aluno_id": "02B", "categoria": "MENSALIDADE"}]


def desistente_com_dev() -> list:
    """03A pagou 3x200=600, devolvido 200 -> dev_pendente 400."""
    return [
        {"data": "2025-05-01", "valor": 200.0, "aluno_id": "03A", "categoria": "MENSALIDADE"},
        {"data": "2025-06-01", "valor": 200.0, "aluno_id": "03A", "categoria": "MENSALIDADE"},
        {"data": "2025-07-01", "valor": 200.0, "aluno_id": "03A", "categoria": "MENSALIDADE"},
        {"data": "2025-12-20", "valor": -200.0, "aluno_id": "03A", "categoria": "DEVOLUCAO"},
    ]


def invest_rows():
    return [
        {"data": "2025-05-01", "valor": -3000.0, "aluno_id": None, "categoria": "INVESTIMENTO"},
        {"data": "2025-06-01", "valor": -1000.0, "aluno_id": None, "categoria": "INVESTIMENTO"},
        {"data": "2025-11-01", "valor": 500.0,   "aluno_id": None, "categoria": "RESGATE"},
        {"data": "2025-11-01", "valor": 50.0,    "aluno_id": None, "categoria": "RENDIMENTO"},
    ]


ALL = (aluno_a1_em_dia() + aluno_a2_devedor() + desistente_com_dev() + invest_rows())


# ─── calcular_aluno ─────────────────────────────────────────────────────────
def test_ativo_em_dia():
    trans = F.carregar_transacoes_agrupadas(aluno_a1_em_dia())
    c = F.calcular_aluno(ALUNOS[0], PERIODOS, trans, "2026-01")
    assert c["total_pago"] == 2050.0
    assert c["meta"] == 2050.0
    assert c["saldo"] == 0.0
    assert c["dev_pendente"] == 0.0


def test_ativo_devedor():
    trans = F.carregar_transacoes_agrupadas(aluno_a2_devedor())
    c = F.calcular_aluno(ALUNOS[1], PERIODOS, trans, "2026-01")
    assert c["total_pago"] == 200.0
    assert c["saldo"] == -1850.0


def test_desistente_dev_pendente():
    trans = F.carregar_transacoes_agrupadas(desistente_com_dev())
    c = F.calcular_aluno(ALUNOS[2], PERIODOS, trans, "2026-01")
    # Devolução nunca reduz o total_pago; dev_pendente = pago - devolvido
    assert c["total_pago"] == 600.0
    assert c["devolucao"] == 200.0
    assert c["dev_pendente"] == 400.0
    assert c["saldo"] == 0.0  # inativo não entra no saldo geral


def test_devolucao_nao_diminui_mensalidade():
    trans = F.carregar_transacoes_agrupadas(
        desistente_com_dev() + [{"data": "2025-08-01", "valor": 200.0,
                                 "aluno_id": "01A", "categoria": "DEVOLUCAO"}])
    assert trans["01A"]["mensalidade"] == 0.0  # devolução não vira mensalidade
    assert trans["01A"]["devolucao"] == 200.0


# ─── meta por ano (balanceia contra planilha) ───────────────────────────────
def test_meta_ano_2025():
    # 2025: Jan/mar=0, abr-dez=200 => 9*200=1800 por aluno. 2 ativos => 3600.
    assert F.calc_meta_ano(PERIODOS, n_ativos=2, ano=2025) == 3600.0


def test_meta_ano_2026():
    # 2026: 12*250 = 3000 por aluno, 2 ativos => 6000.
    assert F.calc_meta_ano(PERIODOS, n_ativos=2, ano=2026) == 6000.0


def test_arrecadacao_por_ano():
    anos = F.arrecadacao_por_ano(ALL)
    # Mensalidades 2025: 9*200(01A) + 200(02B) + 600(03A desistente) = 2600
    assert anos["2025"] == 2600.0
    assert anos["2026"] == 250.0  # só a mensalidade de 01A em jan/26


# ─── painel / caixa ─────────────────────────────────────────────────────────
def test_painel_consistente():
    p = F.calcular_painel(ALL, PERIODOS, ALUNOS, "2026-01")
    # aportes = 3000+1000 = 4000 ; resgates = 500 ; saldo invest = 3500
    assert p["aportes"] == 4000.0
    assert p["resgates"] == 500.0
    assert p["saldo_invest"] == 3500.0
    assert p["rendimento"] == 50.0
    # saldo_conta = soma de todas as linhas
    mensal = 2050 + 200 + 600           # 2850
    saldo_conta = 2850 - 200 - 4000 + 500 + 50   # = -800
    assert p["saldo_conta"] == -800.0
    # patrimonio = saldo_conta + saldo_invest (sem contar rendimento 2x)
    assert p["patrimonio"] == -800 + 3500
    # total mensalidades inclui o que desistente pagou? Sim: é tudo o que entrou.
    assert p["total_mensalidades"] == 2850.0
    # inadimplência: só 02B deve (1850) até 2026-01
    assert p["inadimplencia"] == 1850.0
    assert p["n_ativos"] == 2


def test_painel_nao_conta_rendimento_2x():
    p = F.calcular_painel(ALL, PERIODOS, ALUNOS, "2026-01")
    # patrimônio deve ser == dinheiro real levantado (mensal - devol + rend)
    real = 2850 - 200 + 50
    assert p["patrimonio"] == real


# ─── matching / importação ─────────────────────────────────────────────────
def test_match_aluno_por_termo_pix():
    ativos = [{"id": "07A", "nome": "Giovana Oshiro", "termos_pix": "CRISTIN,CIHARA,CRIS"},
              {"id": "10B", "nome": "Kenji Yoshida", "termos_pix": "ERICA,WILSON"}]
    fid, fnome = F.match_aluno("PIX TRANSF CRISTIN14/04", ativos)
    assert (fid, fnome) == ("07A", "Giovana Oshiro")
    assert F.match_aluno("PIX LIGIA 20/04", ativos) == (None, None)


def test_detecta_categoria():
    assert F.detecta_categoria("INT APLICACAO PRIVILEGE", -3000.0, False) == "INVESTIMENTO"
    assert F.detecta_categoria("INT RESGATE PRIVILEGE", 2550.0, False) == "RESGATE"
    assert F.detecta_categoria("REND PAGO APLIC AUT", 0.18, False) == "RENDIMENTO"
    assert F.detecta_categoria("PIX TRANSF CRISTIN14/04", 200.0, True) == "MENSALIDADE"
    assert F.detecta_categoria("PIX DEVOL", -200.0, True) == "DEVOLUCAO"
    assert F.detecta_categoria("TED PADARIA", -50.0, False) == "SAIDA"


# ─── segurança: escape HTML (XSS armazenado) ───────────────────────────────
def test_esc_bloqueia_script():
    e = F.esc('<script>alert(1)</script>')
    assert "<script>" not in e.lower()
    assert "&lt;script&gt;" in e.lower()


def test_esc_escapa_tudo_quando_exige_aspas():
    e = F.esc('"><img src=x onerror=alert(1)>')
    assert "<img" not in e.lower()
    assert "&quot;" in e  # aspas escapadas p/ não furar atributo


def test_esc_trata_none_e_numeros():
    assert F.esc(None) == ""
    assert F.esc(250.0) == "250.0"


def test_html_marca_seguro_sem_escapar():
    h = F.Html('<span class="badge badge-green">ok</span>')
    assert isinstance(h, F.Html)
    assert str(h) == '<span class="badge badge-green">ok</span>'


# ─── regra de pagamento por mês (FIFO) — cenários reais da comissão ─────────
PERIODOS_2026 = [("2026-01", 100.0)]  # 100/mês durante todo 2026


def _aluno():
    return {"id": "X", "status": "Ativo", "data_desistencia": None}


def _calcular(total: float, ate: str):
    trans = {"X": {"mensalidade": total, "devolucao": 0.0}}
    return F.calcular_aluno(_aluno(), PERIODOS_2026, trans, ate)


def test_pagou_ano_inteiro_de_uma_vez():
    """1200 em janeiro = 100 em cada mês; ninguém fica devendo."""
    ana = F.analise_mensal(PERIODOS_2026, 1200.0, "2026-12")
    assert len(ana["calendario"]) == 12
    assert all(m["pago"] == m["devido"] == 100.0 for m in ana["calendario"])
    assert ana["mes_atual_pago"] is True
    assert ana["mes_inicial_debito"] is None
    c = _calcular(1200.0, "2026-12")
    assert c["mes_atual_pago"] is True and c["divida_mensal"] == 0.0


def test_devendo_2_meses_paga_300_fica_adimplente():
    """Devendo jan+fev, paga 300 no dia 03/03 -> 100 pra cada mês; adimplente até 31/03."""
    ana = F.analise_mensal(PERIODOS_2026, 300.0, "2026-03")
    assert [m["pago"] for m in ana["calendario"]] == [100.0, 100.0, 100.0]
    assert ana["mes_atual_pago"] is True and ana["mes_inicial_debito"] is None
    assert F.calcular_aluno(_aluno(), PERIODOS_2026, {"X": {"mensalidade": 300.0, "devolucao": 0}}, "2026-03")["saldo"] == 0.0


def test_paga_240_falta_60_para_marco():
    """240 -> 100 jan, 100 fev, 40 mar; falta 60 p/ março (devendo até 31/03)."""
    ana = F.analise_mensal(PERIODOS_2026, 240.0, "2026-03")
    assert [m["pago"] for m in ana["calendario"]] == [100.0, 100.0, 40.0]
    assert ana["mes_atual_pago"] is False
    assert ana["mes_inicial_debito"] == "2026-03"
    assert ana["divida"] == 60.0
    c = _calcular(240.0, "2026-03")
    assert c["divida_mensal"] == 60.0 and c["mes_inicial_debito"] == "2026-03"


# ─── importação de extrato (case 2) ─────────────────────────────────────────
def test_linha_informativa():
    assert F.linha_informativa("SALDO EM 30/04 DE 1234,56")
    assert F.linha_informativa("EXTRATO DE MAIO")
    assert F.linha_informativa("LIMITE DO CARTÃO")
    assert not F.linha_informativa("PIX TRANSF CRISTIN14/04")


def test_parse_extrato_duplicado_saldo_e_classificacao():
    alunos = [{"id": "07A", "nome": "Giovana Oshiro", "termos_pix": "CRISTIN"}]
    texto = (
        "14/04/2025,PIX TRANSF CRISTIN14/04,200.00\n"
        "14/04/2025,PIX TRANSF CRISTIN14/04,200.00\n"   # duplicado no arquivo
        "15/04/2025,SALDO,12345.67\n"                    # informativa
        "15/04/2025,INT APLICACAO PRIVILEGE,-3000.00\n"  # aplicação (investimento)
        "15/04/2025,REND PAGO APLIC AUT MAIS,0.05\n"     # rendimento
        "16/04/2025,TED LOCAL BUFFET,-500.00\n"          # despesa
    )
    novas, duplicadas, ignoradas = F.parse_extrato(texto, alunos, set())
    assert len(duplicadas) == 1          # a linha repetida foi apontada e não processada
    assert len(ignoradas) == 1 and "SALDO" in ignoradas[0]["descricao"].upper()
    assert len(novas) == 4
    cats = {n["categoria"] for n in novas}
    # o primeiro lançamento é mensalidade do aluno identificado
    assert novas[0]["categoria"] == "MENSALIDADE" and novas[0]["aluno_id"] == "07A"
    assert "INVESTIMENTO" in cats        # débito p/ aplicação
    assert "RENDIMENTO" in cats          # remuneração extra (centavos)
    assert "SAIDA" in cats               # débito p/ despesa (não localizada como aplicação)


def test_parse_extrato_dedup_com_banco_ja_existente():
    alunos = [{"id": "10B", "nome": "Kenji Yoshida", "termos_pix": "WILSON"}]
    texto = "14/04/2025,PIX TRANSF WILSON03/04,250.00\n"
    ja = {("2025-04-14", "PIX TRANSF WILSON03/04", 250.0)}
    novas, duplicadas, _ = F.parse_extrato(texto, alunos, ja)
    assert novas == [] and len(duplicadas) == 1


def test_parse_valor_formatos():
    assert F._parse_valor("250.00") == 250.0       # ponto decimal
    assert F._parse_valor("250,00") == 250.0       # vírgula decimal (pt-BR)
    assert F._parse_valor("1.234,56") == 1234.56   # milhar . e decimal ,
    assert F._parse_valor("-3.000,00") == -3000.0  # negativo pt-BR
    assert F._parse_valor("0.05") == 0.05


# ─── inventário de despesas ─────────────────────────────────────────────────
def test_resumo_despesas_prev_vs_concretizado():
    itens = [
        {"descricao": "a", "valor": 3200.0, "status": "concretizada"},
        {"descricao": "b", "valor": 2500.0, "status": "prevista"},
        {"descricao": "c", "valor": 980.0,  "status": "prevista"},
    ]
    r = F.resumo_despesas(itens)
    assert r["concretizado"] == 3200.0
    assert r["previsto"] == 3480.0
    assert r["total"] == 6680.0 and r["n"] == 3


def test_resumo_despesas_vazio():
    r = F.resumo_despesas([])
    assert r == {"concretizado": 0.0, "previsto": 0.0, "total": 0.0, "n": 0}


# ─── monitor de investimento (case 3) ───────────────────────────────────────
def test_investimento_sem_saldo_nada_de_rendimento():
    trans = [
        {"categoria": "INVESTIMENTO", "valor": -3000.0},
        {"categoria": "INVESTIMENTO", "valor": -1000.0},
        {"categoria": "RESGATE", "valor": 500.0},
    ]
    iv = F.investimento_resumo(trans)
    assert iv["aportes"] == 4000.0 and iv["resgates"] == 500.0 and iv["rendimento"] is None


def test_investimento_rendimento_saldo_menos_aportes():
    trans = [
        {"categoria": "INVESTIMENTO", "valor": -3000.0},
        {"categoria": "INVESTIMENTO", "valor": -1000.0},
        {"categoria": "RESGATE", "valor": 500.0},
    ]
    # saldo 3500 = aportes 4000 - resgates 500 + rendimento 0
    iv = F.investimento_resumo(trans, saldo_informado=3500.0)
    assert iv["rendimento"] == 0.0
    # saldo 3555 -> rendimento 55
    assert F.investimento_resumo(trans, saldo_informado=3555.0)["rendimento"] == 55.0