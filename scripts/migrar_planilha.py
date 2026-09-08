"""
Gera o script data.sql (INSERTs) a partir da planilha exportada em xlsx,
no formato esperado pelas tabelas do app (ver schema.sql).

Uso:
    python scripts/migrar_planilha.py CAMINHO_DO_XLSX [--out data.sql]

Abas usadas:
  - Cadastros            -> alunos        (id, nome, conta1, conta2 -> termos_pix, celular, status, desistencia)
  - Config_Mensalidades  -> periodos      (de=AAAA-MM, valor)
  - Transacoes           -> transacoes    (já classificadas na planilha)
  - Previsao_Orcamento   -> orcamento

O SQL gerado NÃO apaga dados. Veja o aviso no topo do arquivo se for um banco
que já tem dados de teste (use TRUNCATE antes de rodar).
"""
import sys
import datetime
import openpyxl

CAT_PARA_APP = {
    "Mensalidade": "MENSALIDADE",
    "Devolução": "DEVOLUCAO",
    "Devolucao": "DEVOLUCAO",
    "Investimento": "INVESTIMENTO",
    "Resgate": "RESGATE",
    "Rendimento CC": "RENDIMENTO",
    "Rendimento": "RENDIMENTO",
    "Outro": "OUTRO",
    "Saída": "SAIDA",
}
ESPECIAIS = {"", "INVESTIMENTOS/BANCO", "BANCO"}


def norm(s): return " ".join(str(s).split()).upper()


def fmt_date(v):
    if isinstance(v, (datetime.datetime, datetime.date)):
        return v.strftime("%Y-%m-%d")
    return str(v)[:10]


def ler_alunos(ws):
    alunos = []
    seen = set()
    for row in ws.iter_rows(values_only=True):
        if not row or row[0] is None:
            continue
        aid = str(row[0]).strip()
        nome = (row[1] or "").strip()
        if not aid or not nome or aid in seen:
            continue
        if aid.lower() == "id" or nome.lower() in ("nome do aluno", "nome"):
            continue  # linha de cabeçalho
        seen.add(aid)
        conta1 = (row[4] or "").strip()
        conta2 = (row[5] or "").strip()
        # termos_pix = nomes que aparecem no extrato (contas/responsáveis)
        termos = [t for t in (conta1, conta2) if t]
        if not termos and row[2]:
            termos = [(row[2] or "").strip()]
        status = "Inativo" if str(row[7] or "").strip().lower().startswith("inativo") else "Ativo"
        des = ""
        if status == "Inativo" and len(row) > 8 and row[8]:
            des = fmt_date(row[8])
        alunos.append({
            "id": aid, "nome": nome,
            "termos_pix": ",".join(t.upper() for t in termos),
            "celular": (row[6] or "").strip(),
            "turma": aid[-1] if aid else "",
            "status": status, "data_desistencia": des or None,
        })
    return alunos


def ler_periodos(ws):
    periodos = []
    for row in ws.iter_rows(values_only=True):
        if not row or row[0] is None:
            continue
        de = str(row[0])[:7]  # 'AAAA-MM' (ou 'AAAA-MM-01' -> 'AAAA-MM')
        try:
            valor = float(row[1])
        except Exception:
            continue
        periodos.append((de, valor))
    # mantém contíguo e sem duplicatas
    out = []
    for de, v in periodos:
        if out and out[-1][0] == de:
            out[-1] = (de, v)
        else:
            out.append((de, v))
    return out


def ler_transacoes(ws, nome_para_id):
    rows = []
    for i, row in enumerate(ws.iter_rows(values_only=True), start=1):
        if i == 1 or not row or row[0] is None:
            continue
        data = fmt_date(row[0])
        desc = (row[1] or "").strip()
        if not desc:
            continue
        try:
            valor = float(row[2])
        except Exception:
            continue
        aluno = norm(row[3]) if len(row) > 3 and row[3] else ""
        cat_pt = str(row[4]).strip() if len(row) > 4 and row[4] else "Outro"
        cat = CAT_PARA_APP.get(cat_pt, "OUTRO")
        aluno_id = None
        if aluno and aluno not in ESPECIAIS:
            for n_upper, aid in nome_para_id.items():
                if aluno == n_upper or aluno.endswith("(DESISTÊNCIA)") and aluno.startswith(n_upper):
                    aluno_id = aid
                    break
        rows.append({"data": data, "descricao": desc, "valor": valor,
                     "categoria": cat, "aluno_id": aluno_id})
    return rows


def q(v):
    return "'" + str(v).replace("'", "''") + "'"


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    path = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 and sys.argv[2] != "--out" else "data.sql"
    if "--out" in sys.argv:
        out = sys.argv[sys.argv.index("--out") + 1]

    wb = openpyxl.load_workbook(path, data_only=True)
    alunos = ler_alunos(wb["Cadastros"])
    periodos = ler_periodos(wb["Config_Mensalidades"])
    nome_para_id = {norm(a["nome"]): a["id"] for a in alunos}
    trans = ler_transacoes(wb["Transacoes"], nome_para_id)
    orca = wb["Previsao_Orcamento"]

    # periodos: só até o mês em que o valor muda (200/250); manter consistente
    L = []
    L.append("-- =====================================================")
    L.append("-- data.sql gerado por scripts/migrar_planilha.py")
    L.append("-- Rode DEPOIS do schema.sql. NÃO apaga dados existentes.")
    L.append("-- SE o banco já tem dados de teste/relançados, rode ANTES:")
    L.append("--   DELETE FROM transacoes; DELETE FROM orcamento;")
    L.append("-- (alunos/periodos usam ON CONFLICT e podem rodar de novo.)")
    L.append("-- =====================================================\n")

    if not alunos:
        raise SystemExit("Nenhum aluno encontrado em Cadastros.")
    L.append("-- ALUNOS")
    for a in alunos:
        vals = [q(a["id"]), q(a["nome"]), q(a["celular"]), q(a["termos_pix"]),
                q(a["turma"]), q(a["status"])]
        if a["data_desistencia"]:
            vals.append(q(a["data_desistencia"]))
            L.append("insert into public.alunos (id,nome,celular,termos_pix,turma,status,data_desistencia) "
                     f"values ({','.join(vals)}) on conflict (id) do nothing;")
        else:
            L.append("insert into public.alunos (id,nome,celular,termos_pix,turma,status) "
                     f"values ({','.join(vals)}) on conflict (id) do nothing;")

    L.append("\n-- PERIODOS (mensalidades: de=AAAA-MM, valor)")
    for de, v in periodos:
        L.append(f"insert into public.periodos (de,valor) values ({q(de)},{v}) "
                 f"on conflict (de) do update set valor=excluded.valor;")

    L.append("\n-- TRANSACOES")
    nao_aluno = set()
    for t in trans:
        aid = q(t["aluno_id"]) if t["aluno_id"] else "NULL"
        L.append(f"insert into public.transacoes (data,descricao,valor,categoria,aluno_id) "
                 f"values ({q(t['data'])},{q(t['descricao'])},{t['valor']},{q(t['categoria'])},{aid});")
    if nao_aluno:
        print("aviso: alunos não achados:", nao_aluno)

    L.append("\n-- ORCAMENTO (previsão)")
    for row in orca.iter_rows(values_only=True):
        if not row or row[0] is None:
            continue
        desc = str(row[0]).strip()
        if desc.upper() in ("DESCRIÇÃO",): continue
        try:
            valor = float(row[2])
        except Exception:
            continue
        L.append(f"insert into public.orcamento (descricao,data,valor) "
                 f"values ({q(desc)},{q((row[1] or '').strip())},{valor});")

    with open(out, "w") as f:
        f.write("\n".join(L) + "\n")
    print(f"OK: {out} gerado")
    print(f"  alunos: {len(alunos)} | periodos: {len(periodos)} | "
          f"transacoes: {len(trans)} | orcamento: {orca.max_row-1} (com header)")
    # sem aluno_id
    sem = sum(1 for t in trans if not t["aluno_id"])
    print(f"  transacoes sem aluno (bancarias): {sem}")


if __name__ == "__main__":
    main()