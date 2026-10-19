
import csv
import re
import statistics
from collections import defaultdict
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
CSV_DIR = RAIZ / "results" / "csv"
CPU_DIR = RAIZ / "results" / "cpu"
TABELAS = RAIZ / "results" / "tabelas"

TABELAS.mkdir(parents=True, exist_ok=True)

PADRAO = re.compile(
    r"^(leitura|escrita)_cenario_([ABC])_(30|80|150)u_rep_(\d{2})_stats\.csv$"
)

SERVICOS = [
    "customers-service",
    "vets-service",
    "api-gateway",
]


def numero(valor):
    return float(str(valor).replace(",", "."))


def ler_csv(caminho):
    with caminho.open(
        "r", encoding="utf-8-sig", newline=""
    ) as arquivo:
        return list(csv.DictReader(arquivo))



def calcular_cpu(caminho):
    if not caminho.exists():
        raise ValueError("CSV de CPU ausente.")

    registros = ler_csv(caminho)
    valores = {servico: [] for servico in SERVICOS}

    nome = caminho.name.removesuffix("_cpu.csv")
    historico = CSV_DIR / f"{nome}_stats_history.csv"

    if not historico.exists():
        raise ValueError("Historico do Locust ausente.")

    registros_locust = ler_csv(historico)

    agregados = [
        r for r in registros_locust
        if r["Name"] == "Aggregated"
    ]

    if not agregados:
        raise ValueError("Historico sem registros agregados.")

    inicio_locust = min(
        int(r["Timestamp"]) for r in agregados
    )

    fim_locust = max(
        int(r["Timestamp"]) for r in agregados
    )

    inicio_medicao = inicio_locust + 60

    if fim_locust - inicio_locust < 350:
        raise ValueError("Duracao total insuficiente.")

    for registro in registros:
        from datetime import datetime

        instante = datetime.fromisoformat(
            registro["timestamp"]
        ).timestamp()

        if not inicio_medicao <= instante <= fim_locust:
            continue

        for servico in SERVICOS:
            valores[servico].append(
                numero(registro[servico])
            )

    if any(len(valores[s]) < 40 for s in SERVICOS):
        raise ValueError(
            "Quantidade insuficiente de amostras de CPU."
        )

    return {
        servico: statistics.mean(valores[servico])
        for servico in SERVICOS
    }

def analisar_execucao(caminho):
    correspondencia = PADRAO.match(caminho.name)

    if not correspondencia:
        return None

    perfil, cenario, usuarios, repeticao = (
        correspondencia.groups()
    )

    prefixo = caminho.name.removesuffix("_stats.csv")
    cpu_path = CPU_DIR / f"{prefixo}_cpu.csv"
    log_path = CSV_DIR / f"{prefixo}.log"

    if not log_path.exists():
        raise ValueError("Log ausente.")

    log = log_path.read_text(
        encoding="utf-8", errors="replace"
    )

    if "Aquecimento de 60s descartado" not in log:
        raise ValueError("Aquecimento nao confirmado.")

    registros = ler_csv(caminho)

    agregado = next(
        (r for r in registros if r["Name"] == "Aggregated"),
        None
    )

    if agregado is None:
        raise ValueError("Linha agregada ausente.")

    cpu = calcular_cpu(cpu_path)

    requisicoes = numero(agregado["Request Count"])
    falhas = numero(agregado["Failure Count"])

    if requisicoes <= 0:
        raise ValueError("Nenhuma requisicao registrada.")

    return {
        "execucao": prefixo,
        "perfil": perfil,
        "cenario": cenario,
        "usuarios": int(usuarios),
        "repeticao": int(repeticao),
        "requisicoes": requisicoes,
        "tempo_medio_ms": numero(
            agregado["Average Response Time"]
        ),
        "p95_ms": numero(agregado["95%"]),
        "requisicoes_s": numero(
            agregado["Requests/s"]
        ),
        "falhas_percentual": falhas / requisicoes * 100,
        "cpu_customers": cpu["customers-service"],
        "cpu_vets": cpu["vets-service"],
        "cpu_gateway": cpu["api-gateway"],
    }


def salvar_tabela(caminho, linhas):
    if not linhas:
        return

    with caminho.open(
        "w", encoding="utf-8-sig", newline=""
    ) as arquivo:
        escritor = csv.DictWriter(
            arquivo, fieldnames=list(linhas[0])
        )
        escritor.writeheader()
        escritor.writerows(linhas)


def main():
    execucoes = []
    problemas = []

    for caminho in sorted(CSV_DIR.glob("*_stats.csv")):
        if not PADRAO.match(caminho.name):
            continue

        try:
            resultado = analisar_execucao(caminho)

            if resultado:
                execucoes.append(resultado)

        except (ValueError, KeyError, OSError) as erro:
            problemas.append({
                "arquivo": caminho.name,
                "problema": str(erro)
            })

    if not execucoes:
        print("Nenhuma execucao valida encontrada.")
        return

    salvar_tabela(
        TABELAS / "resultados_por_execucao.csv",
        execucoes
    )

    grupos = defaultdict(list)

    for execucao in execucoes:
        chave = (
            execucao["perfil"],
            execucao["cenario"],
            execucao["usuarios"]
        )
        grupos[chave].append(execucao)

    campos = [
        "requisicoes",
        "tempo_medio_ms",
        "p95_ms",
        "requisicoes_s",
        "falhas_percentual",
        "cpu_customers",
        "cpu_vets",
        "cpu_gateway",
    ]

    resumo = []

    for chave, registros in sorted(grupos.items()):
        perfil, cenario, usuarios = chave

        linha = {
            "perfil": perfil,
            "cenario": cenario,
            "usuarios": usuarios,
            "repeticoes": len(registros),
        }

        for campo in campos:
            linha[campo] = round(
                statistics.mean(
                    r[campo] for r in registros
                ), 4
            )

        resumo.append(linha)

    salvar_tabela(
        TABELAS / "resumo_por_cenario.csv",
        resumo
    )

    if problemas:
        salvar_tabela(
            TABELAS / "execucoes_com_problemas.csv",
            problemas
        )

    print("\nANALISE DOS EXPERIMENTOS")
    print("-" * 55)

    for linha in resumo:
        print(
            f"{linha['perfil']:8} "
            f"Cenario {linha['cenario']} "
            f"({linha['usuarios']} usuarios): "
            f"{linha['repeticoes']}/10 repeticoes"
        )

    print(f"\nExecucoes analisadas: {len(execucoes)}/60")
    print(f"Execucoes com problemas: {len(problemas)}")
    print(f"Tabelas salvas em: {TABELAS}")


if __name__ == "__main__":
    main()
