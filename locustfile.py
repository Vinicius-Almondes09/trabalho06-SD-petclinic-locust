
import os
import random
import uuid

import gevent
from locust import HttpUser, between, events, task


# Endpoints validados na Etapa 2
OWNERS = "/api/customer/owners"
VETS = "/api/vet/vets"

# IDs existentes na base inicial do PetClinic
OWNER_IDS = list(range(1, 11))

def verificar_get(usuario, caminho, nome, espera_lista=False):
    with usuario.client.get(
        caminho,
        name=nome,
        catch_response=True
    ) as resposta:

        if resposta.status_code != 200:
            resposta.failure(
                f"HTTP {resposta.status_code}; esperado 200"
            )
            return

        try:
            dados = resposta.json()

            if espera_lista and not isinstance(dados, list):
                resposta.failure(
                    "Resposta nao e uma lista JSON"
                )

            elif not espera_lista and not isinstance(dados, dict):
                resposta.failure(
                    "Resposta nao e um objeto JSON"
                )

            else:
                resposta.success()

        except ValueError:
            resposta.failure("Resposta JSON invalida")

def consultar_proprietarios(usuario):
    verificar_get(
        usuario,
        OWNERS,
        "GET /owners",
        espera_lista=True
    )

def consultar_proprietario(usuario):
    owner_id = random.choice(OWNER_IDS)

    verificar_get(
        usuario,
        f"{OWNERS}/{owner_id}",
        "GET /owners/{id}"
    )

def consultar_veterinarios(usuario):
    verificar_get(
        usuario,
        VETS,
        "GET /vets",
        espera_lista=True
    )

def cadastrar_proprietario(usuario):
    identificador = uuid.uuid4().hex[:12]

    proprietario = {
        "firstName": "Teste",
        "lastName": f"Locust{identificador}",
        "address": "Rua Teste 123",
        "city": "Madison",
        "telephone": str(
            random.randint(1000000000, 9999999999)
        )
    }

    with usuario.client.post(
        OWNERS,
        json=proprietario,
        name="POST /owners",
        catch_response=True
    ) as resposta:

        if resposta.status_code != 201:
            resposta.failure(
                f"HTTP {resposta.status_code}; esperado 201"
            )
            return

        try:
            dados = resposta.json()

            if not isinstance(dados, dict) or "id" not in dados:
                resposta.failure(
                    "Cadastro sem ID retornado"
                )

            else:
                resposta.success()

        except ValueError:
            resposta.failure("Resposta JSON invalida")

class PerfilLeitura(HttpUser):
    wait_time = between(1, 2)
    weight = 1

    @task(45)
    def listar_proprietarios(self):
        consultar_proprietarios(self)

    @task(35)
    def buscar_proprietario(self):
        consultar_proprietario(self)

    @task(15)
    def listar_veterinarios(self):
        consultar_veterinarios(self)

    @task(5)
    def criar_proprietario(self):
        cadastrar_proprietario(self)


class PerfilEscrita(HttpUser):
    wait_time = between(1, 2)
    weight = 1

    @task(20)
    def listar_proprietarios(self):
        consultar_proprietarios(self)

    @task(20)
    def buscar_proprietario(self):
        consultar_proprietario(self)

    @task(20)
    def listar_veterinarios(self):
        consultar_veterinarios(self)

    @task(40)
    def criar_proprietario(self):
        cadastrar_proprietario(self)


@events.test_start.add_listener
def iniciar_aquecimento(environment, **kwargs):

    segundos = int(
        os.getenv("LOCUST_WARMUP_SECONDS", "0")
    )

    if segundos <= 0:
        return

    def finalizar_aquecimento():
        gevent.sleep(segundos)

        if environment.runner is not None:
            environment.stats.reset_all()

            print(
                f"Aquecimento de {segundos}s descartado. "
                "Iniciando coleta experimental.",
                flush=True
            )

    gevent.spawn(finalizar_aquecimento)
