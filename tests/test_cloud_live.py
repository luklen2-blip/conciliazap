import sys
import os
import urllib3
import requests

# Desativa avisos de SSL não verificado para permitir validação em túneis e ambientes de homologação
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Garante suporte a UTF-8 em terminais Windows (cp1252)
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

def main():
    if len(sys.argv) < 2:
        print("Uso: python tests/test_cloud_live.py <URL_DE_PRODUCAO>")
        print("Exemplo: python tests/test_cloud_live.py https://conciliazap.onrender.com")
        sys.exit(1)

    base_url = sys.argv[1].rstrip("/")
    print("\n" + "="*70)
    print(f" TESTE AO VIVO EM PRODUÇÃO / NUVEM: {base_url}")
    print("="*70 + "\n")

    session = requests.Session()
    session.verify = False

    falhas = 0

    # 1. Teste de Health Check
    try:
        r = session.get(f"{base_url}/api/health", timeout=15)
        if r.status_code == 200 and r.json().get("status") == "ok":
            print(f" [PASS] 1. Health Check 24/7 ativo: {r.json()}")
        else:
            print(f" [FAIL] 1. Health check falhou: {r.status_code} - {r.text}")
            falhas += 1
    except Exception as e:
        print(f" [FAIL] 1. Erro ao conectar em /api/health: {e}")
        falhas += 1

    # 2. Teste do Webhook com Morador Cadastrado
    try:
        payload = {
            "id": "e2e-cloud-001",
            "sender_phone": "5511999990302",
            "text": "Barulho de festa no apto 402 bloco A"
        }
        r = session.post(f"{base_url}/webhook/whatsapp", json=payload, timeout=15)
        if r.status_code == 200 and "reply" in r.json():
            print(f" [PASS] 2. Webhook WhatsApp operacional com resposta inteligente")
        else:
            print(f" [FAIL] 2. Webhook falhou: {r.status_code} - {r.text}")
            falhas += 1
    except Exception as e:
        print(f" [FAIL] 2. Erro no Webhook: {e}")
        falhas += 1

    # 3. Teste de Listagem de Ocorrências e Banco de Dados
    try:
        r = session.get(f"{base_url}/api/ocorrencias", timeout=15)
        if r.status_code == 200 and isinstance(r.json(), list):
            print(f" [PASS] 3. Banco de dados e API de ocorrências respondendo ({len(r.json())} itens)")
        else:
            print(f" [FAIL] 3. Ocorrências falharam: {r.status_code}")
            falhas += 1
    except Exception as e:
        print(f" [FAIL] 3. Erro na listagem de ocorrências: {e}")
        falhas += 1

    # 4. Teste de Geração de PIX Banco Central
    try:
        pix_payload = {
            "plano_nome": "Condomínio Starter E2E",
            "valor": 99.00,
            "chave_pix": "pix@conciliazap.com.br",
            "nome_recebedor": "ConciliaZap Solucoes",
            "cidade": "SAO PAULO"
        }
        r = session.post(f"{base_url}/api/pix/gerar", json=pix_payload, timeout=15)
        if r.status_code == 200 and "pix_copia_e_cola" in r.json():
            print(f" [PASS] 4. Motor PIX Banco Central gerando payload EMV com sucesso")
        else:
            print(f" [FAIL] 4. Motor PIX falhou: {r.status_code}")
            falhas += 1
    except Exception as e:
        print(f" [FAIL] 4. Erro no PIX: {e}")
        falhas += 1

    # 5. Páginas Legais (LGPD e Termos)
    try:
        r_termos = session.get(f"{base_url}/termos", timeout=15)
        r_priv = session.get(f"{base_url}/privacidade", timeout=15)
        if r_termos.status_code == 200 and r_priv.status_code == 200:
            print(f" [PASS] 5. Páginas legais e conformidade LGPD publicadas")
        else:
            print(f" [FAIL] 5. Páginas legais retornaram erro")
            falhas += 1
    except Exception as e:
        print(f" [FAIL] 5. Erro ao consultar páginas legais: {e}")
        falhas += 1

    # 6. Carregamento do Painel Web (Frontend SPA)
    try:
        r = session.get(f"{base_url}/", timeout=15)
        if r.status_code == 200 and "ConciliaZap" in r.text:
            print(f" [PASS] 6. Frontend SPA carregado perfeitamente")
        else:
            print(f" [FAIL] 6. Frontend falhou: {r.status_code}")
            falhas += 1
    except Exception as e:
        print(f" [FAIL] 6. Erro ao carregar frontend: {e}")
        falhas += 1

    print("\n" + "="*70)
    if falhas == 0:
        print(" HOMOLOGAÇÃO AO VIVO CONCLUÍDA: 100% OPERACIONAL NA NUVEM!")
    else:
        print(f" ATENÇÃO: {falhas} teste(s) falharam durante a homologação.")
    print("="*70 + "\n")
    sys.exit(falhas)

if __name__ == "__main__":
    main()
