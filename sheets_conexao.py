import gspread
import pandas as pd

SHEET_ID = "1pvor4LGYpxE_7RJgJKCxMME2Yb47gNbByG4ZwZSctcE"
ABA = "Sheet1"


def run(gc):
    sh = gc.open_by_key(SHEET_ID)
    ws = sh.worksheet(ABA)

    bruto = ws.get_all_values(value_render_option="UNFORMATTED_VALUE")
    header = bruto[0]
    df = pd.DataFrame(bruto[1:], columns=header)

    df = df.rename(columns={"JANELA DE EXPEDIÇÃO": "data_exp", "STATUS TU": "status_tu", "CONF. PUXADA": "data_ats", "QTDE DE PEDIDOS": "qtde_pedidos", "TRANSP. + TP": "transportador", "TU(s)": "TU", "HORÁRIO": "horario"})
    df = df[df["data_exp"] != ""].reset_index(drop=True)
    print(f"Linhas apos remover vazias: {len(df)}")

    df["data_exp"] = pd.to_datetime(df["data_exp"].astype(float), unit="D", origin="1899-12-30")
    df["limite_ats"] = df["data_exp"] - pd.Timedelta(hours=3)
    df["data_ats"] = pd.to_datetime(pd.to_numeric(df["data_ats"], errors="coerce"), unit="D", origin="1899-12-30")

    df["chave"] = df["transportador"] + "_" + df["horario"] + "_" + df["data_exp"].dt.strftime("%d/%m/%Y %H:%M:%S")

    df["sla_ats"] = "fora_do_prazo"
    df.loc[df["data_ats"] <= df["limite_ats"], "sla_ats"] = "dentro_do_prazo"
    df.loc[df["data_ats"].isna(), "sla_ats"] = "em_aberto"

    df = df[~df["status_tu"].isin(["ZERADA TT", "CANCELADO"])].reset_index(drop=True)
    df = df[~df["transportador"].str.contains("LALAMOVE", case=False, na=False)].reset_index(drop=True)
    df = df[df["qtde_pedidos"].astype(str).str.strip() != ""].reset_index(drop=True)
    print(f"Linhas apos filtros de status_tu, transportador e qtde_pedidos: {len(df)}")

    df_envio = df[["data_exp", "limite_ats", "data_ats", "sla_ats", "status_tu", "qtde_pedidos", "transportador", "TU", "horario", "chave"]].copy()
    for col in ["data_exp", "limite_ats", "data_ats"]:
        df_envio[col] = df_envio[col].dt.strftime("%d/%m/%Y %H:%M:%S").fillna("")
    df_envio = df_envio.fillna("")

    ws_etl = sh.worksheet("etl")
    ws_etl.clear()
    ws_etl.resize(rows=len(df_envio) + 1, cols=len(df_envio.columns))
    ws_etl.update([df_envio.columns.tolist()] + df_envio.values.tolist(), value_input_option="USER_ENTERED")
    print(f"Enviado para a aba 'etl': {len(df_envio)} linhas")

    df_resumo_base = df.copy()
    df_resumo_base["data_exp_dia"] = df_resumo_base["data_exp"].dt.date
    df_resumo_base["qtde_pedidos"] = pd.to_numeric(df_resumo_base["qtde_pedidos"], errors="coerce").fillna(0)

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

    LINHA_DADOS = 5
    ws_resumo = sh.worksheet("mes_atual")
    num_cols = len(df_resumo.columns)
    ultima_coluna = gspread.utils.rowcol_to_a1(1, num_cols).rstrip("0123456789")
    ultima_linha = LINHA_DADOS + len(df_resumo) - 1
    if ws_resumo.row_count < ultima_linha:
        ws_resumo.resize(rows=ultima_linha, cols=num_cols)
    ws_resumo.batch_clear([f"A{LINHA_DADOS}:{ultima_coluna}{ws_resumo.row_count}"])
    ws_resumo.update(range_name=f"A{LINHA_DADOS}", values=df_resumo.values.tolist(), value_input_option="USER_ENTERED")

    colunas_pct = [i for i, c in enumerate(df_resumo.columns, start=1) if c.endswith("_pct")]
    for col_idx in colunas_pct:
        letra = gspread.utils.rowcol_to_a1(1, col_idx).rstrip("0123456789")
        ws_resumo.format(f"{letra}{LINHA_DADOS}:{letra}{ultima_linha}", {"numberFormat": {"type": "PERCENT", "pattern": "0.0%"}})

    print(f"Enviado para a aba 'resumo': {len(df_resumo)} linhas")


if __name__ == "__main__":
    import os, json
    creds_env = os.environ.get("GCP_SERVICE_ACCOUNT")
    if creds_env:
        gc = gspread.service_account_from_dict(json.loads(creds_env))
    else:
        gc = gspread.service_account(filename="credenciais.json")
    run(gc)
