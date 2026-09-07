"""
Modo demonstração / desenvolvimento: um mini-cliente Supabase em memória que
replica só as operações que o app usa (select/eq/in_/like/order/limit,
insert/update/upsert/delete), alimentado com dados sintéticos inspirados na
planilha. Ativa com `DEMO=1` quando não houver secrets do Supabase.
"""
import datetime
import random
import re

MESES = ["Jan","Fev","Mar","Abr","Mai","Jun","Jul","Ago","Set","Out","Nov","Dez"]

# Nomes reais (amostra da planilha) + termos PIX correspondentes
_ALUNOS_ATIVOS = [
    ("01A", "Ana Rafaela Watanabe Endo",     "REGINA",   "A"),
    ("02A", "Bárbara Okada",                 "SHEIMI,WAGNER", "A"),
    ("04A", "Clara Otsuru Teixeira",         "CARLOS",   "A"),
    ("05A", "Davi Souza Teixeira Lopes",     "JANETE,PETRONI", "A"),
    ("06A", "Dylan Shin Hattori",            "LEANDRO,CHEN WE", "A"),
    ("07A", "Giovana Yumi Moriguchi Oshiro", "CRISTIN",  "A"),
    ("08A", "Henry H S Hoshika",             "VIVIAN",   "A"),
    ("09A", "Gustavo Nishio Yoshizako",      "SANDRA",   "A"),
    ("10A", "Isabela Kimi O. Oda",           "ANDRE O",  "A"),
    ("11A", "Joaquim P Carvalho da Silveira","LIVIA P",  "A"),
    ("12A", "Lívia Aya Nagata",              "GIBSON",   "A"),
    ("13A", "Lucas Sakai Cassol",            "NATACHA",  "A"),
    ("14A", "Luiza Akemi Azuma",             "LIANE,RODRIGO", "A"),
    ("15A", "Yuto Watanabe",                 "LAURA M",  "A"),
    ("01B", "Anny Leonardo de Castro",       "DAYANA,D F SPA", "B"),
    ("02B", "Camila Barros Murakami",        "MARINA",   "B"),
    ("03B", "Cesar Seiki Imoto",             "JACQUEL",  "B"),
    ("05B", "George Zhicheng Sun",           "GU ZIYU",  "B"),
    ("06B", "Giovanna Seike Tokita",         "GABRIEL",  "B"),
    ("08B", "Henry Tsuyoshi Muramatsu Oya",  "DENISE",   "B"),
    ("09B", "Julia Aya Higaki",              "KAREN M",  "B"),
    ("10B", "Kenji Yoshida",                 "ERICA,WILSON", "B"),
    ("11B", "Lara Tamashiro Webber",         "ANDRE L",  "B"),
    ("12B", "Lia Akemi Minamioka",           "MARGARE",  "B"),
    ("13B", "Marc Naoki Akamine Teruya",     "KATIA M,CLAUDIO", "B"),
    ("14B", "Pedro Henrique Hara Iwata",     "DANIEL,KARINA", "B"),
    ("15B", "Vitor Freitas Bastos",          "ANSELMO",  "B"),
]
_INATIVOS = [
    ("03A", "Breno Zonzini",     "PAULA M,PAULA MADUENO ZON", "2026-04-01", 600.0, 200.0),
    ("07B", "Helena Luli Araujo Moriya", "HENRIQU", "2025-10-08", 1200.0, 0.0),
]


def _gera_dados():
    data = {}
    # periodos
    periodos = []
    valor = 0.0
    for ano in (2025, 2026):
        for mes in range(1, 13):
            de = f"{ano}-{mes:02d}"
            if (ano, mes) >= (2025, 4):
                valor = 200.0 if ano == 2025 else 250.0
            periodos.append({"de": de, "valor": valor})
    data["periodos"] = periodos

    # alunos
    alunos = [{"id": i, "nome": n, "celular": f"11 9{id_.zfill(2)}000{i:02d}00",
               "termos_pix": t, "turma": tm, "status": "Ativo",
               "data_desistencia": None} for i, (id_, n, t, tm) in enumerate(_ALUNOS_ATIVOS)]
    for id_, n, t, data_des, pago, dev in _INATIVOS:
        alunos.append({"id": id_, "nome": n, "celular": "11 900000000",
                       "termos_pix": t, "turma": "A", "status": "Inativo",
                       "data_desistencia": data_des})
    data["alunos"] = alunos

    # transacoes sintéticas
    trans = []
    today = datetime.date.today()
    ano_hj, mes_hj = today.year, today.month
    rng = random.Random(2026)

    for a in _ALUNOS_ATIVOS:
        id_, nome, termos, turma = a
        for ano in (2025, 2026):
            for mes in range(1, 13):
                if (ano, mes) > (ano_hj, mes_hj):
                    continue
                if ano == 2025 and mes < 4:
                    continue
                # ~90% pagam no mês
                if rng.random() > 0.90:
                    continue
                v = 200.0 if ano == 2025 else 250.0
                dia = rng.randint(3, 28)
                termo = termos.split(",")[0].strip()
                trans.append({
                    "id": f"t_{len(trans)+1:04d}",
                    "data": f"{ano}-{mes:02d}-{dia:02d}",
                    "descricao": f"PIX TRANSF {termo}{dia:02d}/{mes:02d}",
                    "valor": v, "categoria": "MENSALIDADE",
                    "aluno_id": id_, "observacao": "",
                })
    # desistente Breno: pagou e devolvido parcial
    for mes in (4, 5, 6):
        trans.append({"id": f"t_{len(trans)+1:04d}", "data": f"2025-{mes:02d}-10",
                      "descricao": f"PIX TRANSF PAULA M{mes:02d}", "valor": 200.0,
                      "categoria": "MENSALIDADE", "aluno_id": "03A", "observacao": ""})
    trans.append({"id": f"t_{len(trans)+1:04d}", "data": "2026-04-06",
                  "descricao": "PIX TRANSF PAULA M03/04", "valor": -200.0,
                  "categoria": "DEVOLUCAO", "aluno_id": "03A", "observacao": ""})
    # aplicações / resgate / rendimento
    invest_seq = [
        ("2025-04-15", -3000.0), ("2025-05-10", -2000.0), ("2025-06-12", -1800.0),
        ("2025-07-20", -500.0), ("2025-08-05", -2500.0), ("2025-10-01", -1200.0),
        ("2025-12-02", -600.0), ("2026-02-14", -4000.0), ("2026-04-06", -3950.0),
        ("2026-04-06", -500.0),
    ]
    acc = 0.0
    for dia, v in invest_seq:
        trans.append({"id": f"t_{len(trans)+1:04d}", "data": dia,
                      "descricao": "APLICACAO PRIVILEGE INT", "valor": v,
                      "categoria": "INVESTIMENTO", "aluno_id": None, "observacao": ""})
        acc -= v
    rend_acum = 0.0
    for mes in range(5, 8):
        r = round(rng.uniform(0.5, 3.0), 2)
        rend_acum += r
        trans.append({"id": f"t_{len(trans)+1:04d}", "data": f"2025-{mes:02d}-15",
                      "descricao": "REND PAGO APLIC AUT MAIS", "valor": r,
                      "categoria": "RENDIMENTO", "aluno_id": None, "observacao": ""})
    trans.append({"id": f"t_{len(trans)+1:04d}", "data": "2026-06-15",
                  "descricao": "INT RESGATE PRIVILEGE", "valor": 1000.0,
                  "categoria": "RESGATE", "aluno_id": None, "observacao": ""})
    data["transacoes"] = trans

    # fechamentos: meses passados confirmados (o draft do mês anterior é criado
    # automaticamente pelo app na primeira execução)
    data["fechamentos"] = [
        {"ano_mes": "2026-05", "status": "confirmado",
         "criado_em": "2026-06-01T10:00:00", "confirmado_em": "2026-06-05T10:00:00",
         "confirmado_por": "Tesouraria"},
        {"ano_mes": "2026-06", "status": "confirmado",
         "criado_em": "2026-07-01T10:00:00", "confirmado_em": "2026-07-05T10:00:00",
         "confirmado_por": "Tesouraria"},
        {"ano_mes": "2026-07", "status": "confirmado",
         "criado_em": "2026-08-01T10:00:00", "confirmado_em": "2026-08-05T10:00:00",
         "confirmado_por": "Tesouraria"},
    ]
    # orcamento
    data["orcamento"] = [
        {"id": 1, "descricao": "Abertura de Associação", "data": "Set/Out", "valor": 1500.0},
        {"id": 2, "descricao": "Mensalidade 2026", "data": "Nov a Dez", "valor": 600.0},
        {"id": 3, "descricao": "Mensalidade 2027", "data": "Jan a Dez", "valor": 3900.0},
        {"id": 4, "descricao": "Mensalidade 2028", "data": "Jan a Dez", "valor": 3900.0},
        {"id": 5, "descricao": "Encerramento", "data": "Dezembro/28", "valor": 600.0},
    ]
    return data


class _Exec:
    def __init__(self, data): self._data = data
    @property
    def data(self): return self._data
    def execute(self): return self  # permite .insert(...).execute().data


class _QB:
    """Mini query-builder para uma tabela."""
    def __init__(self, table, records):
        self._records = list(records)
        self._cols = None

    def select(self, *cols):
        flat = []
        for c in cols:
            if isinstance(c, str) and "," in c:
                flat += [x.strip() for x in c.split(",") if x.strip()]
            else:
                flat.append(c)
        self._cols = tuple(flat) if flat else None
        return self

    def eq(self, k, v):
        self._records = [r for r in self._records if r.get(k) == v]
        return self

    def in_(self, k, vals):
        self._records = [r for r in self._records if r.get(k) in set(vals)]
        return self

    def like(self, k, pat):
        pat = pat.replace("%", ".*")
        rx = re.compile(pat)
        self._records = [r for r in self._records if rx.fullmatch(str(r.get(k, "")))]
        return self

    def order(self, k, desc=False):
        self._records.sort(key=lambda r: str(r.get(k, "")), reverse=desc)
        return self

    def limit(self, n):
        self._records = self._records[:n]
        return self

    def execute(self):
        recs = self._records
        if self._cols is not None and self._cols != ("*",):
            recs = [{c: r.get(c) for c in self._cols} for r in recs]
        return _Exec(recs)


class _Table:
    def __init__(self, name, records):
        self._name, self._records = name, records
        self._pending = None  # ("update", values, cond) | ("delete", None, cond)

    def select(self, *cols):
        return _QB(self._name, self._records).select(*cols)

    def insert(self, rows):
        if not isinstance(rows, list):
            rows = [rows]
        add = []
        for r in rows:
            nr = dict(r)
            if "id" not in nr:
                nr["id"] = f"auto_{len(self._records)+1:04d}"
            add.append(nr)
        self._records.extend(add)
        return _Exec(add)

    def update(self, values):
        self._pending = ("update", dict(values), None)
        return self

    def delete(self):
        self._pending = ("delete", None, None)
        return self

    def eq(self, k, v):
        if self._pending:
            self._pending = (self._pending[0], self._pending[1], (k, v))
        return self

    def execute(self):
        op, values, cond = self._pending
        self._pending = None
        if op == "update":
            k, v = cond
            done = [r for r in self._records if r.get(k) == v]
            for r in done:
                r.update(values)
            return _Exec(done)
        if op == "delete":
            k, v = cond
            self._records[:] = [r for r in self._records if r.get(k) != v]
            return _Exec([])
        return _Exec([])

    def upsert(self, rows):
        if not isinstance(rows, list):
            rows = [rows]
        for r in rows:
            key = "id" if "id" in r else ("de" if "de" in r else None)
            replaced = False
            if key:
                for i, ex in enumerate(self._records):
                    if ex.get(key) == r.get(key):
                        self._records[i] = {**ex, **r}
                        replaced = True
                        break
            if not replaced:
                self._records.append(dict(r))
        return _Exec(rows)


class _Client:
    def __init__(self, url, key, data): self._url, self._key, self._d = url, key, data
    def table(self, name):
        if name == "fechamentos":  # semantica: ultimo confirmado
            return _Table(name, self._d["fechamentos"])
        return _Table(name, self._d.get(name, []))


def create_mock_client(url: str = "http://demo", key: str = "demo"):
    return _Client(url, key, _gera_dados())