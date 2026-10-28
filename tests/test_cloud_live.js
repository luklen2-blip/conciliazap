import https from 'https';
import http from 'http';

const targetUrl = process.argv[2];
if (!targetUrl) {
    console.log("Uso: node tests/test_cloud_live.js <URL>");
    process.exit(1);
}

const client = targetUrl.startsWith('https') ? https : http;
const options = {
    rejectUnauthorized: false
};

console.log(`Validando URL de nuvem: ${targetUrl}/api/health`);
client.get(`${targetUrl}/api/health`, options, (res) => {
    let raw = '';
    res.on('data', chunk => raw += chunk);
    res.on('end', () => {
        try {
            const data = JSON.parse(raw);
            if (res.statusCode === 200 && data.status === 'ok') {
                console.log("✅ [LIVE PASS] Health check respondendo 100%:", data);
                process.exit(0);
            } else {
                console.error("❌ [LIVE FAIL] Resposta inesperada:", res.statusCode, raw);
                process.exit(1);
            }
        } catch (e) {
            console.error("❌ [LIVE FAIL] Erro ao parsear JSON:", raw);
            process.exit(1);
        }
    });
}).on('error', (err) => {
    console.error("❌ [LIVE ERROR] Falha de conexão:", err.message);
    process.exit(1);
});
