import gspread
import streamlit as st
import sheets_conexao

st.set_page_config(page_title="ETL Sheets", layout="wide")
st.title("ETL Sheets + Envio")
st.write("Executa o `sheets_conexao.py`: le a aba Sheet1, trata os dados e envia para as abas `etl` e `mes_atual`.")


def autenticar():
    try:
        creds = st.secrets["gcp_service_account"]
        return gspread.service_account_from_dict(dict(creds))
    except Exception:
        return gspread.service_account(filename="credenciais.json")


if st.button("Executar ETL", type="primary"):
    with st.spinner("Rodando ETL..."):
        try:
            gc = autenticar()
            sheets_conexao.run(gc)
            st.success("ETL executado com sucesso.")
        except Exception as e:
            st.error(f"Erro ao executar o ETL: {e}")
