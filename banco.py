import sqlite3
import os
import sys

# Garante suporte a UTF-8 em terminais Windows (cp1252)
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

DB_NAME = "condominio.db"

def criar_tabelas():
    conexao = sqlite3.connect(DB_NAME, timeout=30.0)
    conexao.execute("PRAGMA journal_mode=WAL;")
    cursor = conexao.cursor()

    # 1. Tabela de Moradores
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS moradores (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nome TEXT NOT NULL,
        telefone TEXT UNIQUE NOT NULL,
        apartamento TEXT NOT NULL,
        bloco TEXT NOT NULL,
        tipo TEXT DEFAULT 'morador',
        criado_em DATETIME DEFAULT CURRENT_TIMESTAMP
    )""")

    # 2. Tabela de Ocorrências
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS ocorrencias (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
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
        FOREIGN KEY(morador_id) REFERENCES moradores(id)
    )""")

    # 3. Tabela de Reservas de Áreas Comuns
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS reservas (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        morador_id INTEGER NOT NULL,
        area TEXT NOT NULL,
        data_reserva TEXT NOT NULL,
        periodo TEXT NOT NULL,
        status TEXT DEFAULT 'Confirmada',
        termo_aceito INTEGER DEFAULT 1,
        criado_em DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(morador_id) REFERENCES moradores(id)
    )""")

    # 4. Tabela de Achados e Perdidos
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS achados_perdidos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        item TEXT NOT NULL,
        local_encontrado TEXT NOT NULL,
        status TEXT DEFAULT 'Disponível',
        devolvido_para TEXT,
        data_registro DATETIME DEFAULT CURRENT_TIMESTAMP
    )""")

    # 5. Tabela de Configurações
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS configuracoes (
        chave TEXT PRIMARY KEY,
        valor TEXT
    )""")

    conexao.commit()
    conexao.close()
    print("✅ Banco de dados e tabelas criados com sucesso!")

def semear_dados_iniciais():
    conexao = sqlite3.connect(DB_NAME)
    cursor = conexao.cursor()

    # Moradores de demonstração
    moradores_iniciais = [
        ("Roberto Oliveira (Síndico)", "5511999990001", "101", "A", "sindico"),
        ("Carlos Mendes", "5511999990302", "302", "A", "morador"),
        ("Marcos Souza", "5511999990402", "402", "A", "morador"),
        ("Juliana Costa", "5511999990205", "205", "B", "morador"),
        ("Fernanda Lima", "5511999990501", "501", "B", "morador"),
        ("Eduardo Rocha", "5511999990104", "104", "A", "morador")
    ]

    for nome, tel, ap, bloco, tipo in moradores_iniciais:
        cursor.execute("""
        INSERT OR IGNORE INTO moradores (nome, telefone, apartamento, bloco, tipo)
        VALUES (?, ?, ?, ?, ?)
        """, (nome, tel, ap, bloco, tipo))

    # Ocorrência inicial de exemplo
    cursor.execute("SELECT COUNT(*) FROM ocorrencias")
    if cursor.fetchone()[0] == 0:
        cursor.execute("""
        INSERT INTO ocorrencias (morador_id, apartamento_alvo, bloco_alvo, categoria, descricao, status, penalidade)
        VALUES (2, '402', 'A', 'Barulho', 'Barulho de obra e som excessivo no 402 após as 22h.', 'Pendente', 'Nenhuma')
        """)

    # Reserva inicial de exemplo
    cursor.execute("SELECT COUNT(*) FROM reservas")
    if cursor.fetchone()[0] == 0:
        cursor.execute("""
        INSERT INTO reservas (morador_id, area, data_reserva, periodo, status)
        VALUES (4, 'Salão de Festas', '2026-11-15', 'Noite (18h às 23h)', 'Confirmada')
        """)

    # Achados e perdidos exemplo
    cursor.execute("SELECT COUNT(*) FROM achados_perdidos")
    if cursor.fetchone()[0] == 0:
        cursor.execute("""
        INSERT INTO achados_perdidos (item, local_encontrado, status)
        VALUES ('Chaveiro com controle de portão', 'Garagem Subsolo 1 (próximo à vaga 22)', 'Disponível')
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

    conexao.commit()
    conexao.close()
    print("🌱 Dados de demonstração semeados com sucesso!")

if __name__ == "__main__":
    criar_tabelas()
    semear_dados_iniciais()
