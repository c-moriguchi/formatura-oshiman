# 🎓 Formatura Oshiman — Gestão Financeira da Comissão

App (Streamlit + Supabase) para controle de **mensalidades**, **fechamento
mensal consolidado**, **importação de extrato** com matching por PIX,
**avisos/cobrança por WhatsApp** e **geração de PDF**. Foi originado de uma
planilha manual do Google Sheets e evoluiu para um app com banco de dados.

## Stack
- **Streamlit** (UI) — um `app.py` + módulo de lógica `financeiro.py`
- **Supabase** (PostgreSQL) — tabelas: `alunos`, `periodos`, `transacoes`,
  `fechamentos`, `orcamento`
- **reportlab** — emissão do PDF de fechamento
- **Meta Cloud API** (opcional) — notificações de WhatsApp

## Funcionalidades
| Área | O que faz |
|---|---|
| 📊 **Visão geral** | Painel de caixa: saldo (conta + investimento), arrecadação por ano × meta (%), monitor de investimento, inadimplência, previsão de orçamento |
| 📋 **Mês corrente** | Prévia de quem já pagou no mês + lembrete WhatsApp individual |
| 📊 **Situação fechada** | Por aluno: em dia / devedor / desistente, com link de cobrança |
| 📥 **Extrato** | Cola CSV do banco → matching automático por termo PIX → revisão → importação. **Correção de lançamento** (editar/excluir transação) |
| 📄 **Fechamento** | Draft mensal → confirmação → PDF + aviso WhatsApp às tesoureiras |
| ⚙️ **Cadastros** | Alunos ativos/desistentes, valores de mensalidade por período, **orçamento** |

## Como rodar

### 1. Banco (Supabase)
1. Crie um projeto gratuito em [supabase.com](https://supabase.com).
2. Abra **SQL Editor** e rode o conteúdo de [`schema.sql`](./schema.sql) (cria as tabelas).
3. Página **Project Settings → API** — copie o **URL** e a **service_role key**.

### 2. Segredos (`.streamlit/secrets.toml`)
Copie `.streamlit/secrets.toml.example` para `.streamlit/secrets.toml` e preencha:

```toml
SUPABASE_URL = "https://xxx.supabase.co"
SUPABASE_SERVICE_KEY = "sb_secret_asdf..."     # service_role — nunca no navegador

NOME_COMISSAO = "Formatura Oshiman 2028"       # usado em título/PDF
NOME_CURTO = "Oshiman"                          # usado no header

SENHA_TESOURARIA = "..."                        # perfil Tesouraria
SENHA_CONSULTA = "..."                          # perfil Consulta (só leitura)

# WhatsApp (opcional — sem isso os avisos são ignorados)
WA_TOKEN = ""
WA_PHONE_ID = ""
TESOUREIRAS_WA = "+5511...,+5511..."            # vírgula separa os números
```

### 3. Rodar local
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```
- Com `SUPABASE_*` nos secrets → usa o banco real.
- **Sem** Supabase configurado (ou com `DEMO=1`) → entra em **modo demonstração**
  com dados fictícios, pra você navegar sem risco.

### 4. Publicar (Streamlit Community Cloud)
1. Suba o repo no GitHub.
2. Em [share.streamlit.io](https://share.streamlit.io) → New app → escolha o repo/branch.
3. **Advanced settings → Secrets**: cole o mesmo conteúdo do `secrets.toml`.

## Testes
```bash
pip install pytest
python -m pytest test_financeiro.py -q
```
A lógica financeira está isolada em `financeiro.py` (sem Streamlit), então dá
pra testar e ajustar as fórmulas do painel sem abrir o app.

⚠️ O app em produção usa `service_role`. Para uso interno da comissão é
aceitável, mas nunca incorpore essa chave em frontend/HTML.

## Melhorias futuras (roadmap)
- Armazenar valores como **centavos (inteiro)** em vez de float.
- Migração para app mobile-first dedicado (Streamlit é limitado em celular);
  hoje a UI já é responsiva com CSS + tabelas HTML.
- Autenticação por conta (email/senha) no lugar da senha única por perfil.