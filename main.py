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

COMFY_API_URL = "https://comfy.org"
COMFY_API_KEY = os.getenv("COMFY_API_KEY")

JSON_PATH = "Sora_3_Unofficial_Model_1_Z-BneL.json"
if not os.path.exists(JSON_PATH):
  raise RuntimeError(f"Arquivo {JSON_PATH} não encontrado na raiz do projeto!")

with open(JSON_PATH, "r", encoding="utf-8") as f:
  BASE_WORKFLOW = json.load(f)

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
  return {"status": "online", "api_key_configurada": bool(COMFY_API_KEY)}


@app.post("/gerar-video")
def gerar_video(req: RenderRequest):
  if not COMFY_API_KEY:
    raise HTTPException(
        status_code=500, detail="COMFY_API_KEY não configurada no Render."
    )

  headers = {"X-API-Key": COMFY_API_KEY, "Content-Type": "application/json"}
  workflow = copy.deepcopy(BASE_WORKFLOW)

  seed = req.seed if req.seed is not None else random.randint(1, 10**12)
  workflow[NODE_VIDEO_PROMPT]["inputs"]["value"] = req.video_prompt
  workflow[NODE_AUDIO_PROMPT]["inputs"]["value"] = req.audio_prompt
  workflow[NODE_VIDEO_SEED]["inputs"]["noise_seed"] = seed
  workflow[NODE_AUDIO_SEED]["inputs"]["seed"] = seed

  res = requests.post(
      f"{COMFY_API_URL}/prompt", json={"prompt": workflow}, headers=headers
  )
  if res.status_code != 200:
    raise HTTPException(status_code=res.status_code, detail=res.text)

  prompt_id = res.json()["prompt_id"]

  while True:
    status_res = requests.get(
        f"{COMFY_API_URL}/job/{prompt_id}/status", headers=headers
    ).json()
    status = status_res.get("status")
    if status == "completed":
      break
    elif status in ["failed", "cancelled"]:
      raise HTTPException(
          status_code=500, detail=f"Falha na geração: {status_res}"
      )
    time.sleep(3)

  history = requests.get(
      f"{COMFY_API_URL}/history_v2/{prompt_id}", headers=headers
  ).json()
  outputs = history.get(prompt_id, {}).get("outputs", {})
  node_out = outputs.get(NODE_SAVE_VIDEO, {})
  media = (node_out.get("videos") or node_out.get("gifs"))

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
