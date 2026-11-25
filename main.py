import copy
import json
import os
import random
import urllib.parse
import urllib.request
import uuid
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
import websocket

app = FastAPI(title="ComfyUI Video & Audio API")

# Endereço do servidor ComfyUI com GPU (ex: "seu-pod.runpod.net" ou túnel Cloudflare/Ngrok)
COMFY_SERVER = os.getenv("COMFY_SERVER", "127.0.0.1:8188")
USE_SSL = os.getenv("COMFY_USE_SSL", "false").lower() == "true"

HTTP_PROTOCOL = "https" if USE_SSL else "http"
WS_PROTOCOL = "wss" if USE_SSL else "ws"

# Carrega o workflow base na memória ao iniciar a API
with open("Sora_3_Unofficial_Model_1_Z-BneL.json", "r", encoding="utf-8") as f:
  BASE_WORKFLOW = json.load(f)

# IDs dos nós do seu workflow
NODE_VIDEO_PROMPT = 'insert:c63baf2405e3284e77dee601c78190ea:root:node:267:insert:c63baf2405e3284e77dee601c78190ea:root/definition:%22b94257db-cdc1-45d3-8913-ca61e782d9c1%22:node:266'
NODE_VIDEO_SEED = 'insert:c63baf2405e3284e77dee601c78190ea:root:node:267:insert:c63baf2405e3284e77dee601c78190ea:root/definition:%22b94257db-cdc1-45d3-8913-ca61e782d9c1%22:node:237'
NODE_AUDIO_PROMPT = 'insert:8bb7429b4862769c2f943dce8f199f7a:root:node:52:insert:8bb7429b4862769c2f943dce8f199f7a:root/definition:%228b66c757-fe2f-4184-91f3-479a19deb565%22:node:31'
NODE_AUDIO_SEED = 'insert:8bb7429b4862769c2f943dce8f199f7a:root:node:52:insert:8bb7429b4862769c2f943dce8f199f7a:root/definition:%228b66c757-fe2f-4184-91f3-479a19deb565%22:node:3'
NODE_SAVE_VIDEO = 'insert:c63baf2405e3284e77dee601c78190ea:root:node:75'


class RenderRequest(BaseModel):
  video_prompt: str
  audio_prompt: str
  seed: int | None = None


def queue_prompt(prompt_workflow: dict, client_id: str) -> dict:
  payload = {"prompt": prompt_workflow, "client_id": client_id}
  data = json.dumps(payload).encode("utf-8")
  req = urllib.request.Request(
      f"{HTTP_PROTOCOL}://{COMFY_SERVER}/prompt",
      data=data,
      headers={"Content-Type": "application/json"},
  )
  with urllib.request.urlopen(req) as res:
    return json.loads(res.read())


def get_history(prompt_id: str) -> dict:
  with urllib.request.urlopen(
      f"{HTTP_PROTOCOL}://{COMFY_SERVER}/history/{prompt_id}"
  ) as res:
    return json.loads(res.read())


def get_file(filename: str, subfolder: str, folder_type: str) -> bytes:
  params = urllib.parse.urlencode(
      {"filename": filename, "subfolder": subfolder, "type": folder_type}
  )
  with urllib.request.urlopen(
      f"{HTTP_PROTOCOL}://{COMFY_SERVER}/view?{params}"
  ) as res:
    return res.read()


@app.get("/")
def health_check():
  return {"status": "online", "comfy_target": COMFY_SERVER}


@app.post("/gerar-video")
def gerar_video(req_data: RenderRequest):
  client_id = str(uuid.uuid4())
  workflow = copy.deepcopy(BASE_WORKFLOW)

  # Injeta os prompts e seeds
  seed = req_data.seed if req_data.seed is not None else random.randint(1, 10**12)
  workflow[NODE_VIDEO_PROMPT]["inputs"]["value"] = req_data.video_prompt
  workflow[NODE_AUDIO_PROMPT]["inputs"]["value"] = req_data.audio_prompt
  workflow[NODE_VIDEO_SEED]["inputs"]["noise_seed"] = seed
  workflow[NODE_AUDIO_SEED]["inputs"]["seed"] = seed

  try:
    ws = websocket.WebSocket()
    ws.connect(f"{WS_PROTOCOL}://{COMFY_SERVER}/ws?clientId={client_id}")

    prompt_res = queue_prompt(workflow, client_id)
    prompt_id = prompt_res["prompt_id"]

    while True:
      out = ws.recv()
      if isinstance(out, str):
        message = json.loads(out)
        if message["type"] == "executing":
          data = message["data"]
          if data["node"] is None and data["prompt_id"] == prompt_id:
            break
    ws.close()

    history = get_history(prompt_id)[prompt_id]
    outputs = history.get("outputs", {})

    if NODE_SAVE_VIDEO not in outputs:
      raise HTTPException(
          status_code=500, detail="Saída de vídeo não encontrada no histórico."
      )

    node_output = outputs[NODE_SAVE_VIDEO]
    media_list = node_output.get("videos", []) or node_output.get("gifs", [])

    if not media_list:
      raise HTTPException(
          status_code=500, detail="Nenhum arquivo de vídeo foi gerado."
      )

    item = media_list[0]
    video_bytes = get_file(item["filename"], item["subfolder"], item["type"])

    return Response(
        content=video_bytes,
        media_type="video/mp4",
        headers={
            "Content-Disposition": f"attachment; filename={item['filename']}"
        },
    )

  except Exception as e:
    raise HTTPException(status_code=500, detail=str(e))
