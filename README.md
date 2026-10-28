# ConciliaZap - Gestão de Conflitos & Condomínio 24/7 🏢⚖️

> **Sistema autônomo de mediação de conflitos, ocorrências e gestão condominial via WhatsApp com moderação humana do síndico em 1 clique e deploy contínuo em nuvem.**

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com)
[![FastAPI](https://img.shields.io/badge/FastAPI-2.0.0-009688.svg?logo=fastapi)](https://fastapi.tiangolo.com)
[![Python 3.12](https://img.shields.io/badge/Python-3.12-blue.svg?logo=python)](https://python.org)
[![Status 24/7](https://img.shields.io/badge/Status-24%2F7_Online-brightgreen.svg)](#)

---

## 🌟 Principais Recursos

1. **Atendimento WhatsApp Autônomo e Inteligente (Evolution API / Z-API):**
   - Identificação instantânea da unidade (apartamento e bloco) pelo número do remetente.
   - Desescalada amigável para conflitos de som alto, ruídos e perturbação do sossego.
   - **Garantia de Anonimato:** O nome do vizinho denunciante nunca é exposto ao infrator.
   - Solicitação de evidências (áudios e vídeos) integrada ao laudo.
   - Autoatendimento para reservas de áreas comuns, achados & perdidos e regras de silêncio.

2. **Painel de Moderação do Síndico em 1 Clique:**
   - Visualização de denúncias pendentes com contador de reincidência por unidade.
   - Homologação de sanções administrativas com 1 clique (*Aviso Amigável*, *Advertência Formal* ou *Multa*).
   - Notificação automática gerada para envio direto ao infrator.
   - Emissão de Laudo Formal de Infração em HTML pronto para impressão ou PDF.

3. **Monetização SaaS e Pagamentos PIX (Banco Central):**
   - Geração de payload PIX EMV oficial com cálculo de CRC16 e QR Code dinâmico.
   - Planos escaláveis: *Starter* (até 40 unidades), *Pro* (até 150 unidades) e *Master* (ilimitado).

4. **Conformidade Legal Brasileira e Ética:**
   - Total aderência aos Arts. 1.336 e 1.337 do Código Civil Brasileiro.
   - Proteção de dados e conformidade LGPD (Lei nº 13.709/2018 - Privacy by Design).
   - Avisos regulatórios claros de que a plataforma não substitui serviços de emergência (190).

5. **Infraestrutura em Nuvem 24/7:**
   - Health check contínuo na rota `/api/health` para monitoramento via UptimeRobot.
   - Blueprint `render.yaml` pronto para deploy no plano gratuito do Render.
   - Imagem `Dockerfile` leve com execução de testes automatizados na fase de build.

---

## 📁 Estrutura do Projeto

```text
├── main.py                  # API FastAPI principal com todas as rotas e regras
├── banco.py                 # Estrutura do SQLite, tabelas e dados de teste
├── pix.py                   # Gerador oficial de PIX EMV Copia-e-Cola e QR Code
├── index.html               # Frontend moderno SPA em Tailwind CSS
├── app.js                   # Lógica de interface, simulador e chamadas à API
├── render.yaml              # Blueprint de infraestrutura para Render.com
├── Dockerfile               # Contêiner universal Python 3.12
├── requirements.txt         # Dependências (fastapi, uvicorn, httpx, etc.)
├── tunnel_manager.py        # Gerenciador de Quick Tunnel Cloudflare (--no-prechecks)
├── INICIAR_24_7_CONCILIAZAP.bat # Inicializador local em 1 clique
└── tests/
    ├── run_all.py           # Suíte de testes automatizados (100% de cobertura)
    └── test_cloud_live.py   # Testes E2E remotos de homologação na nuvem
```

---

## 🚀 Como Rodar Localmente

1. Clone o repositório:
```bash
git clone https://github.com/SEU_USUARIO/conciliazap.git
cd conciliazap
```

2. Instale as dependências:
```bash
pip install -r requirements.txt
```

3. Execute os testes de integridade:
```bash
python tests/run_all.py
```

4. Inicie o servidor:
```bash
uvicorn main:app --host 0.0.0.0 --port 8000
```
Acesse o painel em `http://localhost:8000`.

---

## ☁️ Deploy Contínuo no Render.com

1. Crie um novo repositório no GitHub e envie estes arquivos.
2. No [Render Dashboard](https://dashboard.render.com), clique em **New +** > **Blueprint**.
3. Selecione o repositório e o Render provisionará o Web Service automaticamente lendo o `render.yaml`.
4. Monitore a saúde do serviço em: `https://seu-app.onrender.com/api/health`.
