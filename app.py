import subprocess
import sys
from pathlib import Path

import streamlit as st

st.set_page_config(page_title="ETL Sheets", layout="wide")
st.title("ETL Sheets + Envio")

st.write("Executa o `sheets_conexao.py`: le a aba Sheet1, trata os dados e envia para as abas `etl` e `resumo`.")

if st.button("Executar ETL", type="primary"):
    with st.spinner("Rodando sheets_conexao.py..."):
        resultado = subprocess.run(
            [sys.executable, "sheets_conexao.py"],
            cwd=Path(__file__).parent,
            capture_output=True,
            text=True,
        )

    if resultado.returncode == 0:
        st.success("ETL executado com sucesso.")
    else:
        st.error("Erro ao executar o ETL.")

    if resultado.stdout:
        st.code(resultado.stdout)
    if resultado.stderr:
        st.code(resultado.stderr)
