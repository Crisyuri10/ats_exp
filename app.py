"""One page Drive Expedição no Streamlit (painel principal).

A cada 2 minutos (sem botão): lê a Sheet1, aplica o tratamento do sheets_conexao.py, grava as abas etl e
resumo e mostra o painel. O cache é compartilhado entre todos que estão com o app aberto, então o ETL roda
uma vez a cada 2 minutos, não uma vez por pessoa.

O visual do painel (gráfico, tabela, KPIs) fica no painel_template.html; aqui os dados são montados e
injetados no lugar de __DADOS__.
"""
import json
from pathlib import Path

import pandas as pd
import streamlit as st

import sheets_conexao as etl

# ===== 1. Configuração =====
INTERVALO = 120  # segundos entre atualizações dos dados (2 min)
TEMPLATE = Path(__file__).resolve().parent / "painel_template.html"

SLAS = ["sla_ats", "sla_carregamento", "sla_expedicao", "sla_veiculos", "sla_faturamento"]
TEMPOS = [
    "tempo_criacao_pacote", "tempo_espera_picking", "tempo_coleta", "tempo_conferencia",
    "tempo_faturamento", "tempo_puxada", "tempo_espera_consolidacao", "tempo_consolidacao",
    "tempo_checkin_ate_doca", "tempo_espera_carregamento", "tempo_carregamento", "tempo_saida_veiculo",
    "tempo_ats", "tempo_chegada_doca_antes", "tempo_chegada_doca_depois",
]
COD_SLA = {"dentro_do_prazo": 0, "fora_do_prazo": 1, "em_aberto": 2}
# datas que, quando passam do checkout, indicam célula arrastada no Sheets (bit de cada uma no campo de flags)
ARRASTO = {"data_carregamento": 1, "data_consolidacao": 2, "data_chegada_doca": 4, "data_inicio_carregamento": 8}
# etapas de transporte do histórico (mesma ordem do painel) e as duas datas de cada uma;
# serve para explicar por que a etapa ficou sem tempo
ETAPAS_MOTIVO = [
    ("tempo_puxada", "data_fim_faturamento", "data_ats"),
    ("tempo_espera_consolidacao", "data_ats", "data_espera_consolidacao"),
    ("tempo_consolidacao", "data_espera_consolidacao", "data_consolidacao"),
    ("tempo_espera_carregamento", "data_chegada_doca", "data_inicio_carregamento"),
    ("tempo_carregamento", "data_inicio_carregamento", "data_carregamento"),
    ("tempo_saida_veiculo", "data_carregamento", "data_checkout"),
]


# ===== 2. Montagem dos dados do painel =====
# cada linha: [dia, transportador, status, 5 SLAs, 15 tempos (min), flags, chave, pedidos, motivos sem tempo,
#              TU, datas das etapas de transporte (DATAS_POPUP)]
def minutos(td):
    # Timedelta -> minutos com 1 casa; trunca no segundo como a aba etl, para dar o mesmo valor
    if pd.isna(td):
        return None
    seg = int(abs(td).total_seconds())
    return round(-seg / 60 if td < pd.Timedelta(0) else seg / 60, 1)


def pedidos(v):
    # número da célula ou texto "1,645" -> inteiro; vazio ou inválido -> 0
    try:
        return int(float(str(v).replace(",", "")))
    except ValueError:
        return 0


# datas das etapas de transporte enviadas ao painel para o popup de divergências
# (ordem usada no painel_template.html, em DATAS_POPUP)
DATAS_POPUP = [
    "data_fim_faturamento", "data_ats", "data_espera_consolidacao", "data_consolidacao",
    "data_chegada_doca", "data_inicio_carregamento", "data_carregamento", "data_checkout",
]


def texto_data(v):
    # "aaaa-mm-dd hh:mm:ss" (ordena como texto, o painel compara e formata); vazio quando não apontada
    return "" if pd.isna(v) else v.strftime("%Y-%m-%d %H:%M:%S")


def texto_tu(v):
    # número da TU como texto, sem ".0" quando vier como número da planilha
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).strip()


def motivos(r):
    # um caractere por etapa de ETAPAS_MOTIVO: 0 = tem tempo, 1 = falta data, 2 = datas fora de ordem / após checkout
    cod = ""
    for tempo, ini, fim in ETAPAS_MOTIVO:
        if pd.notna(r[tempo]):
            cod += "0"
        elif pd.isna(r[ini]) or pd.isna(r[fim]):
            cod += "1"
        else:
            cod += "2"
    return cod


def montar_dados(df, agora):
    flags = pd.Series(0, index=df.index)
    for col, bit in ARRASTO.items():
        flags = flags | ((df[col] > df["data_checkout"]).fillna(False).astype(int) * bit)

    linhas = []
    for i, r in df.iterrows():
        linhas.append(
            [r["data_exp"].strftime("%Y-%m-%d"), str(r["transportador"]), str(r["status_tu"])]
            + [COD_SLA.get(r[s], 2) for s in SLAS]
            + [minutos(r[c]) for c in TEMPOS]
            + [int(flags[i]), str(r["chave"]), pedidos(r["qtde_pedidos"]), motivos(r),
               texto_tu(r["TU"]), [texto_data(r[c]) for c in DATAS_POPUP]]
        )
    return {"gerado": agora.strftime("%d/%m/%Y %H:%M"), "linhas": linhas}


def gerar_html(dados):
    template = TEMPLATE.read_text(encoding="utf-8")
    # "</" escapado para o JSON não fechar a tag <script> do HTML
    return template.replace("__DADOS__", json.dumps(dados, ensure_ascii=False).replace("</", "<\\/"))


# ===== 3. Carga dos dados (ETL a cada 2 min, compartilhado entre os acessos) =====
def credencial():
    # no Streamlit Cloud: Settings > Secrets > [gcp_service_account]; localmente cai no credenciais.json
    try:
        return st.secrets["gcp_service_account"]
    except Exception:
        return None


@st.cache_data(ttl=INTERVALO, show_spinner="Atualizando dados da planilha...")
def carregar_dados():
    sh = etl.conectar(credencial()).open_by_key(etl.SHEET_ID)
    df, agora = etl.executar(sh)
    return montar_dados(df, agora)


# ===== 4. Página =====
st.set_page_config(page_title="One page Drive Expedição", layout="wide", initial_sidebar_state="collapsed")
# esconde o cabeçalho/menu do Streamlit e as margens, para o painel ocupar a página inteira
st.markdown(
    """<style>
    header[data-testid="stHeader"], #MainMenu, footer { display: none; }
    .block-container { padding: 0 1rem; max-width: 100%; }
    </style>""",
    unsafe_allow_html=True,
)


# confere a cada 30 s se o cache venceu; o painel só é redesenhado quando chegam dados novos
@st.fragment(run_every=30)
def mostrar_painel():
    try:
        dados = carregar_dados()
    except Exception as erro:
        st.error(f"Não foi possível atualizar os dados: {erro}")
        return
    # altura "content": o quadro cresce junto com o painel (ex: ao expandir transportadoras), sem rolagem dupla
    st.iframe(gerar_html(dados), height="content")


mostrar_painel()
