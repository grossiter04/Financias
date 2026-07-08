from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from google import genai
from google.genai import types
from dotenv import load_dotenv
from fastapi.middleware.cors import CORSMiddleware
import os
import json
from datetime import datetime
import gspread

# Carrega as variáveis do arquivo .env
load_dotenv() 

app = FastAPI(title="API Controle Financeiro")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # Em produção, coloque o domínio real do seu PWA
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configurações do Gemini
api_key = os.environ.get("GEMINI_API_KEY")
client = genai.Client(api_key=api_key)

# Configurações do Google Sheets
SHEET_ID = os.environ.get("GOOGLE_SHEET_ID")
CREDENTIALS_PATH = "credenciais-sheets.json" # Caminho do arquivo na raiz

def salvar_no_sheets(dados: dict):
    """Função interna para conectar e apendar os dados na planilha"""
    try:
        gc = gspread.service_account(filename=CREDENTIALS_PATH)
        planilha = gc.open_by_key(SHEET_ID)
        aba = planilha.sheet1
        data_atual = datetime.now().strftime("%d/%m/%Y")
        
        # 1. Voltamos com a vírgula para respeitar o padrão brasileiro do Sheets
        valor_formatado = str(dados["valor"]).replace(".", ",")
        
        nova_linha = [
            data_atual,
            dados["descricao"],
            valor_formatado,
            dados["categoria"]
        ]
        
        # 2. O SEGREDO: Forçamos o Sheets a interpretar o dado (USER_ENTERED)
        aba.append_row(nova_linha, value_input_option="USER_ENTERED")
        print(f"✅ Gasto salvo com sucesso: {nova_linha}")
        
    except Exception as e:
        print(f"❌ Erro ao salvar no Google Sheets: {str(e)}")
        raise e

class GastoInput(BaseModel):
    texto: str

@app.post("/api/categorizar")
async def categorizar_gasto(gasto: GastoInput):
    prompt = f"""
    Você é um classificador de despesas pessoais.
    Analise o texto do usuário e extraia os dados da compra.
    
    Categorias permitidas: Mercado, Assinatura, Farmácia, Lazer, Transporte, Restaurante, Outros.
    
    Texto do usuário: "{gasto.texto}"
    
    Responda EXCLUSIVAMENTE em formato JSON contendo as chaves:
    - "descricao" (string curta)
    - "valor" (número float, sem cifrão)
    - "categoria" (string, apenas uma das permitidas acima)
    """
    
    try:
        # Chamada ao Gemini
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
            ),
        )
        
        texto_limpo = response.text.replace("```json", "").replace("```", "").strip()
        dados_json = json.loads(texto_limpo)
        
        # Se a IA respondeu certo, enviamos para a planilha
        salvar_no_sheets(dados_json)
        
        return {
            "status": "sucesso",
            "dados_salvos": dados_json
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro no processamento: {str(e)}")
    

@app.get("/api/gastos")
async def listar_gastos():
    """Busca o histórico e injeta o ID (número da linha)"""
    try:
        gc = gspread.service_account(filename=CREDENTIALS_PATH)
        planilha = gc.open_by_key(SHEET_ID)
        aba = planilha.sheet1
        
        linhas = aba.get_all_values()
        if len(linhas) <= 1:
            return {"status": "sucesso", "dados": []}
            
        cabecalho = linhas[0]
        registros = []
        
        # O start=2 mapeia exatamente a linha física lá no Sheets (pulando o cabeçalho)
        for i, linha in enumerate(linhas[1:], start=2):
            registro = dict(zip(cabecalho, linha))
            registro["id"] = i  # <-- NOSSO IDENTIFICADOR ÚNICO
            
            try:
                valor_str = str(registro.get("Valor", "0")).replace(".", "").replace(",", ".")
                registro["Valor"] = float(valor_str)
            except ValueError:
                registro["Valor"] = 0.0
                
            registros.append(registro)
        
        return {"status": "sucesso", "dados": registros}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao ler do Sheets: {str(e)}")

# NOVA ROTA: Apagar um gasto específico
@app.delete("/api/gastos/{linha_id}")
async def deletar_gasto(linha_id: int):
    try:
        gc = gspread.service_account(filename=CREDENTIALS_PATH)
        planilha = gc.open_by_key(SHEET_ID)
        aba = planilha.sheet1
        
        # Apaga a linha exata no Google Sheets
        aba.delete_rows(linha_id)
        
        return {"status": "sucesso", "mensagem": "Gasto removido"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao apagar: {str(e)}")