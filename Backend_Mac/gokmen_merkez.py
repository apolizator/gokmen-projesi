import tkinter as tk
from tkinter import ttk, messagebox, simpledialog, scrolledtext
import json
import os
import math
import tkintermapview
from PIL import Image, ImageTk
import threading
import logging
from flask import Flask, jsonify, request

# --- TASARIM VE RENKLER ---
COLORS = {
    "BG": "#121212", "PANEL": "#f5f6fa", "BLUE": "#00a8ff", 
    "GREEN": "#4cd137", "YELLOW": "#fbc531", "RED": "#e84118", 
    "WHITE": "#ffffff", "GRAY": "#444444", "BTN_TEXT": "#000000"
}

PARAMS = {
    "MAX_ILAC": 100, "HIZ_TRANSIT_KMH": 30, "HIZ_ILACLAMA_KMH": 10,
    "ILAC_DONUM_BASI": 2.0, "PIL_DONUM_BASI": 2.0, "PIL_KM_BASI": 2, 
    "SANIYE_PER_DONUM": 60 
}

def haversine(lat1, lon1, lat2, lon2):
    R = 6371000 
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = math.sin(delta_phi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(delta_lambda/2)**2
    return R * (2 * math.atan2(math.sqrt(a), math.sqrt(1-a)))

class GokmenV39Ultimate:
    def __init__(self, root):
        self.root = root
        self.root.title("ESOGÜ - Gökmen v39.0 (İşgal Korumalı Filo & GCS)")
        self.root.geometry("1450x980")
        self.root.configure(bg=COLORS["BG"])

        try:
            self.transparent_img = Image.new("RGBA", (1, 1), (0,0,0,0))
            self.transparent_icon = ImageTk.PhotoImage(self.transparent_img)
        except:
            self.transparent_icon = None

        self.db_file = "tarla_veritabani_polygon.json" 
        self.data = self.load_data()
        
        self.drones = {} 
        self.init_approved_drones()
        
        self.pending_fields = {} 
        self.pending_drones = {} 
        
        self.role_var = tk.StringVar(value="ÇİFTÇİ MODU")
        self.active_ciftci_drone = tk.StringVar() 
        self.selected_admin_drone = None 

        self.sim_speed = 1
        self.is_windy = False
        self.tick_ms = 30 
        
        self.draw_mode = "NONE" 
        self.temp_coords = []
        self.temp_path = None
        self.temp_marker = None
        
        self.listbox_map = {} 
        self.grid_rects_emb = []
        self.grid_rects_fs = []
        self.fs_window = None
        self.mini_radar_emb = None
        self.fs_radar_map = None

        self.app = Flask(__name__)
        log = logging.getLogger('werkzeug')
        log.setLevel(logging.ERROR) 
        self.setup_api_routes()
        self.server_thread = threading.Thread(target=self.run_server, daemon=True)
        self.server_thread.start()

        self.setup_ui()
        self.update_ciftci_drone_list() 
        
        self.update_telemetry()
        self.update_fsm_ui()
        self.root.after(1000, self.refresh_ops_listbox)

    def load_data(self):
        if os.path.exists(self.db_file):
            try:
                with open(self.db_file, "r") as f: 
                    d = json.load(f)
                    if "drones_registry" not in d: d["drones_registry"] = {}
                    if "fields" not in d: d["fields"] = {}
                    return d
            except: pass
        return {"fields": {}, "drones_registry": {"DRON_1": {"base_lat": 39.7495, "base_lon": 30.4850, "status": "approved"}}}

    def save_data(self):
        with open(self.db_file, "w") as f: json.dump(self.data, f)

    def init_approved_drones(self):
        for d_id, info in self.data["drones_registry"].items():
            if info.get("status") == "approved":
                self.drones[d_id] = self.create_drone_state(info["base_lat"], info["base_lon"])

    def create_drone_state(self, lat, lon):
        return {
            "lat": lat, "lon": lon, "state": "q0", "battery": 100.0, "chemical": float(PARAMS["MAX_ILAC"]),
            "speed": 0, "is_running": False, "is_obstacle": False, "queue": [], "idx": 0, 
            "active_field": None, "active_acre": 0.0, "active_sq_val": 0.0, "active_total_boxes": 0,
            "sprayed_acre": 0.0, "resume_target": None, "mission_chemical_used": 0.0, 
            "total_time_sec": 0, "total_dist_m": 0, "marker": None
        }

    def drone_log(self, drone_id, msg):
        self.log_area.insert(tk.END, f"[{drone_id}] -> {msg}\n")
        self.log_area.see(tk.END)

    def format_time(self, seconds):
        h, rem = divmod(int(seconds), 3600)
        m, s = divmod(rem, 60)
        return f"{h:02d}:{m:02d}:{s:02d}"

    def calculate_eta(self, drone_id):
        if not drone_id or drone_id not in self.drones: return 0
        d = self.drones[drone_id]
        if not d["is_running"] or not d["queue"]: return 0
        rem_sec = 0
        curr_lat, curr_lon = d["lat"], d["lon"]
        for i in range(d["idx"], len(d["queue"])):
            t_name = d["queue"][i]
            t_info = self.data["fields"][t_name]
            dist = haversine(curr_lat, curr_lon, t_info["lat"], t_info["lon"])
            rem_sec += dist / (PARAMS["HIZ_TRANSIT_KMH"] / 3.6)
            rem_acre = t_info["acre"] - t_info["sprayed_acre"]
            if rem_acre > 0:
                sf = 0.4 if (self.is_windy and i == d["idx"]) else 1.0
                rem_sec += (rem_acre * PARAMS["SANIYE_PER_DONUM"]) / sf
            curr_lat, curr_lon = t_info["lat"], t_info["lon"]
        
        base_lat = self.data["drones_registry"][drone_id]["base_lat"]
        base_lon = self.data["drones_registry"][drone_id]["base_lon"]
        dist_home = haversine(curr_lat, curr_lon, base_lat, base_lon)
        rem_sec += dist_home / (PARAMS["HIZ_TRANSIT_KMH"] / 3.6)
        return rem_sec

    # --- MATEMATİKSEL İŞGAL KORUMASI ---
    def point_in_polygon(self, lat, lon, polygon):
        n = len(polygon)
        inside = False
        p1lat, p1lon = polygon[0]
        for i in range(n + 1):
            p2lat, p2lon = polygon[i % n]
            if lon > min(p1lon, p2lon):
                if lon <= max(p1lon, p2lon):
                    if lat <= max(p1lat, p2lat):
                        if p1lon != p2lon:
                            xints = (lon - p1lon) * (p2lat - p1lat) / (p2lon - p1lon) + p1lat
                        if p1lat == p2lat or lat <= xints:
                            inside = not inside
            p1lat, p1lon = p2lat, p2lon
        return inside

    def check_overlap(self, poly1, poly2):
        for lat, lon in poly1:
            if self.point_in_polygon(lat, lon, poly2): return True
        for lat, lon in poly2:
            if self.point_in_polygon(lat, lon, poly1): return True
        return False

    # --- API ---
    def setup_api_routes(self):
        @self.app.route('/api/telemetry', methods=['GET'])
        def api_telemetry():
            drones_dict = {
                cid: {
                    "lat": d["lat"], "lon": d["lon"], "state": d["state"],
                    "battery": round(d["battery"], 1), "chemical": round(d["chemical"], 1), "speed_kmh": d["speed"]
                } for cid, d in self.drones.items()
            }
            return jsonify({"drones": drones_dict, "fields": self.data["fields"]})

        @self.app.route('/api/request_field', methods=['POST'])
        def api_request_field():
            data = request.json
            f_name = data.get("field_name")
            if f_name:
                self.pending_fields[f_name] = data
                self.root.after(0, self.refresh_pending_listbox)
                return jsonify({"status": "pending"})
            return jsonify({"status": "error"}), 400

        @self.app.route('/api/register_drone', methods=['POST'])
        def api_register_drone():
            data = request.json
            d_name = data.get("drone_name")
            if d_name:
                self.pending_drones[d_name] = data
                self.root.after(0, self.refresh_pending_listbox)
                return jsonify({"status": "pending"})
            return jsonify({"status": "error"}), 400

        @self.app.route('/api/start_mission', methods=['POST'])
        def api_start_mission():
            data = request.json
            field_name = data.get("field_name")
            cid = data.get("client_id")
            
            if not field_name or field_name not in self.data["fields"]:
                return jsonify({"status": "error", "msg": "Tarla bulunamadı"}), 400
            
            if self.data["fields"][field_name].get("owner") != cid:
                return jsonify({"status": "error", "msg": "Tarla bu drona ait değil!"}), 403
                
            def trigger_flight():
                d = self.drones[cid]
                if d["is_running"]: return 
                self.data["fields"][field_name]["sprayed_acre"] = 0.0 
                d["mission_chemical_used"] = 0.0 
                d["queue"] = [field_name]
                d["idx"] = 0
                d["is_running"], d["is_obstacle"] = True, False
                d["state"] = "q1" 
                d["active_field"] = field_name
                self.drone_log(cid, f"{field_name} tarlası için havalandı (q1).")
                self.execute_queue(cid, [field_name], 0)
            
            self.root.after(0, trigger_flight)
            return jsonify({"status": "success"})

    def run_server(self): self.app.run(host='0.0.0.0', port=5001)

    # --- UI ---
    def setup_fsm_canvas(self, parent, is_fs=False):
        w = 340 
        canvas = tk.Canvas(parent, width=w, height=140, bg="#1a1a1a", highlightthickness=0)
        indicators = {}
        sf = 0.85 
        canvas.create_text(w/2, 12, text="OTONOM DURUMLAR (İzleme)", fill="gray", font=("Arial", 8, "bold"))
        canvas.create_text(w/2, 75, text="MANUEL MÜDAHALE (Tıklanabilir)", fill="cyan", font=("Arial", 8, "bold"))
        auto_states = {"q0": ("BEKLE", 40, 38), "q1": ("GİDİŞ", 120, 38), "q2": ("İLAÇLA", 200, 38), "q5": ("İKMAL", 280, 38), "q7": ("DÖNÜŞ", 360, 38)}
        manual_states = {"q3": ("ENGEL", 80, 105), "q4": ("RÜZGAR", 160, 105), "q6": ("DURDUR", 240, 105), "q8": ("İPTAL", 320, 105)}
        for st, (name, cx, cy) in auto_states.items():
            cx = cx * sf 
            shape = canvas.create_oval(cx-18, cy-18, cx+18, cy+18, fill=COLORS["GRAY"], outline="white", tags=st)
            canvas.create_text(cx, cy+28, text=name, fill="white", font=("Arial", 7, "bold"), tags=st)
            indicators[st] = shape
        for st, (name, cx, cy) in manual_states.items():
            cx = cx * sf 
            shape = canvas.create_rectangle(cx-22, cy-16, cx+22, cy+16, fill=COLORS["GRAY"], outline="cyan", width=2, tags=st)
            canvas.create_text(cx, cy+28, text=name, fill="cyan", font=("Arial", 7, "bold"), tags=st)
            indicators[st] = shape
        canvas.bind("<Button-1>", self.on_fsm_click)
        return canvas, indicators

    def setup_ui(self):
        self.top_panel = tk.Frame(self.root, bg=COLORS["PANEL"], bd=2, relief="groove")
        self.top_panel.pack(fill="x", side="top", padx=5, pady=5)
        
        self.lbl_action_msg = tk.Label(self.top_panel, text="SİSTEM HAZIR", font=("Arial", 14, "bold"), bg="#dcdde1", fg="#2f3640")
        self.lbl_action_msg.pack(fill="x", padx=10, pady=2)

        self.bar_frame = tk.Frame(self.top_panel, bg=COLORS["PANEL"])
        self.bar_frame.pack(pady=2)
        tk.Label(self.bar_frame, text="🔋 BATARYA:", bg=COLORS["PANEL"], font=("Arial", 10, "bold")).pack(side="left")
        self.bat_bar = ttk.Progressbar(self.bar_frame, orient="horizontal", length=200, mode="determinate")
        self.bat_bar.pack(side="left", padx=5)
        tk.Label(self.bar_frame, text="💧 İLAÇ:", bg=COLORS["PANEL"], font=("Arial", 10, "bold")).pack(side="left", padx=(15,0))
        self.chem_bar = ttk.Progressbar(self.bar_frame, orient="horizontal", length=200, mode="determinate")
        self.chem_bar.pack(side="left", padx=5)

        self.lbl_stats = tk.Label(self.top_panel, text="", font=("Consolas", 11, "bold"), bg=COLORS["PANEL"], fg="#2f3640")
        self.lbl_stats.pack(pady=2)

        self.ctrl_frame = tk.Frame(self.top_panel, bg=COLORS["PANEL"])
        tk.Label(self.ctrl_frame, text="ZAMAN MAKİNESİ (TANRI):", bg=COLORS["PANEL"], fg="red", font=("Arial", 9, "bold")).pack(side="left", padx=5)
        for s in [1, 16, 32, 64, 128, 256, 512, 2048, 4096]:
            tk.Button(self.ctrl_frame, text=f"{s}x", width=4, command=lambda v=s: self.set_speed(v), bg=COLORS["YELLOW"], fg=COLORS["BTN_TEXT"], font=("Arial", 9, "bold")).pack(side="left", padx=2)

        self.main_body = tk.Frame(self.root, bg=COLORS["BG"])
        self.main_body.pack(fill="both", expand=True, padx=10, pady=5)

        self.shortcut_frame = tk.Frame(self.main_body, bg=COLORS["BG"])
        self.shortcut_frame.pack(fill="x", padx=5, pady=(0,5))
        tk.Button(self.shortcut_frame, text="🚁 Drona Odaklan", command=self.focus_drone, bg="#dcdde1", fg="black", font=("Arial", 9, "bold")).pack(side="left", padx=2)
        tk.Button(self.shortcut_frame, text="🏠 Üsse Odaklan", command=self.focus_home, bg="#dcdde1", fg="black", font=("Arial", 9, "bold")).pack(side="left", padx=2)

        self.map_widget = tkintermapview.TkinterMapView(self.main_body, width=950, height=720, corner_radius=0)
        self.map_widget.pack(side="left", padx=5)
        
        first_drone = list(self.drones.values())[0] if self.drones else {"lat": 39.7495, "lon": 30.4850}
        self.map_widget.set_position(first_drone["lat"], first_drone["lon"])
        self.map_widget.set_zoom(15)
        self.map_widget.set_tile_server("https://mt0.google.com/vt/lyrs=s&hl=en&x={x}&y={y}&z={z}&s=Ga", max_zoom=22)
        self.map_widget.add_left_click_map_command(self.map_left_click)

        self.right_panel = tk.Frame(self.main_body, bg=COLORS["BG"])
        self.right_panel.pack(side="right", fill="both", expand=True)

        mode_frame = tk.Frame(self.right_panel, bg=COLORS["BG"])
        mode_frame.pack(fill="x", pady=5)
        tk.Label(mode_frame, text="💻 MOD:", bg=COLORS["BG"], fg="white", font=("Arial", 10, "bold")).pack(side="left")
        self.mode_cb = ttk.Combobox(mode_frame, textvariable=self.role_var, values=["ÇİFTÇİ MODU", "TANRI MODU"], state="readonly", width=15)
        self.mode_cb.pack(side="right")
        self.mode_cb.bind("<<ComboboxSelected>>", self.on_mode_change)

        self.fsm_canvas, self.fsm_indicators = self.setup_fsm_canvas(self.right_panel)
        self.fsm_canvas.pack(fill="x", pady=2)

        # OPERASYON VE TAM EKRAN BUTONU 
        self.op_frame = tk.Frame(self.right_panel, bg="#111", bd=2, relief="sunken")
        op_top_bar = tk.Frame(self.op_frame, bg="#111")
        op_top_bar.pack(fill="x", pady=5, padx=5)
        self.op_lbl_title = tk.Label(op_top_bar, text="AKTİF OPERASYON", bg="#111", fg="white", font=("Arial", 9, "bold"))
        self.op_lbl_title.pack(side="left")
        self.btn_fs = tk.Button(op_top_bar, text="🔲 Tam Ekran", bg="#333", fg="white", font=("Arial", 8, "bold"), command=self.open_fullscreen_op)
        self.btn_fs.pack(side="right")
        
        self.op_canvas = tk.Canvas(self.op_frame, width=380, height=140, bg="#222", highlightthickness=0)
        self.op_canvas.pack(pady=2)
        self.mini_radar_emb = tkintermapview.TkinterMapView(self.op_canvas, width=100, height=100, corner_radius=5)
        self.mini_radar_emb.set_tile_server("https://mt0.google.com/vt/lyrs=s&hl=en&x={x}&y={y}&z={z}&s=Ga", max_zoom=22)
        self.mini_radar_emb.canvas.bind("<ButtonPress-1>", lambda e: "break")
        self.mini_radar_emb.canvas.bind("<B1-Motion>", lambda e: "break")
        self.op_lbl_perc = tk.Label(self.op_frame, text="%0 Tamamlandı", bg="#111", fg=COLORS["GREEN"], font=("Arial", 12, "bold"))
        self.op_lbl_perc.pack(pady=(2,0))

        # --- ÇİFTÇİ PANELİ ---
        self.ciftci_frame = tk.Frame(self.right_panel, bg=COLORS["BG"])
        
        dr_frame = tk.Frame(self.ciftci_frame, bg=COLORS["BG"])
        dr_frame.pack(fill="x", pady=5)
        tk.Label(dr_frame, text="🚁 Aktif Dron:", bg=COLORS["BG"], fg="cyan", font=("Arial", 9, "bold")).pack(side="left")
        self.cb_ciftci_drones = ttk.Combobox(dr_frame, textvariable=self.active_ciftci_drone, state="readonly", width=15)
        self.cb_ciftci_drones.pack(side="left", padx=5)
        self.cb_ciftci_drones.bind("<<ComboboxSelected>>", self.on_ciftci_drone_change)
        tk.Button(dr_frame, text="➕ Yeni Dron", bg="orange", font=("Arial", 8, "bold"), command=self.toggle_add_drone_mode).pack(side="right")

        tk.Label(self.ciftci_frame, text="✅ KAYITLI TARLALAR", bg=COLORS["BG"], fg="white", font=("Arial", 10, "bold")).pack(pady=(5,0))
        self.listbox = tk.Listbox(self.ciftci_frame, selectmode="multiple", bg="#1e1e1e", fg="white", font=("Arial", 10), height=3)
        self.listbox.pack(fill="x", pady=2)
        
        btn_action_frame = tk.Frame(self.ciftci_frame, bg=COLORS["BG"])
        btn_action_frame.pack(fill="x", pady=2)
        self.btn_add_field = tk.Button(btn_action_frame, text="✏️ TARLA ÇİZ", bg=COLORS["WHITE"], fg=COLORS["BTN_TEXT"], font=("Arial", 9, "bold"), command=self.toggle_draw_field_mode)
        self.btn_add_field.pack(side="left", padx=2, fill="x", expand=True)
        self.btn_del_field = tk.Button(btn_action_frame, text="🗑️ SİL", bg=COLORS["RED"], fg="white", font=("Arial", 9, "bold"), command=self.delete_selected_fields)
        self.btn_del_field.pack(side="right", padx=2, fill="x", expand=True)
        self.btn_start = tk.Button(self.ciftci_frame, text="🚀 GÖREVİ BAŞLAT", bg=COLORS["GREEN"], fg=COLORS["BTN_TEXT"], font=("Arial", 12, "bold"), command=self.start_mission, height=1)
        self.btn_start.pack(fill="x", pady=5)

        # --- TANRI PANELİ ---
        self.admin_frame = tk.Frame(self.right_panel, bg=COLORS["BG"])
        tk.Label(self.admin_frame, text="🚁 AKTİF OPERASYONLAR", bg=COLORS["BG"], fg="cyan", font=("Arial", 9, "bold")).pack(pady=(5,0))
        self.ops_listbox = tk.Listbox(self.admin_frame, bg="#0abde3", fg="black", font=("Arial", 9, "bold"), height=2)
        self.ops_listbox.pack(fill="x", pady=2)
        tk.Button(self.admin_frame, text="🔍 DRONU İZLE", bg="cyan", fg="black", font=("Arial", 8, "bold"), command=self.select_active_op).pack(fill="x", pady=2)

        tk.Label(self.admin_frame, text="⏳ BEKLEYEN İSTEKLER (Dron & Tarla)", bg=COLORS["BG"], fg="orange", font=("Arial", 9, "bold")).pack(pady=(5,0))
        self.pending_listbox = tk.Listbox(self.admin_frame, bg="#2d3436", fg="orange", font=("Arial", 9), height=3)
        self.pending_listbox.pack(fill="x", pady=2)
        # ÖNİZLEME ETKİLEŞİMİ EKLENDİ:
        self.pending_listbox.bind("<<ListboxSelect>>", self.on_pending_select)

        pending_btn_frame = tk.Frame(self.admin_frame, bg=COLORS["BG"])
        pending_btn_frame.pack(fill="x", pady=2)
        tk.Button(pending_btn_frame, text="✅ ONAYLA", bg="green", fg="white", font=("Arial", 8, "bold"), command=self.approve_request).pack(side="left", padx=2, fill="x", expand=True)
        tk.Button(pending_btn_frame, text="❌ REDDET", bg="red", fg="white", font=("Arial", 8, "bold"), command=self.reject_request).pack(side="right", padx=2, fill="x", expand=True)

        self.log_area = scrolledtext.ScrolledText(self.right_panel, height=5, bg="black", fg=COLORS["GREEN"], font=("Consolas", 8))
        self.log_area.pack(fill="both", pady=5)

        self.on_mode_change() 

    # --- TAM EKRAN (DASHBOARD) ---
    def close_fs(self):
        if self.fs_window: self.fs_window.destroy()
        self.fs_window = None
        self.fs_radar_map = None
        self.fs_fsm_canvas = None
        self.fs_fsm_indicators = {}

    def open_fullscreen_op(self):
        cid = self.selected_admin_drone
        if not cid or cid not in self.drones: return
        d = self.drones.get(cid)
        if not d or not d["is_running"] or d["active_acre"] == 0: return
        if self.fs_window and self.fs_window.winfo_exists(): return
        
        self.fs_window = tk.Toplevel(self.root)
        self.fs_window.attributes('-fullscreen', True)
        self.fs_window.configure(bg="#111")
        self.fs_window.protocol("WM_DELETE_WINDOW", self.close_fs)
        
        top_bar = tk.Frame(self.fs_window, bg="#111")
        top_bar.pack(fill="x", pady=10, padx=20)
        tk.Label(top_bar, text=f"GÖKMEN KOMUTA PANELİ - [{cid}] - {d['active_acre']:.2f} DÖNÜM", bg="#111", fg="white", font=("Arial", 16, "bold")).pack(side="left")
        tk.Button(top_bar, text="❌ TAM EKRANDAN ÇIK", command=self.close_fs, bg="red", fg="white", font=("Arial", 12, "bold")).pack(side="right")
        
        self.fs_content = tk.Frame(self.fs_window, bg="#111")
        self.fs_content.pack(fill="both", expand=True, padx=20, pady=10)
        
        self.fs_left = tk.Frame(self.fs_content, bg="#111")
        self.fs_left.pack(side="left", fill="both", expand=True)
        self.fs_lbl_perc = tk.Label(self.fs_left, text="%0 Tamamlandı", bg="#111", fg=COLORS["GREEN"], font=("Arial", 22, "bold"))
        self.fs_lbl_perc.pack(pady=(10,0))
        self.fs_lbl_prog = tk.Label(self.fs_left, text="0.00 / 0.00 Dönüm İlaçlandı", bg="#111", fg="white", font=("Arial", 16))
        self.fs_lbl_prog.pack(pady=(0,10))
        
        self.fs_canvas = tk.Canvas(self.fs_left, bg="#222", highlightthickness=0)
        self.fs_canvas.pack(fill="both", expand=True)
        
        self.fs_right = tk.Frame(self.fs_content, bg="#1a1a1a", width=360, bd=2, relief="sunken")
        self.fs_right.pack(side="right", fill="y", padx=(20,0))
        self.fs_right.pack_propagate(False) 
        
        self.fs_fsm_canvas, self.fs_fsm_indicators = self.setup_fsm_canvas(self.fs_right, is_fs=True)
        self.fs_fsm_canvas.pack(pady=(10, 5))
        
        tk.Label(self.fs_right, text="🛰️ UYDU KADRAJI", bg="#1a1a1a", fg="white", font=("Arial", 11, "bold")).pack(pady=(10,5))
        self.fs_radar_map = tkintermapview.TkinterMapView(self.fs_right, width=300, height=200, corner_radius=10)
        self.fs_radar_map.set_tile_server("https://mt0.google.com/vt/lyrs=s&hl=en&x={x}&y={y}&z={z}&s=Ga", max_zoom=22)
        self.fs_radar_map.canvas.bind("<ButtonPress-1>", lambda e: "break")
        self.fs_radar_map.canvas.bind("<B1-Motion>", lambda e: "break")
        self.fs_radar_map.canvas.bind("<MouseWheel>", lambda e: "break")
        self.fs_radar_map.pack(pady=5)
        
        t_name = d["active_field"]
        if t_name and t_name in self.data["fields"]:
            t_info = self.data["fields"][t_name]
            self.fs_radar_map.set_position(t_info["lat"], t_info["lon"])
            self.fs_radar_map.set_zoom(17)
            self.fs_radar_map.set_polygon(t_info["polygon"], fill_color="", outline_color="cyan", border_width=2)
        
        info_frame = tk.Frame(self.fs_right, bg="#1a1a1a")
        info_frame.pack(fill="x", pady=10)
        self.fs_lbl_tname = tk.Label(info_frame, text=f"📍 Hedef: {t_name}", bg="#1a1a1a", fg="cyan", font=("Arial", 11, "bold"))
        self.fs_lbl_tname.pack(anchor="w", padx=25, pady=2)
        self.fs_lbl_tacre = tk.Label(info_frame, text=f"📏 Toplam Alan: {d['active_acre']:.2f} Dönüm", bg="#1a1a1a", fg="white", font=("Arial", 11))
        self.fs_lbl_tacre.pack(anchor="w", padx=25, pady=2)
        self.fs_lbl_tchem = tk.Label(info_frame, text="💦 Harcanan: 0.0 Litre", bg="#1a1a1a", fg="white", font=("Arial", 11))
        self.fs_lbl_tchem.pack(anchor="w", padx=25, pady=2)
        self.fs_lbl_ttime = tk.Label(info_frame, text="⏱️ Kalan Süre: Hesaplanıyor...", bg="#1a1a1a", fg="white", font=("Arial", 11))
        self.fs_lbl_ttime.pack(anchor="w", padx=25, pady=2)

        self.fs_window.update_idletasks()
        w = self.fs_canvas.winfo_width() if self.fs_canvas.winfo_width() > 10 else 800
        h = self.fs_canvas.winfo_height() if self.fs_canvas.winfo_height() > 10 else 600
        
        self.grid_rects_fs = self.draw_grid_on_canvas(self.fs_canvas, w, h, d["active_acre"])
        self.update_op_panel(d["sprayed_acre"], d["active_acre"], cid)
        self.update_fsm_ui()

    def update_ciftci_drone_list(self):
        approved = [k for k, v in self.data["drones_registry"].items() if v["status"] == "approved"]
        self.cb_ciftci_drones['values'] = approved
        if approved and not self.active_ciftci_drone.get():
            self.active_ciftci_drone.set(approved[0])
            self.selected_admin_drone = approved[0]

    def on_ciftci_drone_change(self, event=None):
        self.selected_admin_drone = self.active_ciftci_drone.get()
        self.refresh_listbox()
        self.draw_map_markers()
        self.update_telemetry()
        self.op_frame.pack_forget()

    def on_mode_change(self, event=None):
        if self.role_var.get() == "ÇİFTÇİ MODU":
            self.ctrl_frame.pack_forget() 
            self.admin_frame.pack_forget()
            self.ciftci_frame.pack(fill="x", pady=2, before=self.log_area)
            self.selected_admin_drone = self.active_ciftci_drone.get()
            self.log_area.insert(tk.END, ">>> ÇİFTÇİ MODUNA GEÇİLDİ\n")
        else:
            self.ctrl_frame.pack(pady=2, fill="x", after=self.lbl_stats) 
            self.ciftci_frame.pack_forget()
            self.admin_frame.pack(fill="x", pady=2, before=self.log_area)
            self.log_area.insert(tk.END, ">>> TANRI MODUNA GEÇİLDİ (KULE)\n")
            
        self.log_area.see(tk.END)
        self.refresh_listbox()
        self.refresh_pending_listbox() 
        self.draw_map_markers()
        if self.selected_admin_drone: self.update_telemetry()

    def refresh_ops_listbox(self):
        if self.role_var.get() == "TANRI MODU":
            sel = self.ops_listbox.curselection()
            sel_val = self.ops_listbox.get(sel[0]) if sel else None
            self.ops_listbox.delete(0, tk.END)
            idx_to_select = None
            
            for cid, d in self.drones.items():
                if d["is_running"]:
                    field = d["active_field"] if d["active_field"] else "Yolda/Dönüşte"
                    val = f"{cid} -> {field}"
                    self.ops_listbox.insert(tk.END, val)
                    if sel_val == val: idx_to_select = self.ops_listbox.size() - 1
            
            if idx_to_select is not None: self.ops_listbox.selection_set(idx_to_select)
        self.root.after(1000, self.refresh_ops_listbox)

    def select_active_op(self):
        sel = self.ops_listbox.curselection()
        if not sel: 
            messagebox.showinfo("Bilgi", "Lütfen listeden bir operasyon seçin.")
            return
        val = self.ops_listbox.get(sel[0])
        cid = val.split(" -> ")[0]
        self.selected_admin_drone = cid
        self.update_telemetry()
        d = self.drones[cid]
        if d["active_field"]:
            self.init_op_panel(d["active_field"], self.data["fields"][d["active_field"]]["acre"], d["sprayed_acre"], cid)
        else:
            self.op_frame.pack_forget()
        self.drone_log("KULE", f"Radara kilitlendi: {cid}")

    # --- ÖNİZLEME VE ONAY MEKANİZMASI ---
    def on_pending_select(self, event):
        self.draw_map_markers() # Eski önizlemeleri temizlemek için haritayı tazele
        sel = self.pending_listbox.curselection()
        if not sel: return
        val = self.pending_listbox.get(sel[0])
        
        if val.startswith("[TARLA]"):
            name = val.replace("[TARLA] İstek: ", "")
            if name in self.pending_fields:
                poly = self.pending_fields[name]["polygon"]
                # SARI VE KIRMIZI RENKLE ÖNİZLEME YAP
                self.map_widget.set_polygon(poly, fill_color="yellow", outline_color="red", border_width=3, name="PREVIEW")
                self.map_widget.set_position(poly[0][0], poly[0][1])
                self.map_widget.set_zoom(17)
                self.drone_log("KULE", f"Önizleme: {name} tarlası haritada işaretlendi.")
                
        elif val.startswith("[DRON]"):
            name = val.replace("[DRON] İstek: ", "")
            if name in self.pending_drones:
                lat, lon = self.pending_drones[name]["lat"], self.pending_drones[name]["lon"]
                self.map_widget.set_marker(lat, lon, text=f"⚠️ {name} ÜS ADAYI", text_color="yellow")
                self.map_widget.set_position(lat, lon)
                self.map_widget.set_zoom(17)

    def refresh_pending_listbox(self):
        self.pending_listbox.delete(0, tk.END)
        for name in self.pending_drones.keys():
            self.pending_listbox.insert(tk.END, f"[DRON] İstek: {name}")
        for name in self.pending_fields.keys():
            self.pending_listbox.insert(tk.END, f"[TARLA] İstek: {name}")

    def approve_request(self):
        selected = self.pending_listbox.curselection()
        if not selected: return
        val = self.pending_listbox.get(selected[0])
        
        if val.startswith("[DRON]"):
            name = val.replace("[DRON] İstek: ", "")
            data = self.pending_drones.pop(name)
            self.data["drones_registry"][name] = {"base_lat": data["lat"], "base_lon": data["lon"], "status": "approved"}
            self.drones[name] = self.create_drone_state(data["lat"], data["lon"])
            self.drone_log("KULE", f"{name} Dronu ONAYLANDI ve Filoya eklendi.")
            self.update_ciftci_drone_list()
            
        elif val.startswith("[TARLA]"):
            name = val.replace("[TARLA] İstek: ", "")
            data = self.pending_fields[name]
            new_poly = data["polygon"]
            
            # --- MÜLKİYET VE İŞGAL KONTROLÜ ---
            for ext_name, ext_info in self.data["fields"].items():
                if "polygon" in ext_info:
                    if self.check_overlap(new_poly, ext_info["polygon"]):
                        ans = messagebox.askyesno("Sınır İhlali (İşgal)!", f"DİKKAT: Bu tarla isteği, mevcut '{ext_name}' tarlasının sınırlarına tecavüz ediyor!\n\nYine de onaylamak istiyor musunuz?")
                        if not ans:
                            return # İşlemi iptal et
            
            # İşgal yoksa veya Kule bilerek onaylarsa:
            self.pending_fields.pop(name)
            self.data["fields"][name] = {
                "lat": data["lat"], "lon": data["lon"], "acre": data["acre"], 
                "sprayed_acre": 0.0, "polygon": data["polygon"], "owner": data.get("owner", "BİLİNMEYEN")
            }
            self.drone_log("KULE", f"{name} Tarlası ONAYLANDI.")
            
        self.save_data()
        self.refresh_pending_listbox()
        self.refresh_listbox()
        self.draw_map_markers()

    def reject_request(self):
        selected = self.pending_listbox.curselection()
        if not selected: return
        val = self.pending_listbox.get(selected[0])
        if val.startswith("[DRON]"):
            name = val.replace("[DRON] İstek: ", "")
            del self.pending_drones[name]
        elif val.startswith("[TARLA]"):
            name = val.replace("[TARLA] İstek: ", "")
            del self.pending_fields[name]
        self.refresh_pending_listbox()
        self.draw_map_markers() # Önizlemeyi temizle

    def focus_drone(self): 
        if not self.selected_admin_drone or self.selected_admin_drone not in self.drones: return
        d = self.drones[self.selected_admin_drone]
        self.map_widget.set_position(d["lat"], d["lon"])
        
    def focus_home(self): 
        if not self.selected_admin_drone or self.selected_admin_drone not in self.data["drones_registry"]: return
        reg = self.data["drones_registry"][self.selected_admin_drone]
        self.map_widget.set_position(reg["base_lat"], reg["base_lon"])
        
    def focus_field(self):
        selected = self.listbox.curselection()
        if not selected: return
        name = self.listbox_map[self.listbox.get(selected[0])]
        self.map_widget.set_position(self.data["fields"][name]["lat"], self.data["fields"][name]["lon"])
        self.map_widget.set_zoom(17)

    def on_polygon_click(self, polygon):
        # Preview poligonlarına tıklanmasını engelle
        if polygon.name == "PREVIEW": return
        
        name = polygon.name
        self.listbox.selection_clear(0, tk.END)
        for i in range(self.listbox.size()):
            if self.listbox_map.get(self.listbox.get(i)) == name:
                self.listbox.selection_set(i); self.listbox.see(i)
                break
        
        act_drone = self.active_ciftci_drone.get()
        if self.role_var.get() == "ÇİFTÇİ MODU" and self.data["fields"][name].get("owner") == act_drone:
            menu = tk.Menu(self.root, tearoff=0)
            menu.add_command(label=f"🚀 {name} - Göreve Başla", command=self.start_mission)
            menu.add_separator()
            menu.add_command(label="🗑️ Tarlayı Sil", command=self.delete_selected_fields)
            menu.tk_popup(self.root.winfo_pointerx(), self.root.winfo_pointery())

    def refresh_listbox(self):
        self.listbox.delete(0, tk.END)
        self.listbox_map.clear()
        is_admin = (self.role_var.get() == "TANRI MODU")
        act_drone = self.active_ciftci_drone.get()
        
        for name, info in self.data["fields"].items():
            owner = info.get("owner", "ADMIN")
            if is_admin:
                disp = f"{name} (Sahip: {owner})"
                self.listbox.insert(tk.END, disp)
                self.listbox_map[disp] = name
            elif owner == act_drone:
                disp = f"{name} ({info['acre']:.2f} Dn)"
                self.listbox.insert(tk.END, disp)
                self.listbox_map[disp] = name

    def on_fsm_click(self, event):
        if self.role_var.get() != "TANRI MODU":
            messagebox.showwarning("Kısıtlı Yetki", "Müdahaleler sadece TANRI MODUNDA yapılabilir.")
            return
            
        canvas = event.widget
        item = canvas.find_withtag("current")
        if not item: return
        tags = canvas.gettags(item[0])
        
        if "q4" in tags:
            self.is_windy = not self.is_windy
            self.drone_log("KULE", f"Hava Durumu Değiştirildi. Rüzgar: {'AÇIK' if self.is_windy else 'KAPALI'}")
            self.update_fsm_ui()
        else:
            messagebox.showwarning("Tanrı Modu", "Admin dronları iptal edemez. Sadece rüzgarı değiştirebilir.")

    def calc_grid_scale(self, acre):
        multiplier = 0.1 
        while math.ceil(acre / multiplier) > 30: multiplier *= 10
        col_val = multiplier * 1.0     
        sq_val = col_val / 20.0 
        total_boxes = math.ceil(acre / sq_val)
        return math.ceil(total_boxes / 20), col_val, sq_val, total_boxes

    def draw_grid_on_canvas(self, canvas, W, H, acre):
        canvas.delete("all")
        rects = []
        cols, col_val, sq_val, total_boxes = self.calc_grid_scale(acre)
        draw_w, draw_h = W - 20, H - 30
        cell_w, cell_h = (draw_w / cols if cols > 0 else draw_w), draw_h / 20 
        for c in range(cols):
            for r in range(20):
                if c * 20 + r >= total_boxes: break 
                x0, y0 = 10 + c * cell_w, 20 + r * cell_h
                rects.append(canvas.create_rectangle(x0, y0, x0 + cell_w, y0 + cell_h, fill="#111", outline="#555"))
        return rects

    def init_op_panel(self, field_name, acre, sprayed_already=0.0, drone_id=None):
        if not drone_id: drone_id = self.selected_admin_drone
        if not drone_id or drone_id not in self.drones: return
        
        if self.role_var.get() == "ÇİFTÇİ MODU":
            self.op_frame.pack(fill="x", pady=5, before=self.ciftci_frame)
        else:
            self.op_frame.pack(fill="x", pady=5, before=self.admin_frame)
            
        _, _, sq_val, total_boxes = self.calc_grid_scale(acre)
        
        self.drones[drone_id]["active_acre"] = acre
        self.drones[drone_id]["active_sq_val"] = sq_val
        self.drones[drone_id]["active_total_boxes"] = total_boxes
        
        self.op_lbl_title.config(text=f"AKTİF: {field_name} ({drone_id})")
        self.grid_rects_emb = self.draw_grid_on_canvas(self.op_canvas, 380, 140, acre)
        
        self.mini_radar_emb.place(relx=0.98, rely=0.05, anchor="ne")
        t_info = self.data["fields"][field_name]
        self.mini_radar_emb.set_position(t_info["lat"], t_info["lon"])
        self.mini_radar_emb.set_zoom(17)
        self.mini_radar_emb.delete_all_polygon()
        self.mini_radar_emb.set_polygon(t_info["polygon"], fill_color="", outline_color="cyan", border_width=2)
        
        self.update_op_panel(sprayed_already, acre, drone_id)

    def update_op_panel(self, sprayed, acre, drone_id):
        if drone_id != self.selected_admin_drone: return
        d = self.drones[drone_id]
        sq_val = d["active_sq_val"]
        tot_box = d["active_total_boxes"]
        painted = int(sprayed / sq_val) if sq_val > 0 else 0
        total_progress = min(1.0, sprayed / acre) if acre > 0 else 1.0
        
        fs_exists = self.fs_window and self.fs_window.winfo_exists()
        try:
            for i in range(tot_box):
                color = COLORS["GREEN"] if i < painted else "#111"
                if i < len(self.grid_rects_emb): self.op_canvas.itemconfig(self.grid_rects_emb[i], fill=color)
                if fs_exists and i < len(self.grid_rects_fs): self.fs_canvas.itemconfig(self.grid_rects_fs[i], fill=color)
                
            perc_text = f"%{int(total_progress*100)} Tamamlandı"
            prog_text = f"{sprayed:.2f} / {acre:.2f} Dönüm İlaçlandı"
            self.op_lbl_perc.config(text=perc_text)
            
            if fs_exists:
                self.fs_lbl_perc.config(text=perc_text)
                self.fs_lbl_prog.config(text=prog_text)
                chem_used = sprayed * PARAMS["ILAC_DONUM_BASI"]
                self.fs_lbl_tchem.config(text=f"💦 Harcanan: {chem_used:.1f} Litre")
                rem_sec = (acre - sprayed) * PARAMS["SANIYE_PER_DONUM"]
                self.fs_lbl_ttime.config(text=f"⏱️ Kalan Süre: {self.format_time(rem_sec)}")
        except tk.TclError: pass

    def delete_selected_fields(self):
        selected = self.listbox.curselection()
        if not selected: return
        for idx in reversed(selected):
            name = self.listbox_map.get(self.listbox.get(idx))
            if name and name in self.data["fields"]: 
                del self.data["fields"][name]
        self.save_data(); self.refresh_listbox(); self.draw_map_markers()

    def toggle_add_drone_mode(self):
        if self.draw_mode != "DRONE":
            self.draw_mode = "DRONE"
            self.temp_coords = []
            self.set_action_msg("YENİ DRON İÇİN HARİTADAN ÜS KONUMU SEÇİN", "warning")
        else:
            self.draw_mode = "NONE"
            self.set_action_msg("SİSTEM HAZIR", "normal")

    def toggle_draw_field_mode(self):
        if not self.active_ciftci_drone.get():
            messagebox.showerror("Hata", "Önce bir dron seçmelisiniz!")
            return
        if self.draw_mode != "FIELD":
            self.draw_mode = "FIELD"
            self.temp_coords = []
            self.btn_add_field.config(text="✅ KAYDET", bg=COLORS["YELLOW"])
            self.set_action_msg("ÇİZİM MODU: HARİTAYA TIKLAYARAK KÖŞELERİ BELİRLEYİN", "warning")
        else: self.finish_drawing_field()

    def map_left_click(self, coords):
        if self.draw_mode == "DRONE":
            name = simpledialog.askstring("Yeni Dron", "Dron (Filo) Adı Girin:")
            if name:
                self.pending_drones[name] = {"lat": coords[0], "lon": coords[1], "owner": "MAC_CIFTCI"}
                messagebox.showinfo("İstek Gönderildi", f"[{name}] dronu üs konumuyla Kule'ye onaya gönderildi.")
                self.refresh_pending_listbox()
            self.draw_mode = "NONE"
            self.set_action_msg("SİSTEM HAZIR", "normal")
            return
            
        if self.draw_mode == "FIELD":
            self.temp_coords.append(coords)
            if len(self.temp_coords) == 1:
                self.temp_marker = self.map_widget.set_marker(coords[0], coords[1], text="Başlangıç")
            elif len(self.temp_coords) > 1:
                if self.temp_path: self.temp_path.delete()
                self.temp_path = self.map_widget.set_path(self.temp_coords + [self.temp_coords[0]], color="yellow", width=3)

    def finish_drawing_field(self):
        self.draw_mode = "NONE"
        self.btn_add_field.config(text="✏️ TARLA ÇİZ", bg=COLORS["WHITE"])
        self.set_action_msg("SİSTEM HAZIR", "normal")
        if len(self.temp_coords) < 3:
            if self.temp_path: self.temp_path.delete()
            if self.temp_marker: self.temp_marker.delete()
            return
            
        name = simpledialog.askstring("Girdi", "Tarla Adı:")
        if not name: 
            if self.temp_path: self.temp_path.delete()
            return
            
        lat0, lon0 = self.temp_coords[0]
        pts = [((lon - lon0) * 85500, (lat - lat0) * 111320) for lat, lon in self.temp_coords]
        acre = max(0.01, round((0.5 * abs(sum(pts[i][0]*pts[i-1][1] - pts[i-1][0]*pts[i][1] for i in range(len(pts))))) / 1000, 2)) 
        avg_lat, avg_lon = sum(p[0] for p in self.temp_coords) / len(self.temp_coords), sum(p[1] for p in self.temp_coords) / len(self.temp_coords)
        
        act_drone = self.active_ciftci_drone.get()
        self.pending_fields[name] = {"lat": avg_lat, "lon": avg_lon, "acre": acre, "sprayed_acre": 0.0, "polygon": self.temp_coords, "owner": act_drone}
        messagebox.showinfo("İstek Gönderildi", f"[{name}] tarlası, {act_drone} adına Kule (Admin) onayına gönderildi!")
        
        self.refresh_pending_listbox()
        if self.temp_path: self.temp_path.delete()
        if self.temp_marker: self.temp_marker.delete()
        self.temp_coords = []

    def draw_map_markers(self):
        self.map_widget.delete_all_marker()
        self.map_widget.delete_all_polygon()
        is_admin = (self.role_var.get() == "TANRI MODU")
        act_drone = self.active_ciftci_drone.get()
        kwargs = {"icon": self.transparent_icon} if self.transparent_icon else {}
        
        for cid, info in self.data["drones_registry"].items():
            if info.get("status") == "approved":
                is_mine = (cid == act_drone)
                if is_admin or is_mine:
                    self.map_widget.set_marker(info["base_lat"], info["base_lon"], text=f"🏠 {cid} ÜSSÜ", **kwargs)
                
                if cid in self.drones:
                    d = self.drones[cid]
                    color = "orange" if is_admin else ("cyan" if is_mine else "orange")
                    d["marker"] = self.map_widget.set_marker(d["lat"], d["lon"], text=f"🚁 {cid}", text_color=color, **kwargs)

        for name, info in self.data["fields"].items():
            if "polygon" in info:
                owner = info.get("owner", "ADMIN")
                if is_admin:
                    color = COLORS["BLUE"] if owner != "ADMIN" else COLORS["GREEN"]
                    lbl = f"🌾 {name}\n({owner})"
                else:
                    color = COLORS["GREEN"] if owner == act_drone else COLORS["RED"]
                    lbl = f"🌾 {name}"
                self.map_widget.set_polygon(info["polygon"], fill_color=color, outline_color="white", border_width=2, name=name, command=self.on_polygon_click)
                self.map_widget.set_marker(info["lat"], info["lon"], text=lbl, text_color="white", **kwargs)

    def set_action_msg(self, msg, color_type="normal"):
        colors = {"normal": ("#dcdde1", "black"), "transit": (COLORS["BLUE"], "white"), 
                  "spray": (COLORS["GREEN"], "black"), "warning": (COLORS["RED"], "white"), "takeoff": (COLORS["YELLOW"], "black")}
        bg_c, fg_c = colors.get(color_type, colors["normal"])
        self.lbl_action_msg.config(text=msg.upper(), bg=bg_c, fg=fg_c)

    def set_speed(self, val): 
        self.sim_speed = val
        self.drone_log("KULE", f"Zaman Makinesi {val}x Hızına Ayarlandı.")
        if self.selected_admin_drone: self.update_telemetry()

    def update_fsm_colors(self, canvas, indicators):
        if not self.selected_admin_drone or self.selected_admin_drone not in self.drones: return
        d = self.drones[self.selected_admin_drone]
        for st, shape in indicators.items():
            color = COLORS["GRAY"]
            if st == d["state"]:
                color = COLORS["GREEN"]
                if st in ["q3", "q4", "q5", "q6", "q8"]: color = COLORS["RED"]
                if st in ["q1", "q7"]: color = COLORS["BLUE"]
            if st == "q4" and self.is_windy and d["state"] != "q4": color = "orange"
            if st == "q3" and d["is_obstacle"] and d["state"] != "q3": color = "orange"
            canvas.itemconfig(shape, fill=color)

    def update_fsm_ui(self): 
        self.update_fsm_colors(self.fsm_canvas, self.fsm_indicators)
        if self.fs_window and hasattr(self, 'fs_fsm_canvas'):
            self.update_fsm_colors(self.fs_fsm_canvas, self.fs_fsm_indicators)
    
    def update_telemetry(self):
        if not self.selected_admin_drone or self.selected_admin_drone not in self.drones: return
        d = self.drones[self.selected_admin_drone]
        self.bat_bar["value"] = d["battery"]
        self.chem_bar["value"] = (d["chemical"] / PARAMS["MAX_ILAC"]) * 100
        rem_sec = self.calculate_eta(self.selected_admin_drone)
        
        sim_txt = f" (SİM: {self.sim_speed}x)" if self.role_var.get() == "TANRI MODU" else ""
        txt = (f"⚡ HIZ: {d['speed']} km/h{sim_txt} | ⏱️ SÜRE: {self.format_time(d['total_time_sec'])}\n"
               f"⏳ KALAN: {self.format_time(rem_sec)} | %{int(d['battery'])} Pil - {int(d['chemical'])}L İlaç")
        self.lbl_stats.config(text=txt)
        
        if self.selected_admin_drone == self.active_ciftci_drone.get():
            msg_map = {"q0": "SİSTEM HAZIR", "q1": "HEDEFE GİDİLİYOR...", "q2": "İLAÇLANIYOR...", "q5": "İKMAL İÇİN DÖNÜLÜYOR", "q7": "GÖREV BİTTİ DÖNÜLÜYOR", "q8": "ACİL DÖNÜŞ", "q6": "SİSTEM DURDURULDU"}
            self.set_action_msg(msg_map.get(d["state"], d["state"]), "transit" if d["state"] in ["q1", "q5", "q7"] else "normal")
            
        self.update_fsm_ui()

    def start_mission(self):
        selected_disp = [self.listbox.get(i) for i in self.listbox.curselection()]
        if not selected_disp:
            messagebox.showwarning("Görev Hatası", "Göreve başlamak için listeden tarla seçmelisiniz!")
            return
            
        selected_names = []
        act_drone = self.active_ciftci_drone.get()
        if not act_drone: return
        
        for disp in selected_disp:
            name = self.listbox_map[disp]
            f_info = self.data["fields"][name]
            
            if f_info.get("owner") != act_drone:
                messagebox.showerror("Yetki İhlali", f"[{name}] tarlası {act_drone} cihazına ait değil!")
                return

            if f_info["sprayed_acre"] >= f_info["acre"]:
                if messagebox.askyesno("Uyarı", f"[{name}] tarlası yakın zamanda ilaçlanmış.\nYine de ilaçlamak ister misiniz?"):
                    self.data["fields"][name]["sprayed_acre"] = 0.0
                    selected_names.append(name)
            else: selected_names.append(name)
                
        if not selected_names: return

        d = self.drones[act_drone]
        d["mission_chemical_used"] = 0.0 
        d["queue"] = selected_names
        d["idx"] = 0
        d["is_running"], d["is_obstacle"] = True, False
        d["state"] = "q1" 
        self.drone_log(act_drone, f"{selected_names[0]} tarlası için havalandı.")
        self.execute_queue(act_drone, selected_names, 0)

    def physics_move(self, drone_id, t_lat, t_lon, speed_kmh, callback):
        def move_tick():
            d = self.drones[drone_id]
            if not d["is_running"]: 
                d["speed"] = 0
                if drone_id == self.selected_admin_drone: self.update_telemetry()
                return

            if d["is_obstacle"]:
                d["state"], d["speed"] = "q3", 0
                self.drone_log(drone_id, "ENGEL ALGILANDI - BEKLEMEDE (q3)")
                if drone_id == self.selected_admin_drone: self.update_telemetry()
                self.root.after(self.tick_ms, move_tick)
                return

            if d["state"] == "q3":
                d["state"] = "q1"
                self.drone_log(drone_id, "ENGEL AŞILDI - İLERLİYOR")

            d["speed"] = speed_kmh
            dist_m = haversine(d["lat"], d["lon"], t_lat, t_lon)
            if dist_m < 5: 
                d["lat"], d["lon"] = t_lat, t_lon
                if d["marker"]: d["marker"].set_position(d["lat"], d["lon"])
                callback()
                return

            speed_ms = speed_kmh / 3.6
            move_m = (speed_ms * self.sim_speed) * (self.tick_ms / 1000)
            ratio = move_m / dist_m if dist_m > 0 else 1
            if ratio >= 1:
                d["lat"], d["lon"] = t_lat, t_lon
                d["total_dist_m"] += dist_m
                if d["marker"]: d["marker"].set_position(d["lat"], d["lon"])
                callback()
            else:
                d["lat"] += (t_lat - d["lat"]) * ratio
                d["lon"] += (t_lon - d["lon"]) * ratio
                if d["marker"]: d["marker"].set_position(d["lat"], d["lon"])
                d["total_dist_m"] += move_m
                d["total_time_sec"] += (self.tick_ms / 1000) * self.sim_speed
                d["battery"] -= (move_m / 1000) * PARAMS["PIL_KM_BASI"]
                if drone_id == self.selected_admin_drone: self.update_telemetry()
                self.root.after(self.tick_ms, move_tick)
        move_tick()

    def spraying_phase(self, drone_id, queue, idx):
        d = self.drones[drone_id]
        d["queue"], d["idx"] = queue, idx
        name = queue[idx]
        d["active_field"] = name
        acre = self.data["fields"][name]["acre"]
        
        if not d["resume_target"]:
            if drone_id == self.selected_admin_drone:
                self.init_op_panel(name, acre, self.data["fields"][name]["sprayed_acre"], drone_id)
            d["state"] = "q2"
            self.drone_log(drone_id, f"{name} tarlası ilaçlanmaya başlandı (q2).")
        
        if d["resume_target"] and d["resume_target"][0] == idx: d["resume_target"] = None
        target_lat, target_lon = self.data["fields"][name]["lat"], self.data["fields"][name]["lon"]

        def spray_tick():
            d = self.drones[drone_id]
            if not d["is_running"]: return
            if d["is_obstacle"]:
                d["state"], d["speed"] = "q3", 0
                self.drone_log(drone_id, "ENGEL ALGILANDI - İLAÇLAMA DURDU (q3)")
                if drone_id == self.selected_admin_drone: self.update_telemetry()
                self.root.after(self.tick_ms, spray_tick)
                return

            if self.data["fields"][name]["sprayed_acre"] >= acre:
                self.data["fields"][name]["sprayed_acre"] = acre
                d["active_field"] = None
                self.save_data(); self.refresh_listbox(); self.execute_queue(drone_id, queue, idx + 1)
                return

            if d["battery"] < 5 or d["chemical"] < 1:
                d["resume_target"] = (idx, self.data["fields"][name]["sprayed_acre"])
                d["active_field"] = None
                self.drone_log(drone_id, "Yakıt/İlaç Kritik. İkmale dönülüyor.")
                self.save_data(); self.return_to_base(drone_id, final=False)
                return

            factor = 0.4 if self.is_windy else 1.0
            d["state"] = "q4" if self.is_windy else "q2" 
            d["speed"] = int(PARAMS["HIZ_ILACLAMA_KMH"] * factor)
            
            sim_time_sec = (self.tick_ms / 1000) * self.sim_speed
            d["total_time_sec"] += sim_time_sec
            
            curr_spray = self.data["fields"][name]["sprayed_acre"]
            radius = 0.0002 * (1 - (curr_spray / acre))
            d["lat"] = target_lat + math.sin(curr_spray * math.pi * 10) * radius
            d["lon"] = target_lon + math.cos(curr_spray * math.pi * 10) * radius
            if d["marker"]: d["marker"].set_position(d["lat"], d["lon"])
            
            acre_done_this_tick = (1.0 / PARAMS["SANIYE_PER_DONUM"]) * sim_time_sec * factor
            self.data["fields"][name]["sprayed_acre"] = min(acre, self.data["fields"][name]["sprayed_acre"] + acre_done_this_tick)
            
            cons = acre_done_this_tick * PARAMS["ILAC_DONUM_BASI"]
            d["chemical"] -= cons
            d["battery"] -= acre_done_this_tick * PARAMS["PIL_DONUM_BASI"]

            if drone_id == self.selected_admin_drone:
                self.update_op_panel(self.data["fields"][name]["sprayed_acre"], acre, drone_id)
                self.update_telemetry()
            self.root.after(self.tick_ms, spray_tick)
        spray_tick()

    def return_to_base(self, drone_id, final=True):
        d = self.drones[drone_id]
        d["state"] = "q8" if d["state"] == "q8" else ("q7" if final else "q5")
        self.drone_log(drone_id, "Üsse dönüş rotası oluşturuldu.")
        d["is_running"] = True 
        base_lat = self.data["drones_registry"][drone_id]["base_lat"]
        base_lon = self.data["drones_registry"][drone_id]["base_lon"]
        self.physics_move(drone_id, base_lat, base_lon, PARAMS["HIZ_TRANSIT_KMH"], lambda: self.base_action(drone_id, final))

    def base_action(self, drone_id, final):
        d = self.drones[drone_id]
        is_q8 = (d["state"] == "q8")
        if not is_q8: d["state"] = "q0" if final else "q5"
        self.drone_log(drone_id, "Üsse indi, motorlar durdu.")
        if not final and not is_q8: d["battery"], d["chemical"] = 100.0, float(PARAMS["MAX_ILAC"])
        if drone_id == self.selected_admin_drone: self.update_telemetry()
        self.root.after(max(50, int(3000 / self.sim_speed)), lambda: self.finish_base_action(drone_id, final, is_q8))

    def finish_base_action(self, drone_id, final, is_q8):
        d = self.drones[drone_id]
        if final or is_q8:
            d["state"], d["is_running"] = "q0", False
            self.drone_log(drone_id, "Sistem bekleme moduna geçti (q0).")
            if drone_id == self.selected_admin_drone: 
                self.update_telemetry()
                self.op_frame.pack_forget()
        else:
            self.execute_queue(drone_id, d["queue"], d["idx"])

    def execute_queue(self, drone_id, queue, idx):
        if idx >= len(queue): 
            self.return_to_base(drone_id, final=True)
            return
        d = self.drones[drone_id]
        d["queue"], d["idx"] = queue, idx
        t_name = queue[idx]
        d["active_field"] = t_name 
        if not d["resume_target"] and drone_id == self.selected_admin_drone: 
            self.init_op_panel(t_name, self.data["fields"][t_name]["acre"], self.data["fields"][t_name]["sprayed_acre"], drone_id)
        d["state"] = "q1"
        self.drone_log(drone_id, f"{t_name} rotasına doğru uçuşa geçildi.")
        self.physics_move(drone_id, self.data["fields"][t_name]["lat"], self.data["fields"][t_name]["lon"], PARAMS["HIZ_TRANSIT_KMH"], lambda: self.spraying_phase(drone_id, queue, idx))

if __name__ == "__main__":
    root = tk.Tk()
    app = GokmenV39Ultimate(root)
    root.mainloop()