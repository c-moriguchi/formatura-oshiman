-- ============================================================================
-- Formatura Oshiman — Schema do Supabase (PostgreSQL)
-- Rode este arquivo no editor SQL do seu projeto Supabase.
-- ATENÇÃO: este arquivo cria as tabelas de UM projeto NOVO. Se você já tem as
-- tabelas criadas à mão, compare as colunas antes de rodar (use CREATE IF NOT EXISTS;)
-- ============================================================================

-- ---------- alunos ----------
-- id = código do aluno (ex: 11A); termos_pix = apelidos/contas PIX p/ matching
create table if not exists public.alunos (
  id text primary key,
  nome text not null,
  celular text,
  termos_pix text,                  -- separados por vírgula (ex: "CRISTIN,CRIS")
  turma text,
  status text not null default 'Ativo',      -- 'Ativo' | 'Inativo'
  data_desistencia text,            -- texto por compatibilidade com o app
  criado_em timestamptz not null default now()
);

-- ---------- periodos (valor da mensalidade por mês) ----------
-- de = 'AAAA-MM' (a partir de quando vale). valor = valor mensal.
create table if not exists public.periodos (
  de text primary key,
  valor numeric not null
);

-- ---------- transacoes ----------
-- data/descricao como texto: o app faz busca por prefixo (like 'AAAA-MM%').
-- valor numeric (inteiro em centavos? use numeric mesmo — evita erros de float)
create table if not exists public.transacoes (
  id uuid primary key default gen_random_uuid(),
  data text not null,               -- 'AAAA-MM-DD' (texto, usado com like)
  descricao text,
  valor numeric not null,
  categoria text not null,          -- MENSALIDADE|DEVOLUCAO|INVESTIMENTO|RESGATE|RENDIMENTO|OUTRO|SAIDA
  aluno_id text references public.alunos(id) on delete set null,
  observacao text,
  criado_em timestamptz not null default now()
);
create index if not exists idx_transacoes_aluno on public.transacoes (aluno_id);
create index if not exists idx_transacoes_cat on public.transacoes (categoria);

-- ---------- fechamentos ----------
-- status: 'draft' | 'confirmado'  (consolidação mensal)
create table if not exists public.fechamentos (
  ano_mes text primary key,         -- 'AAAA-MM'
  status text not null default 'draft',
  criado_em timestamptz not null default now(),
  confirmado_em timestamptz,
  confirmado_por text
);

-- ---------- orcamento (NOVO — previsão de caixa/despesas do evento) ----------
create table if not exists public.orcamento (
  id bigserial primary key,
  descricao text not null,
  data text,                        -- texto livre (ex: "Set/Out", "2027")
  valor numeric not null default 0
);

-- (Opcional) Habilite Row Level Security e políticas se quiser usar anon key
-- em vez de service_role. Para um app interno de comissão, service_role nos
-- secrets do Streamlit é aceitável — mas nunca exponha a service key no navegador.