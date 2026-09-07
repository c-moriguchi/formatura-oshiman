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