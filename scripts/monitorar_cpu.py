
import csv
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

SERVICOS = [
    "customers-service",
    "vets-service",
    "api-gateway",
]

TIMEOUT_DOCKER = 10
INTERVALO_COLETA = 2


def coletar_cpu():
  
    comando = [
        "docker",
        "stats",
        "--no-stream",
        "--format",
        "{{json .}}",
    ]

    resultado = subprocess.run(
        comando,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
        timeout=TIMEOUT_DOCKER,
    )

    valores = {}

    for linha in resultado.stdout.splitlines():
        if not linha.strip():
            continue

        dado = json.loads(linha)

        nome = dado.get("Name", "")
        cpu = dado.get("CPUPerc")

        if nome not in SERVICOS:
            continue

        if cpu is None:
            continue

        cpu = str(cpu).strip().replace("%", "")
        cpu = cpu.replace(",", ".")

        if not cpu:
            continue

        valores[nome] = float(cpu)

    return valores


def monitorar(duracao, arquivo, intervalo=INTERVALO_COLETA):

    if duracao <= 0:
        raise ValueError("A duracao deve ser maior que zero.")

    if intervalo <= 0:
        raise ValueError("O intervalo deve ser maior que zero.")

    destino = Path(arquivo)
    destino.parent.mkdir(parents=True, exist_ok=True)

    campos = [
        "timestamp",
        "tempo_s",
        *SERVICOS,
    ]

    inicio = time.monotonic()
    total_amostras = 0
    coletas_com_problemas = 0

    print(
        f"Iniciando monitoramento de CPU por {duracao} segundos.",
        flush=True,
    )

    with destino.open(
        "w",
        newline="",
        encoding="utf-8",
    ) as arquivo_csv:

        escritor = csv.DictWriter(
            arquivo_csv,
            fieldnames=campos,
        )

        escritor.writeheader()
        arquivo_csv.flush()

        while True:
            tempo_inicio_coleta = time.monotonic()
            tempo_decorrido = tempo_inicio_coleta - inicio

            if tempo_decorrido >= duracao:
                break

            valores = {}

            try:
                valores = coletar_cpu()

                faltantes = [
                    servico
                    for servico in SERVICOS
                    if servico not in valores
                ]

                if faltantes:
                    coletas_com_problemas += 1

                    print(
                        "Aviso: dados de CPU ausentes para: "
                        + ", ".join(faltantes),
                        flush=True,
                    )

            except subprocess.TimeoutExpired:
                coletas_com_problemas += 1

                print(
                    "Aviso: docker stats excedeu "
                    f"{TIMEOUT_DOCKER} segundos.",
                    flush=True,
                )

            except subprocess.CalledProcessError as erro:
                coletas_com_problemas += 1

                print(
                    "Aviso: falha no docker stats. "
                    f"Codigo de saida: {erro.returncode}",
                    flush=True,
                )

            except (
                json.JSONDecodeError,
                ValueError,
                TypeError,
                OSError,
            ) as erro:
                coletas_com_problemas += 1

                print(
                    f"Aviso: erro na coleta de CPU: {erro}",
                    flush=True,
                )
                
            instante_coleta = datetime.now(timezone.utc)
            tempo_registro = time.monotonic() - inicio

            registro = {
                "timestamp": instante_coleta.isoformat(),
                "tempo_s": round(tempo_registro, 2),
            }

            for servico in SERVICOS:
                registro[servico] = valores.get(servico, "")

            escritor.writerow(registro)
            arquivo_csv.flush()

            total_amostras += 1

            # Manter o intervalo sem ultrapassar a duracao.
            tempo_atual = time.monotonic()
            restante = duracao - (tempo_atual - inicio)

            if restante <= 0:
                break

            tempo_gasto = tempo_atual - tempo_inicio_coleta

            espera = max(0, intervalo - tempo_gasto)

            if espera > 0:
                time.sleep(min(espera, restante))

    print(
        f"Monitoramento concluido: {destino}",
        flush=True,
    )

    print(
        f"Total de amostras: {total_amostras}",
        flush=True,
    )

    print(
        f"Coletas com problemas: {coletas_com_problemas}",
        flush=True,
    )


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(
            "Uso: python monitorar_cpu.py "
            "<duracao_segundos> <arquivo.csv>"
        )
        sys.exit(1)

    try:
        duracao = int(sys.argv[1])
        arquivo_saida = sys.argv[2]

        monitorar(
            duracao,
            arquivo_saida,
        )

    except (ValueError, OSError) as erro:
        print(
            f"Erro no monitoramento: {erro}",
            file=sys.stderr,
            flush=True,
        )
        sys.exit(1)
