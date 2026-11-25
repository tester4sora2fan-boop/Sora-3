import copy
import json
import os
import random
import time
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
import requests

app = FastAPI(title="Render -> Comfy Cloud API")

# Certifique-se de que não há barra no final
COMFY_API_URL = os.getenv("COMFY_API_URL", "https://cloud.comfy.org/api").rstrip(
    "/"
)
COMFY_API_KEY = os.getenv("COMFY_API_KEY", "").strip()

with open("Sora_3_Unofficial_Model_1_Z-BneL.json", "r", encoding="utf-8") as f:
  RAW_WORKFLOW = json.load(f)

# Remove automaticamente os nós soltos de treino de LoRA (4 a 19) que não vão para o vídeo
UNUSED_NODES = {"4", "5", "7", "8", "11", "12", "14", "16", "17", "18", "19"}
BASE_WORKFLOW = {k: v for k, v in RAW_WORKFLOW.items() if k not in UNUSED_NODES}

NODE_VIDEO_PROMPT = 'insert:c63baf2405e3284e77dee601c78190ea:root:node:267:insert:c63baf2405e3284e77dee601c78190ea:root/definition:%22b94257db-cdc1-45d3-8913-ca61e782d9c1%22:node:266'
NODE_VIDEO_SEED = 'insert:c63baf2405e3284e77dee601c78190ea:root:node:267:insert:c63baf2405e3284e77dee601c78190ea:root/definition:%22b94257db-cdc1-45d3-8913-ca61e782d9c1%22:node:237'
NODE_AUDIO_PROMPT = 'insert:8bb7429b4862769c2f943dce8f199f7a:root:node:52:insert:8bb7429b4862769c2f943dce8f199f7a:root/definition:%228b66c757-fe2f-4184-91f3-479a19deb565%22:node:31'
NODE_AUDIO_SEED = 'insert:8bb7429b4862769c2f943dce8f199f7a:root:node:52:insert:8bb7429b4862769c2f943dce8f199f7a:root/definition:%228b66c757-fe2f-4184-91f3-479a19deb565%22:node:3'
NODE_SAVE_VIDEO = 'insert:c63baf2405e3284e77dee601c78190ea:root:node:75'


class RenderRequest(BaseModel):
  video_prompt: str
  audio_prompt: str
  seed: int | None = None


@app.get("/")
def health_check():
  return {
      "status": "online",
      "comfy_api_url": COMFY_API_URL,
      "api_key_configurada": bool(COMFY_API_KEY),
      "nos_ativos": len(BASE_WORKFLOW),
  }


@app.post("/gerar-video")
def gerar_video(req: RenderRequest):
  if not COMFY_API_KEY:
    raise HTTPException(
        status_code=500, detail="COMFY_API_KEY não configurada no Render."
    )

  headers = {
      "X-API-Key": COMFY_API_KEY,
      "Content-Type": "application/json",
      "Accept": "application/json",
  }

  workflow = copy.deepcopy(BASE_WORKFLOW)
  seed = req.seed if req.seed is not None else random.randint(1, 10**12)
  workflow[NODE_VIDEO_PROMPT]["inputs"]["value"] = req.video_prompt
  workflow[NODE_AUDIO_PROMPT]["inputs"]["value"] = req.audio_prompt
  workflow[NODE_VIDEO_SEED]["inputs"]["noise_seed"] = seed
  workflow[NODE_AUDIO_SEED]["inputs"]["seed"] = seed

  # 1. Envia o workflow para o Comfy Cloud
  submit_url = f"{COMFY_API_URL}/prompt"
  res = requests.post(
      submit_url,
      json={
          "prompt": workflow,
          "extra_data": {"api_key_comfy_org": COMFY_API_KEY},
      },
      headers=headers,
  )

  if res.status_code != 200:
    # Evita retornar HTML gigante e mostra exatamente qual URL deu erro
    preview_erro = res.text[:300].replace("\n", " ")
    raise HTTPException(
        status_code=res.status_code,
        detail=(
            f"Erro ao chamar {submit_url} (HTTP {res.status_code}):"
            f" {preview_erro}"
        ),
    )

  prompt_id = res.json().get("prompt_id")

  # 2. Aguarda a conclusão (status oficiais da Comfy Cloud API v2)
  status_url = f"{COMFY_API_URL}/job/{prompt_id}/status"
  while True:
    st_res = requests.get(status_url, headers=headers)
    if st_res.status_code != 200:
      raise HTTPException(
          status_code=st_res.status_code,
          detail=f"Erro ao checar status em {status_url}: {st_res.text[:300]}",
      )

    status_data = st_res.json()
    status = status_data.get("status")

    if status in ["success", "completed"]:
      break
    elif status in ["error", "non_retryable_error", "lost", "cancelled"]:
      raise HTTPException(
          status_code=500, detail=f"Job falhou no Comfy Cloud: {status_data}"
      )

    time.sleep(3)

  # 3. Busca o histórico e baixa o vídeo
  hist_res = requests.get(
      f"{COMFY_API_URL}/history_v2/{prompt_id}", headers=headers
  )
  if hist_res.status_code != 200:
    hist_res = requests.get(
        f"{COMFY_API_URL}/history/{prompt_id}", headers=headers
    )

  history = hist_res.json()
  outputs = history.get(prompt_id, {}).get("outputs", {})
  node_out = outputs.get(NODE_SAVE_VIDEO, {})
  media_list = node_out.get("videos") or node_out.get("gifs")

  if not media_list:
    raise HTTPException(
        status_code=500,
        detail=f"Vídeo não encontrado na saída do nó. Outputs: {outputs}",
    )

  media = media_list
  video_res = requests.get(
      f"{COMFY_API_URL}/view",
      params={
          "filename": media["filename"],
          "subfolder": media["subfolder"],
          "type": media["type"],
      },
      headers=headers,
  )

  return Response(content=video_res.content, media_type="video/mp4")
