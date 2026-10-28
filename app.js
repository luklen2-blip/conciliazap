// ConciliaZap 24/7 - Core Application Logic

// --- UTILITÁRIO UNIVERSAL DE SANITIZAÇÃO XSS (OWASP TOP 10) ---
function escapeHtml(text) {
    if (text === null || text === undefined) return "";
    const map = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' };
    return String(text).replace(/[&<>"']/g, m => map[m]);
}

function formatarTextoZap(text) {
    if (!text) return "";
    // Transforma *negrito* em <strong>negrito</strong> com sanitização anti-XSS
    return escapeHtml(text).replace(/\*(.*?)\*/g, '<strong>$1</strong>');
}

let ocorrenciasCache = [];
let filtroOcorrenciasAtual = "Todas";
let ocorrenciaEmModeracaoId = null;

// Inicialização ao carregar a página
document.addEventListener("DOMContentLoaded", () => {
    verificarSaude();
    setInterval(verificarSaude, 15000); // Heartbeat 15s
    
    carregarStatusAssinatura();
    setInterval(carregarStatusAssinatura, 20000); // Checagem de assinatura 20s
    
    carregarOcorrencias();
    carregarMoradores();
    carregarReservas();
    carregarAchados();
    carregarPlanos();
    carregarConfiguracoes();

    // Atualiza a URL do webhook visível na tela
    const hostAtual = window.location.origin;
    const displayEl = document.getElementById("webhookUrlDisplay");
    if (displayEl) {
        displayEl.innerText = `${hostAtual}/webhook/whatsapp`;
    }
});

// --- CONTROLE DE ABAS ---
function trocarAba(nomeAba) {
    const abas = ["painel", "simulador", "moradores", "reservas", "planos", "configuracoes", "guia"];
    abas.forEach(aba => {
        const elAba = document.getElementById(`aba-${aba}`);
        const elBtn = document.getElementById(`tab-btn-${aba}`);
        if (elAba) elAba.classList.add("hidden");
        if (elBtn) {
            elBtn.classList.remove("text-brand-600", "bg-brand-50", "font-bold");
            elBtn.classList.add("text-slate-600");
        }
    });

    const abaAtiva = document.getElementById(`aba-${nomeAba}`);
    const btnAtivo = document.getElementById(`tab-btn-${nomeAba}`);
    if (abaAtiva) abaAtiva.classList.remove("hidden");
    if (btnAtivo) {
        btnAtivo.classList.remove("text-slate-600");
        btnAtivo.classList.add("text-brand-600", "bg-brand-50", "font-bold");
    }

    if (nomeAba === 'painel') carregarOcorrencias();
    if (nomeAba === 'moradores') carregarMoradores();
    if (nomeAba === 'reservas') { carregarReservas(); carregarAchados(); }
}

// --- MONITORAMENTO /api/health ---
async function verificarSaude() {
    try {
        const res = await fetch("/api/health");
        const data = await res.json();
        const badge = document.getElementById("healthBadge");
        if (badge && data.status === "ok") {
            const minutos = Math.floor(data.uptime_seconds / 60);
            badge.innerText = `Online (${minutos}m) • v${data.version}`;
        }
    } catch (e) {
        const badge = document.getElementById("healthBadge");
        if (badge) badge.innerText = "Reconectando...";
    }
}

// --- GESTÃO DE ASSINATURA 30 DIAS CORRIDOS (PAYWALL) ---
async function carregarStatusAssinatura() {
    try {
        const res = await fetch("/api/assinatura/status");
        const sub = await res.json();
        
        const badgeText = document.getElementById("subBadgeText");
        const dot = document.getElementById("subDot");
        const banner = document.getElementById("bannerAssinaturaExpirada");
        const bannerData = document.getElementById("bannerExpiraData");
        const textoCiclo = document.getElementById("textoCicloDias");
        const iconCiclo = document.getElementById("iconCicloStatus");
        const badgeCiclo = document.getElementById("badgeCicloStatus");

        if (sub.ativo) {
            if (badgeText) badgeText.innerText = `Assinatura Ativa (${sub.dias_restantes}d)`;
            if (dot) dot.className = "w-2.5 h-2.5 rounded-full bg-emerald-500";
            if (banner) banner.classList.add("hidden");
            if (textoCiclo) {
                textoCiclo.innerHTML = `Plano <strong>${sub.plano_ativo}</strong> ativo até <strong>${sub.plano_expira_formatado}</strong> (Restam ${sub.dias_restantes} dias corridos)`;
            }
            if (iconCiclo) iconCiclo.className = "w-11 h-11 rounded-xl bg-emerald-100 text-emerald-700 flex items-center justify-center text-xl shadow-sm";
            if (badgeCiclo) {
                badgeCiclo.className = "text-[10px] font-black uppercase tracking-wider text-emerald-800 bg-emerald-50 px-2 py-0.5 rounded border border-emerald-200";
                badgeCiclo.innerText = "Ciclo Ativo: 30 Dias Corridos";
            }
        } else {
            if (badgeText) badgeText.innerText = "Bloqueado (Assinatura Vencida)";
            if (dot) dot.className = "w-2.5 h-2.5 rounded-full bg-red-500 animate-ping";
            if (banner) banner.classList.remove("hidden");
            if (bannerData) {
                bannerData.innerText = sub.plano_expira_formatado ? `Venceu em ${sub.plano_expira_formatado}` : "Aguardando pagamento mensal";
            }
            if (textoCiclo) {
                textoCiclo.innerHTML = `<span class="text-red-600 font-extrabold">Assinatura Expirada / Bloqueada</span> • Venceu em ${sub.plano_expira_formatado || 'período recente'}`;
            }
            if (iconCiclo) iconCiclo.className = "w-11 h-11 rounded-xl bg-red-100 text-red-700 flex items-center justify-center text-xl shadow-sm";
            if (badgeCiclo) {
                badgeCiclo.className = "text-[10px] font-black uppercase tracking-wider text-red-800 bg-red-50 px-2 py-0.5 rounded border border-red-200";
                badgeCiclo.innerText = "Acesso Bloqueado: 30 Dias Vencidos";
            }
        }
    } catch (e) {
        console.error("Erro ao verificar status da assinatura:", e);
    }
}

// --- OCORRÊNCIAS & MODERAÇÃO ---
async function carregarOcorrencias() {
    try {
        const res = await fetch("/api/ocorrencias");
        ocorrenciasCache = await res.json();
        atualizarMetricas();
        renderizarOcorrencias();
    } catch (e) {
        console.error("Erro ao buscar ocorrências:", e);
    }
}

function atualizarMetricas() {
    const pendentes = ocorrenciasCache.filter(o => o.status === "Pendente").length;
    const resolvidas = ocorrenciasCache.filter(o => o.status === "Aprovada" || o.status === "Notificada").length;
    
    document.getElementById("statPendentes").innerText = pendentes;
    document.getElementById("statResolvidas").innerText = resolvidas;
    
    const contadorBadge = document.getElementById("badgeContadorPendentes");
    if (contadorBadge) {
        if (pendentes > 0) {
            contadorBadge.innerText = pendentes;
            contadorBadge.classList.remove("hidden");
        } else {
            contadorBadge.classList.add("hidden");
        }
    }
}

function filtrarOcorrencias(status) {
    filtroOcorrenciasAtual = status;
    document.querySelectorAll(".filtro-btn").forEach(btn => {
        if (btn.innerText.includes(status) || (status === 'Todas' && btn.innerText === 'Todas')) {
            btn.className = "filtro-btn px-2.5 py-1 rounded-md bg-slate-800 text-white font-bold";
        } else {
            btn.className = "filtro-btn px-2.5 py-1 rounded-md hover:bg-slate-100 text-slate-600";
        }
    });
    renderizarOcorrencias();
}

function renderizarOcorrencias() {
    const container = document.getElementById("listaOcorrenciasContainer");
    const labelContador = document.getElementById("contadorOcorrenciasTexto");
    if (!container) return;

    let lista = ocorrenciasCache;
    if (filtroOcorrenciasAtual !== "Todas") {
        lista = ocorrenciasCache.filter(o => o.status === filtroOcorrenciasAtual);
    }

    if (labelContador) {
        labelContador.innerText = `Mostrando ${lista.length} de ${ocorrenciasCache.length} ocorrências`;
    }

    if (lista.length === 0) {
        container.innerHTML = `
            <div class="bg-white p-8 rounded-2xl border border-slate-200 text-center space-y-2">
                <div class="w-12 h-12 bg-slate-100 text-slate-400 rounded-full flex items-center justify-center mx-auto text-xl">
                    <i class="fa-solid fa-peace"></i>
                </div>
                <h4 class="font-bold text-slate-700 text-sm">Nenhuma ocorrência encontrada</h4>
                <p class="text-xs text-slate-400">Tudo calmo no condomínio. Simule um conflito na aba "Simulador de Bot".</p>
            </div>
        `;
        return;
    }

    container.innerHTML = lista.map(oc => {
        const isPendente = oc.status === "Pendente";
        const isAprovada = oc.status === "Aprovada" || oc.status === "Notificada";
        
        let statusBadge = `<span class="bg-amber-100 text-amber-800 border border-amber-300 px-2 py-0.5 rounded-full font-bold text-[10px]">Aguardando Moderação</span>`;
        if (isAprovada) {
            statusBadge = `<span class="bg-emerald-100 text-emerald-800 border border-emerald-300 px-2 py-0.5 rounded-full font-bold text-[10px]">Notificação Homologada</span>`;
        } else if (oc.status === "Rejeitada") {
            statusBadge = `<span class="bg-slate-200 text-slate-700 px-2 py-0.5 rounded-full font-bold text-[10px]">Arquivada</span>`;
        }

        const reincidencias = oc.reincidencias_infrator || 0;
        let reincidenciaBadge = `<span class="text-slate-500 bg-slate-100 px-2 py-0.5 rounded text-[10px] font-semibold">1ª Queixa</span>`;
        if (reincidencias === 1) {
            reincidenciaBadge = `<span class="text-amber-700 bg-amber-100 border border-amber-300 px-2 py-0.5 rounded text-[10px] font-bold">2ª Reincidência (Advertência)</span>`;
        } else if (reincidencias >= 2) {
            reincidenciaBadge = `<span class="text-red-700 bg-red-100 border border-red-300 px-2 py-0.5 rounded text-[10px] font-black animate-pulse">Reincidente (${reincidencias}x - Multa Sugerida)</span>`;
        }

        return `
            <div class="bg-white rounded-2xl border ${isPendente ? 'border-amber-300 shadow-md ring-1 ring-amber-100' : 'border-slate-200 shadow-sm'} p-5 transition space-y-3">
                <div class="flex flex-wrap items-center justify-between gap-2 border-b border-slate-100 pb-3">
                    <div class="flex items-center space-x-2">
                        <span class="font-black text-slate-900 text-sm">Ocorrência #${String(oc.id).padStart(4, '0')}</span>
                        ${statusBadge}
                        <span class="text-xs bg-slate-100 text-slate-600 px-2 py-0.5 rounded font-medium">${escapeHtml(oc.categoria)}</span>
                    </div>
                    <div class="text-[11px] text-slate-400 flex items-center space-x-1">
                        <i class="fa-regular fa-clock"></i>
                        <span>${escapeHtml(oc.data_hora)}</span>
                    </div>
                </div>

                <div class="grid grid-cols-1 md:grid-cols-12 gap-3 text-xs">
                    <!-- Detalhes do Alvo e Denunciante -->
                    <div class="md:col-span-4 p-3 bg-slate-50 rounded-xl space-y-2 border border-slate-200/60">
                        <div>
                            <span class="text-[10px] uppercase font-bold text-slate-400 block">Unidade Notificada (Infrator):</span>
                            <span class="font-extrabold text-sm text-slate-900">Apartamento ${escapeHtml(oc.apartamento_alvo)} - Bloco ${escapeHtml(oc.bloco_alvo)}</span>
                            <div class="mt-1">${reincidenciaBadge}</div>
                        </div>
                        <div class="pt-2 border-t border-slate-200">
                            <span class="text-[10px] uppercase font-bold text-slate-400 block flex items-center justify-between">
                                <span>Denunciante (Sigiloso):</span>
                                <i class="fa-solid fa-lock text-slate-400 text-[9px]" title="Apenas o síndico tem acesso à identidade"></i>
                            </span>
                            <span class="font-semibold text-slate-700">${escapeHtml(oc.denunciante_nome)} (Ap ${escapeHtml(oc.denunciante_ap)}-${escapeHtml(oc.denunciante_bloco)})</span>
                        </div>
                    </div>

                    <!-- Descrição da Queixa & Parecer -->
                    <div class="md:col-span-8 flex flex-col justify-between space-y-3">
                        <div class="space-y-1.5">
                            <span class="text-[10px] uppercase font-bold text-slate-400 block">Relato Registrado via WhatsApp:</span>
                            <p class="text-slate-800 text-xs bg-amber-50/50 p-2.5 rounded-lg border border-amber-200/50 italic">
                                "${escapeHtml(oc.descricao)}"
                            </p>
                        </div>

                        ${oc.decisao_sindico ? `
                            <div class="p-2 bg-slate-100 rounded-lg text-slate-700 text-[11px]">
                                <strong>Parecer do Síndico:</strong> ${escapeHtml(oc.decisao_sindico)} • 
                                <span class="font-bold text-brand-700">Sanção: ${escapeHtml(oc.penalidade)}</span>
                                ${oc.valor_multa > 0 ? `<span class="text-red-600 font-bold ml-1">(R$ ${Number(oc.valor_multa).toFixed(2)})</span>` : ''}
                            </div>
                        ` : ''}

                        <!-- Barra de Ações com 1 Clique -->
                        <div class="flex flex-wrap items-center justify-end gap-2 pt-2 border-t border-slate-100">
                            <a href="/api/ocorrencias/${oc.id}/laudo-html" target="_blank" class="px-3 py-1.5 rounded-lg text-xs font-semibold text-slate-600 bg-slate-100 hover:bg-slate-200 transition flex items-center space-x-1">
                                <i class="fa-solid fa-file-pdf text-red-500"></i>
                                <span>Laudo Oficial PDF</span>
                            </a>

                            ${isPendente ? `
                                <button onclick="abrirModalModeracao(${oc.id})" class="px-4 py-1.5 rounded-lg text-xs font-bold text-white bg-brand-600 hover:bg-brand-500 transition shadow flex items-center space-x-1.5">
                                    <i class="fa-solid fa-check"></i>
                                    <span>Moderar & Notificar com 1 Clique</span>
                                </button>
                            ` : `
                                <span class="text-[11px] text-slate-400 italic">Concluído</span>
                            `}
                        </div>
                    </div>
                </div>
            </div>
        `;
    }).join("");
}

// Modal de Moderação
function abrirModalModeracao(id) {
    const oc = ocorrenciasCache.find(o => o.id === id);
    if (!oc) return;
    ocorrenciaEmModeracaoId = id;

    document.getElementById("modalModTitulo").innerText = `Moderar Ocorrência #${String(id).padStart(4, '0')}`;
    document.getElementById("modalModUnidade").innerText = `Ap ${oc.apartamento_alvo} - Bloco ${oc.bloco_alvo}`;
    document.getElementById("modalModDescricao").innerText = `"${oc.descricao}"`;
    document.getElementById("modalModParecer").value = "";

    // Pré-sugere o grau da sanção baseado na reincidência
    const reincidencias = oc.reincidencias_infrator || 0;
    const selectPenalidade = document.getElementById("modalModPenalidade");
    if (reincidencias >= 2) {
        selectPenalidade.value = "Multa";
    } else if (reincidencias === 1) {
        selectPenalidade.value = "Advertência Formal";
    } else {
        selectPenalidade.value = "Aviso Amigável";
    }
    atualizarCampoValorMulta();

    document.getElementById("modalModeracao").classList.remove("hidden");
}

function fecharModalModeracao() {
    document.getElementById("modalModeracao").classList.add("hidden");
    ocorrenciaEmModeracaoId = null;
}

function atualizarCampoValorMulta() {
    const penalidade = document.getElementById("modalModPenalidade").value;
    const divMulta = document.getElementById("campoValorMultaDiv");
    if (penalidade === "Multa") {
        divMulta.classList.remove("hidden");
    } else {
        divMulta.classList.add("hidden");
    }
}

async function executarDecisaoModeracao(status) {
    if (!ocorrenciaEmModeracaoId) return;

    const penalidade = document.getElementById("modalModPenalidade").value;
    const parecer = document.getElementById("modalModParecer").value;
    const valorMulta = parseFloat(document.getElementById("modalModValorMulta").value) || 0.0;

    try {
        const res = await fetch(`/api/ocorrencias/${ocorrenciaEmModeracaoId}/moderar`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                status: status,
                motivo: parecer,
                penalidade: status === "Aprovada" ? penalidade : "Nenhuma",
                valor_multa: status === "Aprovada" && penalidade === "Multa" ? valorMulta : 0.0
            })
        });
        const data = await res.json();
        fecharModalModeracao();
        exibirToast("✅ Decisão homologada e notificação disparada ao morador!");
        carregarOcorrencias();
    } catch (e) {
        exibirToast("Erro ao processar moderação");
    }
}

// --- SIMULADOR DE BOT WHATSAPP ---
function selecionarMoradorSimulador() {
    const sel = document.getElementById("simuladorMoradorSelect");
    document.getElementById("simuladorTelefone").value = sel.value;
}

function enviarMensagemRapida(texto) {
    document.getElementById("chatInput").value = texto;
    enviarMensagemChat();
}

function tratarEnterChat(e) {
    if (e.key === "Enter") enviarMensagemChat();
}

async function enviarMensagemChat() {
    const input = document.getElementById("chatInput");
    const texto = input.value.trim();
    if (!texto) return;

    const telefone = document.getElementById("simuladorTelefone").value.trim();
    const chatContainer = document.getElementById("chatMessages");
    const horaAgora = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

    // Bolha da mensagem do usuário
    const bubbleUser = document.createElement("div");
    bubbleUser.className = "flex justify-end";
    bubbleUser.innerHTML = `
        <div class="chat-bubble-user p-2.5 max-w-[85%] shadow-sm text-slate-800 space-y-1">
            <p class="text-xs leading-relaxed">${escapeHtml(texto)}</p>
            <span class="text-[9px] text-slate-500 block text-right">${horaAgora} ✓✓</span>
        </div>
    `;
    chatContainer.appendChild(bubbleUser);
    input.value = "";
    chatContainer.scrollTop = chatContainer.scrollHeight;

    // Dispara para a rota do webhook / simulador
    try {
        const res = await fetch("/api/simulador/enviar", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                id: "sim-" + Date.now(),
                sender_phone: telefone,
                text: texto
            })
        });
        const data = await res.json();

        // Resposta do bot
        const bubbleBot = document.createElement("div");
        bubbleBot.className = "flex justify-start";
        bubbleBot.innerHTML = `
            <div class="chat-bubble-bot p-2.5 max-w-[85%] shadow-sm text-slate-800 space-y-1 border border-slate-200/50">
                <p class="text-xs leading-relaxed whitespace-pre-wrap">${formatarTextoZap(data.reply)}</p>
                <span class="text-[9px] text-slate-400 block text-right">${horaAgora}</span>
            </div>
        `;
        chatContainer.appendChild(bubbleBot);
        chatContainer.scrollTop = chatContainer.scrollHeight;

        // Se uma nova ocorrência foi criada, atualiza o painel de moderação automaticamente
        if (data.status === "occurrence_created") {
            carregarOcorrencias();
            exibirToast("🔔 Nova ocorrência registrada no Painel de Moderação!");
        }
    } catch (e) {
        console.error(e);
    }
}

function limparHistoricoChat() {
    const chatContainer = document.getElementById("chatMessages");
    chatContainer.innerHTML = `
        <div class="flex justify-start">
            <div class="chat-bubble-bot p-3 max-w-[85%] shadow-sm text-slate-800 space-y-1">
                <p class="text-xs">Chat limpo. Digite uma nova mensagem para testar.</p>
            </div>
        </div>
    `;
}

// --- GESTÃO DE MORADORES ---
async function carregarMoradores() {
    try {
        const res = await fetch("/api/moradores");
        const moradores = await res.json();
        
        document.getElementById("statMoradores").innerText = moradores.length;
        document.getElementById("contadorMoradoresTabela").innerText = `Total: ${moradores.length} condôminos`;

        const tbody = document.getElementById("tabelaMoradoresBody");
        if (!tbody) return;

        tbody.innerHTML = moradores.map(m => `
            <tr class="hover:bg-slate-50 transition">
                <td class="p-3 font-bold text-slate-900">
                    <span class="bg-slate-100 text-slate-800 px-2 py-1 rounded">Ap ${escapeHtml(m.apartamento)} - Bl ${escapeHtml(m.bloco)}</span>
                </td>
                <td class="p-3 font-semibold text-slate-800">${escapeHtml(m.nome)}</td>
                <td class="p-3 font-mono text-slate-600">${escapeHtml(m.telefone)}</td>
                <td class="p-3">
                    <span class="text-[10px] font-bold px-2 py-0.5 rounded-full ${m.tipo === 'sindico' ? 'bg-purple-100 text-purple-700' : 'bg-slate-100 text-slate-600'}">
                        ${escapeHtml((m.tipo || '').toUpperCase())}
                    </span>
                </td>
                <td class="p-3 text-right">
                    <button onclick="deletarMorador(${m.id})" class="text-red-500 hover:text-red-700 text-xs p-1" title="Excluir">
                        <i class="fa-solid fa-trash"></i>
                    </button>
                </td>
            </tr>
        `).join("");
    } catch (e) {
        console.error("Erro ao carregar moradores:", e);
    }
}

function filtrarTabelaMoradores() {
    const filtro = document.getElementById("buscaMoradorInput").value.toLowerCase();
    const linhas = document.querySelectorAll("#tabelaMoradoresBody tr");
    linhas.forEach(linha => {
        const texto = linha.innerText.toLowerCase();
        linha.style.display = texto.includes(filtro) ? "" : "none";
    });
}

function abrirModalNovoMorador() {
    document.getElementById("modalNovoMorador").classList.remove("hidden");
}
function fecharModalNovoMorador() {
    document.getElementById("modalNovoMorador").classList.add("hidden");
}

async function salvarNovoMorador() {
    const nome = document.getElementById("novoMoradorNome").value.trim();
    const tel = document.getElementById("novoMoradorTel").value.trim();
    const ap = document.getElementById("novoMoradorAp").value.trim();
    const bloco = document.getElementById("novoMoradorBloco").value.trim();

    if (!nome || !tel || !ap || !bloco) {
        alert("Preencha todos os campos.");
        return;
    }

    try {
        const res = await fetch("/api/moradores", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ nome, telefone: tel, apartamento: ap, bloco })
        });
        if (res.ok) {
            fecharModalNovoMorador();
            exibirToast("Morador cadastrado com sucesso!");
            carregarMoradores();
        } else {
            const err = await res.json();
            alert(err.detail || "Erro ao cadastrar.");
        }
    } catch (e) {
        alert("Erro na requisição.");
    }
}

async function deletarMorador(id) {
    if (!confirm("Deseja realmente remover este morador do cadastro?")) return;
    try {
        await fetch(`/api/moradores/${id}`, { method: "DELETE" });
        exibirToast("Morador excluído.");
        carregarMoradores();
    } catch (e) {
        alert("Erro ao excluir.");
    }
}

function abrirModalImportarLote() {
    document.getElementById("modalImportarLote").classList.remove("hidden");
}
function fecharModalImportarLote() {
    document.getElementById("modalImportarLote").classList.add("hidden");
}

async function executarImportacaoLote() {
    const texto = document.getElementById("importarLoteTexto").value.trim();
    if (!texto) return;

    const linhas = texto.split("\n");
    const lista = [];
    linhas.forEach(l => {
        const partes = l.split(",").map(p => p.trim());
        if (partes.length >= 4) {
            lista.push({
                nome: partes[0],
                telefone: partes[1],
                apartamento: partes[2],
                bloco: partes[3]
            });
        }
    });

    if (lista.length === 0) {
        alert("Nenhum registro válido identificado. Siga o formato: Nome, Telefone, Apartamento, Bloco");
        return;
    }

    try {
        const res = await fetch("/api/moradores/importar-lote", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(lista)
        });
        const data = await res.json();
        fecharModalImportarLote();
        exibirToast(`✅ ${data.importados} moradores importados (${data.ignorados} duplicados ignorados)!`);
        carregarMoradores();
    } catch (e) {
        alert("Erro na importação em lote.");
    }
}

// --- ÁREAS COMUNS & ACHADOS ---
async function carregarReservas() {
    try {
        const res = await fetch("/api/reservas");
        const reservas = await res.json();
        document.getElementById("statReservas").innerText = reservas.length;
        
        const container = document.getElementById("listaReservasContainer");
        if (!container) return;

        if (reservas.length === 0) {
            container.innerHTML = `<p class="text-xs text-slate-400 italic">Nenhuma reserva agendada.</p>`;
            return;
        }

        container.innerHTML = reservas.map(r => `
            <div class="p-3 bg-slate-50 border border-slate-200 rounded-xl flex items-center justify-between text-xs">
                <div>
                    <span class="font-extrabold text-slate-900 block">${escapeHtml(r.area)}</span>
                    <span class="text-slate-500">${escapeHtml(r.data_reserva)} • ${escapeHtml(r.periodo)}</span>
                    <span class="block text-[11px] text-indigo-700 font-medium">Reservado por: ${escapeHtml(r.morador_nome)} (Ap ${escapeHtml(r.apartamento)}-${escapeHtml(r.bloco)})</span>
                </div>
                <button onclick="cancelarReserva(${r.id})" class="text-red-500 hover:text-red-700 p-1" title="Cancelar">
                    <i class="fa-solid fa-xmark"></i>
                </button>
            </div>
        `).join("");
    } catch (e) {
        console.error(e);
    }
}

async function cancelarReserva(id) {
    if (!confirm("Cancelar esta reserva?")) return;
    await fetch(`/api/reservas/${id}`, { method: "DELETE" });
    exibirToast("Reserva cancelada.");
    carregarReservas();
}

async function carregarAchados() {
    try {
        const res = await fetch("/api/achados");
        const achados = await res.json();
        const container = document.getElementById("listaAchadosContainer");
        if (!container) return;

        if (achados.length === 0) {
            container.innerHTML = `<p class="text-xs text-slate-400 italic">Nenhum item em achados e perdidos.</p>`;
            return;
        }

        container.innerHTML = achados.map(a => `
            <div class="p-3 bg-slate-50 border border-slate-200 rounded-xl flex items-center justify-between text-xs">
                <div>
                    <span class="font-bold text-slate-900 block">${escapeHtml(a.item)}</span>
                    <span class="text-slate-500">Local: ${escapeHtml(a.local_encontrado)}</span>
                    <span class="block text-[10px] ${a.status === 'Disponível' ? 'text-amber-600 font-bold' : 'text-emerald-600'}">
                        Status: ${escapeHtml(a.status)} ${a.devolvido_para ? `(Devolvido para ${escapeHtml(a.devolvido_para)})` : ''}
                    </span>
                </div>
                ${a.status === 'Disponível' ? `
                    <button onclick="marcarDevolvido(${a.id})" class="px-2 py-1 bg-emerald-600 hover:bg-emerald-500 text-white rounded text-[10px] font-bold">
                        Devolver
                    </button>
                ` : ''}
            </div>
        `).join("");
    } catch (e) {
        console.error(e);
    }
}

async function marcarDevolvido(id) {
    const nome = prompt("Nome do morador ou unidade que retirou o item:");
    if (!nome) return;
    await fetch(`/api/achados/${id}/devolver`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ devolvido_para: nome })
    });
    exibirToast("Item marcado como devolvido.");
    carregarAchados();
}

// --- MONETIZAÇÃO SAAS E PIX OFICIAL BACEN ---
async function carregarPlanos() {
    try {
        const res = await fetch("/api/planos");
        const planos = await res.json();
        const container = document.getElementById("gridPlanosSaaS");
        if (!container) return;

        container.innerHTML = planos.map((p, idx) => `
            <div class="bg-white rounded-2xl border ${idx === 1 ? 'border-brand-500 ring-2 ring-brand-100 shadow-lg' : 'border-slate-200 shadow-sm'} p-6 flex flex-col justify-between space-y-4">
                <div class="space-y-3">
                    ${idx === 1 ? '<span class="bg-brand-500 text-white text-[10px] uppercase font-black px-2.5 py-0.5 rounded-full inline-block">Mais Escolhido</span>' : ''}
                    <h3 class="font-bold text-slate-900 text-base">${p.nome}</h3>
                    <div class="flex items-baseline space-x-1">
                        <span class="text-3xl font-black text-slate-900">R$ ${Number(p.preco).toFixed(0)}</span>
                        <span class="text-xs text-slate-500">/${p.periodo}</span>
                    </div>
                    <ul class="text-xs space-y-2 text-slate-600 pt-2 border-t border-slate-100">
                        ${p.recursos.map(r => `<li class="flex items-center space-x-2"><i class="fa-solid fa-check text-emerald-500"></i><span>${r}</span></li>`).join("")}
                    </ul>
                </div>
                <div class="space-y-2 pt-2">
                    <a href="https://pay.kiwify.com.br/mByEbbl" target="_blank" class="w-full py-2.5 rounded-xl font-bold text-xs bg-emerald-600 hover:bg-emerald-500 text-white shadow transition flex items-center justify-center space-x-1.5 text-center">
                        <i class="fa-solid fa-credit-card"></i>
                        <span>Pagar na Kiwify (Cartão/PIX/Boleto)</span>
                        <i class="fa-solid fa-arrow-up-right-from-square text-[10px]"></i>
                    </a>
                    <button onclick="gerarPixPlano('${p.nome}', ${p.preco})" class="w-full py-2 rounded-xl font-bold text-xs bg-slate-100 hover:bg-slate-200 text-slate-700 transition flex items-center justify-center space-x-2">
                        <i class="fa-solid fa-qrcode text-emerald-600"></i>
                        <span>Ou Ver QR Code & PIX Copia-e-Cola</span>
                    </button>
                </div>
            </div>
        `).join("");
    } catch (e) {
        console.error(e);
    }
}

async function gerarPixPlano(nome, preco) {
    try {
        const res = await fetch("/api/pix/gerar", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                plano_nome: nome,
                valor: preco
            })
        });
        const data = await res.json();

        document.getElementById("pixModalPlanoTitulo").innerText = data.plano;
        document.getElementById("pixModalValor").innerText = `R$ ${Number(data.valor).toFixed(2)}`;
        document.getElementById("pixModalQrImg").src = data.qr_code_url;
        document.getElementById("pixModalCopiaCola").value = data.pix_copia_e_cola;

        if (document.getElementById("btnCheckoutKiwify")) {
            document.getElementById("btnCheckoutKiwify").href = data.link_kiwify || "https://pay.kiwify.com.br/mByEbbl";
        }
        if (document.getElementById("modalBoletoLinha")) {
            document.getElementById("modalBoletoLinha").value = data.boleto_linha || "";
        }
        if (document.getElementById("btnLinkCartaoExterno")) {
            document.getElementById("btnLinkCartaoExterno").href = data.link_cartao || "https://mpago.la/pos/conciliazap";
        }
        if (document.getElementById("btnZapComercial")) {
            document.getElementById("btnZapComercial").href = data.whatsapp_link || `https://wa.me/${data.whatsapp_vendas || '5511999998888'}`;
        }

        selecionarFormaPagamento('kiwify');
        document.getElementById("modalPix").classList.remove("hidden");
    } catch (e) {
        alert("Erro ao carregar opções de pagamento.");
    }
}

function selecionarFormaPagamento(tipo) {
    const abas = ['kiwify', 'pix', 'cartao', 'boleto', 'zap'];
    abas.forEach(aba => {
        const btn = document.getElementById(`btnTab${aba.charAt(0).toUpperCase() + aba.slice(1)}`);
        const conteudo = document.getElementById(`tabConteudo${aba.charAt(0).toUpperCase() + aba.slice(1)}`);
        if (btn && conteudo) {
            if (aba === tipo) {
                if (aba === 'kiwify') {
                    btn.className = "py-2 rounded-lg bg-emerald-600 text-white shadow-sm transition flex flex-col items-center justify-center space-y-0.5";
                } else {
                    btn.className = "py-2 rounded-lg bg-white text-emerald-700 shadow-sm transition flex flex-col items-center justify-center space-y-0.5";
                }
                conteudo.classList.remove("hidden");
            } else {
                btn.className = "py-2 rounded-lg text-slate-600 hover:text-slate-900 transition flex flex-col items-center justify-center space-y-0.5";
                conteudo.classList.add("hidden");
            }
        }
    });
}

function copiarKiwifyWebhook() {
    const el = document.getElementById("kiwifyWebhookDisplay");
    navigator.clipboard.writeText(el.innerText);
    exibirToast("URL do Webhook Kiwify copiada com sucesso!");
}

function simularPagamentoCartao() {
    exibirToast("💳 Pagamento com Cartão APROVADO com sucesso!");
    setTimeout(() => {
        fecharModalPix();
    }, 1500);
}

function copiarBoletoLinha() {
    const input = document.getElementById("modalBoletoLinha");
    if (!input) return;
    input.select();
    navigator.clipboard.writeText(input.value);
    exibirToast("Linha digitável do boleto copiada com sucesso!");
}

function fecharModalPix() {
    document.getElementById("modalPix").classList.add("hidden");
}

function copiarPixPayload() {
    const input = document.getElementById("pixModalCopiaCola");
    input.select();
    navigator.clipboard.writeText(input.value);
    exibirToast("Código PIX Copia e Cola copiado com sucesso!");
}

function copiarWebhookUrl() {
    const el = document.getElementById("webhookUrlDisplay");
    navigator.clipboard.writeText(el.innerText);
    exibirToast("URL do Webhook copiada!");
}

// --- CONFIGURAÇÕES & CONTA PIX (LUCIANO) ---
async function carregarConfiguracoes() {
    try {
        const res = await fetch("/api/config");
        const cfg = await res.json();
        if (cfg.nome_condominio) {
            document.getElementById("cfgNomeCondominio").value = cfg.nome_condominio;
            document.getElementById("headerCondoName").innerText = cfg.nome_condominio;
        }
        if (cfg.horario_silencio) document.getElementById("cfgHorarioSilencio").value = cfg.horario_silencio;
        if (cfg.sindico_whatsapp) document.getElementById("cfgSindicoWhats").value = cfg.sindico_whatsapp;
        if (cfg.evolution_api_url) document.getElementById("cfgApiUrl").value = cfg.evolution_api_url;
        if (cfg.whatsapp_instancia) document.getElementById("cfgInstancia").value = cfg.whatsapp_instancia;
        if (cfg.evolution_api_key) document.getElementById("cfgApiKey").value = cfg.evolution_api_key;
        
        // Dados do PIX, Kiwify e Formas de Pagamento do Luciano
        const chavePix = cfg.chave_pix || "luciano@conciliazap.com.br";
        const nomeRecebedor = cfg.nome_recebedor || "Luciano";
        const cidadeRecebedor = cfg.cidade_recebedor || "SAO PAULO";
        const linkCartao = cfg.link_cartao || "https://mpago.la/pos/conciliazap";
        const linkKiwify = cfg.link_kiwify || "https://pay.kiwify.com.br/mByEbbl";
        const whatsVendas = cfg.whatsapp_vendas || "5511999998888";

        if (document.getElementById("cfgChavePix")) document.getElementById("cfgChavePix").value = chavePix;
        if (document.getElementById("cfgNomeRecebedor")) document.getElementById("cfgNomeRecebedor").value = nomeRecebedor;
        if (document.getElementById("cfgCidadeRecebedor")) document.getElementById("cfgCidadeRecebedor").value = cidadeRecebedor;
        if (document.getElementById("cfgLinkCartao")) document.getElementById("cfgLinkCartao").value = linkCartao;
        if (document.getElementById("cfgLinkKiwify")) document.getElementById("cfgLinkKiwify").value = linkKiwify;
        if (document.getElementById("cfgWhatsVendas")) document.getElementById("cfgWhatsVendas").value = whatsVendas;

        if (document.getElementById("kiwifyWebhookDisplay")) {
            document.getElementById("kiwifyWebhookDisplay").innerText = `${window.location.origin}/api/webhook/kiwify`;
        }

        const infoPix = document.getElementById("infoPixDisplay");
        if (infoPix) {
            infoPix.innerHTML = `<strong class="text-emerald-950">${escapeHtml(nomeRecebedor)}</strong> • Kiwify: <span class="font-mono bg-emerald-100 text-emerald-800 px-1.5 py-0.5 rounded text-[11px]">${escapeHtml(linkKiwify)}</span> | PIX: <span class="font-mono bg-emerald-100 text-emerald-800 px-1.5 py-0.5 rounded">${escapeHtml(chavePix)}</span>`;
        }
    } catch (e) {
        console.error("Erro ao carregar configurações:", e);
    }
}

async function salvarConfiguracoes() {
    const payload = {
        nome_condominio: document.getElementById("cfgNomeCondominio").value.trim(),
        horario_silencio: document.getElementById("cfgHorarioSilencio").value.trim(),
        sindico_whatsapp: document.getElementById("cfgSindicoWhats").value.trim(),
        evolution_api_url: document.getElementById("cfgApiUrl").value.trim(),
        whatsapp_instancia: document.getElementById("cfgInstancia").value.trim(),
        evolution_api_key: document.getElementById("cfgApiKey").value.trim(),
        chave_pix: (document.getElementById("cfgChavePix")?.value || "").trim(),
        nome_recebedor: (document.getElementById("cfgNomeRecebedor")?.value || "Luciano").trim(),
        cidade_recebedor: (document.getElementById("cfgCidadeRecebedor")?.value || "SAO PAULO").trim(),
        link_cartao: (document.getElementById("cfgLinkCartao")?.value || "").trim(),
        link_kiwify: (document.getElementById("cfgLinkKiwify")?.value || "").trim(),
        whatsapp_vendas: (document.getElementById("cfgWhatsVendas")?.value || "").trim()
    };

    try {
        await fetch("/api/config", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });
        document.getElementById("headerCondoName").innerText = payload.nome_condominio;
        
        const infoPix = document.getElementById("infoPixDisplay");
        if (infoPix) {
            infoPix.innerHTML = `<strong class="text-emerald-950">${escapeHtml(payload.nome_recebedor)}</strong> • Kiwify: <span class="font-mono bg-emerald-100 text-emerald-800 px-1.5 py-0.5 rounded text-[11px]">${escapeHtml(payload.link_kiwify)}</span> | PIX: <span class="font-mono bg-emerald-100 text-emerald-800 px-1.5 py-0.5 rounded">${escapeHtml(payload.chave_pix)}</span>`;
        }

        exibirToast("✅ Configurações e Link Kiwify salvos com sucesso!");
    } catch (e) {
        alert("Erro ao salvar configurações.");
    }
}

// --- UTILITÁRIOS ---
function exibirToast(msg) {
    const toast = document.getElementById("toast");
    const toastMsg = document.getElementById("toastMsg");
    if (!toast || !toastMsg) return;
    toastMsg.innerText = msg;
    toast.classList.remove("translate-y-20", "opacity-0");
    setTimeout(() => {
        toast.classList.add("translate-y-20", "opacity-0");
    }, 4000);
}

// --- DIVULGAÇÃO AOS MORADORES (GRUPO DE WHATSAPP & CARTAZ) ---
function abrirModalDivulgacao() {
    const nomeCondo = document.getElementById("headerCondoName")?.innerText || "Condomínio Colinas de Campo Grande";
    const whats = (document.getElementById("cfgSindicoWhats")?.value || "5511999990001").replace(/\D/g, "");
    const linkWa = `https://wa.me/${whats}?text=Ol%C3%A1%20ConciliaZap!%20Sou%20morador`;

    const texto = `📢 *COMUNICADO OFICIAL DO CONDOMÍNIO*

Prezados moradores do *${nomeCondo}*!

A partir de hoje, nosso condomínio conta com a *Portaria Digital ConciliaZap 24 Horas*.

Agora você resolve as rotinas do condomínio direto pelo seu WhatsApp:
🔇 *Registro Sigiloso de Barulho:* Resolva perturbações com 100% de sigilo (sua identidade NUNCA é revelada ao vizinho);
📅 *Reserva de Áreas Comuns:* Agende churrasqueira e salão de festas pelo WhatsApp;
📦 *Achados & Perdidos:* Consulte encomendas e objetos deixados na portaria.

👉 *Para começar a usar agora, basta clicar no link abaixo e enviar um "Oi":*
${linkWa}

📱 *Não precisa baixar nenhum aplicativo!* Funciona 100% direto no seu WhatsApp.

Atenciosamente,
*Administração do Condomínio*`;

    const textarea = document.getElementById("textoComunicadoZap");
    if (textarea) textarea.value = texto;

    document.getElementById("modalDivulgacao").classList.remove("hidden");
}

function fecharModalDivulgacao() {
    document.getElementById("modalDivulgacao").classList.add("hidden");
}

function copiarComunicadoZap() {
    const textarea = document.getElementById("textoComunicadoZap");
    if (!textarea) return;
    textarea.select();
    navigator.clipboard.writeText(textarea.value);
    exibirToast("📋 Mensagem copiada! Cole no grupo de WhatsApp dos moradores.");
}
