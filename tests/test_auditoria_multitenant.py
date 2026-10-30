import unittest
import json
import sqlite3
import sys
import os
from datetime import datetime, timedelta

# Garante import do main
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from fastapi.testclient import TestClient
from main import app, get_db, inicializar_banco

client = TestClient(app)

class TestAuditoriaMultiTenant(unittest.TestCase):
    """
    Suíte de Testes Formais de Arquitetura Multi-Tenant e Modelo Comercial Exclusivo por Condomínio
    Garante a conformidade dos 10 Cenários Obrigatórios de Auditoria.
    """

    @classmethod
    def setUpClass(cls):
        inicializar_banco()
        conn = get_db()
        cursor = conn.cursor()
        
        # Garante a existência dos dois condomínios de auditoria
        cursor.execute("SELECT id FROM condominios WHERE id = 1")
        if not cursor.fetchone():
            cursor.execute("INSERT INTO condominios (id, nome, slug, plano_ativo, status_assinatura) VALUES (1, 'Condomínio Colinas de Campo Grande', 'colinas', 'pro', 'ativa')")
            
        cursor.execute("SELECT id FROM condominios WHERE id = 2")
        if not cursor.fetchone():
            cursor.execute("INSERT INTO condominios (id, nome, slug, plano_ativo, status_assinatura) VALUES (2, 'Condomínio Solar das Palmeiras', 'palmeiras', 'starter', 'ativa')")
            
        # Garante moradores em ambos os condomínios
        cursor.execute("INSERT OR IGNORE INTO moradores (id, condominio_id, nome, telefone, apartamento, bloco, tipo) VALUES (101, 1, 'Morador Condo 1', '5511999990101', '101', 'A', 'morador')")
        cursor.execute("INSERT OR IGNORE INTO moradores (id, condominio_id, nome, telefone, apartamento, bloco, tipo) VALUES (201, 2, 'Morador Condo 2', '5511999990201', '201', 'B', 'morador')")
        
        # Garante ocorrências distintas para teste de BOLA/IDOR
        cursor.execute("INSERT OR IGNORE INTO ocorrencias (id, condominio_id, morador_id, apartamento_alvo, bloco_alvo, categoria, descricao, status) VALUES (901, 1, 101, '102', 'A', 'Barulho', 'Barulho no Condo 1', 'Pendente')")
        cursor.execute("INSERT OR IGNORE INTO ocorrencias (id, condominio_id, morador_id, apartamento_alvo, bloco_alvo, categoria, descricao, status) VALUES (902, 2, 201, '202', 'B', 'Barulho', 'Barulho no Condo 2', 'Pendente')")
        
        # Garante reservas distintas
        cursor.execute("INSERT OR IGNORE INTO reservas (id, condominio_id, morador_id, area, data_reserva, periodo, status) VALUES (801, 1, 101, 'Salão de Festas A', '2026-12-01', 'Noite', 'Confirmada')")
        cursor.execute("INSERT OR IGNORE INTO reservas (id, condominio_id, morador_id, area, data_reserva, periodo, status) VALUES (802, 2, 201, 'Churrasqueira B', '2026-12-02', 'Tarde', 'Confirmada')")
        
        # Garante achados distintos
        cursor.execute("INSERT OR IGNORE INTO achados_perdidos (id, condominio_id, item, local_encontrado, status) VALUES (701, 1, 'Chave Condo 1', 'Portaria 1', 'Disponível')")
        cursor.execute("INSERT OR IGNORE INTO achados_perdidos (id, condominio_id, item, local_encontrado, status) VALUES (702, 2, 'Casaco Condo 2', 'Portaria 2', 'Disponível')")
        
        conn.commit()
        conn.close()

    def test_01_sindico_a_nao_acessa_dados_condominio_b(self):
        """1. Comprova que Síndico A não acessa dados do Condomínio B (Isolamento Horizontal)."""
        headers_a = {"X-Condominio-ID": "1", "X-User-Role": "sindico"}
        
        # Tentativa de listar moradores do condomínio 2
        res = client.get("/api/moradores?condominio_id=2", headers=headers_a)
        self.assertEqual(res.status_code, 403, "Síndico A deve ser bloqueado ao requisitar moradores de B")
        
        # Tentativa de listar ocorrências do condomínio 2
        res_oc = client.get("/api/ocorrencias?condominio_id=2", headers=headers_a)
        self.assertEqual(res_oc.status_code, 403, "Síndico A deve ser bloqueado ao requisitar ocorrências de B")
        
        # Tentativa de listar reservas do condomínio 2
        res_res = client.get("/api/reservas?condominio_id=2", headers=headers_a)
        self.assertEqual(res_res.status_code, 403, "Síndico A deve ser bloqueado ao requisitar reservas de B")

    def test_02_sindico_b_nao_acessa_dados_condominio_a(self):
        """2. Comprova que Síndico B não acessa dados do Condomínio A."""
        headers_b = {"X-Condominio-ID": "2", "X-User-Role": "sindico"}
        
        # Tentativa de listar moradores do condomínio 1
        res = client.get("/api/moradores?condominio_id=1", headers=headers_b)
        self.assertEqual(res.status_code, 403, "Síndico B deve ser bloqueado ao requisitar moradores de A")
        
        # Tentativa de listar ocorrências do condomínio 1
        res_oc = client.get("/api/ocorrencias?condominio_id=1", headers=headers_b)
        self.assertEqual(res_oc.status_code, 403, "Síndico B deve ser bloqueado ao requisitar ocorrências de A")
        
        # Tentativa de obter configurações do condomínio 1
        res_cfg = client.get("/api/config?condominio_id=1", headers=headers_b)
        self.assertEqual(res_cfg.status_code, 403, "Síndico B deve ser bloqueado ao requisitar configs de A")

    def test_03_morador_nao_acessa_painel_administrativo(self):
        """3. Comprova que o morador recebe HTTP 403 ao tentar acessar o painel administrativo."""
        headers_morador = {"X-Condominio-ID": "1", "X-User-Role": "morador"}
        
        # Morador não pode listar ocorrências (sigilo da moderação)
        res1 = client.get("/api/ocorrencias", headers=headers_morador)
        self.assertEqual(res1.status_code, 403, "Morador não pode acessar fila de ocorrências")
        
        # Morador não pode moderar ocorrência ou aplicar multa
        res2 = client.post("/api/ocorrencias/901/moderar", json={"status": "Aprovada", "penalidade": "Multa", "valor_multa": 250.0}, headers=headers_morador)
        self.assertEqual(res2.status_code, 403, "Morador não pode moderar ocorrências")
        
        # Morador não pode listar banco completo de moradores (LGPD)
        res3 = client.get("/api/moradores", headers=headers_morador)
        self.assertEqual(res3.status_code, 403, "Morador não pode listar outros moradores")
        
        # Morador não pode alterar configurações
        res4 = client.post("/api/config", json={"teste": "123"}, headers=headers_morador)
        self.assertEqual(res4.status_code, 403, "Morador não pode alterar configurações")

    def test_04_morador_nao_realiza_pagamento_individual(self):
        """4. Confirma que a assinatura é B2B exclusiva do Condomínio (Moradores 100% isentos)."""
        headers_morador = {"X-Condominio-ID": "1", "X-User-Role": "morador"}
        
        # Tentativa de morador contratar/renovar assinatura individual deve ser recusada
        res = client.post("/api/assinatura/renovar", json={"condominio_id": 1, "dias": 30}, headers=headers_morador)
        self.assertEqual(res.status_code, 403, "Morador não pode contratar ou renovar assinatura individualmente")
        
        # Consulta de status comprova modelo comercial
        res_status = client.get("/api/assinatura/status?condominio_id=1")
        self.assertEqual(res_status.status_code, 200)
        data = res_status.json()
        self.assertEqual(data.get("modelo_comercial"), "assinatura_exclusiva_condominio")
        self.assertEqual(data.get("cobranca_moradores"), "isento_sem_cobranca_individual")

    def test_05_assinatura_de_a_nao_altera_assinatura_de_b(self):
        """5. Comprova que renovação de assinatura do Condomínio A não altera o status do B."""
        headers_sindico_a = {"X-Condominio-ID": "1", "X-User-Role": "sindico"}
        
        # Obter estado inicial de B
        res_b_ini = client.get("/api/assinatura/status?condominio_id=2")
        expira_b_ini = res_b_ini.json().get("plano_expira_em")
        
        # Renovar assinatura do condomínio A
        res_renova_a = client.post("/api/assinatura/renovar", json={"condominio_id": 1, "dias": 60}, headers=headers_sindico_a)
        self.assertEqual(res_renova_a.status_code, 200)
        
        # Verificar se B permaneceu inalterado
        res_b_pos = client.get("/api/assinatura/status?condominio_id=2")
        expira_b_pos = res_b_pos.json().get("plano_expira_em")
        self.assertEqual(expira_b_ini, expira_b_pos, "A renovação de A não deve alterar a expiração de B")

    def test_06_bloqueio_financeiro_de_a_nao_bloqueia_b(self):
        """6. Comprova que o bloqueio por inadimplência de A não afeta as operações de B."""
        # Simula expiração do condomínio 1
        res_expira_a = client.post("/api/assinatura/simular-expirado", json={"condominio_id": 1})
        self.assertEqual(res_expira_a.status_code, 200)
        
        # Condomínio 1 deve estar inativo
        res_status_a = client.get("/api/assinatura/status?condominio_id=1")
        self.assertFalse(res_status_a.json().get("ativo"))
        
        # Condomínio 2 DEVE permanecer ativo
        res_status_b = client.get("/api/assinatura/status?condominio_id=2")
        self.assertTrue(res_status_b.json().get("ativo"), "Condomínio B deve continuar ativo mesmo se A expirar")
        
        # Restaura A para testes subsequentes
        client.post("/api/assinatura/renovar", json={"condominio_id": 1, "dias": 30}, headers={"X-Condominio-ID": "1", "X-User-Role": "sindico"})

    def test_07_portaria_respeita_permissoes_operacionais(self):
        """7. Comprova que a Portaria possui permissões operacionais e é bloqueada de funções administrativas."""
        headers_portaria = {"X-Condominio-ID": "1", "X-User-Role": "portaria"}
        
        # 1. Portaria PODE consultar agenda de reservas
        res_reservas = client.get("/api/reservas", headers=headers_portaria)
        self.assertEqual(res_reservas.status_code, 200, "Portaria deve poder visualizar reservas")
        
        # 2. Portaria PODE registrar e consultar achados e perdidos
        res_achados = client.get("/api/achados", headers=headers_portaria)
        self.assertEqual(res_achados.status_code, 200, "Portaria deve poder consultar achados")
        
        res_novo_achado = client.post("/api/achados", json={"item": "Guarda-chuva preto", "local_encontrado": "Guarita"}, headers=headers_portaria)
        self.assertEqual(res_novo_achado.status_code, 200, "Portaria deve poder registrar achado")
        
        # 3. Portaria NÃO PODE moderar ocorrências ou multar moradores
        res_mod = client.post("/api/ocorrencias/901/moderar", json={"status": "Aprovada", "penalidade": "Multa", "valor_multa": 300.0}, headers=headers_portaria)
        self.assertEqual(res_mod.status_code, 403, "Portaria não tem autoridade legal para multar moradores")
        
        # 4. Portaria NÃO PODE cadastrar ou excluir moradores
        res_cad_mor = client.post("/api/moradores", json={"nome": "Tentativa Portaria", "telefone": "5511999990999", "apartamento": "10", "bloco": "A"}, headers=headers_portaria)
        self.assertEqual(res_cad_mor.status_code, 403, "Portaria não pode gerenciar cadastro de moradores")
        
        # 5. Portaria NÃO PODE gerenciar assinatura ou finanças
        res_fin = client.post("/api/assinatura/renovar", json={"condominio_id": 1}, headers=headers_portaria)
        self.assertEqual(res_fin.status_code, 403, "Portaria não tem acesso ao módulo financeiro do condomínio")

    def test_08_registros_associados_corretamente_sem_orfaos(self):
        """8. Comprova integridade relacional do banco de dados (zero registros órfãos ou sem tenant_id)."""
        conn = get_db()
        cursor = conn.cursor()
        
        tabelas = ["moradores", "ocorrencias", "reservas", "achados_perdidos", "cobrancas_pix", "configuracoes"]
        for t in tabelas:
            cursor.execute(f"SELECT COUNT(*) FROM {t} WHERE condominio_id IS NULL")
            orfaos = cursor.fetchone()[0]
            self.assertEqual(orfaos, 0, f"A tabela {t} possui registros órfãos sem tenant_id")
            
        conn.close()

    def test_09_whatsapp_direciona_ao_condominio_correto(self):
        """9. Comprova que o WhatsApp associa o atendimento estritamente ao condomínio do morador."""
        # Mensagem do Morador do Condomínio 1
        res1 = client.post("/webhook/whatsapp", json={
            "id": "wa-test-tenant-1",
            "sender_phone": "5511999990101",
            "text": "Barulho de festa no 102"
        })
        self.assertEqual(res1.status_code, 200)
        data1 = res1.json()
        self.assertEqual(data1.get("status"), "occurrence_created")
        self.assertEqual(data1.get("condominio_id"), 1, "Ocorrência deve ser vinculada ao Condomínio 1")
        
        # Mensagem do Morador do Condomínio 2
        res2 = client.post("/webhook/whatsapp", json={
            "id": "wa-test-tenant-2",
            "sender_phone": "5511999990201",
            "text": "Barulho de obra no 202"
        })
        self.assertEqual(res2.status_code, 200)
        data2 = res2.json()
        self.assertEqual(data2.get("status"), "occurrence_created")
        self.assertEqual(data2.get("condominio_id"), 2, "Ocorrência deve ser vinculada ao Condomínio 2")
        
        # Validação no banco de dados de que as ocorrências estão em tenants separados
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT condominio_id FROM ocorrencias WHERE id = ?", (data1["ocorrencia_id"],))
        self.assertEqual(cursor.fetchone()[0], 1)
        cursor.execute("SELECT condominio_id FROM ocorrencias WHERE id = ?", (data2["ocorrencia_id"],))
        self.assertEqual(cursor.fetchone()[0], 2)
        conn.close()

    def test_10_prevencao_bola_idor_alteracao_identificadores(self):
        """10. Comprova proteção contra manipulação de IDs e BOLA (Broken Object Level Authorization)."""
        headers_sindico_a = {"X-Condominio-ID": "1", "X-User-Role": "sindico"}
        
        # 1. Tentativa de Síndico 1 moderar ocorrência pertencente ao Condomínio 2 (#902)
        res_bola_mod = client.post("/api/ocorrencias/902/moderar", json={"status": "Aprovada", "penalidade": "Multa"}, headers=headers_sindico_a)
        self.assertEqual(res_bola_mod.status_code, 403, "Síndico 1 não pode moderar ocorrência do Condomínio 2")
        
        # 2. Tentativa de Síndico 1 excluir morador do Condomínio 2 (#201)
        res_bola_del_mor = client.delete("/api/moradores/201", headers=headers_sindico_a)
        self.assertEqual(res_bola_del_mor.status_code, 403, "Síndico 1 não pode excluir morador do Condomínio 2")
        
        # 3. Tentativa de Síndico 1 cancelar reserva do Condomínio 2 (#802)
        res_bola_del_res = client.delete("/api/reservas/802", headers=headers_sindico_a)
        self.assertEqual(res_bola_del_res.status_code, 403, "Síndico 1 não pode cancelar reserva do Condomínio 2")
        
        # 4. Tentativa de Síndico 1 devolver achado do Condomínio 2 (#702)
        res_bola_achado = client.put("/api/achados/702/devolver", json={"devolvido_para": "Invasor"}, headers=headers_sindico_a)
        self.assertEqual(res_bola_achado.status_code, 403, "Síndico 1 não pode alterar achado do Condomínio 2")

if __name__ == "__main__":
    print("\n" + "="*70)
    print(" SUÍTE DE TESTES: AUDITORIA MULTI-TENANT E MODELO COMERCIAL CONCILIAZAP")
    print("="*70 + "\n")
    unittest.main(verbosity=2)
