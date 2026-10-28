@echo off
chcp 65001 >nul
title ConciliaZap - Gestão de Conflitos & Condomínio 24/7

echo ======================================================================
echo           CONCILIAZAP - GESTAO DE CONFLITOS CONDOMINIAIS 24/7
echo ======================================================================
echo.

cd /d "c:\Users\luciano\OneDrive\Documentos\nova pasta\index.html\Condominio"

echo [1/3] Executando testes de integridade locais...
python tests\run_all.py
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ERRO] Falha nos testes de integridade. Corrija os erros antes de iniciar.
    pause
    exit /b %ERRORLEVEL%
)

echo.
echo [2/3] Iniciando Servidor Web FastAPI (Porta 8000)...
start "ConciliaZap Backend" cmd /k "chcp 65001 >nul && python -m uvicorn main:app --host 0.0.0.0 --port 8000"

timeout /t 2 >nul

echo.
echo [3/3] Iniciando Tunel Seguro Cloudflare (Acesso Externo / Mobile)...
start "ConciliaZap Cloudflare Tunnel" cmd /k "chcp 65001 >nul && python tunnel_manager.py"

echo.
echo Abrindo painel no navegador padrao...
start http://localhost:8000

echo.
echo ======================================================================
echo  ConciliaZap em execucao 24/7!
echo  Painel Local: http://localhost:8000
echo  Health Check: http://localhost:8000/api/health
echo ======================================================================
echo.
