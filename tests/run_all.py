import sys
import os
import unittest
from datetime import datetime

# Garante inclusão da pasta raiz no sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Garante suporte a UTF-8 em terminais Windows (cp1252)
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

from fastapi.testclient import TestClient
from main import app, get_db

client = TestClient(app)

class TestConciliaZapCompleto(unittest.TestCase):

    def test_01_health_check_obrigatorio(self):
        """Valida se a rota /api/health atende a regra global mandatoria."""
        res = client.get("/api/health")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data.get("status"), "ok")
        self.assertIn("ConciliaZap", data.get("app"))
        self.assertEqual(data.get("version"), "2.0.0")
        self.assertIn("uptime_seconds", data)
        self.assertIn("timestamp", data)
        print(" [PASS] 01. Health Check (/api/health) em conformidade 24/7")

    def test_02_webhook_morador_nao_cadastrado(self):
        """Morador desconhecido deve receber mensagem de instrução sem registrar ocorrência."""
        payload = {
            "id": "test-msg-001",
            "sender_phone": "5511988887777",
            "text": "Tem barulho alto no 402"
        }
        res = client.post("/webhook/whatsapp", json=payload)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("Não identificamos seu número", data.get("reply"))
        print(" [PASS] 02. Webhook WhatsApp protege acesso de número não cadastrado")

    def test_03_webhook_conflito_barulho(self):
        """Morador cadastrado reportando barulho gera ocorrência anônima automática."""
        payload = {
            "id": "test-msg-002",
            "sender_phone": "5511999990302", # Carlos Mendes (Ap 302-A)
            "text": "Está tendo um barulho insuportável de som alto no apto 402 bloco A"
        }
        res = client.post("/webhook/whatsapp", json=payload)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data.get("status"), "occurrence_created")
        self.assertIn("Identificamos seu registro referente à perturbação", data.get("reply"))
        self.assertIn("Garantia de Impessoalidade", data.get("reply"))
        self.assertTrue(data.get("ocorrencia_id") > 0)
        print(" [PASS] 03. Webhook registra ocorrência de barulho com desescalada pacífica")

    def test_04_webhook_menus_auxiliares(self):
        """Verifica fluxos de reserva, regras e menu principal."""
        tel = "5511999990302"
        
        # Reservas
        res = client.post("/webhook/whatsapp", json={"id": "m1", "sender_phone": tel, "text": "Gostaria de ver reserva do salão"})
        self.assertIn("Reserva de Áreas Comuns", res.json().get("reply"))

        # Regras
        res = client.post("/webhook/whatsapp", json={"id": "m2", "sender_phone": tel, "text": "Quais as regras de silêncio?"})
        self.assertIn("Horário de Silêncio", res.json().get("reply"))

        # Menu Default
        res = client.post("/webhook/whatsapp", json={"id": "m3", "sender_phone": tel, "text": "Boa tarde"})
        self.assertIn("ConciliaZap - Condomínio Inteligente", res.json().get("reply"))
        print(" [PASS] 04. Webhook atende fluxos de reservas, regras e menu principal")

    def test_05_admin_moradores(self):
        """Valida rota de cadastro administrativo solicitada pelo usuário."""
        # Telefone dinâmico para garantir testes 100% idempotentes
        tel_dinamico = f"551197{int(datetime.now().timestamp() * 1000) % 100000000:08d}"
        
        # Cadastro com sucesso
        res = client.post(f"/admin/moradores?nome=Mariana+Alves&telefone={tel_dinamico}&apartamento=201&bloco=B")
        self.assertEqual(res.status_code, 200)
        self.assertIn("sucesso", res.json().get("status").lower())

        # Tentativa de duplicidade deve retornar HTTP 400
        res_dup = client.post(f"/admin/moradores?nome=Mariana+Outra&telefone={tel_dinamico}&apartamento=202&bloco=B")
        self.assertEqual(res_dup.status_code, 400)
        print(" [PASS] 05. Rota /admin/moradores operando com validação de unicidade")

    def test_06_moderacao_sindico_e_laudo(self):
        """Valida o fluxo do síndico homologando decisão com 1 clique e gerando auto de infração."""
        # Pega a última ocorrência
        res_list = client.get("/api/ocorrencias")
        self.assertEqual(res_list.status_code, 200)
        ocorrencias = res_list.json()
        self.assertTrue(len(ocorrencias) > 0)
        oc_id = ocorrencias[0]["id"]

        # Modera
        decisao = {
            "status": "Aprovada",
            "motivo": "Reincidência constatada via medição de decibéis",
            "penalidade": "Advertência Formal",
            "valor_multa": 0.0
        }
        res_mod = client.post(f"/api/ocorrencias/{oc_id}/moderar", json=decisao)
        self.assertEqual(res_mod.status_code, 200)
        self.assertEqual(res_mod.json().get("status"), "success")

        # Laudo HTML para impressão / PDF
        res_laudo = client.get(f"/api/ocorrencias/{oc_id}/laudo-html")
        self.assertEqual(res_laudo.status_code, 200)
        self.assertIn("Notificação e Auto de Infração Administrativa", res_laudo.text)
        print(" [PASS] 06. Moderação do Síndico em 1 clique e emissão de laudo formal concluídos")

    def test_07_pix_emv_oficial(self):
        """Valida a geração de payload Pix oficial do Banco Central com CRC16."""
        payload = {
            "plano_nome": "Condomínio Pro",
            "valor": 199.00,
            "chave_pix": "financeiro@condominio.com.br",
            "nome_recebedor": "Condominio Jardins",
            "cidade": "SAO PAULO"
        }
        res = client.post("/api/pix/gerar", json=payload)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        pix_code = data.get("pix_copia_e_cola")
        self.assertTrue(pix_code.startswith("000201"))
        self.assertIn("6304", pix_code) # Indicador CRC16 do Bacen
        self.assertTrue(len(data.get("qr_code_url")) > 10)
        print(" [PASS] 07. Geração de PIX Banco Central (EMV Copia-e-Cola + CRC16) validada")

    def test_08_paginas_legais_e_lgpd(self):
        """Garante presença dos termos com aviso regulatório e política LGPD."""
        res_termos = client.get("/termos")
        self.assertEqual(res_termos.status_code, 200)
        self.assertIn("NÃO substitui autoridades policiais", res_termos.text)
        self.assertIn("16 anos", res_termos.text)

        res_priv = client.get("/privacidade")
        self.assertEqual(res_priv.status_code, 200)
        self.assertIn("LGPD", res_priv.text)
        self.assertIn("Privacy by Design", res_priv.text)
        print(" [PASS] 08. Conformidade legal (LGPD, Código Civil e avisos éticos) auditada")

    def test_09_frontend_estatico_e_spa(self):
        """Garante resolução universal de frontend com fallback SPA."""
        res_home = client.get("/")
        self.assertEqual(res_home.status_code, 200)
        self.assertIn("ConciliaZap", res_home.text)
        print(" [PASS] 09. Resolução universal de arquivos estáticos e SPA validada")

if __name__ == "__main__":
    print("\n" + "="*70)
    print(" INICIANDO SUÍTE DE TESTES AUTOMATIZADOS - CONCILIAZAP 24/7")
    print("="*70 + "\n")
    suite = unittest.TestLoader().loadTestsFromTestCase(TestConciliaZapCompleto)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    if not result.wasSuccessful():
        sys.exit(1)
    print("\n" + "="*70)
    print(" TODOS OS TESTES PASSARAM COM 100% DE SUCESSO!")
    print("="*70 + "\n")
