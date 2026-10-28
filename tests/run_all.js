// Runner de testes em Node.js (ESM) para suporte universal a Docker / Render
import { execSync } from 'child_process';

console.log("Executando suíte de testes de integridade do ConciliaZap via Python...");
try {
    execSync("python tests/run_all.py", { stdio: "inherit" });
    process.exit(0);
} catch (error) {
    console.error("Falha na execução dos testes:", error.message);
    process.exit(1);
}
