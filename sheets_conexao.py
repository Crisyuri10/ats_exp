import os
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import gspread
import pandas as pd

# ===== 1. Conexao com o Google Sheets =====
SHEET_ID = "1pvor4LGYpxE_7RJgJKCxMME2Yb47gNbByG4ZwZSctcE"
ABA = "Sheet1"
BRASILIA = timezone(timedelta(hours=-3))


def conectar(info=None):
    # ordem: credencial passada (st.secrets no Streamlit) > secret GCP_SERVICE_ACCOUNT (GitHub Actions)
    # > arquivo credenciais.json ao lado deste script (uso local)
    if info:
        return gspread.service_account_from_dict(dict(info))
    creds_env = os.environ.get("GCP_SERVICE_ACCOUNT")
    if creds_env:
        return gspread.service_account_from_dict(json.loads(creds_env))
    return gspread.service_account(filename=str(Path(__file__).resolve().parent / "credenciais.json"))


def ler_bruto(sh, aba=ABA):
    # UNFORMATTED_VALUE traz o valor real da celula (serial de data, numero, etc),
    # evitando que a formatacao de exibicao do Sheets esconda informacao (ex: ano)
    return sh.worksheet(aba).get_all_values(value_render_option="UNFORMATTED_VALUE")


def converter_data(coluna):
    # datas antes de 2000 sao erro de digitacao (ex: so hora "05:00" vira 30/12/1899 05:00,
    # ou so um numero "3" vira 02/01/1900) e ficam vazias. 36526 = serial de 01/01/2000
    serial = pd.to_numeric(coluna, errors="coerce")
    # tambem descarta valores absurdos acima de 2100 (73051 = serial de 01/01/2100), que quebrariam a conversao
    serial = serial.where((serial >= 36526) & (serial <= 73051))
    return pd.to_datetime(serial, unit="D", origin="1899-12-30")


def formatar_duracao(td):
    # converte Timedelta para HH:MM:SS (horas podem passar de 24; negativo recebe "-" na frente)
    if pd.isna(td):
        return ""
    sinal = "-" if td < pd.Timedelta(0) else ""
    total = int(abs(td).total_seconds())
    return f"{sinal}{total // 3600:02d}:{total % 3600 // 60:02d}:{total % 60:02d}"


def tratar(bruto):
    # remove espacos nas pontas dos nomes das colunas (ex: " FIM DE CONF." -> "FIM DE CONF.")
    header = [str(h).strip() for h in bruto[0]]
    df = pd.DataFrame(bruto[1:], columns=header)

    # ===== 2. Remocao de linhas vazias =====
    # a aba usa formulas que deixam linhas vazias entre os blocos de dados.
    # data_exp serve de referencia: se estiver vazio, a linha inteira esta vazia
    df = df.rename(columns={"JANELA DE EXPEDIÇÃO": "data_exp", "STATUS TU": "status_tu", "CONF. PUXADA": "data_ats", "QTDE DE PEDIDOS": "qtde_pedidos", "TRANSP. + TP": "transportador", "TU(s)": "TU", "HORÁRIO": "horario", "CHECKOUT": "data_checkout", "FIM DE CARREGAM.": "data_carregamento", "FIM. FATURAMENTO": "data_fim_faturamento", "FIM DE CONSOLIDAÇÃO": "data_fim_consolidacao", "CRIAÇÃO PAC.": "data_criacao_pacote", "DATA E HORA DE CRIAÇÃO": "data_criacao_tu", "INICIO COLET.": "data_inicio_coleta", "FIM COLET.": "data_fim_coleta", "FIM DE CONF.": "data_fim_conferencia", "ENT. PROT. NF": "data_ent_nf", "CHEGADA DOCA": "data_chegada_doca", "CHECK-IN": "data_checkin", "INICIO DE CARREG.": "data_inicio_carregamento"})
    df = df[df["data_exp"] != ""].reset_index(drop=True)
    print(f"Linhas apos remover vazias: {len(df)}")

    # ===== 3. Conversao de data_exp, data_limite_ats e data_ats =====
    # data_exp e data_ats vem como serial de data/hora do Sheets (epoch 1899-12-30)
    # janela sem data valida (ex: so a hora "07:00", que vira 0,29) nao tem como ser tratada: a linha sai, com aviso
    df["data_exp"] = converter_data(df["data_exp"])
    sem_data = df["data_exp"].isna()
    if sem_data.any():
        print(f"Aviso: {sem_data.sum()} linha(s) com janela de expedicao sem data valida foram descartadas "
              f"(TUs: {', '.join(df.loc[sem_data, 'TU'].astype(str).head(10))})")
        df = df[~sem_data].reset_index(drop=True)
    df["data_limite_ats"] = df["data_exp"] - pd.Timedelta(hours=3)

    df["data_ats"] = converter_data(df["data_ats"])
    df["data_checkout"] = converter_data(df["data_checkout"])
    df["data_carregamento"] = converter_data(df["data_carregamento"])
    df["data_fim_faturamento"] = converter_data(df["data_fim_faturamento"])
    df["data_fim_consolidacao"] = converter_data(df["data_fim_consolidacao"])
    df["data_criacao_pacote"] = converter_data(df["data_criacao_pacote"])
    df["data_criacao_tu"] = converter_data(df["data_criacao_tu"])
    df["data_inicio_coleta"] = converter_data(df["data_inicio_coleta"])
    df["data_fim_coleta"] = converter_data(df["data_fim_coleta"])
    df["data_fim_conferencia"] = converter_data(df["data_fim_conferencia"])
    df["data_ent_nf"] = converter_data(df["data_ent_nf"])
    df["data_chegada_doca"] = converter_data(df["data_chegada_doca"])
    df["data_checkin"] = converter_data(df["data_checkin"])
    df["data_inicio_carregamento"] = converter_data(df["data_inicio_carregamento"])
    # o serial do Sheets e um float e perde precisao (ex: 05:25:00 vira 05:24:59.999), entao arredonda para o segundo
    for col in ["data_exp", "data_limite_ats", "data_ats", "data_checkout", "data_carregamento", "data_fim_faturamento", "data_fim_consolidacao", "data_criacao_pacote", "data_criacao_tu", "data_inicio_coleta", "data_fim_coleta", "data_fim_conferencia", "data_ent_nf", "data_chegada_doca", "data_checkin", "data_inicio_carregamento"]:
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

    # ===== 3f3. Criacao da coluna tempo_espera_consolidacao (data_ats ate data_ent_nf) =====
    # vazio quando falta alguma data ou quando a entrada do protocolo da NF e anterior a puxada (erro de apontamento)
    df["tempo_espera_consolidacao"] = df["data_ent_nf"] - df["data_ats"]
    df.loc[df["tempo_espera_consolidacao"] < pd.Timedelta(0), "tempo_espera_consolidacao"] = pd.NaT

    # ===== 3f4. Criacao da coluna tempo_consolidacao (data_ent_nf ate data_fim_consolidacao) =====
    # vazio quando falta alguma data ou quando o fim da consolidacao e anterior a entrada do protocolo da NF (erro de apontamento)
    df["tempo_consolidacao"] = df["data_fim_consolidacao"] - df["data_ent_nf"]
    df.loc[df["tempo_consolidacao"] < pd.Timedelta(0), "tempo_consolidacao"] = pd.NaT
    # data_fim_consolidacao depois do checkout e erro de apontamento (ex: celula arrastada no Sheets avancando o dia)
    df.loc[df["data_fim_consolidacao"] > df["data_checkout"], "tempo_consolidacao"] = pd.NaT

    # ===== 3f4b. Criacao da coluna tempo_checkin_ate_doca (data_checkin ate data_chegada_doca) =====
    # vazio quando falta alguma data ou quando a chegada na doca e anterior ao check-in (erro de apontamento)
    df["tempo_checkin_ate_doca"] = df["data_chegada_doca"] - df["data_checkin"]
    df.loc[df["tempo_checkin_ate_doca"] < pd.Timedelta(0), "tempo_checkin_ate_doca"] = pd.NaT
    # data_chegada_doca depois do checkout e erro de apontamento (ex: celula arrastada no Sheets avancando o dia)
    df.loc[df["data_chegada_doca"] > df["data_checkout"], "tempo_checkin_ate_doca"] = pd.NaT

    # ===== 3f5. Criacao da coluna tempo_chegada_doca (chegada do veiculo na doca x janela de expedicao) =====
    # mede a pontualidade do veiculo em relacao a janela (data_exp): ele pode chegar antes ou depois dela;
    # nos dois casos o tempo e a diferenca positiva.
    # vazio quando falta a chegada na doca ou quando ela e depois do checkout (erro de apontamento)
    df["tempo_chegada_doca"] = (df["data_chegada_doca"] - df["data_exp"]).abs()
    df.loc[df["data_chegada_doca"] > df["data_checkout"], "tempo_chegada_doca"] = pd.NaT
    # separa o tempo em duas colunas para permitir media por caso:
    # antes = veiculo chegou antes da janela (folga); depois = veiculo chegou depois da janela (atraso)
    chegou_antes = df["data_chegada_doca"] < df["data_exp"]
    # geral = conta direta com sinal: negativo quando o veiculo chegou antes da janela, positivo quando chegou atrasado
    df["tempo_chegada_doca_geral"] = (df["data_chegada_doca"] - df["data_exp"]).where(df["tempo_chegada_doca"].notna())
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

    # ===== 4. Filtro de status_tu =====
    df = df[~df["status_tu"].isin(["ZERADA TT", "CANCELADO"])].reset_index(drop=True)
    df = df[~df["transportador"].str.contains("LALAMOVE", case=False, na=False)].reset_index(drop=True)
    df = df[df["qtde_pedidos"].astype(str).str.strip() != ""].reset_index(drop=True)
    print(f"Linhas apos filtros de status_tu, transportador e qtde_pedidos: {len(df)}")

    # ===== 4b. Criacao da coluna status2 =====
    # igual ao status_tu, exceto quando a carga ja esta pronta (AG. CARREGAMENTO) e o veiculo ainda
    # nao chegou na doca (CHEGADA DOCA vazia): nesse caso vira AG. VEÍCULO
    status_tu = df["status_tu"].astype(str).str.strip()
    df["status2"] = df["status_tu"]
    df.loc[(status_tu == "AG. CARREGAMENTO") & df["data_chegada_doca"].isna(), "status2"] = "AG. VEÍCULO"
    return df


def gravar_etl(sh, df, agora, aba="etl"):
    # ===== 5. Envio para a aba "etl" (ou outra aba, ex: historico_etl) =====
    df_envio = df[["data_exp", "data_limite_ats", "data_criacao_tu", "data_criacao_pacote", "data_inicio_coleta", "data_fim_coleta", "data_fim_conferencia", "data_fim_faturamento", "data_ats", "data_ent_nf", "data_fim_consolidacao", "data_checkin", "data_chegada_doca", "data_inicio_carregamento", "data_carregamento", "data_checkout","tempo_criacao_pacote","tempo_espera_picking","tempo_coleta","tempo_conferencia","tempo_faturamento","tempo_puxada","tempo_ats","tempo_espera_consolidacao","tempo_consolidacao","tempo_checkin_ate_doca","tempo_chegada_doca_antes","tempo_chegada_doca_depois","tempo_chegada_doca_geral","tempo_espera_carregamento","tempo_carregamento","tempo_saida_veiculo","sla_faturamento","sla_ats","sla_carregamento","sla_expedicao","sla_veiculos","status_tu", "status2", "qtde_pedidos", "transportador", "TU", "horario", "chave",]].copy()
    for col in ["data_exp", "data_limite_ats", "data_criacao_tu", "data_criacao_pacote", "data_inicio_coleta", "data_fim_coleta", "data_fim_conferencia", "data_fim_faturamento", "data_ats", "data_ent_nf", "data_fim_consolidacao", "data_checkin", "data_chegada_doca", "data_inicio_carregamento", "data_carregamento", "data_checkout"]:
        df_envio[col] = df_envio[col].dt.strftime("%d/%m/%Y %H:%M:%S").fillna("")
    for col in ["tempo_criacao_pacote", "tempo_espera_picking", "tempo_coleta", "tempo_conferencia", "tempo_faturamento", "tempo_puxada", "tempo_ats", "tempo_espera_consolidacao", "tempo_consolidacao", "tempo_checkin_ate_doca", "tempo_chegada_doca_antes", "tempo_chegada_doca_depois", "tempo_chegada_doca_geral", "tempo_espera_carregamento", "tempo_carregamento", "tempo_saida_veiculo"]:
        df_envio[col] = df_envio[col].apply(formatar_duracao)
    df_envio = df_envio.fillna("")
    # data_exp_2 = so a data, em ISO (aaaa-mm-dd) para o Sheets em locale en_US gravar como data real
    df_envio.insert(1, "data_exp_2", df["data_exp"].dt.strftime("%Y-%m-%d"))
    # data_atualizacao = momento em que este ETL rodou, no horario de Brasilia (UTC-3, sem horario de verao).
    # ISO para o Sheets (en_US) gravar como data real
    df_envio["data_atualizacao"] = agora.strftime("%Y-%m-%d %H:%M:%S")

    ws_etl = sh.worksheet(aba)
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
    print(f"Enviado para a aba '{aba}': {len(df_envio)} linhas (atualizado em {agora:%d/%m/%Y %H:%M:%S})")


SLAS_CARRETA_EXTRAS = [("chegada", "sla_veiculos"), ("carregamento", "sla_carregamento"), ("expedicao", "sla_expedicao")]


def montar_resumo(df, extras=False):
    # resumo de SLA ATS por dia (carretas, pedidos e TUs: total, dentro, fora e %), com separadores.
    # extras=True (aba metrica): acrescenta, por carreta, os SLAs de chegada do veiculo, carregamento e expedicao
    df_resumo_base = df.copy()
    df_resumo_base["data_exp_dia"] = df_resumo_base["data_exp"].dt.date
    df_resumo_base["qtde_pedidos"] = pd.to_numeric(df_resumo_base["qtde_pedidos"], errors="coerce").fillna(0)

    # uma carreta (chave) agrupa varias TUs que podem ter sla diferentes entre si.
    # o status da carreta usa a pior ocorrencia: fora_do_prazo > em_aberto > dentro_do_prazo
    PRIORIDADE_SLA = {"fora_do_prazo": 2, "em_aberto": 1, "dentro_do_prazo": 0}
    pior = lambda s: max(s, key=lambda v: PRIORIDADE_SLA.get(v, 1))
    agg = {"data_exp_dia": ("data_exp_dia", "first"), "sla_carreta": ("sla_ats", pior)}
    for nome, coluna in SLAS_CARRETA_EXTRAS:
        agg[f"sla_{nome}"] = (coluna, pior)
    status_carreta = df_resumo_base.groupby("chave").agg(**agg)

    def resumo_metrica(grupo, coluna, agregacao):
        dentro = grupo.loc[grupo["sla_ats"] == "dentro_do_prazo", coluna]
        fora = grupo.loc[grupo["sla_ats"] == "fora_do_prazo", coluna]
        if agregacao == "nunique":
            return grupo[coluna].nunique(), dentro.nunique(), fora.nunique()
        return grupo[coluna].sum(), dentro.sum(), fora.sum()

    def pct(dentro, total):
        return dentro / total if total else ""

    linhas_resumo = []
    for dia, grupo in df_resumo_base.groupby("data_exp_dia"):
        carretas_dia = status_carreta[status_carreta["data_exp_dia"] == dia]
        carreta_total = len(carretas_dia)
        carreta_dentro = (carretas_dia["sla_carreta"] == "dentro_do_prazo").sum()
        carreta_fora = (carretas_dia["sla_carreta"] == "fora_do_prazo").sum()
        pedidos_total, pedidos_dentro, pedidos_fora = resumo_metrica(grupo, "qtde_pedidos", "soma")
        tu_total, tu_dentro, tu_fora = resumo_metrica(grupo, "TU", "nunique")

        linha = {
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
        }
        if extras:
            # mesma base de carretas do ATS (total = ats_carreta_total); em aberto nao entra em dentro nem fora
            for nome, _ in SLAS_CARRETA_EXTRAS:
                dentro = int((carretas_dia[f"sla_{nome}"] == "dentro_do_prazo").sum())
                fora = int((carretas_dia[f"sla_{nome}"] == "fora_do_prazo").sum())
                linha[f"{nome}_carreta_total"] = carreta_total
                linha[f"{nome}_carreta_dentro"] = dentro
                linha[f"{nome}_carreta_fora"] = fora
                linha[f"{nome}_carreta_pct"] = pct(dentro, carreta_total)
        linhas_resumo.append(linha)

    return pd.DataFrame(linhas_resumo)


def gravar_resumo(sh, df, aba="mes_atual", linha_dados=5, cabecalho=False, so_numeros=False):
    # ===== 6. Resumo de SLAs por dia (ats_carreta, ats_pedidos, ats_tu) =====
    # aba "mes_atual": linhas 1 a 4 montadas a mao, dados a partir da linha 5 (padrao).
    # outras abas (ex: metrica): cabecalho=True grava os nomes das colunas na linha anterior aos dados
    df_resumo = montar_resumo(df, extras=so_numeros)
    # so_numeros (ex: aba metrica): sem as colunas de percentual e sem os separadores
    if so_numeros:
        df_resumo = df_resumo[[c for c in df_resumo.columns if not c.endswith("_pct") and not c.startswith("_separador")]]
    # abas novas (cabecalho=True, ex: metrica): data em ISO (aaaa-mm-dd) para o Sheets em locale en_US gravar a
    # data certa (com "dd/mm/aaaa" ele le mes/dia e troca dia e mes); a exibicao fica dd/mm/aaaa pelo formato abaixo
    if cabecalho and len(df_resumo):
        df_resumo["data_exp"] = pd.to_datetime(df_resumo["data_exp"], format="%d/%m/%Y").dt.strftime("%Y-%m-%d")
        df_resumo = df_resumo.rename(columns={"data_exp": "Data"})  # nas abas novas (metrica) a coluna se chama "Data"

    # linhas 1 a 3 da aba "resumo" sao montadas manualmente (cabecalho agrupado + linha "Total"),
    # entao apenas os dados sao escritos, a partir da linha 4
    LINHA_DADOS = linha_dados
    ws_resumo = sh.worksheet(aba)
    num_cols = len(df_resumo.columns)
    ultima_coluna = gspread.utils.rowcol_to_a1(1, num_cols).rstrip("0123456789")
    ultima_linha = LINHA_DADOS + len(df_resumo) - 1
    if ws_resumo.row_count < ultima_linha:
        ws_resumo.resize(rows=ultima_linha, cols=num_cols)
    if cabecalho:
        # aba sem layout manual (ex: metrica): limpa tudo, para nao sobrar coluna antiga quando o formato muda
        ws_resumo.clear()
    else:
        ws_resumo.batch_clear([f"A{LINHA_DADOS}:{ultima_coluna}{ws_resumo.row_count}"])

    if cabecalho:
        ws_resumo.update(range_name=f"A{LINHA_DADOS - 1}", values=[df_resumo.columns.tolist()], value_input_option="USER_ENTERED")
    ws_resumo.update(range_name=f"A{LINHA_DADOS}", values=df_resumo.values.tolist(), value_input_option="USER_ENTERED")

    if cabecalho and len(df_resumo):
        ws_resumo.format(f"A{LINHA_DADOS}:A{ultima_linha}", {"numberFormat": {"type": "DATE", "pattern": "dd/mm/yyyy"}})
    # formata as colunas de percentual com 1 casa decimal
    colunas_pct = [i for i, c in enumerate(df_resumo.columns, start=1) if c.endswith("_pct")]
    for col_idx in colunas_pct:
        letra = gspread.utils.rowcol_to_a1(1, col_idx).rstrip("0123456789")
        ws_resumo.format(f"{letra}{LINHA_DADOS}:{letra}{ultima_linha}", {"numberFormat": {"type": "PERCENT", "pattern": "0.0%"}})

    print(f"Enviado para a aba '{aba}': {len(df_resumo)} linhas")


def empilhar_metrica(sh, df, aba="metrica"):
    # aba metrica = historico dos meses fechados (gravado pelo sheets_conexao_historico.py) + o mes atual
    # empilhado embaixo. A cada rodada substitui so as linhas do mes atual (datas >= 1o dia do mes dos dados);
    # as linhas dos meses anteriores ficam como estao. Na virada do mes, o mes que fechou fica gravado.
    resumo = montar_resumo(df, extras=True)
    if resumo.empty:
        return
    resumo = resumo[[c for c in resumo.columns if not c.endswith("_pct") and not c.startswith("_separador")]]
    datas = pd.to_datetime(resumo["data_exp"], format="%d/%m/%Y")
    inicio_mes = pd.Timestamp(datas.min().year, datas.min().month, 1)
    resumo["data_exp"] = datas.dt.strftime("%Y-%m-%d")
    resumo = resumo.rename(columns={"data_exp": "Data"})  # na metrica a coluna de data se chama "Data"

    ws = sh.worksheet(aba)
    cab = ws.row_values(1)
    # aba ainda com o cabecalho antigo (sem as colunas veiculo/carregamento/expedicao): grava so as colunas que ela tem
    if cab and cab != resumo.columns.tolist() and cab == resumo.columns.tolist()[:len(cab)]:
        resumo = resumo[cab]
    if cab != resumo.columns.tolist():
        print(f"Aviso: cabecalho da aba '{aba}' diferente do esperado; metrica nao atualizada")
        return
    # datas ja gravadas (serial do Sheets) -> primeira linha do mes atual (ou o fim, se ainda nao existe)
    col_a = ws.col_values(1, value_render_option="UNFORMATTED_VALUE")[1:]
    seriais = pd.to_numeric(pd.Series(col_a, dtype=object), errors="coerce")
    datas_gravadas = pd.to_datetime(seriais, unit="D", origin="1899-12-30")
    do_mes = (datas_gravadas >= inicio_mes).to_numpy().nonzero()[0]
    linha_ini = (do_mes[0] if len(do_mes) else len(col_a)) + 2   # +1 cabecalho, +1 base 1
    ultima = max(ws.row_count, linha_ini + len(resumo))
    if ws.row_count < ultima:
        ws.resize(rows=ultima)
    ultima_col = gspread.utils.rowcol_to_a1(1, len(resumo.columns)).rstrip("0123456789")
    ws.batch_clear([f"A{linha_ini}:{ultima_col}{ws.row_count}"])
    ws.update(range_name=f"A{linha_ini}", values=resumo.astype(object).values.tolist(), value_input_option="USER_ENTERED")
    ws.format(f"A{linha_ini}:A{linha_ini + len(resumo) - 1}", {"numberFormat": {"type": "DATE", "pattern": "dd/mm/yyyy"}})
    print(f"Mes atual empilhado na aba '{aba}': {len(resumo)} dias a partir da linha {linha_ini}")


def executar(sh):
    # fluxo completo: le a Sheet1, trata e grava as abas etl e resumo. Devolve o df tratado e a hora da execucao
    df = tratar(ler_bruto(sh))
    agora = datetime.now(BRASILIA)
    gravar_etl(sh, df, agora)
    gravar_resumo(sh, df)
    empilhar_metrica(sh, df)
    return df, agora


if __name__ == "__main__":
    executar(conectar().open_by_key(SHEET_ID))
