from flask import jsonify, request

def setup_api(app, core):
    
    @app.route('/api/telemetry', methods=['GET'])
    def api_telemetry():
        drones_dict = {
            cid: {
                "lat": d["lat"], "lon": d["lon"], "state": d["state"],
                "battery": round(d["battery"], 1), "chemical": round(d["chemical"], 1), "speed_kmh": d["speed"]
            } for cid, d in core.drones.items()
        }
        return jsonify({"drones": drones_dict, "fields": core.data["fields"]})

    @app.route('/api/request_field', methods=['POST'])
    def api_request_field():
        data = request.json
        f_name = data.get("field_name")
        if f_name:
            core.pending_fields[f_name] = data
            core.root.after(0, core.refresh_pending_listbox)
            return jsonify({"status": "pending"})
        return jsonify({"status": "error"}), 400

    @app.route('/api/register_drone', methods=['POST'])
    def api_register_drone():
        data = request.json
        d_name = data.get("drone_name")
        if d_name:
            core.pending_drones[d_name] = data
            core.root.after(0, core.refresh_pending_listbox)
            return jsonify({"status": "pending"})
        return jsonify({"status": "error"}), 400

    @app.route('/api/start_mission', methods=['POST'])
    def api_start_mission():
        data = request.json
        field_name = data.get("field_name")
        cid = data.get("client_id")
        
        if not field_name or field_name not in core.data["fields"]:
            return jsonify({"status": "error", "msg": "Tarla bulunamadı"}), 400
        
        if core.data["fields"][field_name].get("owner") != cid:
            return jsonify({"status": "error", "msg": "Tarla bu drona ait değil!"}), 403
            
        def trigger_flight():
            d = core.drones[cid]
            if d["is_running"]: return 
            core.data["fields"][field_name]["sprayed_acre"] = 0.0 
            d["mission_chemical_used"] = 0.0 
            d["queue"] = [field_name]
            d["idx"] = 0
            d["is_running"], d["is_obstacle"] = True, False
            d["state"] = "q1" 
            d["active_field"] = field_name
            core.drone_log(cid, f"{field_name} tarlası için havalandı (q1).")
            core.execute_queue(cid, [field_name], 0)
        
        core.root.after(0, trigger_flight)
        return jsonify({"status": "success"})