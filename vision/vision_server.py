import threading
import time
from typing import Optional

import uvicorn
from fastapi import FastAPI, Response, Request
from fastapi.responses import StreamingResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
import os
import config.settings as cfg

from core.json_util import sanitize_for_api
from vision.vision_pipeline import VisionPipeline

app = FastAPI(title="Robot Vision Interface")
os.makedirs("scratch/voices", exist_ok=True)
app.mount("/audio", StaticFiles(directory="scratch/voices"), name="audio")

vision_pipeline_instance: Optional[VisionPipeline] = None
_vision_server_instance: Optional["VisionServer"] = None


def _apply_display_names(scene_dict: dict, ui_state: dict) -> dict:
    overrides = ui_state.get("face_display_names") or {}
    pending_global = ui_state.get("pending_display_name")
    faces = scene_dict.get("faces") or []
    unknowns = [f for f in faces if f.get("name") == "Unknown"]
    for f in faces:
        if f.get("name") != "Unknown":
            continue
        tid = str(f.get("track_id", ""))
        label = overrides.get(tid)
        if not label and pending_global and len(unknowns) == 1:
            label = pending_global
        if label:
            f["name"] = label
            f["registration_pending"] = True
    return scene_dict


@app.get("/", response_class=HTMLResponse)
async def get_dashboard():
    with open("vision/templates/dashboard.html", "r", encoding="utf-8") as f:
        return f.read()


@app.get("/video_feed")
async def video_feed():
    def generate():
        while True:
            if vision_pipeline_instance:
                frame = vision_pipeline_instance.get_video_frame()
                if frame:
                    yield (
                        b"--frame\r\n"
                        b"Content-Type: image/jpeg\r\n\r\n" + frame + b"\r\n"
                    )
            time.sleep(0.05)

    return StreamingResponse(
        generate(), media_type="multipart/x-mixed-replace; boundary=frame"
    )


@app.get("/status")
async def get_status():
    if vision_pipeline_instance:
        scene = vision_pipeline_instance.get_latest_scene()
        data = scene.to_dict()
        if _vision_server_instance and _vision_server_instance.ui_state:
            data = _apply_display_names(data, _vision_server_instance.ui_state)
        return data
    return {"error": "Vision pipeline not initialized"}


class VisionServer:
    def __init__(
        self,
        vision_pipeline: VisionPipeline,
        host: str = "0.0.0.0",
        port: int = 8080,
        ui_state: dict = None,
    ):
        global vision_pipeline_instance, _vision_server_instance
        vision_pipeline_instance = vision_pipeline
        _vision_server_instance = self
        self.host = host
        self.port = port
        self.ui_state = ui_state or {
            "conversation_history": [],
            "system_status": "Starting...",
            "thought_log": [],
            "action_log": [],
            "is_running": True
        }
        if "thought_log" not in self.ui_state:
            self.ui_state["thought_log"] = []
        if "action_log" not in self.ui_state:
            self.ui_state["action_log"] = []
        if "is_running" not in self.ui_state:
            self.ui_state["is_running"] = True
            
        self.thread: Optional[threading.Thread] = None
        self.tts = None
        self.stt = None

        @app.get("/session_status")
        async def get_session_status():
            return sanitize_for_api(self.ui_state)

        @app.get("/api/users")
        async def get_users():
            if vision_pipeline_instance:
                users = vision_pipeline_instance.db.list_users()
                return {
                    "users": [
                        {"id": str(u["_id"]), "name": u["name"], **{k:v for k,v in u.items() if k not in ["_id", "name"]}} for u in users
                    ]
                }
            return {"users": []}

        @app.post("/api/users")
        async def add_user(request: Request):
            data = await request.json()
            if not data.get("name"):
                return {"success": False, "error": "Name is required"}
            if vision_pipeline_instance:
                try:
                    uid = vision_pipeline_instance.db.mongo.store_user(data)
                    return {"success": True, "id": str(uid)}
                except Exception as e:
                    return {"success": False, "error": str(e)}
            return {"success": False, "error": "Vision pipeline not initialized"}

        @app.delete("/api/users/{user_id}")
        async def delete_user(user_id: str):
            if vision_pipeline_instance:
                try:
                    ok = vision_pipeline_instance.db.delete_user(user_id)
                    return {"success": ok}
                except Exception as e:
                    return {"success": False, "error": str(e)}
            return {"success": False, "error": "Vision pipeline not initialized"}

        @app.post("/api/database/erase")
        async def erase_database():
            if vision_pipeline_instance:
                try:
                    vision_pipeline_instance.db.mongo.delete_many("users", {})
                    for col in [cfg.COLLECTION_IDENTITY, cfg.COLLECTION_VOICE, cfg.COLLECTION_LTM]:
                        vision_pipeline_instance.db.qdrant.client.delete_collection(col)
                    vision_pipeline_instance.db.qdrant._init_collections()
                    return {"success": True}
                except Exception as e:
                    return {"success": False, "error": str(e)}
            return {"success": False, "error": "Vision pipeline not initialized"}

        @app.get("/api/power")
        async def get_power():
            return {"is_running": self.ui_state.get("is_running", True)}

        @app.post("/api/power")
        async def toggle_power():
            is_running = self.ui_state.get("is_running", True)
            if is_running:
                if self.stt:
                    self.stt.stop()
                if vision_pipeline_instance:
                    vision_pipeline_instance.stop()
                self.ui_state["is_running"] = False
                self.ui_state["system_status"] = "Paused"
            else:
                if self.stt:
                    self.stt.start()
                if vision_pipeline_instance:
                    vision_pipeline_instance.start()
                self.ui_state["is_running"] = True
                self.ui_state["system_status"] = "Active"
            return {"success": True, "is_running": self.ui_state["is_running"]}

        @app.get("/api/thought_process")
        async def get_thought_process():
            return {"thought_log": sanitize_for_api(self.ui_state.get("thought_log", []))}

        @app.get("/api/action_log")
        async def get_action_log():
            return {"action_log": sanitize_for_api(self.ui_state.get("action_log", []))}

        @app.get("/api/system_status")
        async def get_sys_status():
            try:
                import psutil
                import shutil
                import torch
                cpu = psutil.cpu_percent()
                mem = psutil.virtual_memory().percent
                total, used, free = shutil.disk_usage("/")
                disk = (used / total) * 100
                gpu = 0.0
                if torch.cuda.is_available():
                    try:
                        gpu = torch.cuda.utilization()
                    except:
                        try:
                            gpu = (torch.cuda.memory_allocated() / torch.cuda.get_device_properties(0).total_memory) * 100
                        except:
                            pass
                return {"cpu": cpu, "ram": mem, "disk": disk, "gpu": gpu}
            except Exception:
                return {"cpu": 0, "ram": 0, "disk": 0, "gpu": 0}

        @app.post("/api/assign_voice")
        async def assign_voice(request: Request):
            data = await request.json()
            voice_id = data.get("voice_id")
            user_id = data.get("user_id")

            voices = self.ui_state.get("unassigned_voices", [])
            target = next((v for v in voices if v["id"] == voice_id), None)

            if not target:
                return {"success": False, "error": "Voice not found"}

            if vision_pipeline_instance and vision_pipeline_instance.db.register_voice(
                user_id, target["embedding"]
            ):
                self.ui_state["unassigned_voices"] = [
                    v for v in voices if v["id"] != voice_id
                ]
                return {"success": True}

            return {"success": False, "error": "Failed to assign voice"}

    def set_engines(self, tts, stt):
        self.tts = tts
        self.stt = stt

    def start(self):
        self.thread = threading.Thread(
            target=lambda: uvicorn.run(
                app, host=self.host, port=self.port, log_level="warning"
            ),
            daemon=True,
            name="VisionServer",
        )
        self.thread.start()
        print(f"[VisionServer] Dashboard active at http://localhost:{self.port} ✓")

    def stop(self):
        pass
