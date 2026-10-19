import argparse
import csv
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

RAIZ = Path(__file__).resolve().parent.parent
PYTHON = sys.executable
COMPOSE = RAIZ / "spring-petclinic-microservices"
CSV_DIR = RAIZ / "results" / "csv"
CPU_DIR = RAIZ / "results" / "cpu"
MANIFESTO = RAIZ / "results" / "execucoes.csv"

DURACAO = 360
AQUECIMENTO = 60
SPAWN_RATE = 10
REPETICOES = 10
HOST = "http://localhost:8080"
PERFIS = {"leitura": "PerfilLeitura", "escrita": "PerfilEscrita"}
CENARIOS = {"A": 30, "B": 80, "C": 150}
SERVICOS = ("customers-service", "vets-service", "api-gateway")


def ler_csv(caminho):
    with caminho.open("r", encoding="utf-8-sig", newline="") as arquivo:
        return list(csv.DictReader(arquivo))


def nome_execucao(perfil, cenario, repeticao):
    return f"{perfil}_cenario_{cenario}_{CENARIOS[cenario]}u_rep_{repeticao:02d}"


def arquivos_execucao(nome):
    return [
        CSV_DIR / f"{nome}.log",
        CSV_DIR / f"{nome}_stats.csv",
        CSV_DIR / f"{nome}_stats_history.csv",
        CSV_DIR / f"{nome}_failures.csv",
        CSV_DIR / f"{nome}_exceptions.csv",
        CPU_DIR / f"{nome}_cpu.csv",
    ]


def validar_coleta(nome):
    log, stats, historico, falhas_csv, excecoes_csv, cpu = arquivos_execucao(nome)
    if any(not p.is_file() for p in (log, stats, historico, cpu)):
        raise ValueError("Arquivos obrigatorios ausentes.")

    texto = log.read_text(encoding="utf-8", errors="replace")
    if f"Aquecimento de {AQUECIMENTO}s descartado" not in texto:
        raise ValueError("Reset do aquecimento nao confirmado no log.")

    registros = ler_csv(stats)
    agregado = next((r for r in registros if r.get("Name") == "Aggregated"), None)
    if agregado is None or int(agregado["Request Count"]) <= 0:
        raise ValueError("Estatisticas agregadas ausentes ou vazias.")

    historico_agregado = [
        r for r in ler_csv(historico) if r.get("Name") == "Aggregated"
    ]
    if len(historico_agregado) < 100:
        raise ValueError("Historico insuficiente.")

    historico_agregado.sort(key=lambda r: int(r["Timestamp"]))
    inicio = int(historico_agregado[0]["Timestamp"])
    fim = int(historico_agregado[-1]["Timestamp"])
    if not 350 <= fim - inicio <= 380:
        raise ValueError(f"Duracao do historico inesperada: {fim - inicio}s.")

    antes = [
        int(r["Total Request Count"])
        for r in historico_agregado
        if 50 <= int(r["Timestamp"]) - inicio <= 59
    ]
    depois = [
        int(r["Total Request Count"])
        for r in historico_agregado
        if 60 <= int(r["Timestamp"]) - inicio <= 65
    ]
    if not antes or not depois or min(depois) >= max(antes):
        raise ValueError("Nao foi possivel confirmar o reset no historico.")

    if not any(
        int(r["Total Request Count"]) > 0
        for r in historico_agregado
        if int(r["Timestamp"]) - inicio >= 70
    ):
        raise ValueError("Sem requisicoes registradas apos aquecimento.")

    # O CSV de CPU tem timestamps ISO-8601 em UTC; nao depende do
    # tempo relativo de inicio do processo de monitoramento.
    amostras = ler_csv(cpu)
    tempos_validos = []
    for registro in amostras:
        instante = datetime.fromisoformat(registro["timestamp"]).timestamp()
        if inicio + AQUECIMENTO <= instante <= fim:
            for servico in SERVICOS:
                float(registro[servico])
            tempos_validos.append(instante)

    if len(tempos_validos) < 40:
        raise ValueError("Quantidade insuficiente de amostras de CPU.")
    if max(tempos_validos) - min(tempos_validos) < 240:
        raise ValueError("Cobertura temporal de CPU insuficiente.")
    return True


def verificar_base():
    inicio_estavel = None
    limite = time.monotonic() + 240
    ultimo_erro = "API indisponivel"

    while time.monotonic() < limite:
        try:
            resposta = requests.get(
                HOST + "/api/customer/owners",
                timeout=10
            )

            if resposta.status_code != 200:
                raise RuntimeError(
                    f"GET owners retornou HTTP {resposta.status_code}"
                )

            dados = resposta.json()

            if not isinstance(dados, list) or len(dados) != 10:
                raise RuntimeError("Quantidade incorreta de proprietarios.")

            ids = {int(item["id"]) for item in dados}

            if ids != set(range(1, 11)):
                raise RuntimeError("IDs iniciais incorretos.")

            for rota in [
                "/api/customer/owners/1",
                "/api/vet/vets",
            ]:
                resposta = requests.get(HOST + rota, timeout=10)

                if resposta.status_code != 200:
                    raise RuntimeError(
                        f"{rota} retornou HTTP {resposta.status_code}"
                    )

            if inicio_estavel is None:
                inicio_estavel = time.monotonic()

            if time.monotonic() - inicio_estavel >= 30:
                print(
                    "API estavel por 30 segundos consecutivos.",
                    flush=True
                )
                return

        except (
            requests.RequestException,
            ValueError,
            KeyError,
            TypeError,
            RuntimeError,
        ) as erro:
            ultimo_erro = str(erro)
            inicio_estavel = None

        time.sleep(2)

    raise RuntimeError(
        f"API nao estabilizou: {ultimo_erro}"
    )


def restaurar_base():
    print("Restaurando a base inicial...", flush=True)

    subprocess.run(
        [
            "docker", "compose", "up", "-d",
            "--force-recreate",
            "--no-deps",
            "customers-service"
        ],
        cwd=COMPOSE,
        check=True,
    )

    verificar_base()

    print(
        "Base restaurada e API estabilizada.",
        flush=True
    )

def registrar_execucao(nome, perfil, usuarios, retorno, situacao):
    novo = not MANIFESTO.exists() or MANIFESTO.stat().st_size == 0
    with MANIFESTO.open("a", newline="", encoding="utf-8") as arquivo:
        escritor = csv.writer(arquivo)
        if novo:
            escritor.writerow([
                "execucao", "perfil", "usuarios", "duracao_s", "aquecimento_s",
                "codigo_saida", "situacao", "data_hora"
            ])
        escritor.writerow([
            nome, perfil, usuarios, DURACAO, AQUECIMENTO,
            retorno, situacao, datetime.now().isoformat()
        ])



def ja_concluida(nome):
    if not MANIFESTO.exists():
        return False

    registros = ler_csv(MANIFESTO)

    registros_execucao = [
        r for r in registros
        if r.get("execucao") == nome
    ]

    if not registros_execucao:
        return False

    ultimo = registros_execucao[-1]

    situacao = ultimo.get("situacao")
    codigo = ultimo.get("codigo_saida")

    # Aceita coleta concluida normalmente.
    # Tambem aceita codigo 1 quando a coleta terminou
    # integralmente e os arquivos passaram na validacao.
    if not (
        (situacao == "COLETA_CONCLUIDA" and codigo == "0")
        or (situacao == "VERIFICAR" and codigo == "1")
    ):
        return False

    try:
        validar_coleta(nome)

        if situacao == "VERIFICAR":
            log_path = CSV_DIR / f"{nome}.log"
            log = log_path.read_text(
                encoding="utf-8", errors="replace"
            )

            if "--run-time limit reached" not in log:
                return False

            if "Shutting down (exit code 1)" not in log:
                return False

            print(
                f"Coleta completa com falhas HTTP preservadas: {nome}",
                flush=True,
            )

        return True

    except (ValueError, KeyError, OSError, IndexError):
        return False

def executar(perfil, cenario, repeticao):
    usuarios = CENARIOS[cenario]
    classe = PERFIS[perfil]
    nome = nome_execucao(perfil, cenario, repeticao)

    if ja_concluida(nome):
        print(f"Execucao ja concluida: {nome}. Pulando.", flush=True)
        return

    if any(p.exists() for p in arquivos_execucao(nome)):
        raise FileExistsError(
            f"Existem arquivos anteriores/incompletos para {nome}. "
            "Verifique-os antes de continuar; nada sera sobrescrito."
        )

    print(f"\nIniciando: {nome}", flush=True)
    restaurar_base()

    prefixo = CSV_DIR / nome
    log_path = CSV_DIR / f"{nome}.log"
    cpu_path = CPU_DIR / f"{nome}_cpu.csv"
    ambiente = os.environ.copy()
    ambiente["LOCUST_WARMUP_SECONDS"] = str(AQUECIMENTO)

    comando_locust = [
        PYTHON, "-m", "locust", "-f", str(RAIZ / "locustfile.py"),
        "--headless", "--host", HOST, "--users", str(usuarios),
        "--spawn-rate", str(SPAWN_RATE), "--run-time", f"{DURACAO}s",
        "--csv", str(prefixo), "--csv-full-history","--exit-code-on-error", "0", classe,
    ]
    comando_cpu = [
        PYTHON, str(RAIZ / "scripts" / "monitorar_cpu.py"),
        str(DURACAO), str(cpu_path),
    ]

    processo_cpu = None
    retorno = -1
    situacao = "VERIFICAR"
    try:
        with log_path.open("w", encoding="utf-8") as log:
            processo_cpu = subprocess.Popen(comando_cpu, cwd=RAIZ)
            resultado = subprocess.run(
                comando_locust, cwd=RAIZ, env=ambiente,
                stdout=log, stderr=subprocess.STDOUT,
            )
            retorno = resultado.returncode

        if processo_cpu.poll() is None:
            processo_cpu.wait(timeout=30)

        if retorno != 0:
            raise RuntimeError(f"Locust terminou com codigo {retorno}.")
        if processo_cpu.returncode != 0:
            raise RuntimeError("Monitor de CPU terminou com erro.")

        validar_coleta(nome)
        situacao = "COLETA_CONCLUIDA"
        print(f"Resultado: {situacao}", flush=True)

    except Exception as erro:
        print(f"Resultado: VERIFICAR - {erro}", flush=True)
        raise

    finally:
        if processo_cpu is not None and processo_cpu.poll() is None:
            processo_cpu.terminate()
            try:
                processo_cpu.wait(timeout=10)
            except subprocess.TimeoutExpired:
                processo_cpu.kill()
                processo_cpu.wait()
        if log_path.exists():
            registrar_execucao(nome, perfil, usuarios, retorno, situacao)


def main():
    parser = argparse.ArgumentParser(description="Experimentos Locust - Trabalho 06")
    parser.add_argument(
        "--modo", choices=["planejar", "unico", "lote", "todos"], default="planejar"
    )
    parser.add_argument("--perfil", choices=list(PERFIS), default="leitura")
    parser.add_argument("--cenario", choices=list(CENARIOS), default="A")
    parser.add_argument("--repeticao", type=int, default=1)
    parser.add_argument("--quantidade", type=int, default=10,
                        help="Numero de novas execucoes no modo lote (1 a 60).")
    args = parser.parse_args()

    CSV_DIR.mkdir(parents=True, exist_ok=True)
    CPU_DIR.mkdir(parents=True, exist_ok=True)

    if args.modo == "planejar":
        for perfil in PERFIS:
            for cenario, usuarios in CENARIOS.items():
                print(
                    f"{perfil}: cenario {cenario}, {usuarios} usuarios, "
                    f"{REPETICOES} repeticoes"
                )
        print(f"Total: {len(PERFIS) * len(CENARIOS) * REPETICOES} execucoes.")
        return

    if args.modo == "unico":
        if not 1 <= args.repeticao <= REPETICOES:
            parser.error("Repeticao deve estar entre 1 e 10.")
        executar(args.perfil, args.cenario, args.repeticao)
        return

    if args.modo == "lote":
        if not 1 <= args.quantidade <= 60:
            parser.error("--quantidade deve estar entre 1 e 60.")
        feitas = 0
        for perfil in PERFIS:
            for cenario in CENARIOS:
                for repeticao in range(1, REPETICOES + 1):
                    nome = nome_execucao(perfil, cenario, repeticao)
                    if ja_concluida(nome):
                        print(f"Execucao ja concluida: {nome}. Pulando.", flush=True)
                        continue
                    executar(perfil, cenario, repeticao)
                    feitas += 1
                    print(f"Progresso deste lote: {feitas}/{args.quantidade}", flush=True)
                    if feitas >= args.quantidade:
                        print("Lote concluido. Voce pode retomar outro dia.", flush=True)
                        return
        print(f"Todas as execucoes pendentes concluidas ({feitas} neste lote).")
        return

    for perfil in PERFIS:
        for cenario in CENARIOS:
            for repeticao in range(1, REPETICOES + 1):
                executar(perfil, cenario, repeticao)


if __name__ == "__main__":
    main()
