import sqlite3
import os
import sys
import time
import re
import html
import urllib.parse
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, HTTPException, Body, Request, Query
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import pix

# Garante suporte a UTF-8 em terminais Windows (cp1252)
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

START_TIME = time.time()
DB_NAME = "condominio.db"

app = FastAPI(
    title="ConciliaZap - Gestão de Conflitos e Condomínio 24/7",
    description="Sistema autônomo de mediação de conflitos, ocorrências e gestão condominial via WhatsApp com moderação do síndico.",
    version="2.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- MIDDLEWARE DE SEGURANÇA OWASP & RATE LIMITING CONTRA FLOOD/DOS ---
RATE_LIMIT_STORE: Dict[str, List[float]] = {}
RATE_LIMIT_WINDOW = 60 # Janela de 60 segundos
MAX_REQUESTS_GLOBAL = 250 # Até 250 req/min por IP
MAX_REQUESTS_SENSITIVE = 60 # Até 60 req/min em rotas sensíveis (webhook, pix)

@app.middleware("http")
async def security_and_rate_limit_middleware(request: Request, call_next):
    client_ip = request.client.host if request.client else "127.0.0.1"
    path = request.url.path
    agora = time.time()
    
    # Isenta health check e arquivos estáticos do limitador
    is_exempt = path.startswith("/api/health") or path.startswith("/static") or path in ["/", "/favicon.ico", "/index.html"]
    
    if not is_exempt:
        limite = MAX_REQUESTS_SENSITIVE if any(path.startswith(p) for p in ["/api/webhook", "/api/pix/gerar", "/api/simulador"]) else MAX_REQUESTS_GLOBAL
        
        historico = RATE_LIMIT_STORE.get(client_ip, [])
        historico = [t for t in historico if agora - t < RATE_LIMIT_WINDOW]
        
        if len(historico) >= limite:
            return JSONResponse(
                status_code=429,
                content={"detail": "Muitas requisições. Limite temporário de segurança atingido. Aguarde alguns segundos."},
                headers={"Retry-After": "30"}
            )
            
        historico.append(agora)
        RATE_LIMIT_STORE[client_ip] = historico
        
    response = await call_next(request)
    
    # Injeção de cabeçalhos de segurança obrigatórios (OWASP Top 10)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    
    return response

# --- MODELOS DE ENTRADA Pydantic ---
class WhatsAppMessage(BaseModel):
    id: Optional[str] = "msg-auto"
    sender_phone: str  # Ex: "5511999990302" ou "11999990302"
    text: str          # Mensagem enviada pelo morador

class MoradorCreate(BaseModel):
    nome: str
    telefone: str
    apartamento: str
    bloco: str
    tipo: Optional[str] = "morador"
    condominio_id: Optional[int] = 1

class MoradorUpdate(BaseModel):
    nome: Optional[str] = None
    telefone: Optional[str] = None
    apartamento: Optional[str] = None
    bloco: Optional[str] = None
    tipo: Optional[str] = None
    condominio_id: Optional[int] = None

class CondominioCreate(BaseModel):
    nome: str
    slug: str
    cnpj: Optional[str] = None
    plano_ativo: Optional[str] = "starter"

class ReservaCreate(BaseModel):
    morador_id: int
    area: str
    data_reserva: str
    periodo: str
    condominio_id: Optional[int] = 1

class AchadoCreate(BaseModel):
    item: str
    local_encontrado: str
    condominio_id: Optional[int] = 1

class OcorrenciaDecisao(BaseModel):
    status: str  # 'Aprovada', 'Rejeitada' ou 'Arquivada'
    motivo: Optional[str] = ""
    penalidade: Optional[str] = "Aviso Amigável" # 'Aviso Amigável', 'Advertência Formal', 'Multa', 'Nenhuma'
    valor_multa: Optional[float] = 0.0

class PixRequest(BaseModel):
    plano_nome: str
    valor: float
    chave_pix: Optional[str] = "contato@conciliazap.com.br"
    nome_recebedor: Optional[str] = "ConciliaZap Solucoes Ltda"
    cidade: Optional[str] = "SAO PAULO"
    condominio_id: Optional[int] = 1

class PixConfirmRequest(BaseModel):
    txid: str

class AssinaturaRenovacao(BaseModel):
    condominio_id: Optional[int] = 1
    plano: Optional[str] = "Condomínio Pro"
    dias: Optional[int] = 30

# --- INICIALIZAÇÃO E CONEXÃO COM O BANCO ---
def get_db():
    conn = sqlite3.connect(DB_NAME, timeout=30.0)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.row_factory = sqlite3.Row
    return conn

def inicializar_banco():
    conn = sqlite3.connect(DB_NAME, timeout=30.0)
    conn.execute("PRAGMA journal_mode=WAL;")
    cursor = conn.cursor()
    
    # 0. Tabela de Condomínios (Multiempresa / Multitenant)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS condominios (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nome TEXT NOT NULL,
        slug TEXT UNIQUE NOT NULL,
        cnpj TEXT,
        plano_ativo TEXT DEFAULT 'starter',
        plano_expira_em DATETIME,
        criado_em DATETIME DEFAULT CURRENT_TIMESTAMP
    )""")
    
    # 1. Tabela de Moradores
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS moradores (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        condominio_id INTEGER DEFAULT 1,
        nome TEXT NOT NULL,
        telefone TEXT UNIQUE NOT NULL,
        apartamento TEXT NOT NULL,
        bloco TEXT NOT NULL,
        tipo TEXT DEFAULT 'morador',
        criado_em DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(condominio_id) REFERENCES condominios(id)
    )""")
    
    # 2. Tabela de Ocorrências
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS ocorrencias (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        condominio_id INTEGER DEFAULT 1,
        morador_id INTEGER NOT NULL,
        apartamento_alvo TEXT,
        bloco_alvo TEXT,
        categoria TEXT DEFAULT 'Barulho',
        descricao TEXT NOT NULL,
        evidencia_url TEXT,
        status TEXT DEFAULT 'Pendente',
        decisao_sindico TEXT,
        notificacao_enviada INTEGER DEFAULT 0,
        penalidade TEXT DEFAULT 'Nenhuma',
        valor_multa REAL DEFAULT 0.0,
        data_hora DATETIME DEFAULT CURRENT_TIMESTAMP,
        resolvido_em DATETIME,
        FOREIGN KEY(condominio_id) REFERENCES condominios(id),
        FOREIGN KEY(morador_id) REFERENCES moradores(id)
    )""")
    
    # 3. Tabela de Reservas
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS reservas (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        condominio_id INTEGER DEFAULT 1,
        morador_id INTEGER NOT NULL,
        area TEXT NOT NULL,
        data_reserva TEXT NOT NULL,
        periodo TEXT NOT NULL,
        status TEXT DEFAULT 'Confirmada',
        termo_aceito INTEGER DEFAULT 1,
        criado_em DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(condominio_id) REFERENCES condominios(id),
        FOREIGN KEY(morador_id) REFERENCES moradores(id)
    )""")
    
    # 4. Tabela de Achados e Perdidos
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS achados_perdidos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        condominio_id INTEGER DEFAULT 1,
        item TEXT NOT NULL,
        local_encontrado TEXT NOT NULL,
        status TEXT DEFAULT 'Disponível',
        devolvido_para TEXT,
        data_registro DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(condominio_id) REFERENCES condominios(id)
    )""")
    
    # 5. Tabela de Cobranças e Faturas PIX
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS cobrancas_pix (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        txid TEXT UNIQUE NOT NULL,
        condominio_id INTEGER DEFAULT 1,
        plano TEXT NOT NULL,
        valor REAL NOT NULL,
        status TEXT DEFAULT 'PENDENTE',
        pix_copia_e_cola TEXT,
        qr_code_url TEXT,
        criado_em DATETIME DEFAULT CURRENT_TIMESTAMP,
        pago_em DATETIME,
        FOREIGN KEY(condominio_id) REFERENCES condominios(id)
    )""")
    
    # 6. Tabela de Configurações
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS configuracoes (
        chave TEXT PRIMARY KEY,
        valor TEXT
    )""")

    # Migrações seguras de colunas existentes
    def migrar_coluna(table, col):
        try:
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN {col}")
        except sqlite3.OperationalError:
            pass

    migrar_coluna("moradores", "condominio_id INTEGER DEFAULT 1")
    migrar_coluna("ocorrencias", "condominio_id INTEGER DEFAULT 1")
    migrar_coluna("reservas", "condominio_id INTEGER DEFAULT 1")
    migrar_coluna("achados_perdidos", "condominio_id INTEGER DEFAULT 1")
    migrar_coluna("condominios", "plano_expira_em DATETIME")
    migrar_coluna("condominios", "status_assinatura TEXT DEFAULT 'ativa'")
    
    # Condomínios de demonstração (Multiempresa)
    cursor.execute("SELECT COUNT(*) FROM condominios")
    agora = datetime.now()
    expira_padrao = (agora + timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
    if cursor.fetchone()[0] == 0:
        cursor.execute("""
        INSERT INTO condominios (id, nome, slug, cnpj, plano_ativo, plano_expira_em, status_assinatura)
        VALUES (1, 'Condomínio Residencial Jardins', 'jardins', '12.345.678/0001-90', 'pro', ?, 'ativa'),
               (2, 'Condomínio Solar das Palmeiras', 'palmeiras', '98.765.432/0001-10', 'starter', ?, 'ativa')
        """, (expira_padrao, expira_padrao))
    else:
        # Garante inicialização de 30 dias para os existentes sem data
        cursor.execute("UPDATE condominios SET plano_expira_em = ?, status_assinatura = 'ativa' WHERE plano_expira_em IS NULL", (expira_padrao,))
    
    # Moradores de demonstração Condomínio 1
    moradores_iniciais = [
        (1, "Roberto Oliveira (Síndico)", "5511999990001", "101", "A", "sindico"),
        (1, "Carlos Mendes", "5511999990302", "302", "A", "morador"),
        (1, "Marcos Souza", "5511999990402", "402", "A", "morador"),
        (1, "Juliana Costa", "5511999990205", "205", "B", "morador"),
        (1, "Fernanda Lima", "5511999990501", "501", "B", "morador"),
        (1, "Eduardo Rocha", "5511999990104", "104", "A", "morador")
    ]
    for cid, nome, tel, ap, bloco, tipo in moradores_iniciais:
        cursor.execute("""
        INSERT OR IGNORE INTO moradores (condominio_id, nome, telefone, apartamento, bloco, tipo)
        VALUES (?, ?, ?, ?, ?, ?)
        """, (cid, nome, tel, ap, bloco, tipo))

    # Moradores de demonstração Condomínio 2 (Para teste de isolamento multiempresa)
    moradores_condo2 = [
        (2, "Beatriz Ramos (Síndica Palmeiras)", "5511999990888", "101", "A", "sindico"),
        (2, "Rodrigo Silveira", "5511999990777", "202", "B", "morador")
    ]
    for cid, nome, tel, ap, bloco, tipo in moradores_condo2:
        cursor.execute("""
        INSERT OR IGNORE INTO moradores (condominio_id, nome, telefone, apartamento, bloco, tipo)
        VALUES (?, ?, ?, ?, ?, ?)
        """, (cid, nome, tel, ap, bloco, tipo))

    # Ocorrência inicial de exemplo
    cursor.execute("SELECT COUNT(*) FROM ocorrencias")
    if cursor.fetchone()[0] == 0:
        cursor.execute("""
        INSERT INTO ocorrencias (condominio_id, morador_id, apartamento_alvo, bloco_alvo, categoria, descricao, status, penalidade)
        VALUES (1, 2, '402', 'A', 'Barulho', 'Barulho de obra e som excessivo no 402 após as 22h com batidas fortes.', 'Pendente', 'Nenhuma')
        """)

    # Reserva inicial
    cursor.execute("SELECT COUNT(*) FROM reservas")
    if cursor.fetchone()[0] == 0:
        cursor.execute("""
        INSERT INTO reservas (condominio_id, morador_id, area, data_reserva, periodo, status)
        VALUES (1, 4, 'Salão de Festas', '2026-11-15', 'Noite (18h às 23h)', 'Confirmada')
        """)

    # Achados e perdidos
    cursor.execute("SELECT COUNT(*) FROM achados_perdidos")
    if cursor.fetchone()[0] == 0:
        cursor.execute("""
        INSERT INTO achados_perdidos (condominio_id, item, local_encontrado, status)
        VALUES (1, 'Chaveiro com controle de portão', 'Garagem Subsolo 1 (próximo à vaga 22)', 'Disponível')
        """)

    # Configurações padrão
    configs_padrao = [
        ("nome_condominio", "Condomínio Residencial Jardins"),
        ("horario_silencio", "22:00 às 08:00"),
        ("whatsapp_instancia", "ConciliaZap-Bot"),
        ("evolution_api_url", "https://api.meucondominio.com.br"),
        ("evolution_api_key", "secret-key-demo-xyz"),
        ("sindico_whatsapp", "5511999990001")
    ]
    for k, v in configs_padrao:
        cursor.execute("INSERT OR IGNORE INTO configuracoes (chave, valor) VALUES (?, ?)", (k, v))
        
    conn.commit()
    conn.close()

inicializar_banco()

# --- FUNÇÕES DE BUSCA E APOIO ---
def sanitizar_telefone(tel: str) -> str:
    limpo = re.sub(r"\D", "", tel)
    if not limpo.startswith("55") and len(limpo) in [10, 11]:
        limpo = "55" + limpo
    return limpo

def extrair_dados_mensagem(body: Any) -> tuple[str, str, str]:
    if not isinstance(body, dict):
        return "msg-auto", "", ""
        
    # 1. Formato Evolution API: {"event": "messages.upsert", "data": {"key": {"remoteJid": "...@s.whatsapp.net"}, "message": {"conversation": "..."}}}
    if "data" in body and isinstance(body["data"], dict):
        d = body["data"]
        key = d.get("key", {}) if isinstance(d.get("key"), dict) else {}
        msg_id = key.get("id", "evo-msg")
        remote_jid = key.get("remoteJid", "")
        message = d.get("message", {}) if isinstance(d.get("message"), dict) else {}
        texto = message.get("conversation") or message.get("extendedTextMessage", {}).get("text") or ""
        return msg_id, remote_jid, texto

    # 2. Formato Z-API: {"phone": "...", "text": {"message": "..."}, "messageId": "..."}
    if "phone" in body:
        msg_id = body.get("messageId", "zapi-msg")
        phone = body.get("phone", "")
        text_obj = body.get("text", {})
        texto = text_obj.get("message") if isinstance(text_obj, dict) else str(text_obj)
        return msg_id, phone, texto

    # 3. Formato Padrão / Simulador: {"sender_phone": "...", "text": "...", "id": "..."}
    msg_id = body.get("id", "msg-direct")
    sender_phone = body.get("sender_phone") or body.get("from") or body.get("telefone") or ""
    texto = body.get("text") or body.get("mensagem") or body.get("body") or ""
    return msg_id, sender_phone, texto

def buscar_morador_por_telefone(telefone: str):
    tel_limpo = sanitizar_telefone(telefone)
    conn = get_db()
    cursor = conn.cursor()
    # Tenta com 55 e sem 55
    cursor.execute("SELECT id, nome, telefone, apartamento, bloco, tipo, condominio_id FROM moradores WHERE telefone = ? OR telefone LIKE ?", 
                   (tel_limpo, f"%{tel_limpo[-8:]}"))
    morador = cursor.fetchone()
    conn.close()
    return morador

def extrair_apartamento_alvo(texto: str):
    # Procura padrões como "402", "apto 302", "apartamento 101", "bloco b"
    match_ap = re.search(r"(?:ap(?:to|artamento)?\s*[:#]?\s*|no\s+)?(\d{2,4})", texto, re.IGNORECASE)
    match_bloco = re.search(r"(?:bloco|bl)\s*[:#]?\s*([a-zA-Z0-9]+)", texto, re.IGNORECASE)
    
    ap = match_ap.group(1) if match_ap else None
    bloco = match_bloco.group(1).upper() if match_bloco else "A"
    return ap, bloco

def contar_reincidencias(apartamento: str, bloco: str, condominio_id: int = 1) -> int:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
    SELECT COUNT(*) FROM ocorrencias 
    WHERE apartamento_alvo = ? AND bloco_alvo = ? AND status IN ('Aprovada', 'Notificada') AND condominio_id = ?
    """, (apartamento, bloco, condominio_id))
    total = cursor.fetchone()[0]
    conn.close()
    return total

def registrar_ocorrencia(morador_id: int, descricao: str, apartamento_alvo: str = "A Definir", bloco_alvo: str = "A", condominio_id: int = 1) -> int:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
    INSERT INTO ocorrencias (morador_id, apartamento_alvo, bloco_alvo, categoria, descricao, status, condominio_id)
    VALUES (?, ?, ?, 'Barulho', ?, 'Pendente', ?)
    """, (morador_id, apartamento_alvo, bloco_alvo, descricao, condominio_id))
    ocorrencia_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return ocorrencia_id

def verificar_status_assinatura(condominio_id: int = 1) -> dict:
    """
    Verifica se a assinatura mensal do condomínio está ativa (ciclo de 30 dias corridos).
    Se passar dos 30 dias sem pagamento, o sistema é bloqueado automaticamente.
    """
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM condominios WHERE id = ?", (condominio_id,))
    condo = cursor.fetchone()
    
    # Recupera o link da Kiwify configurado
    cursor.execute("SELECT valor FROM configuracoes WHERE chave = 'link_kiwify'")
    cfg_link = cursor.fetchone()
    link_kiwify = (cfg_link["valor"] if cfg_link else None) or "https://pay.kiwify.com.br/mByEbbl"
    conn.close()
    
    if not condo:
        return {
            "condominio_id": condominio_id,
            "ativo": False,
            "status": "inexistente",
            "motivo": "Condomínio não encontrado",
            "dias_restantes": 0,
            "plano_expira_em": None,
            "link_kiwify": link_kiwify
        }
        
    plano_expira_em = condo["plano_expira_em"] if "plano_expira_em" in condo.keys() else None
    plano_nome = condo["plano_ativo"] if "plano_ativo" in condo.keys() else "pro"
    
    if not plano_expira_em:
        return {
            "condominio_id": condo["id"],
            "nome": condo["nome"],
            "plano_ativo": plano_nome,
            "ativo": False,
            "status": "pendente_pagamento",
            "motivo": "Assinatura mensal não iniciada. Pagamento pendente.",
            "dias_restantes": 0,
            "plano_expira_em": None,
            "link_kiwify": link_kiwify
        }
        
    try:
        data_str = str(plano_expira_em).split(".")[0].replace("T", " ")
        dt_expira = datetime.strptime(data_str, "%Y-%m-%d %H:%M:%S")
        agora = datetime.now()
        
        if agora <= dt_expira:
            dias_restantes = (dt_expira - agora).days + 1
            return {
                "condominio_id": condo["id"],
                "nome": condo["nome"],
                "plano_ativo": plano_nome,
                "ativo": True,
                "status": "ativa",
                "dias_restantes": dias_restantes,
                "plano_expira_em": dt_expira.strftime("%Y-%m-%d %H:%M:%S"),
                "plano_expira_formatado": dt_expira.strftime("%d/%m/%Y"),
                "link_kiwify": link_kiwify
            }
        else:
            return {
                "condominio_id": condo["id"],
                "nome": condo["nome"],
                "plano_ativo": plano_nome,
                "ativo": False,
                "status": "expirada",
                "motivo": "Período de 30 dias corridos encerrado. Sistema aguardando renovação mensal.",
                "dias_restantes": 0,
                "plano_expira_em": dt_expira.strftime("%Y-%m-%d %H:%M:%S"),
                "plano_expira_formatado": dt_expira.strftime("%d/%m/%Y"),
                "link_kiwify": link_kiwify
            }
    except Exception as e:
        return {
            "condominio_id": condo["id"],
            "nome": condo["nome"],
            "plano_ativo": plano_nome,
            "ativo": False,
            "status": "erro_data",
            "motivo": str(e),
            "dias_restantes": 0,
            "plano_expira_em": str(plano_expira_em),
            "link_kiwify": link_kiwify
        }

def ativar_assinatura_30_dias(condominio_id: int = 1, plano_nome: str = "Condomínio Pro", dias: int = 30, conn_externa = None) -> str:
    """
    Ativa ou estende a assinatura do condomínio por 30 dias corridos a partir do pagamento.
    """
    deve_fechar = False
    if conn_externa is not None:
        conn = conn_externa
    else:
        conn = get_db()
        deve_fechar = True
        
    cursor = conn.cursor()
    
    agora = datetime.now()
    nova_expiracao = agora + timedelta(days=dias)
    str_expira = nova_expiracao.strftime("%Y-%m-%d %H:%M:%S")
    
    cursor.execute("""
    UPDATE condominios 
    SET plano_ativo = ?, plano_expira_em = ?, status_assinatura = 'ativa'
    WHERE id = ?
    """, (plano_nome, str_expira, condominio_id))
    
    conn.commit()
    if deve_fechar:
        conn.close()
    return str_expira

# --- 1. HEALTH CHECK MONITORING 24/7 (REGRA GLOBAL MANDATÓRIA) ---
@app.get("/api/health")
async def health_check():
    """
    Endpoint obrigatório de monitoramento para Render / Railway / UptimeRobot.
    """
    uptime = int(time.time() - START_TIME)
    return {
        "status": "ok",
        "app": "ConciliaZap - Gestão de Conflitos e Condomínio 24/7",
        "version": "2.0.0",
        "uptime_seconds": uptime,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

# --- 2. WEBHOOK WHATSAPP & PROCESSAMENTO AUTÔNOMO ---
@app.post("/webhook/whatsapp")
@app.post("/api/webhook/whatsapp")
async def processar_mensagem_whatsapp(request: Request):
    """
    Processador autônomo e universal de mensagens WhatsApp recebidas da Evolution API / Z-API.
    Identifica o morador, seu condomínio (multiempresa), detecta a intenção
    (Barulho/Conflito, Reservas, Achados, Regras) e executa o fluxo automatizado sem atrito.
    """
    try:
        body = await request.json()
    except Exception:
        body = {}
        
    msg_id, sender_phone, texto_raw = extrair_dados_mensagem(body)
    telefone_limpo = sanitizar_telefone(sender_phone)
    morador = buscar_morador_por_telefone(telefone_limpo)
    
    if not morador:
        return {
            "status": "unauthorized",
            "reply": "🔒 *ConciliaZap Portaria Digital*\n\nOlá! Não identificamos seu número no cadastro ativo deste condomínio.\n\nPor favor, envie seu nome completo, bloco e apartamento para a administração atualizar seu cadastro oficial."
        }
        
    morador_id = morador["id"]
    nome = morador["nome"]
    ap = morador["apartamento"]
    bloco = morador["bloco"]
    condo_id = morador["condominio_id"] if "condominio_id" in morador.keys() else 1
    
    # Validação da Assinatura Mensal de 30 Dias Corridos do Condomínio
    status_sub = verificar_status_assinatura(condo_id)
    if not status_sub["ativo"]:
        link_pgto = status_sub.get("link_kiwify") or "https://pay.kiwify.com.br/mByEbbl"
        dt_venc = status_sub.get("plano_expira_formatado") or "período recente"
        return {
            "status": "subscription_expired",
            "reply": (
                "⚠️ *ConciliaZap — Assinatura Mensal Expirada*\n\n"
                f"Olá {nome}! O sistema deste condomínio teve o ciclo de 30 dias corridos encerrado em *{dt_venc}* e as funções automatizadas estão temporariamente suspensas.\n\n"
                f"Para reativar o ConciliaZap imediatamente por mais 30 dias, a administração deve efetuar o pagamento mensal na Kiwify:\n"
                f"👉 {link_pgto}\n\n"
                f"Após a confirmação do pagamento, o robô é reativado automaticamente 24/7."
            )
        }
    
    texto = (texto_raw or "").strip()
    texto_lower = texto.lower()
    
    # 1. FLUXO DE CONFLITO E BARULHO (MODERAÇÃO SEM ATRITO)
    palavras_barulho = ["barulho", "ruido", "ruído", "som alto", "furadeira", "festa", "grito", "obra", "som", "gritaria", "latido"]
    if any(p in texto_lower for p in palavras_barulho):
        ap_alvo, bloco_alvo = extrair_apartamento_alvo(texto)
        if not ap_alvo:
            ap_alvo = "A Definir"
            
        ocorrencia_id = registrar_ocorrencia(morador_id, texto, ap_alvo, bloco_alvo, condo_id)
        
        return {
            "status": "occurrence_created",
            "ocorrencia_id": ocorrencia_id,
            "condominio_id": condo_id,
            "reply": (
                f"⚖️ *Ocorrência #{ocorrencia_id} Registrada com Sucesso!*\n\n"
                f"Olá {nome} (Ap {ap}-{bloco}). Identificamos seu registro referente à perturbação no apartamento {ap_alvo} (Bloco {bloco_alvo}).\n\n"
                f"🛡️ *Garantia de Impessoalidade:*\n"
                f"Seu nome permanece estritamente sigiloso. O caso foi encaminhado ao Painel de Moderação do Síndico.\n\n"
                f"📎 *Evidência:* Se tiver áudio ou vídeo do barulho, envie como resposta neste chat para anexarmos ao laudo da administração."
            )
        }
        
    # 2. FLUXO DE RESERVAS DE ÁREAS COMUNS
    if any(p in texto_lower for p in ["reserva", "salao", "salão", "churrasqueira", "quadra"]):
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT area, data_reserva, periodo FROM reservas WHERE condominio_id = ? AND date(data_reserva) >= date('now') ORDER BY data_reserva ASC LIMIT 3", (condo_id,))
        proximas = cursor.fetchall()
        conn.close()
        
        lista_reservas = "\n".join([f"• {r['area']} em {r['data_reserva']} ({r['periodo']})" for r in proximas]) or "Nenhuma reserva ativa nos próximos dias."
        
        return {
            "status": "reservation_info",
            "reply": (
                f"🎉 *Reserva de Áreas Comuns - {nome}*\n\n"
                f"Áreas disponíveis para locação:\n"
                f"1. Salão de Festas Climatizado\n"
                f"2. Espaço Gourmet com Churrasqueira\n"
                f"3. Quadra Poliesportiva\n\n"
                f"📅 *Próximos agendamentos confirmados:*\n{lista_reservas}\n\n"
                f"Para solicitar sua reserva, acesse o painel ou envie: 'Reservar Churrasqueira em DD/MM/AAAA'."
            )
        }

    # 3. FLUXO DE ACHADOS E PERDIDOS
    if any(p in texto_lower for p in ["achado", "perdido", "perdi", "encontrei", "chave", "carteira", "objeto"]):
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT id, item, local_encontrado, data_registro FROM achados_perdidos WHERE condominio_id = ? AND status = 'Disponível' ORDER BY id DESC LIMIT 4", (condo_id,))
        itens = cursor.fetchall()
        conn.close()
        
        lista_itens = "\n".join([f"• Item #{i['id']}: *{i['item']}* (Local: {i['local_encontrado']})" for i in itens]) or "Nenhum item pendente na portaria no momento."
        
        return {
            "status": "lost_found",
            "reply": (
                f"📦 *Achados & Perdidos da Portaria*\n\n"
                f"Itens aguardando retirada pelo proprietário:\n{lista_itens}\n\n"
                f"Para retirar seu item, compareça à portaria munido de identificação do seu apartamento {ap}-{bloco}."
            )
        }

    # 4. REGIMENTO INTERNO E NORMAS
    if any(p in texto_lower for p in ["regimento", "regra", "regras", "horario", "horário", "silencio", "silêncio"]):
        return {
            "status": "rules",
            "reply": (
                f"📖 *Regimento Interno e Regras de Convivência*\n\n"
                f"⏰ *Horário de Silêncio:* Obrigatório das 22h00 às 08h00 todos os dias.\n"
                f"🔨 *Obras e Reformas:* Permitidas de Seg a Sex das 08h00 às 17h00 (Sábados até as 12h00).\n"
                f"🐶 *Animais de Estimação:* Devem circular em guias adequadas nas áreas sociais.\n"
                f"🗑️ *Descarte de Lixo:* Utilizar as lixeiras seletivas no subsolo até as 20h.\n\n"
                f"Dúvidas adicionais podem ser consultadas diretamente com a administração."
            )
        }

    # 5. MENU PRINCIPAL DE AUTOATENDIMENTO (DEFAULT)
    return {
        "status": "menu",
        "reply": (
            f"🏢 *ConciliaZap - Condomínio Inteligente*\n"
            f"Olá, *{nome}* (Apto {ap} - Bloco {bloco})!\n\n"
            f"Como podemos te ajudar hoje?\n\n"
            f"1️⃣ *Barulho:* Digite 'Barulho no [apto]' para registrar perturbação de forma 100% anônima.\n"
            f"2️⃣ *Reservas:* Digite 'Reserva' para consultar disponibilidade do salão ou churrasqueira.\n"
            f"3️⃣ *Achados:* Digite 'Achados' para verificar itens guardados na portaria.\n"
            f"4️⃣ *Regimento:* Digite 'Regras' para consultar os horários de silêncio e regulamentos."
        )
    }

# --- 3. SIMULADOR DE WHATSAPP PARA TESTES NO NAVEGADOR ---
@app.post("/api/simulador/enviar")
async def simular_envio_whatsapp(request: Request):
    """
    Permite testar o fluxo completo de atendimento e moderação direto do navegador
    sem precisar de celular ou API externa conectada.
    """
    resposta = await processar_mensagem_whatsapp(request)
    return resposta

# --- 4. GESTÃO DE OCORRÊNCIAS & PAINEL DO SÍNDICO ---
@app.get("/api/ocorrencias")
async def listar_ocorrencias(status: Optional[str] = None, condominio_id: Optional[int] = None):
    conn = get_db()
    cursor = conn.cursor()
    query = """
    SELECT o.*, m.nome as denunciante_nome, m.apartamento as denunciante_ap, m.bloco as denunciante_bloco, m.telefone as denunciante_tel
    FROM ocorrencias o
    JOIN moradores m ON o.morador_id = m.id
    WHERE 1=1
    """
    params = []
    if condominio_id:
        query += " AND o.condominio_id = ?"
        params.append(condominio_id)
    if status and status != "Todas":
        query += " AND o.status = ?"
        params.append(status)
    query += " ORDER BY o.id DESC"
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    
    lista = []
    for r in rows:
        cid = r["condominio_id"] if "condominio_id" in r.keys() else 1
        reincidencias = contar_reincidencias(r["apartamento_alvo"], r["bloco_alvo"], cid)
        item = dict(r)
        item["reincidencias_infrator"] = reincidencias
        lista.append(item)
    return lista

@app.post("/api/ocorrencias/{ocorrencia_id}/moderar")
async def moderar_ocorrencia(ocorrencia_id: int, decisao: OcorrenciaDecisao):
    """
    Ação de 1 clique do Síndico: Homologa o envio de Notificação/Advertência/Multa
    ou Rejeita/Arquiva a queixa, despersonalizando o conflito.
    """
    # Validações de limites e segurança (OWASP Input Validation)
    if decisao.status not in ["Aprovada", "Rejeitada", "Arquivada", "Pendente"]:
        raise HTTPException(status_code=400, detail="Status de moderação inválido. Valores aceitos: Aprovada, Rejeitada, Arquivada, Pendente.")
    if decisao.penalidade and decisao.penalidade not in ["Aviso Amigável", "Advertência Formal", "Multa", "Nenhuma"]:
        raise HTTPException(status_code=400, detail="Penalidade inválida.")
    if decisao.valor_multa is not None and (decisao.valor_multa < 0.0 or decisao.valor_multa > 50000.0):
        raise HTTPException(status_code=400, detail="Valor da multa deve estar entre R$ 0,00 e R$ 50.000,00.")
    if decisao.motivo and len(decisao.motivo) > 1000:
        raise HTTPException(status_code=400, detail="Parecer do síndico não pode exceder 1.000 caracteres.")

    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("SELECT o.*, m.nome as denunciante_nome FROM ocorrencias o JOIN moradores m ON o.morador_id = m.id WHERE o.id = ?", (ocorrencia_id,))
    ocorrencia = cursor.fetchone()
    if not ocorrencia:
        conn.close()
        raise HTTPException(status_code=404, detail="Ocorrência não encontrada.")
        
    agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute("""
    UPDATE ocorrencias 
    SET status = ?, decisao_sindico = ?, penalidade = ?, valor_multa = ?, notificacao_enviada = 1, resolvido_em = ?
    WHERE id = ?
    """, (decisao.status, decisao.motivo, decisao.penalidade, decisao.valor_multa, agora, ocorrencia_id))
    conn.commit()
    conn.close()
    
    # Texto automatizado enviado ao WhatsApp do infrator caso aprovada
    mensagem_notificacao = ""
    if decisao.status == "Aprovada":
        if decisao.penalidade == "Multa":
            mensagem_notificacao = (
                f"🚨 *NOTIFICAÇÃO FORMAL DE MULTA CONDOMINIAL*\n"
                f"Prezado morador da unidade {ocorrencia['apartamento_alvo']} (Bloco {ocorrencia['bloco_alvo']}),\n\n"
                f"Devido à reincidência em ruídos excessivos fora do horário permitido, conforme Art. 42 do Regimento Interno, "
                f"foi homologada multa administrativa no valor de R$ {decisao.valor_multa:.2f}.\n\n"
                f"O boleto e o laudo formal foram anexados à sua cota condominial."
            )
        elif decisao.penalidade == "Advertência Formal":
            mensagem_notificacao = (
                f"⚠️ *ADVERTÊNCIA CONDOMINIAL ADMINISTRATIVA*\n"
                f"Prezado morador da unidade {ocorrencia['apartamento_alvo']} (Bloco {ocorrencia['bloco_alvo']}),\n\n"
                f"Constatamos registro formal de perturbação do sossego ({ocorrencia['descricao']}). "
                f"Solicitamos a cessação imediata para evitar a aplicação de sanções pecuniárias."
            )
        else:
            mensagem_notificacao = (
                f"🔔 *Aviso Amigável de Convivência*\n"
                f"Olá morador do apto {ocorrencia['apartamento_alvo']}! Recebemos um aviso interno da vizinhança sobre sons/ruídos no momento. "
                f"Contamos com sua colaboração para manter o bem-estar de todos no condomínio. Obrigado!"
            )
            
    return {
        "status": "success",
        "ocorrencia_id": ocorrencia_id,
        "decisao": decisao.status,
        "penalidade": decisao.penalidade,
        "mensagem_robô_enviada": mensagem_notificacao
    }

# --- 5. GERAÇÃO DE LAUDO / ADVERTÊNCIA FORMAL EM FORMATO IMPRESSÃO / PDF ---
@app.get("/api/ocorrencias/{ocorrencia_id}/laudo-html", response_class=HTMLResponse)
async def gerar_laudo_formal_html(ocorrencia_id: int):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
    SELECT o.*, m.nome as denunciante_nome, m.apartamento as denunciante_ap, m.bloco as denunciante_bloco
    FROM ocorrencias o
    JOIN moradores m ON o.morador_id = m.id
    WHERE o.id = ?
    """, (ocorrencia_id,))
    oc = cursor.fetchone()
    conn.close()
    
    if not oc:
        raise HTTPException(status_code=404, detail="Ocorrência não encontrada")
        
    # Sanitização anti-XSS de dados dinâmicos exibidos no documento
    safe_ap = html.escape(str(oc['apartamento_alvo'] or ''))
    safe_bloco = html.escape(str(oc['bloco_alvo'] or ''))
    safe_data_hora = html.escape(str(oc['data_hora'] or ''))
    safe_categoria = html.escape(str(oc['categoria'] or ''))
    safe_descricao = html.escape(str(oc['descricao'] or ''))
    safe_penalidade = html.escape(str(oc['penalidade'] or ''))
    safe_decisao = html.escape(str(oc['decisao_sindico'] or 'Aprovado envio de notificação formal conforme regimento.'))
    valor_multa = float(oc['valor_multa'] or 0.0)

    html_content = f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <title>Notificação Formal #{oc['id']} - ConciliaZap</title>
    <style>
        body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; padding: 40px; color: #1e293b; background: #fff; }}
        .header {{ border-bottom: 2px solid #0284c7; padding-bottom: 15px; margin-bottom: 25px; display: flex; justify-content: space-between; align-items: center; }}
        .title {{ font-size: 24px; font-weight: bold; color: #0f172a; }}
        .badge {{ background: #0284c7; color: #fff; padding: 6px 14px; border-radius: 6px; font-size: 13px; font-weight: bold; }}
        .field-group {{ margin-bottom: 16px; }}
        .label {{ font-size: 12px; font-weight: bold; text-transform: uppercase; color: #64748b; }}
        .value {{ font-size: 16px; margin-top: 4px; }}
        .box {{ background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 18px; margin: 20px 0; }}
        .footer {{ margin-top: 50px; border-top: 1px solid #cbd5e1; padding-top: 20px; font-size: 12px; color: #64748b; text-align: center; }}
        @media print {{ body {{ padding: 0; }} .btn-print {{ display: none; }} }}
    </style>
</head>
<body>
    <div style="text-align: right; margin-bottom: 20px;">
        <button class="btn-print" onclick="window.print()" style="background: #0284c7; color: white; border: none; padding: 10px 20px; border-radius: 6px; cursor: pointer; font-weight: bold;">🖨️ Imprimir / Salvar PDF</button>
    </div>
    <div class="header">
        <div>
            <div class="title">CONDOMÍNIO RESIDENCIAL JARDINS</div>
            <div style="font-size: 14px; color: #64748b;">Notificação e Auto de Infração Administrativa</div>
        </div>
        <div class="badge">PROCESSO #{oc['id']:04d}</div>
    </div>
    
    <div class="box">
        <div class="field-group">
            <div class="label">Unidade Notificada</div>
            <div class="value"><strong>Apartamento {safe_ap} - Bloco {safe_bloco}</strong></div>
        </div>
        <div class="field-group">
            <div class="label">Data e Hora do Registro</div>
            <div class="value">{safe_data_hora}</div>
        </div>
        <div class="field-group">
            <div class="label">Natureza da Infração</div>
            <div class="value">{safe_categoria} (Regimento Interno - Cláusula de Convivência & Sossego)</div>
        </div>
        <div class="field-group">
            <div class="label">Descrição do Fato Conflituoso</div>
            <div class="value" style="font-style: italic;">"{safe_descricao}"</div>
        </div>
    </div>
    
    <div class="box" style="border-left: 4px solid #0284c7;">
        <div class="field-group">
            <div class="label">Sanção Aplicada pela Administração</div>
            <div class="value"><strong style="color: #b91c1c; font-size: 18px;">{safe_penalidade}</strong></div>
        </div>
        <div class="field-group">
            <div class="label">Parecer do Síndico / Moderador</div>
            <div class="value">{safe_decisao}</div>
        </div>
        {f'<div class="field-group"><div class="label">Valor da Sanção Pecuniária</div><div class="value"><strong>R$ {valor_multa:.2f}</strong></div></div>' if valor_multa > 0 else ''}
    </div>
    
    <div style="margin-top: 40px; font-size: 14px; line-height: 1.6; color: #334155;">
        <p>Esta notificação foi homologada via <strong>ConciliaZap</strong>, sistema autônomo de gestão condominial com auditoria de registros. A preservação da identidade das partes garante a imparcialidade e o cumprimento dos Arts. 1.336 e 1.337 do Código Civil Brasileiro.</p>
    </div>
    
    <div class="footer">
        Condomínio Residencial Jardins • Sistema ConciliaZap 24/7 • Emissão em {datetime.now().strftime("%d/%m/%Y às %H:%M:%S")}
    </div>
</body>
</html>"""
    return HTMLResponse(content=html_content)
    return HTMLResponse(content=html)

# --- 6. GESTÃO DE MORADORES E IMPORTAÇÃO EM LOTE ---
@app.get("/api/moradores")
async def listar_moradores(condominio_id: Optional[int] = None):
    conn = get_db()
    cursor = conn.cursor()
    if condominio_id:
        cursor.execute("SELECT * FROM moradores WHERE condominio_id = ? ORDER BY bloco ASC, apartamento ASC", (condominio_id,))
    else:
        cursor.execute("SELECT * FROM moradores ORDER BY bloco ASC, apartamento ASC")
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

@app.post("/api/moradores")
async def cadastrar_morador(m: MoradorCreate, request: Request):
    user_role = request.headers.get("X-User-Role", "sindico").lower()
    if user_role not in ["sindico", "administrador", "admin"]:
        raise HTTPException(status_code=403, detail="Apenas síndicos ou administradores têm permissão para cadastrar moradores.")
        
    if not m.nome or len(m.nome.strip()) < 2 or len(m.nome) > 150:
        raise HTTPException(status_code=422, detail="Nome do morador deve conter entre 2 e 150 caracteres.")
    if not m.apartamento or len(m.apartamento.strip()) < 1 or len(m.apartamento) > 20:
        raise HTTPException(status_code=422, detail="Apartamento deve conter entre 1 e 20 caracteres.")
    if not m.bloco or len(m.bloco.strip()) < 1 or len(m.bloco) > 20:
        raise HTTPException(status_code=422, detail="Bloco deve conter entre 1 e 20 caracteres.")

    tel_limpo = sanitizar_telefone(m.telefone)
    condo_id = m.condominio_id or 1
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("""
        INSERT INTO moradores (nome, telefone, apartamento, bloco, tipo, condominio_id)
        VALUES (?, ?, ?, ?, ?, ?)
        """, (m.nome, tel_limpo, m.apartamento, m.bloco.upper(), m.tipo, condo_id))
        novo_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return {"status": "success", "id": novo_id, "mensagem": "Morador cadastrado com sucesso!"}
    except sqlite3.IntegrityError:
        conn.close()
        raise HTTPException(status_code=400, detail="Este telefone já se encontra cadastrado em outra unidade.")

@app.put("/api/moradores/{morador_id}")
async def editar_morador(morador_id: int, m: MoradorUpdate, request: Request):
    user_role = request.headers.get("X-User-Role", "sindico").lower()
    if user_role not in ["sindico", "administrador", "admin"]:
        raise HTTPException(status_code=403, detail="Apenas síndicos ou administradores têm permissão para editar moradores.")
        
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM moradores WHERE id = ?", (morador_id,))
    morador = cursor.fetchone()
    if not morador:
        conn.close()
        raise HTTPException(status_code=404, detail="Morador não encontrado.")
        
    novo_nome = m.nome if m.nome is not None else morador["nome"]
    novo_tel = sanitizar_telefone(m.telefone) if m.telefone is not None else morador["telefone"]
    novo_ap = m.apartamento if m.apartamento is not None else morador["apartamento"]
    novo_bloco = m.bloco.upper() if m.bloco is not None else morador["bloco"]
    novo_tipo = m.tipo if m.tipo is not None else morador["tipo"]
    novo_condo = m.condominio_id if m.condominio_id is not None else (morador["condominio_id"] if "condominio_id" in morador.keys() else 1)
    
    try:
        cursor.execute("""
        UPDATE moradores 
        SET nome = ?, telefone = ?, apartamento = ?, bloco = ?, tipo = ?, condominio_id = ?
        WHERE id = ?
        """, (novo_nome, novo_tel, novo_ap, novo_bloco, novo_tipo, novo_condo, morador_id))
        conn.commit()
        conn.close()
        return {"status": "success", "mensagem": "Dados do morador atualizados com sucesso!"}
    except sqlite3.IntegrityError:
        conn.close()
        raise HTTPException(status_code=400, detail="Este telefone já está cadastrado em outra unidade.")

@app.post("/admin/moradores")
async def cadastrar_morador_teste(
    nome: Optional[str] = Query(None), 
    telefone: Optional[str] = Query(None), 
    apartamento: Optional[str] = Query(None), 
    bloco: Optional[str] = Query(None),
    body: Optional[MoradorCreate] = Body(None)
):
    """
    Rota de apoio administrativo / testes que aceita tanto Query Params quanto JSON Body.
    """
    final_nome = (body.nome if body else None) or nome
    final_tel = (body.telefone if body else None) or telefone
    final_ap = (body.apartamento if body else None) or apartamento
    final_bloco = (body.bloco if body else None) or bloco
    final_condo = (body.condominio_id if body and body.condominio_id else 1)
    
    if not all([final_nome, final_tel, final_ap, final_bloco]):
        raise HTTPException(status_code=422, detail="Campos nome, telefone, apartamento e bloco são obrigatórios.")
        
    if len(final_nome.strip()) < 2 or len(final_nome) > 150:
        raise HTTPException(status_code=422, detail="Nome do morador deve conter entre 2 e 150 caracteres.")
    if len(final_ap.strip()) < 1 or len(final_ap) > 20:
        raise HTTPException(status_code=422, detail="Apartamento deve conter entre 1 e 20 caracteres.")
    if len(final_bloco.strip()) < 1 or len(final_bloco) > 20:
        raise HTTPException(status_code=422, detail="Bloco deve conter entre 1 e 20 caracteres.")
        
    tel_limpo = sanitizar_telefone(final_tel)
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO moradores (nome, telefone, apartamento, bloco, tipo, condominio_id) VALUES (?, ?, ?, ?, 'morador', ?)", 
                       (final_nome, tel_limpo, final_ap, final_bloco.upper(), final_condo))
        conn.commit()
        conn.close()
        return {"status": "Morador cadastrado com sucesso!"}
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=400, detail="Este telefone já está cadastrado.")

@app.delete("/api/moradores/{morador_id}")
async def deletar_morador(morador_id: int, request: Request):
    user_role = request.headers.get("X-User-Role", "sindico").lower()
    if user_role not in ["sindico", "administrador", "admin"]:
        raise HTTPException(status_code=403, detail="Apenas síndicos ou administradores têm permissão para remover moradores.")
        
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM moradores WHERE id = ?", (morador_id,))
    conn.commit()
    conn.close()
    return {"status": "success", "mensagem": "Morador excluído do sistema."}

@app.post("/api/moradores/importar-lote")
async def importar_moradores_lote(lista: List[MoradorCreate]):
    conn = get_db()
    cursor = conn.cursor()
    importados = 0
    ignorados = 0
    for m in lista:
        tel_limpo = sanitizar_telefone(m.telefone)
        try:
            cursor.execute("""
            INSERT INTO moradores (nome, telefone, apartamento, bloco, tipo)
            VALUES (?, ?, ?, ?, ?)
            """, (m.nome, tel_limpo, m.apartamento, m.bloco.upper(), m.tipo))
            importados += 1
        except sqlite3.IntegrityError:
            ignorados += 1
    conn.commit()
    conn.close()
    return {"status": "success", "importados": importados, "ignorados": ignorados}

# --- 7. ÁREAS COMUNS E RESERVAS ---
@app.get("/api/reservas")
async def listar_reservas(condominio_id: Optional[int] = None):
    conn = get_db()
    cursor = conn.cursor()
    query = """
    SELECT r.*, m.nome as morador_nome, m.apartamento, m.bloco, m.telefone
    FROM reservas r
    JOIN moradores m ON r.morador_id = m.id
    """
    params = []
    if condominio_id:
        query += " WHERE r.condominio_id = ?"
        params.append(condominio_id)
    query += " ORDER BY r.data_reserva ASC"
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

@app.post("/api/reservas")
async def criar_reserva(reserva: ReservaCreate):
    # Validação de limites (OWASP Input Validation)
    if not reserva.area or len(reserva.area.strip()) < 2 or len(reserva.area) > 100:
        raise HTTPException(status_code=422, detail="Nome da área comum deve ter entre 2 e 100 caracteres.")
    if not reserva.periodo or len(reserva.periodo.strip()) < 2 or len(reserva.periodo) > 50:
        raise HTTPException(status_code=422, detail="Período da reserva deve ter entre 2 e 50 caracteres.")

    conn = get_db()
    cursor = conn.cursor()
    
    # 1. Valida se o morador existe
    cursor.execute("SELECT id, condominio_id FROM moradores WHERE id = ?", (reserva.morador_id,))
    morador = cursor.fetchone()
    if not morador:
        conn.close()
        raise HTTPException(status_code=404, detail="Morador não encontrado.")
        
    condo_id = reserva.condominio_id or (morador["condominio_id"] if "condominio_id" in morador.keys() else 1)
    
    # 2. Prevenção de conflito de agenda (Item 4 do checklist)
    cursor.execute("""
    SELECT id, morador_id FROM reservas 
    WHERE area = ? AND data_reserva = ? AND periodo = ? AND status = 'Confirmada' AND condominio_id = ?
    """, (reserva.area, reserva.data_reserva, reserva.periodo, condo_id))
    conflito = cursor.fetchone()
    if conflito:
        conn.close()
        raise HTTPException(
            status_code=409, 
            detail=f"Conflito de agenda: A área '{reserva.area}' já está reservada para o período '{reserva.periodo}' em {reserva.data_reserva}."
        )
        
    cursor.execute("""
    INSERT INTO reservas (morador_id, area, data_reserva, periodo, status, condominio_id)
    VALUES (?, ?, ?, ?, 'Confirmada', ?)
    """, (reserva.morador_id, reserva.area, reserva.data_reserva, reserva.periodo, condo_id))
    reserva_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return {"status": "success", "id": reserva_id, "mensagem": "Reserva confirmada com sucesso!"}

@app.delete("/api/reservas/{reserva_id}")
async def cancelar_reserva(reserva_id: int):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM reservas WHERE id = ?", (reserva_id,))
    conn.commit()
    conn.close()
    return {"status": "success", "mensagem": "Reserva cancelada."}

# --- 8. ACHADOS E PERDIDOS ---
@app.get("/api/achados")
async def listar_achados():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM achados_perdidos ORDER BY id DESC")
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

@app.post("/api/achados")
async def registrar_achado(achado: AchadoCreate):
    # Validação de limites (OWASP Input Validation)
    if not achado.item or len(achado.item.strip()) < 2 or len(achado.item) > 150:
        raise HTTPException(status_code=422, detail="Descrição do item deve conter entre 2 e 150 caracteres.")
    if not achado.local_encontrado or len(achado.local_encontrado.strip()) < 2 or len(achado.local_encontrado) > 150:
        raise HTTPException(status_code=422, detail="Local encontrado deve conter entre 2 e 150 caracteres.")

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
    INSERT INTO achados_perdidos (item, local_encontrado, status)
    VALUES (?, ?, 'Disponível')
    """, (achado.item, achado.local_encontrado))
    item_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return {"status": "success", "id": item_id, "mensagem": "Item registrado em Achados e Perdidos!"}

@app.put("/api/achados/{item_id}/devolver")
async def devolver_achado(item_id: int, devolvido_para: str = Body(..., embed=True)):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
    UPDATE achados_perdidos SET status = 'Devolvido', devolvido_para = ? WHERE id = ?
    """, (devolvido_para, item_id))
    conn.commit()
    conn.close()
    return {"status": "success", "mensagem": "Item marcado como devolvido."}

# --- 9. MONETIZAÇÃO SAAS E PIX NATIVO EMV (BANCO CENTRAL) ---
@app.get("/api/planos")
async def listar_planos():
    return [
        {
            "id": "starter",
            "nome": "Condomínio Starter (Até 40 Unidades)",
            "preco": 99.00,
            "periodo": "mês",
            "recursos": ["Bot WhatsApp 24/7", "Moderação com 1 Clique", "Ocorrências Ilimitadas", "Suporte WhatsApp"]
        },
        {
            "id": "pro",
            "nome": "Condomínio Pro (Até 150 Unidades)",
            "preco": 199.00,
            "periodo": "mês",
            "recursos": ["Tudo do Starter", "Módulo de Áreas Comuns", "Achados e Perdidos", "Laudos em PDF", "Painel Síndico Completo"]
        },
        {
            "id": "enterprise",
            "nome": "Condomínio Master / Administradoras",
            "preco": 399.00,
            "periodo": "mês",
            "recursos": ["Múltiplas Torres", "Unidades Ilimitadas", "API Evolution Dedicada", "Relatórios Financeiros", "SLA 99.9%"]
        }
    ]

@app.post("/api/pix/gerar")
async def gerar_pix_cobranca(req: PixRequest):
    """
    Gera o código Copia-e-Cola PIX oficial (EMV Bacen) e URL de QR Code dinâmico,
    além de suportar métodos adicionais (Kiwify Checkout, Boleto Bancário, Link de Cartão e Contato Comercial).
    """
    if req.valor <= 0.0 or req.valor > 100000.0:
        raise HTTPException(status_code=400, detail="Valor de cobrança deve ser maior que R$ 0,00 e até R$ 100.000,00.")

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT chave, valor FROM configuracoes WHERE chave IN ('chave_pix', 'nome_recebedor', 'cidade_recebedor', 'link_cartao', 'whatsapp_vendas', 'link_kiwify')")
    configs = {r["chave"]: r["valor"] for r in cursor.fetchall()}
    
    chave_final = configs.get("chave_pix") or req.chave_pix or "luciano@conciliazap.com.br"
    nome_final = configs.get("nome_recebedor") or req.nome_recebedor or "Luciano"
    cidade_final = configs.get("cidade_recebedor") or req.cidade or "SAO PAULO"
    link_cartao = configs.get("link_cartao") or "https://mpago.la/pos/conciliazap"
    link_kiwify = configs.get("link_kiwify") or "https://pay.kiwify.com.br/mByEbbl"
    whatsapp_vendas = configs.get("whatsapp_vendas") or "5511999998888"
    
    txid = f"CONCILIA{int(time.time())}{os.urandom(2).hex().upper()}"
    payload_emv = pix.gerar_pix_copia_e_cola(
        chave_pix=chave_final,
        nome_recebedor=nome_final,
        cidade=cidade_final,
        valor=req.valor,
        txid=txid[:25]
    )
    qr_code_url = pix.gerar_url_qr_code(payload_emv)
    condo_id = req.condominio_id or 1
    
    boleto_linha = pix.gerar_linha_digitavel_boleto(req.valor, txid)
    msg_zap = f"Olá Luciano! Gostaria de contratar a assinatura do plano *{req.plano_nome}* (R$ {req.valor:.2f}) para o meu condomínio."
    zap_url = f"https://wa.me/{whatsapp_vendas}?text={urllib.parse.quote(msg_zap)}"
    
    cursor.execute("""
    INSERT INTO cobrancas_pix (txid, condominio_id, plano, valor, status, pix_copia_e_cola, qr_code_url)
    VALUES (?, ?, ?, ?, 'PENDENTE', ?, ?)
    """, (txid, condo_id, req.plano_nome, req.valor, payload_emv, qr_code_url))
    conn.commit()
    conn.close()
    
    return {
        "status": "success",
        "txid": txid,
        "plano": req.plano_nome,
        "valor": req.valor,
        "pix_copia_e_cola": payload_emv,
        "qr_code_url": qr_code_url,
        "chave_pix": chave_final,
        "nome_recebedor": nome_final,
        "cidade": cidade_final,
        "boleto_linha": boleto_linha,
        "link_cartao": link_cartao,
        "link_kiwify": link_kiwify,
        "whatsapp_vendas": whatsapp_vendas,
        "whatsapp_link": zap_url
    }

# --- WEBHOOK OFICIAL KIWIFY ---
@app.post("/api/webhook/kiwify")
async def webhook_kiwify(request: Request):
    """
    Webhook oficial para integração com Kiwify.
    Recebe eventos de compra aprovada (order_status: 'paid' ou 'approved') e ativa o plano no condomínio.
    """
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="JSON inválido.")
        
    order_id = payload.get("order_id") or payload.get("id") or f"KIWI-{int(time.time())}"
    order_status = str(payload.get("order_status") or payload.get("status") or "").lower()
    
    prod_data = payload.get("Product")
    product_name = (prod_data.get("product_name") if isinstance(prod_data, dict) else None) or payload.get("product_name") or "Condomínio Pro"
    
    customer = payload.get("Customer") if isinstance(payload.get("Customer"), dict) else {}
    customer_name = customer.get("full_name") or payload.get("full_name") or "Cliente Kiwify"
    
    commissions = payload.get("Commissions") if isinstance(payload.get("Commissions"), dict) else {}
    charge_amount = (commissions.get("charge_amount", 0) / 100.0) if commissions.get("charge_amount") else 199.00
    
    agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = get_db()
    cursor = conn.cursor()
    
    if order_status in ["paid", "approved", "completed", "pago"]:
        expira_em = ativar_assinatura_30_dias(1, product_name, dias=30, conn_externa=conn)
        
        cursor.execute("""
        INSERT OR REPLACE INTO cobrancas_pix (txid, condominio_id, plano, valor, status, pix_copia_e_cola, qr_code_url, pago_em)
        VALUES (?, 1, ?, ?, 'PAGO', 'PAGAMENTO_VIA_KIWIFY', 'KIWIFY_CHECKOUT', ?)
        """, (order_id, product_name, charge_amount, agora))
        conn.commit()
        conn.close()
        
        return {
            "status": "success",
            "mensagem": f"Pagamento Kiwify processado com sucesso! Plano {product_name} ativado por 30 dias corridos para {customer_name}.",
            "order_id": order_id,
            "order_status": order_status,
            "plano_expira_em": expira_em,
            "dias_validade": 30
        }
    elif order_status in ["refunded", "reembolsado", "chargeback"]:
        cursor.execute("UPDATE cobrancas_pix SET status = 'REEMBOLSADO' WHERE txid = ?", (order_id,))
        ontem = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute("UPDATE condominios SET plano_ativo = 'starter', status_assinatura = 'bloqueada', plano_expira_em = ? WHERE id = 1", (ontem,))
        conn.commit()
        conn.close()
        return {
            "status": "refunded",
            "mensagem": "Reembolso Kiwify registrado. Condomínio bloqueado.",
            "order_id": order_id
        }
    else:
        conn.close()
        return {
            "status": "ignored",
            "mensagem": f"Status '{order_status}' recebido e registrado sem alteração de plano.",
            "order_id": order_id
        }

@app.post("/api/pix/confirmar")
async def confirmar_pagamento_pix(req: PixConfirmRequest):
    """
    Confirmação do pagamento PIX com garantia de IDEMPOTÊNCIA (sem duplicidade).
    Ativa o plano contratado no condomínio por 30 dias corridos.
    """
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM cobrancas_pix WHERE txid = ?", (req.txid,))
    cobranca = cursor.fetchone()
    
    if not cobranca:
        conn.close()
        raise HTTPException(status_code=404, detail="Cobrança PIX não encontrada.")
        
    if cobranca["status"] == "PAGO":
        conn.close()
        return {
            "status": "already_paid",
            "mensagem": "Pagamento já havia sido processado e confirmado anteriormente sem duplicidade.",
            "txid": req.txid,
            "plano": cobranca["plano"],
            "pago_em": cobranca["pago_em"]
        }
        
    agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute("UPDATE cobrancas_pix SET status = 'PAGO', pago_em = ? WHERE txid = ?", (agora, req.txid))
    
    condo_id = cobranca["condominio_id"] or 1
    expira_em = ativar_assinatura_30_dias(condo_id, cobranca["plano"], dias=30, conn_externa=conn)
    conn.commit()
    conn.close()
    
    return {
        "status": "confirmed",
        "mensagem": "Pagamento confirmado com sucesso! Plano liberado para o condomínio por 30 dias corridos.",
        "txid": req.txid,
        "plano": cobranca["plano"],
        "pago_em": agora,
        "plano_expira_em": expira_em
    }

# --- 9.1 GESTÃO DO PAYWALL E ASSINATURA 30 DIAS ---
@app.get("/api/assinatura/status")
async def rota_status_assinatura(condominio_id: Optional[int] = 1):
    """
    Retorna o status da assinatura de 30 dias corridos, dias restantes e data de expiração.
    """
    return verificar_status_assinatura(condominio_id or 1)

@app.post("/api/assinatura/renovar")
async def rota_renovar_assinatura(req: AssinaturaRenovacao):
    """
    Renova a assinatura do condomínio por 30 dias corridos a partir do pagamento.
    """
    expira = ativar_assinatura_30_dias(req.condominio_id or 1, req.plano or "Condomínio Pro", req.dias or 30)
    return {
        "status": "success",
        "mensagem": f"Assinatura do condomínio ativada por {req.dias or 30} dias corridos!",
        "plano_expira_em": expira
    }

@app.post("/api/assinatura/simular-expirado")
async def rota_simular_expirado(body: Optional[Dict[str, Any]] = Body(None)):
    """
    Rota de apoio a testes: expira a assinatura para validar o bloqueio total do condomínio.
    """
    cid = (body.get("condominio_id") if body else None) or 1
    conn = get_db()
    cursor = conn.cursor()
    ontem = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute("UPDATE condominios SET plano_expira_em = ?, status_assinatura = 'expirada' WHERE id = ?", (ontem, cid))
    conn.commit()
    conn.close()
    return {
        "status": "expired_simulated",
        "mensagem": "Condomínio colocado em estado EXPIRADO para teste do paywall.",
        "plano_expira_em": ontem
    }

@app.get("/api/pix/status/{txid}")
async def status_pagamento_pix(txid: str):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT txid, plano, valor, status, criado_em, pago_em FROM cobrancas_pix WHERE txid = ?", (txid,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Cobrança não encontrada.")
    return dict(row)

# --- 10. MULTIEMPRESA: GESTÃO DE CONDOMÍNIOS ---
@app.get("/api/condominios")
async def listar_condominios():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM condominios ORDER BY id ASC")
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

@app.post("/api/condominios")
async def criar_condominio(c: CondominioCreate):
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("""
        INSERT INTO condominios (nome, slug, cnpj, plano_ativo)
        VALUES (?, ?, ?, ?)
        """, (c.nome, c.slug, c.cnpj, c.plano_ativo))
        novo_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return {"status": "success", "id": novo_id, "mensagem": "Condomínio cadastrado com sucesso!"}
    except sqlite3.IntegrityError:
        conn.close()
        raise HTTPException(status_code=400, detail="Já existe um condomínio cadastrado com este slug.")

# --- 10. CONFIGURAÇÕES DO CONDOMÍNIO & WHATSAPP ---
@app.get("/api/config")
async def obter_configuracoes():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT chave, valor FROM configuracoes")
    rows = cursor.fetchall()
    conn.close()
    return {r["chave"]: r["valor"] for r in rows}

@app.post("/api/config")
async def salvar_configuracoes(dados: Dict[str, str]):
    conn = get_db()
    cursor = conn.cursor()
    for k, v in dados.items():
        cursor.execute("INSERT OR REPLACE INTO configuracoes (chave, valor) VALUES (?, ?)", (k, v))
    conn.commit()
    conn.close()
    return {"status": "success", "mensagem": "Configurações salvas!"}

# --- 11. PÁGINAS LEGAIS E CONFORMIDADE (LGPD E TERMOS) ---
@app.get("/termos", response_class=HTMLResponse)
async def pagina_termos():
    return HTMLResponse(content=obter_html_termos())

@app.get("/privacidade", response_class=HTMLResponse)
async def pagina_privacidade():
    return HTMLResponse(content=obter_html_privacidade())

def obter_html_termos() -> str:
    return """<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Termos de Uso - ConciliaZap</title>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; line-height: 1.6; max-width: 800px; margin: 40px auto; padding: 0 20px; color: #334155; }
        h1, h2 { color: #0f172a; }
        .alert { background: #fef3c7; border-left: 4px solid #f59e0b; padding: 12px; margin: 20px 0; border-radius: 4px; }
        .box { background: #f8fafc; border: 1px solid #e2e8f0; padding: 14px; border-radius: 6px; margin: 15px 0; font-size: 14px; }
        a { color: #0284c7; text-decoration: none; }
    </style>
</head>
<body>
    <a href="/">← Voltar ao Painel ConciliaZap</a>
    <h1>Termos de Uso e Condições de Serviço</h1>
    <p><em>Última atualização: Outubro de 2026 • Versão 2.0.0 Auditada</em></p>
    
    <div class="alert">
        <strong>⚠️ AVISO REGULATÓRIO E ÉTICO IMPORTANTE:</strong><br>
        O ConciliaZap é uma ferramenta tecnológica de comunicação, automação e mediação pacífica de rotina condominial. 
        Este sistema <strong>NÃO substitui autoridades policiais, judiciais ou serviços médicos/psicológicos de emergência</strong>. 
        Em caso de violência física, ameaça à vida ou crimes graves, contate imediatamente a Polícia Militar (190), SAMU (192) ou Bombeiros (193).
    </div>

    <h2>1. Objeto do Serviço</h2>
    <p>O ConciliaZap provê uma plataforma de automação de mensagens, gestão de reservas, achados e perdidos e suporte administrativo ao síndico para despersonalizar o contato e evitar atritos entre condôminos.</p>

    <h2>2. Classificação Indicativa de Idade</h2>
    <p>O serviço de envio de ocorrências é indicado para residentes a partir de <strong>16 anos</strong>. A contratação de planos comerciais, assinaturas e pagamentos financeiros é estritamente restrita a <strong>maiores de 18 anos</strong> ou legalmente representados.</p>

    <h2>3. Moderação do Síndico e Imparcialidade</h2>
    <p>Todo registro feito por morador passa por crivo e moderação humana do Síndico ou Administradora antes da expedição de advertências formais ou penalidades pecuniárias, coibindo denúncias infundadas ou trotes conforme Arts. 1.336 e 1.337 do Código Civil Brasileiro.</p>

    <h2>4. Pagamentos Seguros e Não Armazenamento de Dados de Cartão</h2>
    <p>As transações financeiras são intermediadas por gateways oficiais (Kiwify e Banco Central via PIX). O ConciliaZap <strong>não coleta nem armazena números de cartões de crédito</strong> ou senhas bancárias em seus servidores.</p>

    <h2>5. Canal de Contato e DPO</h2>
    <div class="box">
        <strong>Encarregado de Proteção de Dados (DPO):</strong> Luclen Soluções Tecnológicas Ltda<br>
        <strong>E-mail de Contato:</strong> <a href="mailto:dpo@conciliazap.com.br">dpo@conciliazap.com.br</a>
    </div>

    <h2>6. Legislação Aplicável e Foro</h2>
    <p>Estes termos regem-se pelas Leis da República Federativa do Brasil, em especial o Código Civil (Lei 10.406/2002), o Marco Civil da Internet (Lei 12.965/2014) e a LGPD (Lei 13.709/2018). Fica eleito o foro da comarca de domicílio do condomínio contratante.</p>
</body>
</html>"""

def obter_html_privacidade() -> str:
    return """<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Política de Privacidade e LGPD - ConciliaZap</title>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; line-height: 1.6; max-width: 800px; margin: 40px auto; padding: 0 20px; color: #334155; }
        h1, h2 { color: #0f172a; }
        .box { background: #f0fdf4; border: 1px solid #bbf7d0; padding: 15px; border-radius: 6px; margin: 20px 0; }
        .security-box { background: #f8fafc; border: 1px solid #cbd5e1; padding: 15px; border-radius: 6px; margin: 20px 0; font-size: 14px; }
        a { color: #0284c7; text-decoration: none; }
    </style>
</head>
<body>
    <a href="/">← Voltar ao Painel ConciliaZap</a>
    <h1>Política de Privacidade e Conformidade LGPD</h1>
    <p><em>Em estrita conformidade com a Lei Geral de Proteção de Dados (Lei nº 13.709/2018) • Versão 2.0.0</em></p>

    <div class="box">
        <strong>🔒 Princípio do Sigilo da Denúncia (Privacy by Design):</strong><br>
        O ConciliaZap foi arquitetado com privacidade desde a concepção (Privacy by Design e Privacy by Default). Quando uma notificação pacífica é enviada a uma unidade sobre barulho ou ruído, o nome e contato do morador denunciante <strong>nunca são expostos</strong> ao vizinho, resguardando a paz e a integridade de todos os moradores.
    </div>

    <h2>1. Dados Pessoais Tratados</h2>
    <p>Tratamos estritamente os dados necessários e mínimos para o cumprimento da convenção condominial:</p>
    <ul>
        <li>Nome completo do condômino ou locatário</li>
        <li>Número de telefone para comunicação via WhatsApp</li>
        <li>Identificação da unidade residencial (Apartamento e Bloco)</li>
        <li>Histórico de registros de ocorrências, reservas de áreas comuns e itens de achados e perdidos</li>
    </ul>

    <h2>2. Bases Legais de Tratamento</h2>
    <p>O tratamento de dados é realizado com base no cumprimento de obrigação legal e regulatória de gestão condominial edilícia (Art. 7º, II da LGPD) e na execução regular do contrato de convivência e regimento interno (Art. 7º, V da LGPD).</p>

    <h2>3. Direitos dos Titulares de Dados (Art. 18 da LGPD)</h2>
    <p>O titular tem pleno direito de solicitar, a qualquer momento e gratuitamente:</p>
    <ul>
        <li>Confirmação da existência de tratamento e acesso aos dados</li>
        <li>Correção de dados incompletos, inexatos ou desatualizados</li>
        <li>Anonimização, bloqueio ou eliminação de dados desnecessários</li>
        <li>Revogação do consentimento, ressalvadas as obrigações legais de guarda</li>
    </ul>

    <h2>4. Medidas Técnicas de Segurança da Informação</h2>
    <div class="security-box">
        <strong>🛡️ Padrão de Engenharia de Segurança Cibernética Ativo:</strong>
        <ul style="margin-top: 8px;">
            <li>Criptografia de tráfego ponta a ponta via HTTPS / TLS 1.3</li>
            <li>Proteção rigorosa contra Injeção de SQL (consultas 100% parametrizadas)</li>
            <li>Sanitização contra XSS (Cross-Site Scripting) em todas as exibições no navegador</li>
            <li>Rate Limiting automático para mitigação de ataques de negação de serviço (DoS/Brute-force)</li>
            <li>Cabeçalhos de proteção HTTP (X-Content-Type-Options, X-Frame-Options, X-XSS-Protection, Referrer-Policy)</li>
        </ul>
    </div>

    <h2>5. Prazo de Retenção e Descarte Seguro</h2>
    <p>Os dados cadastrais e registros de ocorrências são armazenados durante a vigência do vínculo do morador com o condomínio e pelo período prescricional legal previsto no Código Civil (5 anos), sendo após esse prazo permanentemente descartados ou anonimizados para fins estatísticos.</p>

    <h2>6. Canal do Encarregado de Dados (DPO)</h2>
    <p>Para exercer seus direitos de titular ou esclarecer dúvidas sobre a privacidade dos seus dados, entre em contato diretamente com o nosso Encarregado através do canal oficial: <a href="mailto:dpo@conciliazap.com.br"><strong>dpo@conciliazap.com.br</strong></a>.</p>
</body>
</html>"""

# --- 12. RESOLUÇÃO UNIVERSAL DE ARQUIVOS ESTÁTICOS (REGRA GLOBAL MANDATÓRIA) ---
# Suporta tanto a pasta public/ quanto a raiz do projeto e SPA fallback
CANDIDATE_DIRS = [
    os.path.join(os.path.dirname(__file__), "public"),
    os.path.dirname(__file__),
    os.path.join(os.getcwd(), "public"),
    os.getcwd()
]

# Monta arquivos estáticos caso exista pasta public
public_dir = os.path.join(os.path.dirname(__file__), "public")
if os.path.exists(public_dir):
    app.mount("/static", StaticFiles(directory=public_dir), name="static")

@app.get("/")
@app.get("/painel")
async def servir_frontend_principal():
    for base in CANDIDATE_DIRS:
        caminho_index = os.path.join(base, "index.html")
        if os.path.exists(caminho_index):
            return FileResponse(caminho_index)
            
    # Fallback se index.html ainda não existir fisicamente
    return HTMLResponse("<h1>ConciliaZap rodando! Acesse /api/health ou crie index.html</h1>")

# Fallback universal para outros arquivos estáticos requisitados
@app.get("/{caminho:path}")
async def servir_estatico_ou_spa(caminho: str):
    # Ignora rotas de API
    if caminho.startswith("api/") or caminho.startswith("webhook/"):
        raise HTTPException(status_code=404, detail="Rota de API inexistente")
        
    for base in CANDIDATE_DIRS:
        arquivo = os.path.join(base, caminho)
        if os.path.exists(arquivo) and os.path.isfile(arquivo):
            return FileResponse(arquivo)
            
    # SPA Fallback para index.html
    for base in CANDIDATE_DIRS:
        caminho_index = os.path.join(base, "index.html")
        if os.path.exists(caminho_index):
            return FileResponse(caminho_index)
            
    raise HTTPException(status_code=404, detail="Arquivo não encontrado")

if __name__ == "__main__":
    import uvicorn
    porta = int(os.environ.get("PORT", 8000))
    print(f"🚀 Iniciando ConciliaZap 24/7 na porta {porta}...")
    uvicorn.run("main:app", host="0.0.0.0", port=porta, reload=False)
