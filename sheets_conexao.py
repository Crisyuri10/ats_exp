import os
import json
from datetime import datetime, timedelta, timezone
import gspread
import pandas as pd

# ===== 1. Conexao com o Google Sheets =====
SHEET_ID = "1pvor4LGYpxE_7RJgJKCxMME2Yb47gNbByG4ZwZSctcE"
ABA = "Sheet1"

# no GitHub Actions a credencial vem da secret GCP_SERVICE_ACCOUNT (json em texto);
# localmente cai no arquivo credenciais.json
creds_env = os.environ.get("GCP_SERVICE_ACCOUNT")
if creds_env:
    gc = gspread.service_account_from_dict(json.loads(creds_env))
else:
    gc = gspread.service_account(filename="credenciais.json")
sh = gc.open_by_key(SHEET_ID)
ws = sh.worksheet(ABA)

# UNFORMATTED_VALUE traz o valor real da celula (serial de data, numero, etc),
# evitando que a formatacao de exibicao do Sheets esconda informacao (ex: ano)
bruto = ws.get_all_values(value_render_option="UNFORMATTED_VALUE")
# remove espacos nas pontas dos nomes das colunas (ex: " FIM DE CONF." -> "FIM DE CONF.")
header = [str(h).strip() for h in bruto[0]]
df = pd.DataFrame(bruto[1:], columns=header)

# ===== 2. Remocao de linhas vazias =====
# a aba usa formulas que deixam linhas vazias entre os blocos de dados.
# data_exp serve de referencia: se estiver vazio, a linha inteira esta vazia
df = df.rename(columns={"JANELA DE EXPEDIÇÃO": "data_exp", "STATUS TU": "status_tu", "CONF. PUXADA": "data_ats", "QTDE DE PEDIDOS": "qtde_pedidos", "TRANSP. + TP": "transportador", "TU(s)": "TU", "HORÁRIO": "horario", "CHECKOUT": "data_checkout", "FIM DE CARREGAM.": "data_carregamento", "FIM. FATURAMENTO": "data_fim_faturamento", "FIM DE CONSOLIDAÇÃO": "data_consolidacao", "CRIAÇÃO PAC.": "data_criacao_pacote", "DATA E HORA DE CRIAÇÃO": "data_criacao_tu", "INICIO COLET.": "data_inicio_coleta", "FIM COLET.": "data_fim_coleta", "FIM DE CONF.": "data_fim_conferencia", "ENT. PROT. NF": "data_espera_consolidacao", "CHEGADA DOCA": "data_chegada_doca", "CHECK-IN": "data_checkin", "INICIO DE CARREG.": "data_inicio_carregamento"})
df = df[df["data_exp"] != ""].reset_index(drop=True)
print(f"Linhas apos remover vazias: {len(df)}")

# ===== 3. Conversao de data_exp, data_limite_ats e data_ats =====
# data_exp e data_ats vem como serial de data/hora do Sheets (epoch 1899-12-30)
df["data_exp"] = pd.to_datetime(df["data_exp"].astype(float), unit="D", origin="1899-12-30")
df["data_limite_ats"] = df["data_exp"] - pd.Timedelta(hours=3)


def converter_data(coluna):
    # datas antes de 2000 sao erro de digitacao (ex: so hora "05:00" vira 30/12/1899 05:00,
    # ou so um numero "3" vira 02/01/1900) e ficam vazias. 36526 = serial de 01/01/2000
    serial = pd.to_numeric(coluna, errors="coerce")
    serial = serial.where(serial >= 36526)
    return pd.to_datetime(serial, unit="D", origin="1899-12-30")


df["data_ats"] = converter_data(df["data_ats"])
df["data_checkout"] = converter_data(df["data_checkout"])
df["data_carregamento"] = converter_data(df["data_carregamento"])
df["data_fim_faturamento"] = converter_data(df["data_fim_faturamento"])
df["data_consolidacao"] = converter_data(df["data_consolidacao"])
df["data_criacao_pacote"] = converter_data(df["data_criacao_pacote"])
df["data_criacao_tu"] = converter_data(df["data_criacao_tu"])
df["data_inicio_coleta"] = converter_data(df["data_inicio_coleta"])
df["data_fim_coleta"] = converter_data(df["data_fim_coleta"])
df["data_fim_conferencia"] = converter_data(df["data_fim_conferencia"])
df["data_espera_consolidacao"] = converter_data(df["data_espera_consolidacao"])
df["data_chegada_doca"] = converter_data(df["data_chegada_doca"])
df["data_checkin"] = converter_data(df["data_checkin"])
df["data_inicio_carregamento"] = converter_data(df["data_inicio_carregamento"])
# o serial do Sheets e um float e perde precisao (ex: 05:25:00 vira 05:24:59.999), entao arredonda para o segundo
for col in ["data_exp", "data_limite_ats", "data_ats", "data_checkout", "data_carregamento", "data_fim_faturamento", "data_consolidacao", "data_criacao_pacote", "data_criacao_tu", "data_inicio_coleta", "data_fim_coleta", "data_fim_conferencia", "data_espera_consolidacao", "data_chegada_doca", "data_checkin", "data_inicio_carregamento"]:
    df[col] = df[col].dt.round("s")

# ===== 3b. Criacao da coluna chave (transportador + horario + data_exp) =====
df["chave"] = df["transportador"] + "_" + df["horario"] + "_" + df["data_exp"].dt.strftime("%d/%m/%Y %H:%M:%S")

# ===== 3c. Criacao da coluna sla_ats =====
df["sla_ats"] = "fora_do_prazo"
df.loc[df["data_ats"] <= df["data_limite_ats"], "sla_ats"] = "dentro_do_prazo"
df.loc[df["data_ats"].isna(), "sla_ats"] = "em_aberto"

# ===== 3d. Criacao da coluna sla_expedicao =====
df["sla_expedicao"] = "fora_do_prazo"
df.loc[df["data_checkout"] <= df["data_exp"], "sla_expedicao"] = "dentro_do_prazo"
df.loc[df["data_checkout"].isna(), "sla_expedicao"] = "em_aberto"

# ===== 3d2. Criacao da coluna sla_veiculos (chegada na doca ate a janela de expedicao) =====
df["sla_veiculos"] = "fora_do_prazo"
df.loc[df["data_chegada_doca"] <= df["data_exp"], "sla_veiculos"] = "dentro_do_prazo"
df.loc[df["data_chegada_doca"].isna(), "sla_veiculos"] = "em_aberto"

# ===== 3e. Criacao da coluna sla_carregamento =====
df["sla_carregamento"] = "fora_do_prazo"
df.loc[df["data_carregamento"] <= df["data_exp"], "sla_carregamento"] = "dentro_do_prazo"
df.loc[df["data_carregamento"].isna(), "sla_carregamento"] = "em_aberto"

# ===== 3f. Criacao da coluna sla_faturamento =====
df["sla_faturamento"] = "dentro_do_prazo"
df.loc[df["data_fim_faturamento"].isna(), "sla_faturamento"] = "em_aberto"

# ===== 3f1. Criacao da coluna tempo_criacao_pacote (data_criacao_tu ate data_criacao_pacote) =====
# vazio quando falta alguma data ou quando o pacote foi criado antes da TU (erro de apontamento)
df["tempo_criacao_pacote"] = df["data_criacao_pacote"] - df["data_criacao_tu"]
df.loc[df["tempo_criacao_pacote"] < pd.Timedelta(0), "tempo_criacao_pacote"] = pd.NaT

# ===== 3f1b. Criacao da coluna tempo_espera_picking (data_criacao_pacote ate data_inicio_coleta) =====
# vazio quando falta alguma data ou quando a coleta comecou antes da criacao do pacote (erro de apontamento)
df["tempo_espera_picking"] = df["data_inicio_coleta"] - df["data_criacao_pacote"]
df.loc[df["tempo_espera_picking"] < pd.Timedelta(0), "tempo_espera_picking"] = pd.NaT

# ===== 3f1c. Criacao da coluna tempo_coleta (data_inicio_coleta ate data_fim_coleta) =====
# vazio quando falta alguma data ou quando o fim da coleta e anterior ao inicio (erro de apontamento)
df["tempo_coleta"] = df["data_fim_coleta"] - df["data_inicio_coleta"]
df.loc[df["tempo_coleta"] < pd.Timedelta(0), "tempo_coleta"] = pd.NaT

# ===== 3f1d. Criacao da coluna tempo_conferencia (data_fim_coleta ate data_fim_conferencia) =====
# vazio quando falta alguma data ou quando a conferencia termina antes do fim da coleta (erro de apontamento)
df["tempo_conferencia"] = df["data_fim_conferencia"] - df["data_fim_coleta"]
df.loc[df["tempo_conferencia"] < pd.Timedelta(0), "tempo_conferencia"] = pd.NaT

# ===== 3f1e. Criacao da coluna tempo_faturamento (data_fim_conferencia ate data_fim_faturamento) =====
# vazio quando falta alguma data ou quando o faturamento termina antes do fim da conferencia (erro de apontamento)
df["tempo_faturamento"] = df["data_fim_faturamento"] - df["data_fim_conferencia"]
df.loc[df["tempo_faturamento"] < pd.Timedelta(0), "tempo_faturamento"] = pd.NaT

# ===== 3f1f. Criacao da coluna tempo_puxada (data_fim_faturamento ate data_ats) =====
# vazio quando falta alguma data ou quando a puxada e anterior ao fim do faturamento (erro de apontamento)
df["tempo_puxada"] = df["data_ats"] - df["data_fim_faturamento"]
df.loc[df["tempo_puxada"] < pd.Timedelta(0), "tempo_puxada"] = pd.NaT

# ===== 3f2. Criacao da coluna tempo_ats (data_ats ate data_limite_ats) =====
# mantem o sinal: positivo = puxada antes do limite (folga), negativo = puxada depois do limite (atraso).
# vazio quando falta data_ats
df["tempo_ats"] = df["data_limite_ats"] - df["data_ats"]

# ===== 3f3. Criacao da coluna tempo_espera_consolidacao (data_ats ate data_espera_consolidacao) =====
# vazio quando falta alguma data ou quando a entrada do protocolo da NF e anterior a puxada (erro de apontamento)
df["tempo_espera_consolidacao"] = df["data_espera_consolidacao"] - df["data_ats"]
df.loc[df["tempo_espera_consolidacao"] < pd.Timedelta(0), "tempo_espera_consolidacao"] = pd.NaT

# ===== 3f4. Criacao da coluna tempo_consolidacao (data_espera_consolidacao ate data_consolidacao) =====
# vazio quando falta alguma data ou quando o fim da consolidacao e anterior a entrada do protocolo da NF (erro de apontamento)
df["tempo_consolidacao"] = df["data_consolidacao"] - df["data_espera_consolidacao"]
df.loc[df["tempo_consolidacao"] < pd.Timedelta(0), "tempo_consolidacao"] = pd.NaT
# data_consolidacao depois do checkout e erro de apontamento (ex: celula arrastada no Sheets avancando o dia)
df.loc[df["data_consolidacao"] > df["data_checkout"], "tempo_consolidacao"] = pd.NaT

# ===== 3f4b. Criacao da coluna tempo_checkin_ate_doca (data_checkin ate data_chegada_doca) =====
# vazio quando falta alguma data ou quando a chegada na doca e anterior ao check-in (erro de apontamento)
df["tempo_checkin_ate_doca"] = df["data_chegada_doca"] - df["data_checkin"]
df.loc[df["tempo_checkin_ate_doca"] < pd.Timedelta(0), "tempo_checkin_ate_doca"] = pd.NaT
# data_chegada_doca depois do checkout e erro de apontamento (ex: celula arrastada no Sheets avancando o dia)
df.loc[df["data_chegada_doca"] > df["data_checkout"], "tempo_checkin_ate_doca"] = pd.NaT

# ===== 3f5. Criacao da coluna tempo_chegada_doca (data_consolidacao ate data_chegada_doca) =====
# o veiculo pode chegar antes ou depois do fim da consolidacao; nos dois casos o tempo e a diferenca positiva.
# vazio quando falta alguma data ou quando data_consolidacao/data_chegada_doca e depois do checkout (erro de apontamento)
df["tempo_chegada_doca"] = (df["data_chegada_doca"] - df["data_consolidacao"]).abs()
df.loc[df["data_consolidacao"] > df["data_checkout"], "tempo_chegada_doca"] = pd.NaT
df.loc[df["data_chegada_doca"] > df["data_checkout"], "tempo_chegada_doca"] = pd.NaT
# separa o tempo em duas colunas para permitir media por caso:
# antes = veiculo chegou e aguardou a consolidacao terminar; depois = consolidacao terminou e aguardou o veiculo
chegou_antes = df["data_chegada_doca"] < df["data_consolidacao"]
# geral = conta direta com sinal: negativo quando o veiculo chegou antes do fim da consolidacao
df["tempo_chegada_doca_geral"] = (df["data_chegada_doca"] - df["data_consolidacao"]).where(df["tempo_chegada_doca"].notna())
df["tempo_chegada_doca_antes"] = df["tempo_chegada_doca"].where(chegou_antes)
df["tempo_chegada_doca_depois"] = df["tempo_chegada_doca"].where(~chegou_antes)

# ===== 3f6. Criacao da coluna tempo_espera_carregamento (data_chegada_doca ate data_inicio_carregamento) =====
# vazio quando falta alguma data, quando o inicio do carregamento e anterior a chegada na doca
# ou quando data_chegada_doca/data_inicio_carregamento e depois do checkout (erro de apontamento)
df["tempo_espera_carregamento"] = df["data_inicio_carregamento"] - df["data_chegada_doca"]
df.loc[df["tempo_espera_carregamento"] < pd.Timedelta(0), "tempo_espera_carregamento"] = pd.NaT
df.loc[df["data_chegada_doca"] > df["data_checkout"], "tempo_espera_carregamento"] = pd.NaT
df.loc[df["data_inicio_carregamento"] > df["data_checkout"], "tempo_espera_carregamento"] = pd.NaT

# ===== 3g. Criacao da coluna tempo_carregamento (data_inicio_carregamento ate data_carregamento) =====
# fica vazio (NaT) quando data_inicio_carregamento ou data_carregamento nao foram preenchidos ou sao invalidos,
# e tambem quando data_carregamento e anterior a data_inicio_carregamento (erro de apontamento)
df["tempo_carregamento"] = df["data_carregamento"] - df["data_inicio_carregamento"]
df.loc[df["tempo_carregamento"] < pd.Timedelta(0), "tempo_carregamento"] = pd.NaT
df.loc[df["data_inicio_carregamento"] > df["data_checkout"], "tempo_carregamento"] = pd.NaT
# data_carregamento depois do checkout e erro de apontamento (ex: celula arrastada no Sheets avancando o dia)
df.loc[df["data_carregamento"] > df["data_checkout"], "tempo_carregamento"] = pd.NaT

# ===== 3h. Criacao da coluna tempo_saida_veiculo (data_carregamento ate data_checkout) =====
# mesma regra: vazio quando falta alguma data ou quando data_checkout e anterior a data_carregamento
df["tempo_saida_veiculo"] = df["data_checkout"] - df["data_carregamento"]
df.loc[df["tempo_saida_veiculo"] < pd.Timedelta(0), "tempo_saida_veiculo"] = pd.NaT


def formatar_duracao(td):
    # converte Timedelta para HH:MM:SS (horas podem passar de 24; negativo recebe "-" na frente)
    if pd.isna(td):
        return ""
    sinal = "-" if td < pd.Timedelta(0) else ""
    total = int(abs(td).total_seconds())
    return f"{sinal}{total // 3600:02d}:{total % 3600 // 60:02d}:{total % 60:02d}"

# ===== 4. Filtro de status_tu =====
df = df[~df["status_tu"].isin(["ZERADA TT", "CANCELADO"])].reset_index(drop=True)
df = df[~df["transportador"].str.contains("LALAMOVE", case=False, na=False)].reset_index(drop=True)
df = df[df["qtde_pedidos"].astype(str).str.strip() != ""].reset_index(drop=True)
print(f"Linhas apos filtros de status_tu, transportador e qtde_pedidos: {len(df)}")

# ===== 5. Envio para a aba "etl" =====
df_envio = df[["data_exp", "data_limite_ats", "data_criacao_tu", "data_criacao_pacote", "data_inicio_coleta", "data_fim_coleta", "data_fim_conferencia", "data_fim_faturamento", "data_ats", "data_espera_consolidacao", "data_consolidacao", "data_checkin", "data_chegada_doca", "data_inicio_carregamento", "data_carregamento", "data_checkout","tempo_criacao_pacote","tempo_espera_picking","tempo_coleta","tempo_conferencia","tempo_faturamento","tempo_puxada","tempo_ats","tempo_espera_consolidacao","tempo_consolidacao","tempo_checkin_ate_doca","tempo_chegada_doca_antes","tempo_chegada_doca_depois","tempo_chegada_doca_geral","tempo_espera_carregamento","tempo_carregamento","tempo_saida_veiculo","sla_faturamento","sla_ats","sla_carregamento","sla_expedicao","sla_veiculos","status_tu", "qtde_pedidos", "transportador", "TU", "horario", "chave",]].copy()
for col in ["data_exp", "data_limite_ats", "data_criacao_tu", "data_criacao_pacote", "data_inicio_coleta", "data_fim_coleta", "data_fim_conferencia", "data_fim_faturamento", "data_ats", "data_espera_consolidacao", "data_consolidacao", "data_checkin", "data_chegada_doca", "data_inicio_carregamento", "data_carregamento", "data_checkout"]:
    df_envio[col] = df_envio[col].dt.strftime("%d/%m/%Y %H:%M:%S").fillna("")
for col in ["tempo_criacao_pacote", "tempo_espera_picking", "tempo_coleta", "tempo_conferencia", "tempo_faturamento", "tempo_puxada", "tempo_ats", "tempo_espera_consolidacao", "tempo_consolidacao", "tempo_checkin_ate_doca", "tempo_chegada_doca_antes", "tempo_chegada_doca_depois", "tempo_chegada_doca_geral", "tempo_espera_carregamento", "tempo_carregamento", "tempo_saida_veiculo"]:
    df_envio[col] = df_envio[col].apply(formatar_duracao)
df_envio = df_envio.fillna("")
# data_exp_2 = so a data, em ISO (aaaa-mm-dd) para o Sheets em locale en_US gravar como data real
df_envio.insert(1, "data_exp_2", df["data_exp"].dt.strftime("%Y-%m-%d"))
# data_atualizacao = momento em que este ETL rodou, no horario de Brasilia (UTC-3, sem horario de verao).
# o GitHub Actions roda em UTC, por isso a conversao explicita; ISO para o Sheets (en_US) gravar como data real
agora_brasilia = datetime.now(timezone(timedelta(hours=-3)))
df_envio["data_atualizacao"] = agora_brasilia.strftime("%Y-%m-%d %H:%M:%S")

ws_etl = sh.worksheet("etl")
ws_etl.clear()
ws_etl.resize(rows=len(df_envio) + 1, cols=len(df_envio.columns))
ws_etl.update([df_envio.columns.tolist()] + df_envio.values.tolist(), value_input_option="USER_ENTERED")

# forca formato de duracao nas colunas de tempo; sem isso o Sheets pode exibir como hora do dia
# (ex: -06:35:00 aparecia como 17:25:00)
colunas_tempo = [i for i, c in enumerate(df_envio.columns, start=1) if c.startswith("tempo_")]
ws_etl.batch_format([
    {"range": f"{gspread.utils.rowcol_to_a1(2, i)}:{gspread.utils.rowcol_to_a1(len(df_envio) + 1, i)}",
     "format": {"numberFormat": {"type": "TIME", "pattern": "[h]:mm:ss"}}}
    for i in colunas_tempo
])
ws_etl.format(f"B2:B{len(df_envio) + 1}", {"numberFormat": {"type": "DATE", "pattern": "dd/mm/yyyy"}})
col_atualizacao = gspread.utils.rowcol_to_a1(1, len(df_envio.columns)).rstrip("1")
ws_etl.format(f"{col_atualizacao}2:{col_atualizacao}{len(df_envio) + 1}",
              {"numberFormat": {"type": "DATE_TIME", "pattern": "dd/mm/yyyy hh:mm:ss"}})
print(f"Enviado para a aba 'etl': {len(df_envio)} linhas (atualizado em {agora_brasilia:%d/%m/%Y %H:%M:%S})")

# ===== 6. Resumo diario de SLAs para a aba "etl_resumo" =====
# uma linha por dia de data_exp, sem colunas separadoras (facilita importar em ferramentas de BI).
# Datas vao em ISO (aaaa-mm-dd) porque a planilha esta em locale en_US e "dd/mm/aaaa" seria lido com
# dia e mes trocados; o formato de exibicao dd/mm/aaaa e aplicado depois. Percentuais vao como numero
SLAS_RESUMO = {"sla_ats": "ats", "sla_carregamento": "carregamento", "sla_expedicao": "expedicao"}
# tempos por carreta: cada carreta assume o maior tempo entre suas TUs (as TUs de uma carreta
# diferem so por minutos, ex: protocolo de cada NF entrando em minuto diferente)
TEMPOS_CARRETA = {"tempo_consolidacao": "consolidacao", "tempo_carregamento": "carregamento"}
# mesma regra da aba mes_atual: a carreta (chave) assume o pior status entre suas TUs
PRIORIDADE_STATUS = {"fora_do_prazo": 2, "em_aberto": 1, "dentro_do_prazo": 0}

base_etl_resumo = df[df["data_exp"].dt.year >= 2000].copy()
base_etl_resumo["dia"] = base_etl_resumo["data_exp"].dt.normalize()


def bloco_sla(linha, prefixo, total, no_prazo, fora_do_prazo):
    # % sobre o total (inclui em aberto), igual a aba mes_atual
    linha[f"{prefixo}_total"] = total
    linha[f"{prefixo}_no_prazo"] = no_prazo
    linha[f"{prefixo}_fora_do_prazo"] = fora_do_prazo
    linha[f"{prefixo}_pct"] = no_prazo / total if total else ""


linhas_etl_resumo = []
for dia, grupo in base_etl_resumo.groupby("dia"):
    linha = {"data_exp": dia.strftime("%Y-%m-%d")}
    for sla, nome in SLAS_RESUMO.items():
        status_carreta = grupo.groupby("chave")[sla].agg(lambda s: max(s, key=lambda v: PRIORIDADE_STATUS[v]))
        bloco_sla(linha, f"{nome}_carretas", len(status_carreta),
                  int((status_carreta == "dentro_do_prazo").sum()), int((status_carreta == "fora_do_prazo").sum()))
    for col, nome in TEMPOS_CARRETA.items():
        por_carreta = grupo.groupby("chave")[col].max().dropna() / pd.Timedelta(days=1)
        linha[f"{nome}_carretas_com_tempo"] = len(por_carreta)
        linha[f"tempo_{nome}_carreta_media"] = float(por_carreta.mean()) if len(por_carreta) else ""
        linha[f"tempo_{nome}_carreta_mediana"] = float(por_carreta.median()) if len(por_carreta) else ""
    linhas_etl_resumo.append(linha)

df_etl_resumo = pd.DataFrame(linhas_etl_resumo)
colunas_etl_resumo = df_etl_resumo.columns.tolist()
ultima_linha_etl_resumo = len(df_etl_resumo) + 1

try:
    ws_etl_resumo = sh.worksheet("etl_resumo")
except gspread.WorksheetNotFound:
    ws_etl_resumo = sh.add_worksheet("etl_resumo", rows=ultima_linha_etl_resumo, cols=len(colunas_etl_resumo))
ws_etl_resumo.clear()
ws_etl_resumo.resize(rows=ultima_linha_etl_resumo, cols=len(colunas_etl_resumo))
ws_etl_resumo.update([colunas_etl_resumo] + df_etl_resumo.values.tolist(), value_input_option="USER_ENTERED")


def faixa_coluna(indice):
    letra = gspread.utils.rowcol_to_a1(1, indice).rstrip("0123456789")
    return f"{letra}2:{letra}{ultima_linha_etl_resumo}"


# clear() nao remove formatos; reseta tudo para numero inteiro antes de aplicar data e %
ultima_col_etl_resumo = gspread.utils.rowcol_to_a1(1, len(colunas_etl_resumo)).rstrip("0123456789")
formatos = [
    {"range": f"A2:{ultima_col_etl_resumo}{ultima_linha_etl_resumo}", "format": {"numberFormat": {"type": "NUMBER", "pattern": "#,##0"}}},
    {"range": faixa_coluna(1), "format": {"numberFormat": {"type": "DATE", "pattern": "dd/mm/yyyy"}}},
]
for i, col in enumerate(colunas_etl_resumo, start=1):
    if col.endswith("_pct"):
        formatos.append({"range": faixa_coluna(i), "format": {"numberFormat": {"type": "PERCENT", "pattern": "0.0%"}}})
    elif col.startswith("tempo_"):
        formatos.append({"range": faixa_coluna(i), "format": {"numberFormat": {"type": "TIME", "pattern": "[h]:mm:ss"}}})
ws_etl_resumo.batch_format(formatos)
ws_etl_resumo.freeze(rows=1, cols=1)
print(f"Enviado para a aba 'etl_resumo': {len(df_etl_resumo)} linhas")

# ===== 7. Resumo de SLAs por dia (ats_carreta, ats_pedidos, ats_tu) =====
df_resumo_base = df.copy()
df_resumo_base["data_exp_dia"] = df_resumo_base["data_exp"].dt.date
df_resumo_base["qtde_pedidos"] = pd.to_numeric(df_resumo_base["qtde_pedidos"], errors="coerce").fillna(0)

# uma carreta (chave) agrupa varias TUs que podem ter sla_ats diferentes entre si.
# o status da carreta usa a pior ocorrencia: fora_do_prazo > em_aberto > dentro_do_prazo
PRIORIDADE_SLA = {"fora_do_prazo": 2, "em_aberto": 1, "dentro_do_prazo": 0}
status_carreta = df_resumo_base.groupby("chave").agg(
    data_exp_dia=("data_exp_dia", "first"),
    sla_carreta=("sla_ats", lambda s: max(s, key=lambda v: PRIORIDADE_SLA[v])),
)


def resumo_metrica(grupo, coluna, agregacao):
    dentro = grupo.loc[grupo["sla_ats"] == "dentro_do_prazo", coluna]
    fora = grupo.loc[grupo["sla_ats"] == "fora_do_prazo", coluna]
    if agregacao == "nunique":
        return grupo[coluna].nunique(), dentro.nunique(), fora.nunique()
    return grupo[coluna].sum(), dentro.sum(), fora.sum()


linhas_resumo = []
for dia, grupo in df_resumo_base.groupby("data_exp_dia"):
    carretas_dia = status_carreta[status_carreta["data_exp_dia"] == dia]
    carreta_total = len(carretas_dia)
    carreta_dentro = (carretas_dia["sla_carreta"] == "dentro_do_prazo").sum()
    carreta_fora = (carretas_dia["sla_carreta"] == "fora_do_prazo").sum()
    pedidos_total, pedidos_dentro, pedidos_fora = resumo_metrica(grupo, "qtde_pedidos", "soma")
    tu_total, tu_dentro, tu_fora = resumo_metrica(grupo, "TU", "nunique")
    def pct(dentro, total):
        return dentro / total if total else ""

    linhas_resumo.append({
        "data_exp": dia.strftime("%d/%m/%Y"),
        "ats_carreta_total": carreta_total,
        "ats_carreta_dentro": carreta_dentro,
        "ats_carreta_fora": carreta_fora,
        "ats_carreta_pct": pct(carreta_dentro, carreta_total),
        "_separador1": "",
        "ats_pedidos_total": pedidos_total,
        "ats_pedidos_dentro": pedidos_dentro,
        "ats_pedidos_fora": pedidos_fora,
        "ats_pedidos_pct": pct(pedidos_dentro, pedidos_total),
        "_separador2": "",
        "ats_tu_total": tu_total,
        "ats_tu_dentro": tu_dentro,
        "ats_tu_fora": tu_fora,
        "ats_tu_pct": pct(tu_dentro, tu_total),
    })

df_resumo = pd.DataFrame(linhas_resumo)

# linhas 1 a 3 da aba "resumo" sao montadas manualmente (cabecalho agrupado + linha "Total"),
# entao apenas os dados sao escritos, a partir da linha 4
LINHA_DADOS = 5
ws_resumo = sh.worksheet("mes_atual")
num_cols = len(df_resumo.columns)
ultima_coluna = gspread.utils.rowcol_to_a1(1, num_cols).rstrip("0123456789")
ultima_linha = LINHA_DADOS + len(df_resumo) - 1
if ws_resumo.row_count < ultima_linha:
    ws_resumo.resize(rows=ultima_linha, cols=num_cols)
ws_resumo.batch_clear([f"A{LINHA_DADOS}:{ultima_coluna}{ws_resumo.row_count}"])

ws_resumo.update(range_name=f"A{LINHA_DADOS}", values=df_resumo.values.tolist(), value_input_option="USER_ENTERED")

# formata as colunas de percentual com 1 casa decimal
colunas_pct = [i for i, c in enumerate(df_resumo.columns, start=1) if c.endswith("_pct")]
for col_idx in colunas_pct:
    letra = gspread.utils.rowcol_to_a1(1, col_idx).rstrip("0123456789")
    ws_resumo.format(f"{letra}{LINHA_DADOS}:{letra}{ultima_linha}", {"numberFormat": {"type": "PERCENT", "pattern": "0.0%"}})

print(f"Enviado para a aba 'resumo': {len(df_resumo)} linhas")
